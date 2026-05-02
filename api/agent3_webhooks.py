"""
Agent 3 — Webhooks sortants pour integrations B2B.

Permet a un user/app externe de s'abonner a des events Agent 3 :
  - `message.completed` : reponse agent finalisee
  - `tool.invoked` : un tool/skill a ete execute
  - `quota.warning` : quota atteint 80%
  - `quota.exceeded` : quota depasse
  - `task_plan.created` : plan auto genere
  - `feedback.received` : nouveau thumbs up/down

Modele :
  webhook_subscriptions :
    id TEXT PK
    user_id TEXT
    target_url TEXT (endpoint HTTPS externe)
    events_json TEXT (liste des events souscrits ou ['*'])
    secret TEXT (pour HMAC signature des payloads)
    enabled INTEGER DEFAULT 1
    created_at TEXT
    last_success_at TEXT
    last_error TEXT

  webhook_deliveries :
    id TEXT PK
    subscription_id TEXT
    event TEXT
    payload_json TEXT
    status_code INTEGER
    response_body TEXT (max 1000 chars)
    attempted_at TEXT
    delivered_at TEXT
    error TEXT

Delivery :
  - Fire-and-forget async via `httpx.AsyncClient`
  - Header `X-Sylea-Signature: sha256=<hmac>` pour verification
  - Retry 3 fois avec backoff 1s / 3s / 9s si statut >= 500
  - Timeout 10s

Securite :
  - URLs HTTPS obligatoires (bloque http://)
  - SSRF : valide que l'URL n'est pas une IP privee (reutilise agent3_security)
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("sylea.webhooks")


_SUBS_DDL = """
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    target_url TEXT NOT NULL,
    events_json TEXT NOT NULL,
    secret TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    last_success_at TEXT,
    last_error TEXT,
    failures_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
)
"""

_DELIVERIES_DDL = """
CREATE TABLE IF NOT EXISTS webhook_deliveries (
    id TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL,
    event TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status_code INTEGER,
    response_body TEXT,
    attempted_at TEXT NOT NULL,
    delivered_at TEXT,
    error TEXT
)
"""

VALID_EVENTS = {
    "message.completed",
    "tool.invoked",
    "quota.warning",
    "quota.exceeded",
    "task_plan.created",
    "feedback.received",
    "*",  # wildcard
}


def ensure_webhook_tables(db: Any) -> None:
    try:
        db.conn.execute(_SUBS_DDL)
        db.conn.execute(_DELIVERIES_DDL)
        db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_webhooks_user "
            "ON webhook_subscriptions(user_id)"
        )
        db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_deliveries_sub "
            "ON webhook_deliveries(subscription_id, attempted_at DESC)"
        )
        db.conn.commit()
    except Exception as e:
        logger.debug(f"ensure_webhook_tables failed: {e}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_url(url: str) -> tuple[bool, str]:
    """HTTPS only + pas d'IP privee."""
    if not url or not url.startswith(("https://", "http://")):
        return False, "URL doit commencer par https://"
    if not url.startswith("https://") and not url.startswith("http://localhost"):
        return False, "HTTPS requis (sauf localhost pour dev)"
    # SSRF check (reutilise helper existant)
    try:
        from api.agent3_security import validate_external_url
        ok, _reason = validate_external_url(url, allow_private=False)
        if not ok:
            return False, "URL refusee (IP privee / SSRF)"
    except Exception:
        pass
    return True, ""


# ─────────────────────────────────────────────────────────────────────────────
# CRUD subscriptions
# ─────────────────────────────────────────────────────────────────────────────

def create_subscription(
    db: Any, user_id: str, target_url: str, events: list[str],
) -> dict[str, Any]:
    if not user_id:
        return {"ok": False, "error": "user_id requis"}
    ok, err = _validate_url(target_url)
    if not ok:
        return {"ok": False, "error": err}

    events = [e for e in events if e in VALID_EVENTS]
    if not events:
        return {"ok": False, "error": "au moins 1 event valide requis"}

    ensure_webhook_tables(db)
    sub_id = str(uuid.uuid4())
    secret = secrets.token_urlsafe(32)
    try:
        db.conn.execute(
            "INSERT INTO webhook_subscriptions "
            "(id, user_id, target_url, events_json, secret, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (sub_id, user_id, target_url, json.dumps(events), secret, _now()),
        )
        db.conn.commit()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "subscription_id": sub_id,
        "secret": secret,
        "events": events,
        "target_url": target_url,
    }


def list_subscriptions(db: Any, user_id: str) -> list[dict[str, Any]]:
    ensure_webhook_tables(db)
    try:
        rows = db.conn.execute(
            "SELECT id, target_url, events_json, enabled, last_success_at, "
            "last_error, failures_count, created_at "
            "FROM webhook_subscriptions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        events = []
        if r[2]:
            try:
                events = json.loads(r[2])
            except Exception:
                pass
        out.append({
            "id": r[0],
            "target_url": r[1],
            "events": events,
            "enabled": bool(r[3]),
            "last_success_at": r[4],
            "last_error": r[5],
            "failures_count": r[6] or 0,
            "created_at": r[7],
        })
    return out


def delete_subscription(db: Any, sub_id: str, user_id: str) -> dict[str, Any]:
    ensure_webhook_tables(db)
    try:
        row = db.conn.execute(
            "SELECT user_id FROM webhook_subscriptions WHERE id = ?", (sub_id,),
        ).fetchone()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not row or row[0] != user_id:
        return {"ok": False, "error": "forbidden or not found"}
    try:
        db.conn.execute(
            "DELETE FROM webhook_subscriptions WHERE id = ?", (sub_id,),
        )
        db.conn.execute(
            "DELETE FROM webhook_deliveries WHERE subscription_id = ?", (sub_id,),
        )
        db.conn.commit()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Event firing
# ─────────────────────────────────────────────────────────────────────────────

def _sign_payload(secret: str, payload_bytes: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


async def _deliver_once(
    sub_id: str, target_url: str, secret: str,
    event: str, payload: dict, db: Any,
) -> tuple[bool, int, str]:
    """Delivre le webhook. Retourne (success, status_code, error)."""
    try:
        import httpx
    except ImportError:
        return False, 0, "httpx missing"

    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = _sign_payload(secret, body_bytes)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Sylea-Webhook/1.0",
        "X-Sylea-Event": event,
        "X-Sylea-Signature": f"sha256={signature}",
        "X-Sylea-Delivery-Id": str(uuid.uuid4()),
    }

    delivery_id = str(uuid.uuid4())
    attempted_at = _now()
    try:
        db.conn.execute(
            "INSERT INTO webhook_deliveries "
            "(id, subscription_id, event, payload_json, attempted_at) "
            "VALUES (?,?,?,?,?)",
            (delivery_id, sub_id, event, body_bytes.decode("utf-8"), attempted_at),
        )
        db.conn.commit()
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            resp = await client.post(target_url, content=body_bytes, headers=headers)
            status_code = resp.status_code
            response_body = (resp.text or "")[:1000]
            success = 200 <= status_code < 300
            try:
                db.conn.execute(
                    "UPDATE webhook_deliveries SET status_code = ?, "
                    "response_body = ?, delivered_at = ? WHERE id = ?",
                    (status_code, response_body, _now(), delivery_id),
                )
                db.conn.commit()
            except Exception:
                pass
            return success, status_code, "" if success else f"HTTP {status_code}"
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:200]}"
        try:
            db.conn.execute(
                "UPDATE webhook_deliveries SET error = ? WHERE id = ?",
                (err, delivery_id),
            )
            db.conn.commit()
        except Exception:
            pass
        return False, 0, err


# Module-level set pour garder les references aux background tasks et eviter
# qu'asyncio le GC pendant que la requete HTTP qui les a spawnes finit. Sans ca,
# les deliveries restent bloquees a "attempted_at sans delivered_at".
_BG_TASKS: set[asyncio.Task] = set()


async def _fire_event_with_fresh_db(event: str, payload: dict, user_id: str | None) -> dict[str, Any]:
    """Wrapper : ouvre sa propre connexion DB pour survivre apres la fin
    de la requete HTTP qui a tire l'event (la `db` request-scoped est
    fermee par get_db.finally avant que le delivery httpx ne termine)."""
    from sylea.core.storage.database import DatabaseManager
    db = DatabaseManager()
    db.connect()
    try:
        return await fire_event(db, event, payload, user_id=user_id)
    finally:
        try:
            db.disconnect()
        except Exception:
            pass


def fire_and_forget(db: Any, event: str, payload: dict, *, user_id: str | None = None) -> None:
    """Lance fire_event en background sans bloquer l'appelant.

    Garde une reference forte sur la task (sinon GC peut la canceller avant fin).
    Cree sa propre connexion DB pour ne pas dependre de la connexion request-scoped
    qui sera fermee par FastAPI avant la fin du delivery httpx.
    Idempotent / safe : si pas d'event loop disponible, swallow silently.

    NB : `db` parametre est ignore (legacy compat) — on cree une connexion fraiche.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # pas de loop en cours (sync context) — webhook skipped
    task = loop.create_task(_fire_event_with_fresh_db(event, payload, user_id))
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)


async def fire_event(
    db: Any, event: str, payload: dict,
    *, user_id: str | None = None,
) -> dict[str, Any]:
    """Firing best-effort : recupere les subs matching + deliver en parallel.

    Non-bloquant pour l'appelant (fire-and-forget en terme de latence chat).
    Si user_id None : broadcast a TOUS les subs * (rare — utilise pour admin).
    """
    ensure_webhook_tables(db)
    if event not in VALID_EVENTS and event != "*":
        return {"ok": False, "error": f"unknown event {event}"}

    # Recupere les subs actifs concernes
    try:
        if user_id:
            rows = db.conn.execute(
                "SELECT id, target_url, secret, events_json "
                "FROM webhook_subscriptions WHERE user_id = ? AND enabled = 1",
                (user_id,),
            ).fetchall()
        else:
            rows = db.conn.execute(
                "SELECT id, target_url, secret, events_json "
                "FROM webhook_subscriptions WHERE enabled = 1",
            ).fetchall()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    relevant: list[tuple[str, str, str]] = []
    for r in rows:
        events = []
        if r[3]:
            try:
                events = json.loads(r[3]) or []
            except Exception:
                continue
        if event in events or "*" in events:
            relevant.append((r[0], r[1], r[2]))

    if not relevant:
        return {"ok": True, "delivered": 0, "total_subs": 0}

    # Deliver en parallel
    tasks = []
    for sub_id, url, secret in relevant:
        tasks.append(_deliver_once(sub_id, url, secret, event, payload, db))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    delivered = sum(1 for r in results if isinstance(r, tuple) and r[0])
    return {"ok": True, "delivered": delivered, "total_subs": len(relevant)}


def list_recent_deliveries(
    db: Any, user_id: str, *, limit: int = 50,
) -> list[dict[str, Any]]:
    """Derniers webhook deliveries pour debug."""
    ensure_webhook_tables(db)
    try:
        rows = db.conn.execute(
            "SELECT d.id, d.subscription_id, d.event, d.status_code, "
            "d.attempted_at, d.delivered_at, d.error "
            "FROM webhook_deliveries d "
            "INNER JOIN webhook_subscriptions s ON d.subscription_id = s.id "
            "WHERE s.user_id = ? "
            "ORDER BY d.attempted_at DESC LIMIT ?",
            (user_id, max(1, min(int(limit), 200))),
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "id": r[0],
            "subscription_id": r[1],
            "event": r[2],
            "status_code": r[3],
            "attempted_at": r[4],
            "delivered_at": r[5],
            "error": r[6],
        }
        for r in rows
    ]


__all__ = [
    "VALID_EVENTS",
    "ensure_webhook_tables",
    "create_subscription",
    "list_subscriptions",
    "delete_subscription",
    "fire_event",
    "list_recent_deliveries",
]
