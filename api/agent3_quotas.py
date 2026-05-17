"""
Agent 3 — Quotas & Plans (free / pro / team).

Modele economique :
  - free   : 100k tokens/mois, 10 skills ClawHub, 5 crons, 100 uploads, 10 deep_research/mois
  - pro    : 1M tokens/mois, 50 skills, 30 crons, 1000 uploads, 100 deep_research/mois
  - team   : 10M tokens/mois, unlimited skills, unlimited crons, unlimited uploads, 1000 deep_research/mois

API :
  - `get_user_plan(db, user_id)` -> dict
  - `set_user_plan(db, user_id, plan_name)`
  - `check_quota(db, user_id, resource, amount=1)` -> (ok, reason, remaining)
  - `record_usage(db, user_id, resource, amount=1)`
  - `get_usage(db, user_id, month_key=None)` -> dict
  - `reset_usage(db, user_id)` (admin only)

Tables :
  - user_plans : user_id PK, plan_name, custom_limits_json, updated_at
  - user_quota_usage : user_id + month_key (YYYY-MM) PK, tokens, requests,
    skills_installed, deep_researches, uploads, updated_at
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("sylea.quotas")


# ─────────────────────────────────────────────────────────────────────────────
# Plans definitions
# ─────────────────────────────────────────────────────────────────────────────

PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "name": "free",
        "display_name": "Free",
        "price_usd": 0,
        "limits": {
            "tokens_per_month": 100_000,
            "skills_installed": 10,
            "crons": 5,
            "uploads_per_month": 100,
            "deep_researches_per_month": 10,
            "workspaces": 1,
            "team_members": 0,
        },
    },
    "pro": {
        "name": "pro",
        "display_name": "Pro",
        "price_usd": 20,
        "limits": {
            "tokens_per_month": 1_000_000,
            "skills_installed": 50,
            "crons": 30,
            "uploads_per_month": 1000,
            "deep_researches_per_month": 100,
            "workspaces": 5,
            "team_members": 0,
        },
    },
    "team": {
        "name": "team",
        "display_name": "Team",
        "price_usd": 50,
        "limits": {
            "tokens_per_month": 10_000_000,
            "skills_installed": -1,    # unlimited
            "crons": -1,
            "uploads_per_month": -1,
            "deep_researches_per_month": 1000,
            "workspaces": -1,
            "team_members": 10,
        },
    },
}

# Resources trackees dans `user_quota_usage`
TRACKED_RESOURCES = (
    "tokens",
    "requests",
    "skills_installed",
    "crons",
    "uploads",
    "deep_researches",
)


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

_PLANS_DDL = """
CREATE TABLE IF NOT EXISTS user_plans (
    user_id TEXT PRIMARY KEY,
    plan_name TEXT NOT NULL DEFAULT 'free',
    custom_limits_json TEXT,
    started_at TEXT,
    expires_at TEXT,
    updated_at TEXT NOT NULL
)
"""

_USAGE_DDL = """
CREATE TABLE IF NOT EXISTS user_quota_usage (
    user_id TEXT NOT NULL,
    month_key TEXT NOT NULL,
    tokens INTEGER DEFAULT 0,
    requests INTEGER DEFAULT 0,
    skills_installed INTEGER DEFAULT 0,
    crons INTEGER DEFAULT 0,
    uploads INTEGER DEFAULT 0,
    deep_researches INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, month_key)
)
"""


def ensure_quota_tables(db: Any) -> None:
    try:
        db.conn.execute(_PLANS_DDL)
        db.conn.execute(_USAGE_DDL)
        db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quota_user ON user_quota_usage(user_id)"
        )
        db.conn.commit()
    except Exception as e:
        logger.debug(f"ensure_quota_tables failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _current_month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Plan management
# ─────────────────────────────────────────────────────────────────────────────

# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

_TRACKED_RESOURCES_ASYNC = frozenset((
    "tokens", "requests", "skills_installed",
    "crons", "uploads", "deep_researches",
))


async def get_usage_value_async(user_id: str, resource: str) -> int:
    """Version async — PG-compatible."""
    if not user_id or resource not in _TRACKED_RESOURCES_ASYNC:
        return 0
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    try:
        async with factory() as session:
            # SECURITE : resource est en whitelist statique (TRACKED_RESOURCES_ASYNC).
            # Jamais derive d'input user → pas d'injection SQL possible.
            result = await session.execute(
                text(
                    f"SELECT {resource} FROM user_quota_usage "
                    "WHERE user_id = :uid AND month_key = :mk"
                ),
                {"uid": user_id, "mk": _current_month_key()},
            )
            row = result.first()
    except Exception:
        return 0
    if not row:
        return 0
    return int(row[0] or 0)


async def get_usage_async(
    user_id: str, month_key: str | None = None,
) -> dict[str, Any]:
    """Version async — PG-compatible."""
    if not user_id:
        return {}
    from sqlalchemy import text
    from api.database import get_session_factory
    mk = month_key or _current_month_key()
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT tokens, requests, skills_installed, crons, "
                    "uploads, deep_researches, updated_at "
                    "FROM user_quota_usage WHERE user_id = :uid AND month_key = :mk"
                ),
                {"uid": user_id, "mk": mk},
            )
            row = result.mappings().first()
    except Exception:
        return {}
    if not row:
        return {
            "month_key": mk, "tokens": 0, "requests": 0,
            "skills_installed": 0, "crons": 0, "uploads": 0,
            "deep_researches": 0,
        }
    return {
        "month_key": mk,
        "tokens": row["tokens"] or 0,
        "requests": row["requests"] or 0,
        "skills_installed": row["skills_installed"] or 0,
        "crons": row["crons"] or 0,
        "uploads": row["uploads"] or 0,
        "deep_researches": row["deep_researches"] or 0,
        "updated_at": row["updated_at"],
    }


async def record_usage_async(
    user_id: str, resource: str, amount: int = 1,
) -> bool:
    """Version async — PG-compatible.

    Upsert portable (SELECT-then-UPDATE/INSERT) — pas `ON CONFLICT` SQLite-specific.
    SECURITE : resource est en whitelist (_TRACKED_RESOURCES_ASYNC).
    """
    if not user_id or resource not in _TRACKED_RESOURCES_ASYNC or amount == 0:
        return False
    from sqlalchemy import text
    from api.database import get_session_factory
    mk = _current_month_key()
    now = _now_iso()
    factory = get_session_factory()
    try:
        async with factory() as session:
            try:
                # Verifier existence
                result = await session.execute(
                    text(
                        "SELECT 1 FROM user_quota_usage "
                        "WHERE user_id = :uid AND month_key = :mk"
                    ),
                    {"uid": user_id, "mk": mk},
                )
                existing = result.first()
                if existing:
                    await session.execute(
                        text(
                            f"UPDATE user_quota_usage SET "
                            f"{resource} = COALESCE({resource}, 0) + :amount, "
                            f"updated_at = :now "
                            f"WHERE user_id = :uid AND month_key = :mk"
                        ),
                        {"amount": amount, "now": now,
                         "uid": user_id, "mk": mk},
                    )
                else:
                    await session.execute(
                        text(
                            f"INSERT INTO user_quota_usage "
                            f"(user_id, month_key, {resource}, updated_at) "
                            f"VALUES (:uid, :mk, :amount, :now)"
                        ),
                        {"uid": user_id, "mk": mk,
                         "amount": amount, "now": now},
                    )
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                return False
    except Exception as e:
        logger.warning(f"record_usage_async failed: {e}")
        return False


async def reset_usage_async(
    user_id: str, month_key: str | None = None,
) -> bool:
    """Version async de reset_usage — PG-compatible."""
    if not user_id:
        return False
    from sqlalchemy import text
    from api.database import get_session_factory
    mk = month_key or _current_month_key()
    factory = get_session_factory()
    try:
        async with factory() as session:
            try:
                await session.execute(
                    text(
                        "DELETE FROM user_quota_usage "
                        "WHERE user_id = :uid AND month_key = :mk"
                    ),
                    {"uid": user_id, "mk": mk},
                )
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                return False
    except Exception:
        return False


async def set_user_plan_async(
    user_id: str,
    plan_name: str,
    *,
    custom_limits: dict | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Version async — PG-compatible. Upsert portable."""
    if not user_id:
        return {"ok": False, "error": "no user_id"}
    if plan_name not in PLANS:
        return {"ok": False, "error": f"unknown plan: {plan_name}"}
    from sqlalchemy import text
    from api.database import get_session_factory
    now = _now_iso()
    custom_json = json.dumps(custom_limits) if custom_limits else None
    factory = get_session_factory()
    try:
        async with factory() as session:
            try:
                result = await session.execute(
                    text("SELECT user_id FROM user_plans WHERE user_id = :uid"),
                    {"uid": user_id},
                )
                existing = result.first()
                if existing:
                    await session.execute(
                        text(
                            "UPDATE user_plans SET plan_name = :pname, "
                            "custom_limits_json = :cjson, expires_at = :exp, "
                            "updated_at = :now WHERE user_id = :uid"
                        ),
                        {"pname": plan_name, "cjson": custom_json,
                         "exp": expires_at, "now": now, "uid": user_id},
                    )
                else:
                    await session.execute(
                        text(
                            "INSERT INTO user_plans "
                            "(user_id, plan_name, custom_limits_json, "
                            "started_at, expires_at, updated_at) "
                            "VALUES (:uid, :pname, :cjson, :started, :exp, :now)"
                        ),
                        {"uid": user_id, "pname": plan_name,
                         "cjson": custom_json, "started": now,
                         "exp": expires_at, "now": now},
                    )
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.warning(f"set_user_plan_async failed: {e}")
                return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "plan": plan_name}


async def check_quota_async(
    user_id: str, resource: str, amount: int = 1,
) -> tuple[bool, str, int]:
    """Version async — PG-compatible. Note : ne fire pas les webhooks
    (best-effort, peut etre ajoute plus tard via async task)."""
    if not user_id:
        return True, "anon", -1
    plan = await get_user_plan_async(user_id)
    limits = plan["limits"]
    limit_keys = {
        "tokens": "tokens_per_month",
        "uploads": "uploads_per_month",
        "deep_researches": "deep_researches_per_month",
        "skills_installed": "skills_installed",
        "crons": "crons",
    }
    limit_key = limit_keys.get(resource)
    if not limit_key:
        return True, f"unknown resource {resource}", -1
    limit = limits.get(limit_key)
    if limit is None:
        return True, "no limit defined", -1
    if limit == -1:
        return True, "unlimited", -1

    current = await get_usage_value_async(user_id, resource)
    if current + amount > limit:
        remaining = max(0, limit - current)
        return False, (
            f"Quota {resource} depasse : {current}/{limit} "
            f"(plan {plan['name']}). Passe au plan superieur."
        ), remaining
    return True, "ok", limit - current - amount


async def get_user_plan_async(user_id: str) -> dict[str, Any]:
    """Version async de get_user_plan — PG-compatible.

    Plus de parametre `db` : utilise get_session_factory(). Si la table
    user_plans n'existe pas (PG fresh schema), fallback gracieux a 'free'.
    """
    if not user_id:
        return PLANS["free"]

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT plan_name, custom_limits_json, started_at, expires_at "
                    "FROM user_plans WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
            row = result.mappings().first()
    except Exception as e:
        logger.debug(f"get_user_plan_async failed: {e}")
        return PLANS["free"]

    if not row:
        return PLANS["free"]

    plan_name = row["plan_name"] or "free"
    base = PLANS.get(plan_name) or PLANS["free"]
    plan = {
        "name": base["name"],
        "display_name": base["display_name"],
        "price_usd": base["price_usd"],
        "limits": dict(base["limits"]),
        "started_at": row["started_at"],
        "expires_at": row["expires_at"],
    }
    # Override custom limits si defini
    if row["custom_limits_json"]:
        try:
            custom = json.loads(row["custom_limits_json"]) or {}
            if isinstance(custom, dict):
                plan["limits"].update(custom)
        except Exception:
            pass
    return plan


__all__ = [
    "PLANS",
    "TRACKED_RESOURCES",
    "ensure_quota_tables",
    "get_user_plan_async",
    "set_user_plan_async",
    "check_quota_async",
    "get_usage_async",
    "get_usage_value_async",
    "record_usage_async",
    "reset_usage_async",
]
