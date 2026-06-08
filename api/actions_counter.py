"""
Compteur d'actions quotidien — Syléa.AI.

Wrapper minimaliste autour de `api.daily_action_limit` qui :
  - Compte les actions de l'utilisateur via les tables existantes
    (decisions, agent_messages, agent2_messages) — pas de table dédiée
  - Limites :
      free  : 10 actions / jour
      pro/advanced : 30 actions / jour
      team  : illimité
  - Reset : 00h00 UTC chaque jour

But du module : exposer une API simple `get_actions_status_async(user_id)`
utilisée par le badge éclair de l'UI (Dashboard + chats Agent 1 / 2).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger("sylea.actions_counter")


def _next_reset_iso() -> str:
    """ISO timestamp du prochain reset (minuit UTC suivant)."""
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    return tomorrow.isoformat()


async def _get_profil_id_for_user(user_id: str) -> str | None:
    """Resolve profil_id depuis auth_user_id (1 profil par user max)."""
    if not user_id:
        return None
    try:
        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT id FROM profil_utilisateur "
                    "WHERE auth_user_id = :uid LIMIT 1"
                ),
                {"uid": user_id},
            )
            row = result.first()
            return row[0] if row else None
    except Exception as e:
        logger.debug("[actions_counter] profil_id lookup failed: %s", e)
        return None


async def get_actions_status_async(user_id: str | None) -> dict[str, Any]:
    """Retourne le statut d'actions du user pour aujourd'hui.

    Format pour le frontend (badge éclair) :
      {
        "used": 4,
        "limit": 10,
        "remaining": 6,
        "plan": "free",            # ou "pro", "team"
        "is_unlimited": false,
        "reset_at": "2026-05-20T00:00:00+00:00"
      }

    Si l'utilisateur n'est pas authentifié : limits free + counts 0.
    """
    reset_at = _next_reset_iso()

    if not user_id:
        return {
            "used": 0, "limit": 10, "remaining": 10,
            "plan": "free", "is_unlimited": False,
            "reset_at": reset_at,
        }

    # 1) Plan utilisateur
    plan_name = "free"
    try:
        from api.agent3_quotas import get_user_plan_async
        plan_info = await get_user_plan_async(user_id)
        plan_name = plan_info.get("name", "free")
    except Exception as e:
        logger.debug("[actions_counter] get_user_plan failed: %s", e)

    # 2) Limite selon le plan
    from api.daily_action_limit import (
        get_daily_limit_for_plan,
        count_user_actions_today_async,
    )
    limit = get_daily_limit_for_plan(plan_name)
    is_unlimited = limit < 0

    # 3) Profil ID puis count
    profil_id = await _get_profil_id_for_user(user_id) or user_id
    try:
        used = await count_user_actions_today_async(profil_id, user_id)
    except Exception as e:
        logger.debug("[actions_counter] count failed: %s", e)
        used = 0

    if is_unlimited:
        return {
            "used": used,
            "limit": -1,
            "remaining": -1,
            "plan": plan_name,
            "is_unlimited": True,
            "reset_at": reset_at,
        }

    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "plan": plan_name,
        "is_unlimited": False,
        "reset_at": reset_at,
    }
