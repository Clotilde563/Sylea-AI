"""Push Notifications — Web Push API support for Sylea."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_db, get_optional_user
from sylea.core.storage.database import DatabaseManager

logger = logging.getLogger("notifications")

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: dict  # {p256dh: str, auth: str}


class NotificationIn(BaseModel):
    title: str
    body: str
    icon: str = "/logo192.png"
    url: str | None = None
    tag: str | None = None


def _ensure_push_table(db):
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            auth_user_id TEXT NOT NULL,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth_key TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    db.conn.commit()


@router.post("/subscribe")
async def subscribe_push(
    data: PushSubscriptionIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Enregistre un abonnement push pour l'utilisateur."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    _ensure_push_table(db)
    now = datetime.now(timezone.utc).isoformat()

    try:
        db.conn.execute(
            "INSERT OR REPLACE INTO push_subscriptions (auth_user_id, endpoint, p256dh, auth_key, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, data.endpoint, data.keys.get("p256dh", ""), data.keys.get("auth", ""), now),
        )
        db.conn.commit()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/subscribe")
async def unsubscribe_push(
    data: dict,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Supprime un abonnement push."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    _ensure_push_table(db)
    endpoint = data.get("endpoint", "")
    if endpoint:
        db.conn.execute("DELETE FROM push_subscriptions WHERE auth_user_id = ? AND endpoint = ?", (user_id, endpoint))
        db.conn.commit()
    return {"ok": True}


async def send_push_notification(db, user_id: str, title: str, body: str, url: str | None = None):
    """Envoie une notification push a tous les appareils de l'utilisateur.

    Utilise la Web Push API via pywebpush (si installe) ou via fetch direct.
    """
    _ensure_push_table(db)

    vapid_private = os.environ.get("VAPID_PRIVATE_KEY", "")
    vapid_email = os.environ.get("VAPID_EMAIL", "")

    if not vapid_private:
        logger.debug("VAPID_PRIVATE_KEY non configure — push desactive")
        return {"sent": 0, "error": "VAPID non configure"}

    subs = db.conn.execute(
        "SELECT endpoint, p256dh, auth_key FROM push_subscriptions WHERE auth_user_id = ?",
        (user_id,),
    ).fetchall()

    if not subs:
        return {"sent": 0, "error": "Aucun abonnement push"}

    payload = json.dumps({
        "title": title,
        "body": body,
        "icon": "/logo192.png",
        "url": url or "/",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    sent = 0
    errors = []

    try:
        from pywebpush import webpush, WebPushException

        for endpoint, p256dh, auth_key in subs:
            try:
                webpush(
                    subscription_info={"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth_key}},
                    data=payload,
                    vapid_private_key=vapid_private,
                    vapid_claims={"sub": f"mailto:{vapid_email}"},
                )
                sent += 1
            except WebPushException as e:
                errors.append(str(e)[:100])
                # Supprimer les abonnements expires (410 Gone)
                if "410" in str(e) or "404" in str(e):
                    db.conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
                    db.conn.commit()
            except Exception as e:
                errors.append(str(e)[:100])
    except ImportError:
        logger.debug("pywebpush non installe — push indisponible")
        return {"sent": 0, "error": "pywebpush non installe (pip install pywebpush)"}

    return {"sent": sent, "total": len(subs), "errors": errors[:3] if errors else None}


@router.get("/subscriptions")
async def list_subscriptions(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Liste les abonnements push de l'utilisateur."""
    if not user_id:
        return {"subscriptions": []}

    _ensure_push_table(db)
    subs = db.conn.execute(
        "SELECT endpoint, created_at FROM push_subscriptions WHERE auth_user_id = ?",
        (user_id,),
    ).fetchall()

    return {
        "subscriptions": [{"endpoint": s[0][:50] + "...", "created_at": s[1]} for s in subs],
        "count": len(subs),
    }


@router.post("/test")
async def test_push(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Envoie une notification de test."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    result = await send_push_notification(
        db, user_id,
        title="Test Sylea",
        body="Les notifications push fonctionnent !",
        url="/",
    )
    return result
