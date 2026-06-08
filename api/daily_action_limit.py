"""
Rate limit quotidien des actions IA selon le plan d'abonnement.

Compteur applique sur 4 endpoints qui consomment de l'IA :
  - POST /api/evenement/confirmer  (enregistrement d'evenement)
  - POST /api/dilemme/choisir      (analyse de dilemme + choix)
  - POST /api/agent/chat           (message a l'Agent Sylea 1)
  - POST /api/agent2/chat          (message a l'Agent Sylea 2)

Plans :
  - free  : 10 actions / jour
  - pro   : 30 actions / jour      (abonnement Avance 19,99 EUR/mois)
  - team  : illimite

Implementation : on compte les rows persistees dans la DB pour la journee
en cours :
  - decisions      : 1 row par confirmer evenement OU choisir dilemme
  - agent_messages : 1 row par message user a l'Agent 1 (role='user')
  - agent2_messages: 1 row par message user a l'Agent 2 (role='user')

Cette approche ne necessite pas de table dediee : les compteurs sont
naturellement reset a minuit (filtre WHERE cree_le >= today_start).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Tuple

from sylea.core.storage.database import DatabaseManager


# Limites quotidiennes par plan. Les plans inconnus tombent sur 'free'.
# Note : 'pro' garde 30 en alias backward-compat (rows DB pre-rename).
_DAILY_LIMITS: dict[str, int] = {
    'free': 10,
    'advanced': 30,     # Sylea Avance (19,99 EUR/mois) — nouveau nom
    'pro': 30,          # ALIAS backward-compat — utiliser 'advanced'
    'team': -1,         # illimite (49,99 EUR/mois)
    'enterprise': -1,   # alias illimite (futur)
}


def get_daily_limit_for_plan(plan_name: str | None) -> int:
    """Retourne le quota quotidien d'actions pour un plan.

    -1 = illimite. Defaut a 'free' si plan inconnu (securite : on prefere
    sous-quoter qu'over-quoter).
    """
    if plan_name is None:
        return _DAILY_LIMITS['free']
    return _DAILY_LIMITS.get(plan_name.lower(), _DAILY_LIMITS['free'])


def _today_start_iso() -> str:
    """Timestamp UTC du debut de la journee courante (00:00:00)."""
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat()


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

async def count_user_actions_today_async(
    profil_id: str,
    auth_user_id: str | None,
) -> int:
    """Version async de count_user_actions_today — PG-compatible.

    Plus de parametre `db` : utilise get_session_factory() directement.
    Best-effort sur chaque table (try/except) — si une table n'existe pas
    encore (PG fresh schema), on tombe a 0.
    """
    from sqlalchemy import text
    from api.database import get_session_factory
    today_start = _today_start_iso()
    factory = get_session_factory()

    decisions_today = 0
    agent1_today = 0
    agent2_today = 0

    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM decisions "
                    "WHERE user_id = :uid AND cree_le >= :ts"
                ),
                {"uid": profil_id, "ts": today_start},
            )
            decisions_today = int(result.scalar() or 0)
        except Exception:
            decisions_today = 0

        if auth_user_id:
            try:
                result = await session.execute(
                    text(
                        "SELECT COUNT(*) FROM agent_messages "
                        "WHERE auth_user_id = :uid AND role = 'user' "
                        "AND created_at >= :ts"
                    ),
                    {"uid": auth_user_id, "ts": today_start},
                )
                agent1_today = int(result.scalar() or 0)
            except Exception:
                agent1_today = 0
            try:
                result = await session.execute(
                    text(
                        "SELECT COUNT(*) FROM agent2_messages "
                        "WHERE auth_user_id = :uid AND role = 'user' "
                        "AND created_at >= :ts"
                    ),
                    {"uid": auth_user_id, "ts": today_start},
                )
                agent2_today = int(result.scalar() or 0)
            except Exception:
                agent2_today = 0

    return decisions_today + agent1_today + agent2_today


async def check_daily_action_quota_async(
    profil_id: str,
    auth_user_id: str | None,
    plan_name: str | None,
) -> Tuple[bool, int, int]:
    """Version async de check_daily_action_quota — PG-compatible."""
    limit = get_daily_limit_for_plan(plan_name)
    if limit < 0:
        return True, 0, -1
    count = await count_user_actions_today_async(profil_id, auth_user_id)
    return (count < limit), count, limit
