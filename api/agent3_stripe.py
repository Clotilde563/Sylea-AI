"""
Agent 3 — Stripe checkout integration pour les plans pro/team.

Flow :
  1. Frontend appelle POST /api/agent3/stripe/checkout {plan: 'pro'|'team'}
  2. Backend cree une Stripe Checkout Session + retourne l'URL
  3. User redirige vers Stripe, paie, revient sur /success ou /cancel
  4. Webhook POST /api/agent3/stripe/webhook recoit `checkout.session.completed`
     -> met a jour user_plans via set_user_plan()
  5. Le user peut gerer son abo via Stripe Customer Portal (POST /portal)

Configuration (env) :
  STRIPE_SECRET_KEY        : sk_test_... ou sk_live_...
  STRIPE_WEBHOOK_SECRET    : whsec_... (pour verifier les webhooks)
  STRIPE_PRICE_PRO         : price_... (cree dans le dashboard Stripe)
  STRIPE_PRICE_TEAM        : price_...
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


# Mapping plan -> env var avec le price_id Stripe
_PLAN_TO_PRICE_ENV: dict[str, str] = {
    "pro": "STRIPE_PRICE_PRO",
    "team": "STRIPE_PRICE_TEAM",
}


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

    if plan not in _PLAN_TO_PRICE_ENV:
        return {"ok": False, "error": f"Plan {plan} non payant (utilise pro ou team)"}

    price_id = os.environ.get(_PLAN_TO_PRICE_ENV[plan], "").strip()
    if not price_id:
        return {
            "ok": False,
            "error": f"Price Stripe pour plan {plan} non configure (env {_PLAN_TO_PRICE_ENV[plan]})",
        }

    ensure_stripe_columns(db)
    success_url, cancel_url = _default_urls()

    # Recupere ou cree un customer Stripe pour ce user
    customer_id = _get_or_create_customer(stripe, db, user_id, email)
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


def _get_or_create_customer(stripe: Any, db: Any, user_id: str, email: str) -> str | None:
    """Recupere le stripe_customer_id s'il existe, sinon cree + sauve."""
    try:
        row = db.conn.execute(
            "SELECT stripe_customer_id FROM user_plans WHERE user_id = ?", (user_id,),
        ).fetchone()
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

    # Sauve le customer_id
    try:
        now = datetime.now(timezone.utc).isoformat()
        existing = db.conn.execute(
            "SELECT user_id FROM user_plans WHERE user_id = ?", (user_id,),
        ).fetchone()
        if existing:
            db.conn.execute(
                "UPDATE user_plans SET stripe_customer_id = ? WHERE user_id = ?",
                (customer.id, user_id),
            )
        else:
            db.conn.execute(
                "INSERT INTO user_plans "
                "(user_id, plan_name, stripe_customer_id, started_at, updated_at) "
                "VALUES (?, 'free', ?, ?, ?)",
                (user_id, customer.id, now, now),
            )
        db.conn.commit()
    except Exception as e:
        logger.debug(f"save customer_id failed: {e}")
    return customer.id


# ─────────────────────────────────────────────────────────────────────────────
# Customer portal (auto-serve : user gere son abo)
# ─────────────────────────────────────────────────────────────────────────────

async def create_portal_session(db: Any, user_id: str) -> dict[str, Any]:
    """Cree un lien vers le Stripe Customer Portal pour gerer l'abo."""
    if not is_configured():
        return {"ok": False, "error": "Stripe non configure"}
    stripe = _get_stripe()
    if stripe is None:
        return {"ok": False, "error": "stripe lib manquante"}

    ensure_stripe_columns(db)
    try:
        row = db.conn.execute(
            "SELECT stripe_customer_id FROM user_plans WHERE user_id = ?", (user_id,),
        ).fetchone()
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

    event_type = event.get("type", "")
    data_obj = event.get("data", {}).get("object", {})

    try:
        if event_type == "checkout.session.completed":
            return _handle_checkout_completed(db, data_obj)
        elif event_type == "customer.subscription.updated":
            return _handle_subscription_updated(db, data_obj)
        elif event_type == "customer.subscription.deleted":
            return _handle_subscription_deleted(db, data_obj)
        else:
            return {"ok": True, "event_type": event_type, "action": "ignored"}
    except Exception as e:
        logger.exception(f"webhook handler failed for {event_type}: {e}")
        return {"ok": False, "error": f"handler crash: {type(e).__name__}"}


def _handle_checkout_completed(db: Any, session: dict) -> dict[str, Any]:
    """Premier paiement reussi : upgrade le plan."""
    metadata = session.get("metadata", {}) or {}
    user_id = metadata.get("sylea_user_id")
    plan = metadata.get("sylea_plan")
    subscription_id = session.get("subscription")
    if not user_id or not plan:
        return {"ok": False, "error": "metadata manquante"}

    from api.agent3_quotas import set_user_plan
    set_user_plan(db, user_id, plan)

    # Sauve le subscription_id
    if subscription_id:
        try:
            db.conn.execute(
                "UPDATE user_plans SET stripe_subscription_id = ? WHERE user_id = ?",
                (subscription_id, user_id),
            )
            db.conn.commit()
        except Exception:
            pass

    return {"ok": True, "event_type": "checkout.completed", "action": f"upgraded to {plan}"}


def _handle_subscription_updated(db: Any, sub: dict) -> dict[str, Any]:
    """Changement d'abo : update plan si pertinent."""
    metadata = sub.get("metadata", {}) or {}
    user_id = metadata.get("sylea_user_id")
    plan = metadata.get("sylea_plan")
    status = sub.get("status", "")
    if not user_id:
        return {"ok": True, "event_type": "subscription.updated", "action": "no user_id"}

    from api.agent3_quotas import set_user_plan

    # Si status != active -> degrade free
    if status not in ("active", "trialing"):
        set_user_plan(db, user_id, "free")
        return {"ok": True, "event_type": "subscription.updated", "action": "downgraded to free"}

    if plan:
        set_user_plan(db, user_id, plan)
        return {"ok": True, "event_type": "subscription.updated", "action": f"synced to {plan}"}

    return {"ok": True, "event_type": "subscription.updated", "action": "noop"}


def _handle_subscription_deleted(db: Any, sub: dict) -> dict[str, Any]:
    """Annulation : downgrade free."""
    metadata = sub.get("metadata", {}) or {}
    user_id = metadata.get("sylea_user_id")
    if not user_id:
        return {"ok": True, "event_type": "subscription.deleted", "action": "no user_id"}

    from api.agent3_quotas import set_user_plan
    set_user_plan(db, user_id, "free")
    return {"ok": True, "event_type": "subscription.deleted", "action": "downgraded to free"}


__all__ = [
    "is_configured",
    "ensure_stripe_columns",
    "create_checkout_session",
    "create_portal_session",
    "handle_webhook",
]
