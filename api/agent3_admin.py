"""
Agent 3 — Admin dashboard : cross-user vision pour owner/admin.

Modele :
  - Champ `is_admin` BOOLEAN sur table `users` (migration legere).
  - `require_admin(db, user_id)` raise HTTPException 403 si non-admin.
  - Endpoints expose uniquement aux admins :
    - `GET /api/admin/users` liste + stats
    - `GET /api/admin/stats` globales
    - `GET /api/admin/activity` derniers events
    - `POST /api/admin/users/{id}/plan` change le plan
    - `POST /api/admin/users/{id}/disable` desactive (soft delete)

First admin : variable d'env `SYLEA_ADMIN_EMAILS="admin@foo.com,bob@foo.com"`.
A la creation d'un user avec email matching, is_admin=1 automatique.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("sylea.admin")


# ─────────────────────────────────────────────────────────────────────────────
# Schema migration (add is_admin / disabled_at columns)
# ─────────────────────────────────────────────────────────────────────────────

def ensure_admin_columns(db: Any) -> None:
    """Ajoute is_admin + disabled_at a `users` si absents."""
    try:
        cols = [
            r[1] for r in db.conn.execute("PRAGMA table_info(users)").fetchall()
        ]
    except Exception:
        return
    try:
        if "is_admin" not in cols:
            db.conn.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        if "disabled_at" not in cols:
            db.conn.execute("ALTER TABLE users ADD COLUMN disabled_at TEXT")
        db.conn.commit()
    except Exception as e:
        logger.debug(f"ensure_admin_columns failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Check admin
# ─────────────────────────────────────────────────────────────────────────────

def is_admin(db: Any, user_id: str) -> bool:
    """Retourne True si le user est admin."""
    if not user_id:
        return False
    ensure_admin_columns(db)
    # 1) Cherche la colonne is_admin
    try:
        row = db.conn.execute(
            "SELECT is_admin, email FROM users WHERE id = ?", (user_id,),
        ).fetchone()
    except Exception:
        return False
    if not row:
        return False

    # 2) is_admin flag
    if row[0]:
        return True

    # 3) Fallback env : SYLEA_ADMIN_EMAILS
    admin_emails = os.getenv("SYLEA_ADMIN_EMAILS", "").strip()
    if admin_emails and row[1]:
        whitelist = {e.strip().lower() for e in admin_emails.split(",") if e.strip()}
        if row[1].lower() in whitelist:
            # Auto-promote : set is_admin=1 pour prochaine fois
            try:
                db.conn.execute(
                    "UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,),
                )
                db.conn.commit()
            except Exception:
                pass
            return True
    return False


def promote_user_to_admin(db: Any, target_user_id: str) -> dict[str, Any]:
    ensure_admin_columns(db)
    try:
        db.conn.execute(
            "UPDATE users SET is_admin = 1 WHERE id = ?", (target_user_id,),
        )
        db.conn.commit()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "user_id": target_user_id}


def demote_user(db: Any, target_user_id: str) -> dict[str, Any]:
    ensure_admin_columns(db)
    try:
        db.conn.execute(
            "UPDATE users SET is_admin = 0 WHERE id = ?", (target_user_id,),
        )
        db.conn.commit()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "user_id": target_user_id}


def disable_user(db: Any, target_user_id: str) -> dict[str, Any]:
    """Soft-disable : set disabled_at. L'auth doit verifier ce champ."""
    ensure_admin_columns(db)
    now = datetime.now(timezone.utc).isoformat()
    try:
        db.conn.execute(
            "UPDATE users SET disabled_at = ? WHERE id = ?", (now, target_user_id),
        )
        db.conn.commit()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "disabled_at": now}


def enable_user(db: Any, target_user_id: str) -> dict[str, Any]:
    ensure_admin_columns(db)
    try:
        db.conn.execute(
            "UPDATE users SET disabled_at = NULL WHERE id = ?", (target_user_id,),
        )
        db.conn.commit()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


# ─────────────────────────────────────────────────────────────────────────────
# Queries pour dashboard
# ─────────────────────────────────────────────────────────────────────────────

def list_users_with_stats(db: Any, *, limit: int = 100) -> list[dict[str, Any]]:
    """Liste des users + basiques stats usage (current month).

    Ne retourne pas les passwords / champs sensibles.
    """
    ensure_admin_columns(db)
    try:
        rows = db.conn.execute(
            "SELECT id, email, provider, created_at, is_admin, disabled_at "
            "FROM users ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
    except Exception:
        return []

    users: list[dict[str, Any]] = []
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    for r in rows:
        uid = r[0]
        # Plan + usage (best-effort)
        plan_name = "free"
        try:
            plan_row = db.conn.execute(
                "SELECT plan_name FROM user_plans WHERE user_id = ?", (uid,),
            ).fetchone()
            if plan_row:
                plan_name = plan_row[0] or "free"
        except Exception:
            pass

        usage = {"tokens": 0, "requests": 0}
        try:
            u_row = db.conn.execute(
                "SELECT tokens, requests FROM user_quota_usage "
                "WHERE user_id = ? AND month_key = ?",
                (uid, current_month),
            ).fetchone()
            if u_row:
                usage = {"tokens": u_row[0] or 0, "requests": u_row[1] or 0}
        except Exception:
            pass

        # Messages count
        msg_count = 0
        try:
            m_row = db.conn.execute(
                "SELECT COUNT(*) FROM agent3_messages WHERE auth_user_id = ?", (uid,),
            ).fetchone()
            if m_row:
                msg_count = m_row[0] or 0
        except Exception:
            pass

        users.append({
            "id": uid,
            "email": r[1],
            "provider": r[2],
            "created_at": r[3],
            "is_admin": bool(r[4]),
            "disabled": bool(r[5]),
            "plan": plan_name,
            "usage_this_month": usage,
            "messages_total": msg_count,
        })
    return users


def get_global_stats(db: Any) -> dict[str, Any]:
    """Stats globales : # users, # messages total, tokens consommes ce mois."""
    ensure_admin_columns(db)
    try:
        n_users = db.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] or 0
        n_active = db.conn.execute(
            "SELECT COUNT(*) FROM users WHERE disabled_at IS NULL"
        ).fetchone()[0] or 0
        n_admins = db.conn.execute(
            "SELECT COUNT(*) FROM users WHERE is_admin = 1"
        ).fetchone()[0] or 0
        n_messages = db.conn.execute(
            "SELECT COUNT(*) FROM agent3_messages"
        ).fetchone()[0] or 0

        # Plans distribution
        plans_dist: dict[str, int] = {"free": 0, "pro": 0, "team": 0}
        try:
            for row in db.conn.execute(
                "SELECT plan_name, COUNT(*) FROM user_plans GROUP BY plan_name"
            ).fetchall():
                plans_dist[row[0]] = row[1]
        except Exception:
            pass

        # Tokens mois courant
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        tokens_month = 0
        requests_month = 0
        try:
            row = db.conn.execute(
                "SELECT SUM(tokens), SUM(requests) FROM user_quota_usage "
                "WHERE month_key = ?",
                (current_month,),
            ).fetchone()
            if row:
                tokens_month = row[0] or 0
                requests_month = row[1] or 0
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"get_global_stats failed: {e}")
        return {}

    return {
        "users_total": n_users,
        "users_active": n_active,
        "admins": n_admins,
        "messages_total": n_messages,
        "plans_distribution": plans_dist,
        "tokens_this_month": tokens_month,
        "requests_this_month": requests_month,
        "month_key": current_month,
    }


def get_recent_activity(db: Any, *, limit: int = 50) -> list[dict[str, Any]]:
    """Derniers events / actions depuis agent3_audit_log."""
    try:
        rows = db.conn.execute(
            "SELECT id, auth_user_id, action_type, action_summary, success, created_at "
            "FROM agent3_audit_log ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "id": r[0],
            "user_id": r[1],
            "action_type": r[2],
            "summary": r[3],
            "success": bool(r[4]),
            "created_at": r[5],
        }
        for r in rows
    ]


__all__ = [
    "is_admin",
    "promote_user_to_admin",
    "demote_user",
    "disable_user",
    "enable_user",
    "list_users_with_stats",
    "get_global_stats",
    "get_recent_activity",
    "ensure_admin_columns",
]
