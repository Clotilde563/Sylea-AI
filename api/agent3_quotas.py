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

def get_user_plan(db: Any, user_id: str) -> dict[str, Any]:
    """Retourne le plan de l'user (defaut: free) avec ses limites effectives."""
    if not user_id:
        return PLANS["free"]
    ensure_quota_tables(db)

    try:
        row = db.conn.execute(
            "SELECT plan_name, custom_limits_json, started_at, expires_at "
            "FROM user_plans WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    except Exception as e:
        logger.debug(f"get_user_plan failed: {e}")
        return PLANS["free"]

    if not row:
        return PLANS["free"]

    plan_name = row[0] or "free"
    base = PLANS.get(plan_name) or PLANS["free"]
    # Copy pour pas muter le dict module-level
    plan = {
        "name": base["name"],
        "display_name": base["display_name"],
        "price_usd": base["price_usd"],
        "limits": dict(base["limits"]),
        "started_at": row[2],
        "expires_at": row[3],
    }
    # Override custom limits si defini
    if row[1]:
        try:
            custom = json.loads(row[1]) or {}
            if isinstance(custom, dict):
                plan["limits"].update(custom)
        except Exception:
            pass
    return plan


def set_user_plan(
    db: Any,
    user_id: str,
    plan_name: str,
    *,
    custom_limits: dict | None = None,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Definit le plan d'un user. Cree ou met a jour."""
    if not user_id:
        return {"ok": False, "error": "no user_id"}
    if plan_name not in PLANS:
        return {"ok": False, "error": f"unknown plan: {plan_name}"}
    ensure_quota_tables(db)

    now = _now_iso()
    custom_json = json.dumps(custom_limits) if custom_limits else None
    try:
        existing = db.conn.execute(
            "SELECT user_id FROM user_plans WHERE user_id = ?", (user_id,),
        ).fetchone()
        if existing:
            db.conn.execute(
                "UPDATE user_plans SET plan_name = ?, custom_limits_json = ?, "
                "expires_at = ?, updated_at = ? WHERE user_id = ?",
                (plan_name, custom_json, expires_at, now, user_id),
            )
        else:
            db.conn.execute(
                "INSERT INTO user_plans "
                "(user_id, plan_name, custom_limits_json, started_at, expires_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (user_id, plan_name, custom_json, now, expires_at, now),
            )
        db.conn.commit()
    except Exception as e:
        logger.warning(f"set_user_plan failed: {e}")
        return {"ok": False, "error": str(e)}
    return {"ok": True, "plan": plan_name}


# ─────────────────────────────────────────────────────────────────────────────
# Quota checking
# ─────────────────────────────────────────────────────────────────────────────

def check_quota(
    db: Any, user_id: str, resource: str, amount: int = 1,
) -> tuple[bool, str, int]:
    """Verifie qu'il reste du quota pour `resource` + `amount`.

    Retourne (ok, reason, remaining) :
      - ok=True : quota OK, reason = "", remaining = N
      - ok=False : depasse, reason = message, remaining = 0

    Les resources cummulatives (tokens, uploads, deep_researches) sont trackees
    mois par mois. Les resources-instance (skills_installed, crons) comparent
    simplement le count actuel.
    """
    if not user_id:
        return True, "anon", -1  # anon : pas de quota (limite par IP/reverse proxy)

    plan = get_user_plan(db, user_id)
    limits = plan["limits"]

    # Mapping resource -> cle de limite dans le plan
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

    current = get_usage_value(db, user_id, resource)

    if current + amount > limit:
        remaining = max(0, limit - current)
        # Webhook : fire quota.exceeded (best-effort, non-blocking)
        try:
            from api.agent3_webhooks import fire_and_forget as _fire_wh
            _fire_wh(db, "quota.exceeded", {
                "user_id": user_id,
                "resource": resource,
                "current": current,
                "limit": limit,
                "plan": plan.get("name"),
            }, user_id=user_id)
        except Exception:
            pass
        return False, (
            f"Quota {resource} depasse : {current}/{limit} "
            f"(plan {plan['name']}). Passe au plan superieur."
        ), remaining

    # Webhook : fire quota.warning si on franchit le seuil 80% sur cet appel
    new_total = current + amount
    if limit > 0 and current < int(limit * 0.8) <= new_total:
        try:
            from api.agent3_webhooks import fire_and_forget as _fire_wh
            _fire_wh(db, "quota.warning", {
                "user_id": user_id,
                "resource": resource,
                "current": new_total,
                "limit": limit,
                "percent": int(new_total * 100 / limit),
                "plan": plan.get("name"),
            }, user_id=user_id)
        except Exception:
            pass

    return True, "ok", limit - current - amount


def get_usage_value(db: Any, user_id: str, resource: str) -> int:
    """Retourne la valeur actuelle pour resource (mois courant si resource mensuelle)."""
    if not user_id or resource not in TRACKED_RESOURCES:
        return 0
    ensure_quota_tables(db)

    try:
        row = db.conn.execute(
            f"SELECT {resource} FROM user_quota_usage "
            "WHERE user_id = ? AND month_key = ?",
            (user_id, _current_month_key()),
        ).fetchone()
    except Exception:
        return 0
    if not row:
        return 0
    return int(row[0] or 0)


def get_usage(db: Any, user_id: str, month_key: str | None = None) -> dict[str, Any]:
    """Snapshot usage du user pour le mois courant (ou specifie)."""
    if not user_id:
        return {}
    ensure_quota_tables(db)
    mk = month_key or _current_month_key()
    try:
        row = db.conn.execute(
            "SELECT tokens, requests, skills_installed, crons, uploads, deep_researches, updated_at "
            "FROM user_quota_usage WHERE user_id = ? AND month_key = ?",
            (user_id, mk),
        ).fetchone()
    except Exception:
        return {}
    if not row:
        return {
            "month_key": mk,
            "tokens": 0, "requests": 0, "skills_installed": 0,
            "crons": 0, "uploads": 0, "deep_researches": 0,
        }
    return {
        "month_key": mk,
        "tokens": row[0] or 0,
        "requests": row[1] or 0,
        "skills_installed": row[2] or 0,
        "crons": row[3] or 0,
        "uploads": row[4] or 0,
        "deep_researches": row[5] or 0,
        "updated_at": row[6],
    }


def record_usage(
    db: Any, user_id: str, resource: str, amount: int = 1,
) -> bool:
    """Incremente le compteur d'usage. Upsert sur (user_id, month_key)."""
    if not user_id or resource not in TRACKED_RESOURCES or amount == 0:
        return False
    ensure_quota_tables(db)

    mk = _current_month_key()
    now = _now_iso()
    try:
        # Upsert via SQLite ON CONFLICT
        db.conn.execute(
            f"INSERT INTO user_quota_usage (user_id, month_key, {resource}, updated_at) "
            f"VALUES (?, ?, ?, ?) "
            f"ON CONFLICT(user_id, month_key) DO UPDATE SET "
            f"{resource} = {resource} + ?, updated_at = ?",
            (user_id, mk, amount, now, amount, now),
        )
        db.conn.commit()
        return True
    except Exception as e:
        logger.warning(f"record_usage failed: {e}")
        return False


def reset_usage(db: Any, user_id: str, month_key: str | None = None) -> bool:
    """Reset l'usage d'un user pour un mois (admin only)."""
    if not user_id:
        return False
    ensure_quota_tables(db)
    mk = month_key or _current_month_key()
    try:
        db.conn.execute(
            "DELETE FROM user_quota_usage WHERE user_id = ? AND month_key = ?",
            (user_id, mk),
        )
        db.conn.commit()
        return True
    except Exception:
        return False


__all__ = [
    "PLANS",
    "TRACKED_RESOURCES",
    "ensure_quota_tables",
    "get_user_plan",
    "set_user_plan",
    "check_quota",
    "get_usage",
    "get_usage_value",
    "record_usage",
    "reset_usage",
]
