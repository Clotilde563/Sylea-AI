"""
Router FastAPI — Historique des décisions.

Routes :
  GET /api/historique              → liste des décisions (query: limite=20)
  GET /api/historique/agent-rapport → rapport des actions agent
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from sylea.core.models.decision import Decision
from sylea.config.settings import PROB_MIN, PROB_MAX
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository

from api.schemas import DecisionOut, OptionDilemmeOut, ActionAgentOut, AgentRapportOut, HistoriquePagineOut
from api.dependencies import get_profil_repo, get_decision_repo

router = APIRouter(prefix="/api/historique", tags=["historique"])


def _option_to_out(opt) -> OptionDilemmeOut:
    return OptionDilemmeOut(
        id=opt.id,
        description=opt.description,
        impact_score=opt.impact_score,
        explication_impact=opt.explication_impact,
        est_delegable=opt.est_delegable,
        temps_estime=opt.temps_estime,
    )


def _action_to_out(action) -> ActionAgentOut:
    return ActionAgentOut(
        id=action.id,
        instruction=action.instruction,
        skill_utilise=action.skill_utilise,
        statut=action.statut,
        resultat=action.resultat,
        temps_passe=action.temps_passe,
        execute_le=action.execute_le.isoformat(),
    )


def _decision_to_out(d: Decision) -> DecisionOut:
    chosen = d.get_option_choisie()
    return DecisionOut(
        id=d.id,
        user_id=d.user_id,
        question=d.question,
        options=[_option_to_out(o) for o in d.options],
        probabilite_avant=d.probabilite_avant,
        option_choisie_id=d.option_choisie_id,
        probabilite_apres=d.probabilite_apres,
        action_agent=_action_to_out(d.action_agent) if d.action_agent else None,
        cree_le=d.cree_le.isoformat(),
        option_choisie_description=chosen.description if chosen else None,
        impact_net=(
            (d.probabilite_apres - d.probabilite_avant)
            if d.probabilite_apres is not None else None
        ),
    )


@router.get("", response_model=List[DecisionOut])
async def get_historique(
    limite: int = Query(default=20, ge=1, le=100),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
):
    """Retourne les N dernières décisions de l'utilisateur."""
    if not profil_repo.existe():
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil = profil_repo.charger()
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    decisions = decision_repo.lister_pour_utilisateur(profil.id, limite=limite)
    return [_decision_to_out(d) for d in decisions]


@router.get("/pagine", response_model=HistoriquePagineOut)
async def get_historique_pagine(
    page: int = Query(default=1, ge=1),
    par_page: int = Query(default=10, ge=1, le=50),
    tri: str = Query(default="recent"),
    recherche: str = Query(default=""),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
):
    """Retourne les decisions paginées avec tri et recherche."""
    if not profil_repo.existe():
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")
    profil = profil_repo.charger()
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    rech = recherche.strip() or None
    total = decision_repo.compter_filtre(profil.id, rech)
    import math
    pages_total = max(1, math.ceil(total / par_page))
    decisions = decision_repo.lister_pagine(profil.id, page, par_page, tri, rech)
    return HistoriquePagineOut(
        decisions=[_decision_to_out(d) for d in decisions],
        total=total,
        page=page,
        par_page=par_page,
        pages_total=pages_total,
    )


@router.get("/agent-rapport", response_model=AgentRapportOut)
async def get_agent_rapport(
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
):
    """Retourne le rapport des actions effectuées par l'agent."""
    if not profil_repo.existe():
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil = profil_repo.charger()
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    decisions = decision_repo.lister_pour_utilisateur(profil.id, limite=50)
    actions = [d.action_agent for d in decisions if d.action_agent is not None]

    return AgentRapportOut(
        total_actions=len(actions),
        actions=[_action_to_out(a) for a in actions],
    )


@router.delete("/{decision_id}")
async def supprimer_decision(
    decision_id: str,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
):
    """Supprime une décision et recalcule la probabilité actuelle."""
    if not profil_repo.existe():
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil = profil_repo.charger()
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    # 1. Charger la décision AVANT suppression pour connaître son impact
    decision = decision_repo.obtenir_par_id(decision_id, profil.id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Décision introuvable.")

    # 2. Calculer l'impact_net
    impact_net = 0.0
    if decision.probabilite_apres is not None and decision.probabilite_avant is not None:
        impact_net = decision.probabilite_apres - decision.probabilite_avant

    # 2b. Reverser la progression du sous-objectif si la décision en impactait un
    if decision.sous_objectif_id and decision.impact_sous_objectif:
        try:
            db = profil_repo._db
            so_row = db.conn.execute(
                "SELECT id, progression FROM sous_objectifs WHERE id = ?",
                (decision.sous_objectif_id,),
            ).fetchone()
            if so_row:
                new_prog = max(0, so_row["progression"] - decision.impact_sous_objectif)
                db.conn.execute(
                    "UPDATE sous_objectifs SET progression = ? WHERE id = ?",
                    (new_prog, decision.sous_objectif_id),
                )
                db.conn.commit()
        except Exception:
            pass  # Best-effort: ne pas bloquer la suppression

    # 3. Supprimer la décision
    decision_repo.supprimer_par_id(decision_id, profil.id)

    # 4. Recalculer probabilite_actuelle depuis TOUS les impacts restants
    remaining = decision_repo.lister_pour_utilisateur(profil.id, limite=10000)
    new_prob = sum(
        (d.probabilite_apres or 0) - (d.probabilite_avant or 0)
        for d in remaining
    )
    new_prob = max(PROB_MIN, min(PROB_MAX, new_prob))
    profil.probabilite_actuelle = new_prob
    profil.marquer_modification()
    profil_repo.sauvegarder(profil)

    return {"detail": "Décision supprimée.", "probabilite_actuelle": new_prob}
