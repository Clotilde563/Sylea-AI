"""
Routes REST pour le compteur d'actions journalier.

  GET  /api/actions/today  -> {used, limit, remaining, plan, is_unlimited, reset_at}

Le compteur s'appuie sur les actions déjà persistées en DB (decisions,
agent_messages, agent2_messages) — pas de table dédiée. Voir
api/daily_action_limit.py pour le détail.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from api.actions_counter import get_actions_status_async
from api.dependencies import get_optional_user

logger = logging.getLogger("sylea.routers.actions")

router = APIRouter(prefix="/api/actions", tags=["actions"])


@router.get("/today")
async def actions_today(user: str | None = Depends(get_optional_user)):
    """Retourne le quota d'actions du jour pour l'utilisateur courant.

    Utilisé par le badge éclair affiché dans le Dashboard et les chats
    Agent 1 / Agent 2.

    Note : `get_optional_user` retourne un user_id (str) ou None, PAS un dict.
    L'ancienne signature `user: dict` causait un AttributeError 500 sur
    `user.get("id")` au lieu de juste utiliser la string directement.
    """
    # user_id est déjà un str ou None — pas besoin de .get("id")
    return await get_actions_status_async(user)
