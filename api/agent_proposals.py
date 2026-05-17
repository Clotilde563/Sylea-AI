"""
Gestion des propositions émises par les Agents Sylea 1 et 2 lors d'une
conversation, en attente de confirmation/refus utilisateur.

Workflow :
  1. Pendant un chat, l'agent détecte un event/decision important (héritage,
     promotion, gain majeur, etc.) → il émet une PROPOSITION (pas un impact
     direct).
  2. La proposition est sauvegardée en DB statut='pending' + envoyée au
     frontend dans le payload de réponse.
  3. Le frontend affiche une carte de proposition avec boutons "Confirmer" /
     "Refuser" sous le message.
  4. Au clic, on appelle confirm() ou reject().
  5. Si confirmed : on crée une vraie Decision via le path event existant
     (qui passe par apply_impact_invariant_safe → invariant préservé).
  6. Si rejected : on note dans agent_collected_info que l'info a été
     reconnue mais non comptée comme event.

Cette séparation garantit que :
  - Aucune mutation stats ne se fait sans consentement utilisateur explicite.
  - Les banalités ne créent pas de bruit (l'agent ne propose que pour les
     events importants — l'instruction est dans le system prompt).
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional


# Regex pour extraire les propositions du texte de l'agent.
# Format attendu : [[PROPOSITION]]{json}[[/PROPOSITION]]
_PROPOSAL_PATTERN = re.compile(
    r"\[\[PROPOSITION\]\]\s*(\{.*?\})\s*\[\[/PROPOSITION\]\]",
    re.DOTALL,
)


def extract_proposal_from_text(text: str) -> tuple[str, Optional[dict]]:
    """Extrait une proposition JSON du texte de l'agent.

    Returns:
        (text_clean, proposal_dict | None)
        - text_clean : texte sans le bloc [[PROPOSITION]]
        - proposal_dict : dict parsé OU None si pas de proposition / parse failed
    """
    match = _PROPOSAL_PATTERN.search(text)
    if not match:
        return text, None

    json_str = match.group(1)
    try:
        prop = json.loads(json_str)
    except json.JSONDecodeError:
        # Mal formé → on retire quand même le bloc et on ignore
        text_clean = _PROPOSAL_PATTERN.sub("", text).strip()
        return text_clean, None

    text_clean = _PROPOSAL_PATTERN.sub("", text).strip()

    # Validation minimale du dict
    if not isinstance(prop, dict):
        return text_clean, None
    if not prop.get("type") or not prop.get("description"):
        return text_clean, None

    # Normalisation des champs
    return text_clean, {
        "type": str(prop.get("type", "evenement"))[:40],
        "description": str(prop["description"])[:500],
        "impact_jours": float(prop.get("impact_jours", 0) or 0),
        "resume": str(prop.get("resume", ""))[:200],
        "rationale": str(prop.get("rationale", ""))[:500],
        "target_so_hint": str(prop.get("target_so_hint", ""))[:120],
    }


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

async def save_proposal_async(
    auth_user_id: str,
    agent_label: str,
    proposal: dict,
) -> dict:
    """Version async de save_proposal — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    prop_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO agent_proposals "
                    "(id, auth_user_id, agent_label, type, description, impact_jours, "
                    "resume, rationale, target_so_hint, statut, created_at) "
                    "VALUES (:id, :uid, :alabel, :ptype, :desc, :impact_jours, "
                    ":resume, :rationale, :target_so_hint, 'pending', :created_at)"
                ),
                {
                    "id": prop_id, "uid": auth_user_id, "alabel": agent_label,
                    "ptype": proposal["type"], "desc": proposal["description"],
                    "impact_jours": proposal["impact_jours"],
                    "resume": proposal["resume"], "rationale": proposal["rationale"],
                    "target_so_hint": proposal["target_so_hint"],
                    "created_at": now_iso,
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return {
        "id": prop_id,
        "agent_label": agent_label,
        "type": proposal["type"],
        "description": proposal["description"],
        "impact_jours": proposal["impact_jours"],
        "resume": proposal["resume"],
        "rationale": proposal["rationale"],
        "target_so_hint": proposal["target_so_hint"],
        "statut": "pending",
        "created_at": now_iso,
    }


async def get_proposal_async(prop_id: str, auth_user_id: str) -> Optional[dict]:
    """Version async de get_proposal — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT id, auth_user_id, agent_label, type, description, "
                "impact_jours, resume, rationale, target_so_hint, statut, "
                "created_at, responded_at, decision_id FROM agent_proposals "
                "WHERE id = :pid AND auth_user_id = :uid"
            ),
            {"pid": prop_id, "uid": auth_user_id},
        )
        row = result.mappings().first()
    if not row:
        return None
    return {
        "id": row["id"], "auth_user_id": row["auth_user_id"],
        "agent_label": row["agent_label"], "type": row["type"],
        "description": row["description"], "impact_jours": row["impact_jours"],
        "resume": row["resume"], "rationale": row["rationale"],
        "target_so_hint": row["target_so_hint"], "statut": row["statut"],
        "created_at": row["created_at"], "responded_at": row["responded_at"],
        "decision_id": row["decision_id"],
    }


async def list_pending_proposals_async(
    auth_user_id: str, limit: int = 20,
) -> list[dict]:
    """Version async — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT id, agent_label, type, description, impact_jours, resume, "
                "rationale, target_so_hint, created_at FROM agent_proposals "
                "WHERE auth_user_id = :uid AND statut = 'pending' "
                "ORDER BY created_at DESC LIMIT :lim"
            ),
            {"uid": auth_user_id, "lim": limit},
        )
        rows = result.mappings().all()
    return [
        {
            "id": r["id"], "agent_label": r["agent_label"], "type": r["type"],
            "description": r["description"], "impact_jours": r["impact_jours"],
            "resume": r["resume"], "rationale": r["rationale"],
            "target_so_hint": r["target_so_hint"], "created_at": r["created_at"],
            "statut": "pending",
        }
        for r in rows
    ]


async def mark_responded_async(
    prop_id: str, statut: str, decision_id: Optional[str] = None,
) -> None:
    """Version async — PG-compatible."""
    if statut not in ("confirmed", "rejected"):
        raise ValueError(f"statut invalide : {statut}")
    from sqlalchemy import text
    from api.database import get_session_factory
    now_iso = datetime.now(timezone.utc).isoformat()
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "UPDATE agent_proposals SET statut = :statut, "
                    "responded_at = :responded_at, decision_id = :decision_id "
                    "WHERE id = :pid"
                ),
                {"statut": statut, "responded_at": now_iso,
                 "decision_id": decision_id, "pid": prop_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
