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
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository

from api.schemas import DecisionOut, OptionDilemmeOut, ActionAgentOut, AgentRapportOut
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
