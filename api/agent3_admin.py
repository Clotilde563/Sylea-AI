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

__all__ = [
    # Versions async (migration PG) — toutes les sync versions ont ete supprimees
    "ensure_admin_columns_async",
    "is_admin_async",
    "promote_user_to_admin_async",
    "demote_user_async",
    "disable_user_async",
    "enable_user_async",
    "list_users_with_stats_async",
    "get_global_stats_async",
    "get_recent_activity_async",
]


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

async def ensure_admin_columns_async() -> None:
    """Version async : ajoute is_admin + disabled_at a `users` si absents.

    Utilise `inspect` de SQLAlchemy pour lister les colonnes de maniere
    portable (compat SQLite + PostgreSQL). Les ALTER TABLE sont autocommit.
    """
    from sqlalchemy import inspect, text
    from api.database import get_engine, get_session_factory

    engine = get_engine()
    try:
        async with engine.connect() as conn:
            def _get_cols(sync_conn: Any) -> list[str]:
                insp = inspect(sync_conn)
                if not insp.has_table("users"):
                    return []
                return [c["name"] for c in insp.get_columns("users")]
            cols = await conn.run_sync(_get_cols)
    except Exception:
        return

    if not cols:
        return

    factory = get_session_factory()
    async with factory() as session:
        try:
            if "is_admin" not in cols:
                await session.execute(
                    text("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0"),
                )
            if "disabled_at" not in cols:
                await session.execute(
                    text("ALTER TABLE users ADD COLUMN disabled_at TEXT"),
                )
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.debug(f"ensure_admin_columns_async failed: {e}")


async def is_admin_async(user_id: str) -> bool:
    """Version async : retourne True si le user est admin."""
    if not user_id:
        return False
    await ensure_admin_columns_async()

    from sqlalchemy import text
    from api.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text("SELECT is_admin, email FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
            row = result.first()
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
            whitelist = {
                e.strip().lower() for e in admin_emails.split(",") if e.strip()
            }
            if row[1].lower() in whitelist:
                # Auto-promote : set is_admin=1 pour prochaine fois
                try:
                    await session.execute(
                        text("UPDATE users SET is_admin = 1 WHERE id = :uid"),
                        {"uid": user_id},
                    )
                    await session.commit()
                except Exception:
                    await session.rollback()
                return True
    return False


async def promote_user_to_admin_async(target_user_id: str) -> dict[str, Any]:
    """Version async : promeut un user au rang d'admin."""
    await ensure_admin_columns_async()

    from sqlalchemy import text
    from api.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text("UPDATE users SET is_admin = 1 WHERE id = :uid"),
                {"uid": target_user_id},
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            return {"ok": False, "error": str(e)}
    return {"ok": True, "user_id": target_user_id}


async def demote_user_async(target_user_id: str) -> dict[str, Any]:
    """Version async : retire le statut admin."""
    await ensure_admin_columns_async()

    from sqlalchemy import text
    from api.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text("UPDATE users SET is_admin = 0 WHERE id = :uid"),
                {"uid": target_user_id},
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            return {"ok": False, "error": str(e)}
    return {"ok": True, "user_id": target_user_id}


async def disable_user_async(target_user_id: str) -> dict[str, Any]:
    """Version async : soft-disable un user (set disabled_at)."""
    await ensure_admin_columns_async()
    now = datetime.now(timezone.utc).isoformat()

    from sqlalchemy import text
    from api.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "UPDATE users SET disabled_at = :now WHERE id = :uid",
                ),
                {"now": now, "uid": target_user_id},
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            return {"ok": False, "error": str(e)}
    return {"ok": True, "disabled_at": now}


async def enable_user_async(target_user_id: str) -> dict[str, Any]:
    """Version async : re-active un user (clear disabled_at)."""
    await ensure_admin_columns_async()

    from sqlalchemy import text
    from api.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text("UPDATE users SET disabled_at = NULL WHERE id = :uid"),
                {"uid": target_user_id},
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            return {"ok": False, "error": str(e)}
    return {"ok": True}


async def list_users_with_stats_async(*, limit: int = 100) -> list[dict[str, Any]]:
    """Version async : liste des users + basiques stats usage (current month).

    Ne retourne pas les passwords / champs sensibles.
    """
    await ensure_admin_columns_async()

    from sqlalchemy import text
    from api.database import get_session_factory

    safe_limit = max(1, min(int(limit), 1000))
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT id, email, provider, created_at, is_admin, disabled_at "
                    "FROM users ORDER BY created_at DESC LIMIT :lim"
                ),
                {"lim": safe_limit},
            )
            rows = result.mappings().all()
        except Exception:
            return []

        users: list[dict[str, Any]] = []
        for r in rows:
            uid = r["id"]
            # Plan + usage (best-effort)
            plan_name = "free"
            try:
                plan_res = await session.execute(
                    text("SELECT plan_name FROM user_plans WHERE user_id = :uid"),
                    {"uid": uid},
                )
                plan_row = plan_res.first()
                if plan_row:
                    plan_name = plan_row[0] or "free"
            except Exception:
                pass

            usage = {"tokens": 0, "requests": 0}
            try:
                u_res = await session.execute(
                    text(
                        "SELECT tokens, requests FROM user_quota_usage "
                        "WHERE user_id = :uid AND month_key = :mk"
                    ),
                    {"uid": uid, "mk": current_month},
                )
                u_row = u_res.first()
                if u_row:
                    usage = {
                        "tokens": u_row[0] or 0,
                        "requests": u_row[1] or 0,
                    }
            except Exception:
                pass

            # Messages count
            msg_count = 0
            try:
                m_res = await session.execute(
                    text(
                        "SELECT COUNT(*) FROM agent3_messages "
                        "WHERE auth_user_id = :uid"
                    ),
                    {"uid": uid},
                )
                msg_count = m_res.scalar() or 0
            except Exception:
                pass

            users.append({
                "id": uid,
                "email": r["email"],
                "provider": r["provider"],
                "created_at": r["created_at"],
                "is_admin": bool(r["is_admin"]),
                "disabled": bool(r["disabled_at"]),
                "plan": plan_name,
                "usage_this_month": usage,
                "messages_total": msg_count,
            })
    return users


async def get_global_stats_async() -> dict[str, Any]:
    """Version async : stats globales (# users, # messages, tokens mois courant)."""
    await ensure_admin_columns_async()

    from sqlalchemy import text
    from api.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        try:
            res = await session.execute(text("SELECT COUNT(*) FROM users"))
            n_users = res.scalar() or 0

            res = await session.execute(
                text("SELECT COUNT(*) FROM users WHERE disabled_at IS NULL"),
            )
            n_active = res.scalar() or 0

            res = await session.execute(
                text("SELECT COUNT(*) FROM users WHERE is_admin = 1"),
            )
            n_admins = res.scalar() or 0

            res = await session.execute(text("SELECT COUNT(*) FROM agent3_messages"))
            n_messages = res.scalar() or 0

            # Plans distribution
            plans_dist: dict[str, int] = {"free": 0, "pro": 0, "team": 0}
            try:
                p_res = await session.execute(
                    text("SELECT plan_name, COUNT(*) FROM user_plans GROUP BY plan_name"),
                )
                for row in p_res.all():
                    plans_dist[row[0]] = row[1]
            except Exception:
                pass

            # Tokens mois courant
            current_month = datetime.now(timezone.utc).strftime("%Y-%m")
            tokens_month = 0
            requests_month = 0
            try:
                t_res = await session.execute(
                    text(
                        "SELECT SUM(tokens), SUM(requests) FROM user_quota_usage "
                        "WHERE month_key = :mk"
                    ),
                    {"mk": current_month},
                )
                row = t_res.first()
                if row:
                    tokens_month = row[0] or 0
                    requests_month = row[1] or 0
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"get_global_stats_async failed: {e}")
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


async def get_recent_activity_async(*, limit: int = 50) -> list[dict[str, Any]]:
    """Version async : derniers events / actions depuis agent3_audit_log."""
    from sqlalchemy import text
    from api.database import get_session_factory

    safe_limit = max(1, min(int(limit), 500))

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT id, auth_user_id, action_type, action_summary, "
                    "success, created_at FROM agent3_audit_log "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                {"lim": safe_limit},
            )
            rows = result.mappings().all()
        except Exception:
            return []
    return [
        {
            "id": r["id"],
            "user_id": r["auth_user_id"],
            "action_type": r["action_type"],
            "summary": r["action_summary"],
            "success": bool(r["success"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]
