"""
Helper module pour la gestion des "decisions en attente de confirmation".

Logique metier (validee avec l'utilisateur) :
- Quand l'utilisateur analyse un evenement ou choisit une option de dilemme :
  on cree un pending_action AVEC l'impact_jours mais on ne l'applique PAS
  encore au profil (temps_gagne reste inchange).
- Une notification est planifiee selon impact_jours :
    - impact_jours <= 30 : 1 push a echeance_le (apres impact_jours jours)
    - impact_jours >  30 : push mensuel ("toujours en cours ?") puis push
      final a echeance_le ("realise integralement ?")
- L'utilisateur repond Oui/Non via :
    - bandeau dashboard (web) ou
    - toast natif desktop avec boutons inline (push WS)
- Reponse "Non" -> abandoned, impact JAMAIS applique
- Reponse "Oui" intermediaire -> on continue, prochain push +1 mois
- Reponse "Oui" finale (a echeance_le) -> completed, impact applique au profil
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Optional, Literal

from sylea.core.storage.database import DatabaseManager


# Constantes
_SEUIL_LONG_TERME_JOURS = 30  # Au-dela : verifications mensuelles intermediaires
_INTERVALLE_MENSUEL_JOURS = 30


PendingStatut = Literal['pending', 'in_progress', 'completed', 'abandoned']


@dataclass
class PendingAction:
    id: str
    auth_user_id: str
    source_type: str          # 'event' | 'dilemma'
    source_id: Optional[str]
    description: str
    impact_jours: float
    cree_le: str              # ISO datetime
    echeance_le: str          # ISO datetime
    prochaine_verification_le: str
    statut: PendingStatut
    verifications_ok_count: int
    derniere_reponse_le: Optional[str]

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'source_type': self.source_type,
            'source_id': self.source_id,
            'description': self.description,
            'impact_jours': self.impact_jours,
            'cree_le': self.cree_le,
            'echeance_le': self.echeance_le,
            'prochaine_verification_le': self.prochaine_verification_le,
            'statut': self.statut,
            'verifications_ok_count': self.verifications_ok_count,
            'derniere_reponse_le': self.derniere_reponse_le,
            'is_long_terme': abs(self.impact_jours) > _SEUIL_LONG_TERME_JOURS,
            'is_final_check': _is_final_check(self),
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str) -> datetime:
    """Parse ISO datetime, force UTC si pas de timezone."""
    dt = datetime.fromisoformat(s.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_final_check(action: PendingAction) -> bool:
    """Le prochain push est-il le check FINAL (= echeance_le) ?

    Pour <= 30 jours : oui, le seul check est le final.
    Pour > 30 jours : oui SEULEMENT si prochaine_verification_le == echeance_le.
    """
    return action.prochaine_verification_le == action.echeance_le


def _compute_initial_next_check(cree_le: datetime, impact_jours: float) -> datetime:
    """Calcule le timestamp du PREMIER push apres creation.

    - impact_jours <= 30 : un seul push a cree_le + impact_jours
    - impact_jours >  30 : premier push mensuel a cree_le + 30 jours
    """
    abs_impact = abs(impact_jours)
    if abs_impact <= _SEUIL_LONG_TERME_JOURS:
        return cree_le + timedelta(days=abs_impact)
    return cree_le + timedelta(days=_INTERVALLE_MENSUEL_JOURS)


def _compute_next_check_after_yes(action: PendingAction) -> Optional[datetime]:
    """Apres une reponse "Oui" intermediaire, calcule le prochain push.

    Si la prochaine verification serait apres l'echeance, on renvoie l'echeance
    elle-meme (= check FINAL). None si on est deja sur le check final
    (mais alors la fonction ne devrait pas etre appelee).
    """
    if _is_final_check(action):
        return None  # Pas de "next" : c'etait le check final
    cree = _parse_iso(action.cree_le)
    echeance = _parse_iso(action.echeance_le)
    courant = _parse_iso(action.prochaine_verification_le)
    candidat = courant + timedelta(days=_INTERVALLE_MENSUEL_JOURS)
    if candidat >= echeance:
        return echeance  # Bascule sur le check final
    return candidat


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

_PENDING_COLS = (
    "id, auth_user_id, source_type, source_id, description, impact_jours, "
    "cree_le, echeance_le, prochaine_verification_le, statut, "
    "verifications_ok_count, derniere_reponse_le"
)


async def create_pending_async(
    auth_user_id: str,
    source_type: str,
    source_id: Optional[str],
    description: str,
    impact_jours: float,
) -> PendingAction:
    """Version async de create_pending — PG-compatible."""
    if impact_jours == 0:
        raise ValueError("impact_jours doit etre non nul pour creer un pending")
    from sqlalchemy import text
    from api.database import get_session_factory
    now = datetime.now(timezone.utc)
    abs_impact = abs(impact_jours)
    echeance = now + timedelta(days=abs_impact)
    prochaine = _compute_initial_next_check(now, impact_jours)
    pid = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO pending_actions "
                    "(id, auth_user_id, source_type, source_id, description, "
                    "impact_jours, cree_le, echeance_le, prochaine_verification_le, "
                    "statut, verifications_ok_count) "
                    "VALUES (:pid, :uid, :stype, :sid, :desc, :ij, :cree, :ech, :proch, "
                    "'pending', 0)"
                ),
                {
                    "pid": pid, "uid": auth_user_id, "stype": source_type,
                    "sid": source_id, "desc": description,
                    "ij": float(impact_jours), "cree": now.isoformat(),
                    "ech": echeance.isoformat(),
                    "proch": prochaine.isoformat(),
                },
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return PendingAction(
        id=pid, auth_user_id=auth_user_id, source_type=source_type,
        source_id=source_id, description=description, impact_jours=float(impact_jours),
        cree_le=now.isoformat(), echeance_le=echeance.isoformat(),
        prochaine_verification_le=prochaine.isoformat(),
        statut='pending', verifications_ok_count=0, derniere_reponse_le=None,
    )


async def list_active_for_user_async(auth_user_id: str) -> list[PendingAction]:
    """Version async — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                f"SELECT {_PENDING_COLS} FROM pending_actions "
                "WHERE auth_user_id = :uid AND statut IN ('pending', 'in_progress') "
                "ORDER BY prochaine_verification_le ASC"
            ),
            {"uid": auth_user_id},
        )
        rows = result.mappings().all()
    return [PendingAction(**dict(r)) for r in rows]


async def list_due_for_user_async(auth_user_id: str) -> list[PendingAction]:
    """Version async — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    now_s = _now_iso()
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                f"SELECT {_PENDING_COLS} FROM pending_actions "
                "WHERE auth_user_id = :uid "
                "AND statut IN ('pending', 'in_progress') "
                "AND prochaine_verification_le <= :now "
                "ORDER BY prochaine_verification_le ASC"
            ),
            {"uid": auth_user_id, "now": now_s},
        )
        rows = result.mappings().all()
    return [PendingAction(**dict(r)) for r in rows]


async def list_all_due_global_async() -> list[PendingAction]:
    """Version async — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    now_s = _now_iso()
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                f"SELECT {_PENDING_COLS} FROM pending_actions "
                "WHERE statut IN ('pending', 'in_progress') "
                "AND prochaine_verification_le <= :now "
                "ORDER BY prochaine_verification_le ASC"
            ),
            {"now": now_s},
        )
        rows = result.mappings().all()
    return [PendingAction(**dict(r)) for r in rows]


async def get_by_id_async(pending_id: str) -> Optional[PendingAction]:
    """Version async — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(f"SELECT {_PENDING_COLS} FROM pending_actions WHERE id = :pid"),
            {"pid": pending_id},
        )
        row = result.mappings().first()
    return PendingAction(**dict(row)) if row else None


async def respond_async(
    pending_id: str,
    auth_user_id: str,
    response: bool,
) -> tuple[PendingAction, bool]:
    """Version async de respond — PG-compatible.

    Returns:
        (action_updated, impact_applique_au_profil)
        impact_applique = True UNIQUEMENT au check final apres "Oui".
    """
    action = await get_by_id_async(pending_id)
    if action is None:
        raise ValueError(f"pending_action {pending_id} introuvable")
    if action.auth_user_id != auth_user_id:
        raise PermissionError("Cette pending_action n'appartient pas a cet utilisateur")
    if action.statut not in ('pending', 'in_progress'):
        raise ValueError(f"pending_action {pending_id} deja {action.statut}")

    from sqlalchemy import text
    from api.database import get_session_factory
    now_s = _now_iso()
    factory = get_session_factory()

    if not response:
        # ABANDON
        async with factory() as session:
            try:
                await session.execute(
                    text(
                        "UPDATE pending_actions SET statut = 'abandoned', "
                        "derniere_reponse_le = :now WHERE id = :pid"
                    ),
                    {"now": now_s, "pid": pending_id},
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        action.statut = 'abandoned'
        action.derniere_reponse_le = now_s
        return action, False

    # OUI : Defense-in-depth — AND auth_user_id = :uid en plus du check Python.
    if _is_final_check(action):
        async with factory() as session:
            try:
                await session.execute(
                    text(
                        "UPDATE pending_actions SET statut = 'completed', "
                        "derniere_reponse_le = :now, "
                        "verifications_ok_count = verifications_ok_count + 1 "
                        "WHERE id = :pid AND auth_user_id = :uid"
                    ),
                    {"now": now_s, "pid": pending_id, "uid": auth_user_id},
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        action.statut = 'completed'
        action.verifications_ok_count += 1
        action.derniere_reponse_le = now_s
        return action, True

    # Check intermediaire
    next_check = _compute_next_check_after_yes(action)
    next_check_s = action.echeance_le if next_check is None else next_check.isoformat()

    async with factory() as session:
        try:
            await session.execute(
                text(
                    "UPDATE pending_actions SET statut = 'in_progress', "
                    "derniere_reponse_le = :now, "
                    "verifications_ok_count = verifications_ok_count + 1, "
                    "prochaine_verification_le = :next "
                    "WHERE id = :pid AND auth_user_id = :uid"
                ),
                {"now": now_s, "next": next_check_s,
                 "pid": pending_id, "uid": auth_user_id},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    action.statut = 'in_progress'
    action.verifications_ok_count += 1
    action.derniere_reponse_le = now_s
    action.prochaine_verification_le = next_check_s
    return action, False


async def cancel_for_objectif_change_async(auth_user_id: str) -> int:
    """Version async — PG-compatible.

    Returns: nombre de rowcount (note : SQLAlchemy + aiosqlite ne renvoie
    pas toujours rowcount fiable, donc on retourne 0 par defaut si non dispo).
    """
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "UPDATE pending_actions SET statut = 'abandoned', "
                    "derniere_reponse_le = :now "
                    "WHERE auth_user_id = :uid AND statut IN ('pending', 'in_progress')"
                ),
                {"now": _now_iso(), "uid": auth_user_id},
            )
            await session.commit()
            return result.rowcount or 0
        except Exception:
            await session.rollback()
            raise
