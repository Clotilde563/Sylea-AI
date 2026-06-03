"""
Agent 3 — Stripe checkout integration pour les plans advanced/team.

Flow :
  1. Frontend appelle POST /api/agent3/stripe/checkout {plan: 'advanced'|'team'}
  2. Backend cree une Stripe Checkout Session + retourne l'URL
  3. User redirige vers Stripe, paie, revient sur /success ou /cancel
  4. Webhook POST /api/agent3/stripe/webhook recoit `checkout.session.completed`
     -> met a jour user_plans via set_user_plan()
  5. Le user peut gerer son abo via Stripe Customer Portal (POST /portal)

Configuration (env) :
  STRIPE_SECRET_KEY        : sk_test_... ou sk_live_...
  STRIPE_WEBHOOK_SECRET    : whsec_... (pour verifier les webhooks)
  STRIPE_PRICE_ADVANCED    : price_... (Sylea Avance, 19,99 EUR/mois)
                             Alias accepte : STRIPE_PRICE_PRO (pre-rename)
  STRIPE_PRICE_TEAM        : price_... (Sylea Team, 49,99 EUR/mois)
  STRIPE_SUCCESS_URL       : https://app.sylea.ai/quotas?paid=1 (defaut)
  STRIPE_CANCEL_URL        : https://app.sylea.ai/quotas?cancelled=1 (defaut)
  FRONTEND_BASE_URL        : fallback pour success/cancel urls

Sans Stripe configure (dev local), les fonctions retournent un message clair
sans crasher — le user voit "Stripe non configure, contactez l'admin".

Implementation :
  - Depend de `stripe` python lib (ajouter dans requirements.txt)
  - Import lazy pour que le reste de l'app marche sans Stripe installe
  - Stocke stripe_customer_id + stripe_subscription_id dans user_plans (extension
    du schema via migration legere).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("sylea.stripe")


# Mapping plan -> env var avec le price_id Stripe.
# Note : pour "advanced" on accepte aussi l'ancien nom de var STRIPE_PRICE_PRO
# (cf. _get_price_id ci-dessous) pour ne pas casser les .env existants.
_PLAN_TO_PRICE_ENV: dict[str, str] = {
    "advanced": "STRIPE_PRICE_ADVANCED",
    "team": "STRIPE_PRICE_TEAM",
}


def _get_price_id(plan: str) -> str:
    """Retourne le price_id Stripe pour un plan, avec fallback retrocompatible.

    Pour "advanced", lit STRIPE_PRICE_ADVANCED puis (fallback) STRIPE_PRICE_PRO
    pour rester compatible avec les .env d'avant le rename.
    """
    env_var = _PLAN_TO_PRICE_ENV.get(plan)
    if not env_var:
        return ""
    price_id = os.environ.get(env_var, "").strip()
    if not price_id and plan == "advanced":
        # Fallback retrocompat : ancien nom de variable
        price_id = os.environ.get("STRIPE_PRICE_PRO", "").strip()
    return price_id


def is_configured() -> bool:
    """Check si Stripe est configure correctement."""
    return bool(os.environ.get("STRIPE_SECRET_KEY", "").strip())


def _get_stripe():
    """Lazy import + setup."""
    try:
        import stripe  # type: ignore
    except ImportError:
        return None
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not key:
        return None
    stripe.api_key = key
    return stripe


def _default_urls() -> tuple[str, str]:
    """URLs de success/cancel avec fallback."""
    base = os.environ.get("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
    success = os.environ.get("STRIPE_SUCCESS_URL") or f"{base}/quotas?paid=1&session_id={{CHECKOUT_SESSION_ID}}"
    cancel = os.environ.get("STRIPE_CANCEL_URL") or f"{base}/quotas?cancelled=1"
    return success, cancel


# ─────────────────────────────────────────────────────────────────────────────
# Schema migration : ajouter stripe_* columns a user_plans
# ─────────────────────────────────────────────────────────────────────────────

def ensure_stripe_columns(db: Any) -> None:
    try:
        from api.agent3_quotas import ensure_quota_tables
        ensure_quota_tables(db)
        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(user_plans)").fetchall()]
        if "stripe_customer_id" not in cols:
            db.conn.execute("ALTER TABLE user_plans ADD COLUMN stripe_customer_id TEXT")
        if "stripe_subscription_id" not in cols:
            db.conn.execute("ALTER TABLE user_plans ADD COLUMN stripe_subscription_id TEXT")
        db.conn.commit()
    except Exception as e:
        logger.debug(f"ensure_stripe_columns failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Checkout session creation
# ─────────────────────────────────────────────────────────────────────────────

async def create_checkout_session(
    db: Any, user_id: str, email: str, plan: str,
) -> dict[str, Any]:
    """Cree une Stripe Checkout Session pour un plan.

    Retourne {ok, url, session_id} ou {ok=False, error}.
    """
    if not is_configured():
        return {
            "ok": False,
            "error": "Stripe n'est pas configure. Contacte l'admin pour activer les paiements.",
        }
    stripe = _get_stripe()
    if stripe is None:
        return {"ok": False, "error": "stripe python lib non installee (pip install stripe)"}

    # Backward-compat : ancien plan "pro" -> nouveau "advanced"
    if plan == "pro":
        plan = "advanced"

    if plan not in _PLAN_TO_PRICE_ENV:
        return {"ok": False, "error": f"Plan {plan} non payant (utilise advanced ou team)"}

    # Utilise le helper qui gere le fallback STRIPE_PRICE_PRO -> STRIPE_PRICE_ADVANCED
    price_id = _get_price_id(plan)
    if not price_id:
        return {
            "ok": False,
            "error": f"Price Stripe pour plan {plan} non configure (env {_PLAN_TO_PRICE_ENV[plan]})",
        }

    ensure_stripe_columns(db)
    success_url, cancel_url = _default_urls()

    # Migration PG (2026-05-13) : utiliser la version async
    customer_id = await _get_or_create_customer_async(stripe, user_id, email)
    if not customer_id:
        return {"ok": False, "error": "Erreur creation customer Stripe"}

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"sylea_user_id": user_id, "sylea_plan": plan},
            # Subscription metadata repercutee sur events
            subscription_data={
                "metadata": {"sylea_user_id": user_id, "sylea_plan": plan},
            },
            allow_promotion_codes=True,
        )
        return {
            "ok": True,
            "url": session.url,
            "session_id": session.id,
        }
    except Exception as e:
        logger.exception(f"create_checkout_session failed: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


async def _get_or_create_customer_async(
    stripe: Any, user_id: str, email: str,
) -> str | None:
    """Version async — PG-compatible.

    Recupere le stripe_customer_id s'il existe, sinon cree via Stripe API
    + sauve dans user_plans (upsert portable).
    """
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT stripe_customer_id FROM user_plans WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
            row = result.first()
            if row and row[0]:
                return row[0]
    except Exception:
        pass

    try:
        customer = stripe.Customer.create(
            email=email,
            metadata={"sylea_user_id": user_id},
        )
    except Exception as e:
        logger.warning(f"stripe customer create failed: {e}")
        return None

    try:
        now = datetime.now(timezone.utc).isoformat()
        async with factory() as session:
            try:
                result = await session.execute(
                    text("SELECT user_id FROM user_plans WHERE user_id = :uid"),
                    {"uid": user_id},
                )
                if result.first():
                    await session.execute(
                        text(
                            "UPDATE user_plans SET stripe_customer_id = :cid "
                            "WHERE user_id = :uid"
                        ),
                        {"cid": customer.id, "uid": user_id},
                    )
                else:
                    await session.execute(
                        text(
                            "INSERT INTO user_plans "
                            "(user_id, plan_name, stripe_customer_id, started_at, updated_at) "
                            "VALUES (:uid, 'free', :cid, :now, :now)"
                        ),
                        {"uid": user_id, "cid": customer.id, "now": now},
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    except Exception as e:
        logger.debug(f"save customer_id async failed: {e}")
    return customer.id


# ─────────────────────────────────────────────────────────────────────────────
# Customer portal (auto-serve : user gere son abo)
# ─────────────────────────────────────────────────────────────────────────────

async def create_portal_session(db: Any, user_id: str) -> dict[str, Any]:
    """Cree un lien vers le Stripe Customer Portal pour gerer l'abo.

    Migration PG (2026-05-13) : SELECT via SQLAlchemy text() async.
    """
    if not is_configured():
        return {"ok": False, "error": "Stripe non configure"}
    stripe = _get_stripe()
    if stripe is None:
        return {"ok": False, "error": "stripe lib manquante"}

    ensure_stripe_columns(db)
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT stripe_customer_id FROM user_plans WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
            row = result.first()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not row or not row[0]:
        return {"ok": False, "error": "Aucun abonnement Stripe pour ce user"}

    base = os.environ.get("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
    try:
        session = stripe.billing_portal.Session.create(
            customer=row[0],
            return_url=f"{base}/quotas",
        )
        return {"ok": True, "url": session.url}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


# ─────────────────────────────────────────────────────────────────────────────
# Webhook handler
# ─────────────────────────────────────────────────────────────────────────────

def _run_async(coro):
    """Execute une coroutine depuis un contexte sync OU depuis un thread ou une
    boucle asyncio tourne deja.

    Le webhook est appele depuis un endpoint FastAPI `async def` : un simple
    asyncio.run() y leverait 'cannot be called from a running event loop' (et
    les ecritures DB seraient silencieusement perdues). On retombe alors sur un
    thread separe. Meme pattern eprouve que api.auth.router._run_async.
    """
    import asyncio as _aio
    try:
        return _aio.run(coro)
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_aio.run, coro).result()


# Idempotence : Stripe re-livre le MEME event (event.id stable) en cas de retry
# apres timeout. On memorise les event.id deja traites pour ne pas re-appliquer
# leurs effets. Defense en profondeur : les handlers sont deja majoritairement
# idempotents (set_user_plan = SET), mais ceci protege tout effet de bord futur
# non-idempotent (credits, emails, etc.).
_PROCESSED_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS stripe_processed_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT,
    processed_at TEXT NOT NULL
)
"""


async def _is_stripe_event_processed_async(event_id: str) -> bool:
    """True si cet event.id a deja ete traite. Cree la table au besoin (idempotent)."""
    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        await session.execute(_sa_text(_PROCESSED_EVENTS_DDL))
        await session.commit()
        res = await session.execute(
            _sa_text("SELECT 1 FROM stripe_processed_events WHERE event_id = :eid"),
            {"eid": event_id},
        )
        return res.first() is not None


async def _mark_stripe_event_processed_async(event_id: str, event_type: str) -> None:
    """Enregistre event_id comme traite (no-op silencieux si deja present)."""
    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(_sa_text(_PROCESSED_EVENTS_DDL))
            await session.execute(
                _sa_text(
                    "INSERT INTO stripe_processed_events (event_id, event_type, processed_at) "
                    "VALUES (:eid, :et, :now)"
                ),
                {
                    "eid": event_id,
                    "et": event_type,
                    "now": datetime.now(timezone.utc).isoformat(),
                },
            )
            await session.commit()
        except Exception:
            # Doublon (violation PK) ou erreur transitoire -> swallow.
            await session.rollback()


def handle_webhook(
    db: Any, payload: bytes, sig_header: str,
) -> dict[str, Any]:
    """Traite un webhook Stripe.

    Events geres :
      - checkout.session.completed : premier paiement -> upgrade plan
      - customer.subscription.updated : changement/renouvellement
      - customer.subscription.deleted : annulation -> downgrade free

    Retourne {ok, event_type, action} ou {ok=False, error}.
    """
    stripe = _get_stripe()
    if stripe is None:
        return {"ok": False, "error": "stripe non configure"}

    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not webhook_secret:
        return {"ok": False, "error": "STRIPE_WEBHOOK_SECRET non configure"}

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as e:
        logger.warning(f"webhook signature invalid: {e}")
        return {"ok": False, "error": f"invalid signature: {type(e).__name__}"}

    # NOTE : stripe.Webhook.construct_event() retourne un stripe.Event
    # (StripeObject) qui n'expose PAS la methode dict .get(). Il faut utiliser
    # l'acces par attribut OU par cle directe.
    try:
        event_type = event["type"] if hasattr(event, "__getitem__") else getattr(event, "type", "")
    except (KeyError, AttributeError):
        event_type = ""
    try:
        data_obj = event["data"]["object"] if hasattr(event, "__getitem__") else getattr(getattr(event, "data", {}), "object", {})
    except (KeyError, AttributeError):
        data_obj = {}

    # event.id (stable a travers les re-livraisons Stripe) pour l'idempotence.
    try:
        event_id = event["id"] if hasattr(event, "__getitem__") else getattr(event, "id", "")
    except (KeyError, AttributeError):
        event_id = ""

    # Skip si deja traite. FAIL-OPEN : si le check DB echoue, on traite quand
    # meme (ne JAMAIS perdre un event de paiement legitime ; le risque inverse,
    # un double-traitement, est borne car les handlers sont idempotents).
    if event_id:
        try:
            if _run_async(_is_stripe_event_processed_async(event_id)):
                return {"ok": True, "event_type": event_type, "action": "duplicate_ignored"}
        except Exception as e:
            logger.debug(f"stripe idempotency check failed (fail-open): {e}")

    try:
        if event_type == "checkout.session.completed":
            result = _handle_checkout_completed(db, data_obj)
        elif event_type == "customer.subscription.updated":
            result = _handle_subscription_updated(db, data_obj)
        elif event_type == "customer.subscription.deleted":
            result = _handle_subscription_deleted(db, data_obj)
        else:
            result = {"ok": True, "event_type": event_type, "action": "ignored"}
    except Exception as e:
        logger.exception(f"webhook handler failed for {event_type}: {e}")
        return {"ok": False, "error": f"handler crash: {type(e).__name__}"}

    # Marque l'event traite UNIQUEMENT si le handler a reussi (sinon on laisse
    # Stripe re-livrer pour reessayer).
    if event_id and result.get("ok"):
        try:
            _run_async(_mark_stripe_event_processed_async(event_id, event_type))
        except Exception as e:
            logger.debug(f"stripe mark-processed failed: {e}")
    return result


def _handle_checkout_completed(db: Any, session: dict) -> dict[str, Any]:
    """Premier paiement reussi : upgrade le plan.

    Migration PG (2026-05-13) : utilise asyncio.run pour appeler set_user_plan_async
    + UPDATE subscription_id en async. handle_webhook reste sync (webhook
    Stripe verifie la signature sync) mais delegue les DB writes a l'async.
    """
    import asyncio as _asyncio
    metadata = session.get("metadata", {}) or {}
    user_id = metadata.get("sylea_user_id")
    plan = metadata.get("sylea_plan")
    subscription_id = session.get("subscription")
    if not user_id or not plan:
        return {"ok": False, "error": "metadata manquante"}

    # Backward-compat : subscription Stripe d'avant le rename pro -> advanced
    if plan == "pro":
        plan = "advanced"

    from api.agent3_quotas import set_user_plan_async

    async def _do_writes():
        await set_user_plan_async(user_id, plan)
        if subscription_id:
            from sqlalchemy import text
            from api.database import get_session_factory
            factory = get_session_factory()
            async with factory() as sess:
                try:
                    await sess.execute(
                        text(
                            "UPDATE user_plans SET stripe_subscription_id = :sid "
                            "WHERE user_id = :uid"
                        ),
                        {"sid": subscription_id, "uid": user_id},
                    )
                    await sess.commit()
                except Exception:
                    await sess.rollback()

    try:
        _run_async(_do_writes())
    except Exception as e:
        logger.warning(f"checkout_completed writes failed: {e}")

    return {"ok": True, "event_type": "checkout.completed", "action": f"upgraded to {plan}"}


def _handle_subscription_updated(db: Any, sub: dict) -> dict[str, Any]:
    """Changement d'abo : update plan si pertinent.

    Migration PG : utilise set_user_plan_async via asyncio.run.
    """
    import asyncio as _asyncio
    metadata = sub.get("metadata", {}) or {}
    user_id = metadata.get("sylea_user_id")
    plan = metadata.get("sylea_plan")
    status = sub.get("status", "")
    if not user_id:
        return {"ok": True, "event_type": "subscription.updated", "action": "no user_id"}

    from api.agent3_quotas import set_user_plan_async

    if status not in ("active", "trialing"):
        try:
            _run_async(set_user_plan_async(user_id, "free"))
        except Exception:
            pass
        return {"ok": True, "event_type": "subscription.updated", "action": "downgraded to free"}

    if plan:
        # Backward-compat : sub Stripe d'avant le rename pro -> advanced
        if plan == "pro":
            plan = "advanced"
        try:
            _run_async(set_user_plan_async(user_id, plan))
        except Exception:
            pass
        return {"ok": True, "event_type": "subscription.updated", "action": f"synced to {plan}"}

    return {"ok": True, "event_type": "subscription.updated", "action": "noop"}


def _handle_subscription_deleted(db: Any, sub: dict) -> dict[str, Any]:
    """Annulation : downgrade free.

    Migration PG : utilise set_user_plan_async via asyncio.run.
    """
    import asyncio as _asyncio
    metadata = sub.get("metadata", {}) or {}
    user_id = metadata.get("sylea_user_id")
    if not user_id:
        return {"ok": True, "event_type": "subscription.deleted", "action": "no user_id"}

    from api.agent3_quotas import set_user_plan_async
    try:
        _run_async(set_user_plan_async(user_id, "free"))
    except Exception:
        pass
    return {"ok": True, "event_type": "subscription.deleted", "action": "downgraded to free"}


__all__ = [
    "is_configured",
    "ensure_stripe_columns",
    "create_checkout_session",
    "create_portal_session",
    "handle_webhook",
]
