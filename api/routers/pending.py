"""
Router FastAPI — Decisions en attente de confirmation.

Endpoints :
  GET  /api/pending             → liste des pending_actions actives de l'user
  GET  /api/pending/due         → liste des verifications dues (a notifier)
  POST /api/pending/{id}/respond → reponse Oui/Non a une verification

Logique : voir api/pending_actions.py pour le detail metier.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import (
    get_db, get_optional_user, get_profil_repo, get_decision_repo,
)
from api.pending_actions import (
    get_by_id_async, respond_async,
)
from api.schemas import PendingActionOut, PendingRespondIn
from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository


router = APIRouter(prefix="/api/pending", tags=["pending"])


@router.get("", response_model=list[PendingActionOut])
async def list_pending(
    user_id: str | None = Depends(get_optional_user),
):
    """Liste toutes les pending_actions actives (pending + in_progress).

    Migration PG : SELECT via SQLAlchemy text() — compatible SQLite + PG.
    """
    if not user_id:
        return []
    from sqlalchemy import text
    from api.database import get_session_factory
    from api.pending_actions import PendingAction
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                SELECT id, auth_user_id, source_type, source_id, description, impact_jours,
                       cree_le, echeance_le, prochaine_verification_le, statut,
                       verifications_ok_count, derniere_reponse_le
                FROM pending_actions
                WHERE auth_user_id = :uid AND statut IN ('pending', 'in_progress')
                ORDER BY prochaine_verification_le ASC
            """),
            {"uid": user_id},
        )
        rows = result.mappings().all()
    return [PendingAction(**dict(r)).to_dict() for r in rows]


@router.get("/due", response_model=list[PendingActionOut])
async def list_pending_due(
    user_id: str | None = Depends(get_optional_user),
):
    """Liste les verifications a echeance (a afficher en banniere ou push).

    Migration PG : SELECT via SQLAlchemy text() — compatible SQLite + PG.
    """
    if not user_id:
        return []
    from datetime import datetime, timezone
    from sqlalchemy import text
    from api.database import get_session_factory
    from api.pending_actions import PendingAction
    now_iso = datetime.now(timezone.utc).isoformat()
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text("""
                SELECT id, auth_user_id, source_type, source_id, description, impact_jours,
                       cree_le, echeance_le, prochaine_verification_le, statut,
                       verifications_ok_count, derniere_reponse_le
                FROM pending_actions
                WHERE auth_user_id = :uid
                  AND statut IN ('pending', 'in_progress')
                  AND prochaine_verification_le <= :now
                ORDER BY prochaine_verification_le ASC
            """),
            {"uid": user_id, "now": now_iso},
        )
        rows = result.mappings().all()
    return [PendingAction(**dict(r)).to_dict() for r in rows]


@router.post("/{pending_id}/respond", response_model=PendingActionOut)
async def respond_pending(
    pending_id: str,
    data: PendingRespondIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
):
    """Traite une reponse Oui/Non a une pending_action.

    Effets :
    - Non         → statut 'abandoned', aucun impact applique
    - Oui interm. → continue (long-terme), prochain push +1 mois
    - Oui finale  → statut 'completed', impact applique au profil + sous-objectif
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    # Migration PG (2026-05-13) : versions async (compat SQLite + PG).
    action = await get_by_id_async(pending_id)
    if action is None:
        raise HTTPException(status_code=404, detail="pending_action introuvable")
    if action.auth_user_id != user_id:
        raise HTTPException(status_code=403, detail="Cette pending_action ne vous appartient pas")

    try:
        updated, impact_to_apply = await respond_async(pending_id, user_id, data.response)
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Si on a bascule en 'completed' : appliquer l'impact au profil + sous-objectif
    if impact_to_apply:
        await _apply_impact_to_profile(
            db, profil_repo, decision_repo, user_id, updated.impact_jours,
            updated.source_id, updated.description,
        )

    return updated.to_dict()


async def _apply_impact_to_profile(
    db: DatabaseManager,
    profil_repo: ProfilRepository,
    decision_repo: DecisionRepository,
    user_id: str,
    impact_jours: float,
    decision_id: str | None,
    description: str,
) -> None:
    """Applique l'impact au profil + repercute sur les sous-objectifs.

    Appele uniquement quand un pending_action passe en 'completed'.
    """
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        return

    # Mise a jour temps_gagne avec clamp
    temps_gagne_avant = profil.temps_gagne_jours
    temps_gagne_apres = max(0, min(profil.temps_initial_jours, temps_gagne_avant + impact_jours))

    profil.temps_gagne_jours = temps_gagne_apres
    if profil.temps_initial_jours > 0:
        profil.probabilite_actuelle = round(
            (temps_gagne_apres / profil.temps_initial_jours) * 100, 2
        )
    profil.marquer_modification()
    profil_repo.sauvegarder(profil)

    # Migration PG (2026-05-13) : tout dans UNE seule session async — atomique.
    from sqlalchemy import text
    from api.database import get_session_factory
    from api.so_invariant import apply_impact_invariant_safe_async
    factory = get_session_factory()
    async with factory() as session:
        try:
            # Mise a jour de la decision originale
            if decision_id:
                try:
                    await session.execute(
                        text(
                            "UPDATE decisions SET probabilite_apres = :prob, "
                            "temps_gagne_apres = :tga WHERE id = :did"
                        ),
                        {"prob": profil.probabilite_actuelle,
                         "tga": temps_gagne_apres, "did": decision_id},
                    )
                except Exception:
                    pass

            # Repercussion sur le sous-objectif pertinent
            so_result = await session.execute(
                text(
                    "SELECT id, titre, progression, ordre, temps_estime "
                    "FROM sous_objectifs WHERE user_id = :uid ORDER BY ordre"
                ),
                {"uid": profil.id},
            )
            all_so_all = list(so_result.mappings().all())
            all_so = [so for so in all_so_all if (so["progression"] or 0) < 100]
            if all_so:
                so_cible = await _identify_so(description, all_so)
                if so_cible is None:
                    so_cible = all_so[0]
                target_id_used, applied_delta_pct = await apply_impact_invariant_safe_async(
                    session, profil.id, so_cible["id"], impact_jours,
                    profil.temps_initial_jours,
                )
                if decision_id:
                    try:
                        await session.execute(
                            text(
                                "UPDATE decisions SET sous_objectif_id = :soid, "
                                "impact_sous_objectif = :impact WHERE id = :did"
                            ),
                            {"soid": target_id_used or so_cible["id"],
                             "impact": applied_delta_pct, "did": decision_id},
                        )
                    except Exception:
                        pass
            await session.commit()
        except Exception:
            await session.rollback()


async def _identify_so(description: str, sous_objectifs: list) -> dict | None:
    """Identifie le sous-objectif le plus pertinent pour cette description.

    Reutilise la logique de matching simple (mots-cles). Pour un matching IA
    plus fin on peut a terme appeler Claude comme dans evenement.py.
    """
    if not sous_objectifs:
        return None
    desc_lower = description.lower()
    best_score = 0
    best_so = None
    for so in sous_objectifs:
        titre = (so["titre"] or "").lower()
        # Score = nombre de mots du titre presents dans la description
        score = sum(1 for w in titre.split() if len(w) > 3 and w in desc_lower)
        if score > best_score:
            best_score = score
            best_so = so
    return best_so
