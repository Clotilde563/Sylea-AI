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
from api.dependencies import get_profil_repo, get_decision_repo, get_optional_user

router = APIRouter(prefix="/api/historique", tags=["historique"])


def _recompute_so_progressions(db, profil_id: str, exclude_decision_id: str | None = None) -> None:
    """Recalcule toutes les SO progressions pour profil_id en respectant
    l'invariant DASHBOARD critique :

        sum(so.temps_estime / sum_te * temps_initial * (1 - so.prog/100))
            == profil.temps_gagne_jours    (a un epsilon pres)

    => sum(so.temps_estime * so.prog) / sum_te == temps_gagne / temps_initial × 100
    => sum(so.temps_estime * so.prog) == temps_gagne × sum_te / temps_initial × 100

    Strategy :
      1. Cumul = sum(impact_sous_objectif) par SO (signal relatif des decisions)
      2. Si cumul total == 0 : distribution equitable (chaque SO a la meme prog =
         progression globale du profil).
      3. Sinon : scale les progressions par "scale" tel que l'invariant Dashboard
         tienne, en preservant la repartition relative des cumuls.
      4. Clamp [0, 100].

    Le banner "Desynchronisation detectee" du Dashboard ne devrait plus
    apparaitre apres cet appel.
    """
    # Charger profil pour temps_initial et temps_gagne (sources de verite)
    profil_row = db.conn.execute(
        "SELECT temps_initial_jours, temps_gagne_jours FROM profil_utilisateur WHERE id = ?",
        (profil_id,),
    ).fetchone()
    if not profil_row:
        return
    temps_initial = profil_row["temps_initial_jours"] or 0
    temps_gagne = profil_row["temps_gagne_jours"] or 0

    # Charger les SO avec leurs temps_estime
    so_rows = db.conn.execute(
        "SELECT id, temps_estime FROM sous_objectifs WHERE user_id = ?",
        (profil_id,),
    ).fetchall()
    if not so_rows:
        return
    so_te = {r["id"]: max(30, r["temps_estime"] or 180) for r in so_rows}
    sum_te = sum(so_te.values())
    if sum_te == 0 or temps_initial == 0:
        return

    # Cumul des impacts par SO depuis les decisions restantes
    cumul = {sid: 0.0 for sid in so_te}
    query = (
        "SELECT sous_objectif_id, impact_sous_objectif FROM decisions "
        "WHERE user_id = ? AND sous_objectif_id IS NOT NULL "
    )
    params: list = [profil_id]
    if exclude_decision_id:
        query += "AND id != ? "
        params.append(exclude_decision_id)
    query += "ORDER BY cree_le ASC"
    rows = db.conn.execute(query, tuple(params)).fetchall()
    for r in rows:
        sid = r["sous_objectif_id"]
        impact = r["impact_sous_objectif"] or 0.0
        if sid in cumul:
            cumul[sid] += impact

    # Target pondere : sum(te × prog) doit egaler ce nombre pour respecter
    # l'invariant Dashboard.
    target_weighted = temps_gagne * sum_te / temps_initial * 100  # en % * jours

    # Sum pondere actuel des cumul (te × cumul)
    weighted_cumul = sum(so_te[sid] * cumul[sid] for sid in so_te)

    if weighted_cumul > 0:
        # Scale proportionnel
        scale = target_weighted / weighted_cumul
        progressions = {sid: max(0.0, min(100.0, cumul[sid] * scale)) for sid in so_te}
        # Note : si certaines progressions sont clampees a 100, l'invariant ne
        # tient plus exactement. On accepte cette degradation graceuse plutot
        # que de redistribuer.
    else:
        # Distribution equitable : chaque SO a la meme progression = profil%
        equal_prog = temps_gagne / temps_initial * 100
        progressions = {sid: max(0.0, min(100.0, equal_prog)) for sid in so_te}

    for sid, prog in progressions.items():
        db.conn.execute(
            "UPDATE sous_objectifs SET progression = ? WHERE id = ?",
            (prog, sid),
        )
    db.conn.commit()


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
    # Récupérer l'ID et l'impact du sous-objectif
    so_id = getattr(d, 'sous_objectif_id', None) or None
    so_impact = getattr(d, 'impact_sous_objectif', 0.0) or 0.0
    # Compute impact_net from temps fields (use is not None, not truthiness, since 0.0 is valid)
    if d.temps_gagne_apres is not None and d.temps_gagne_avant is not None and (d.temps_gagne_apres != 0.0 or d.temps_gagne_avant != 0.0):
        impact_net = d.temps_gagne_apres - d.temps_gagne_avant
    else:
        impact_net = 0.0  # Old decisions without time data: no time impact
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
        impact_net=impact_net,
        sous_objectif_impacte=so_id,
        sous_objectif_id=so_id,
        impact_sous_objectif=so_impact if so_impact else None,
        temps_gagne_avant=d.temps_gagne_avant,
        temps_gagne_apres=d.temps_gagne_apres,
    )


@router.get("", response_model=List[DecisionOut])
async def get_historique(
    limite: int = Query(default=20, ge=1, le=1000),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Retourne les N dernières décisions de l'utilisateur."""
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil = profil_repo.charger(auth_user_id=user_id)
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
    user_id: str | None = Depends(get_optional_user),
):
    """Retourne les decisions paginées avec tri et recherche."""
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")
    profil = profil_repo.charger(auth_user_id=user_id)
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
    user_id: str | None = Depends(get_optional_user),
):
    """Retourne le rapport des actions effectuées par l'agent."""
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil = profil_repo.charger(auth_user_id=user_id)
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
    user_id: str | None = Depends(get_optional_user),
):
    """Supprime une décision et recalcule la probabilité actuelle."""
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    # 1. Charger la décision AVANT suppression pour connaître son impact
    decision = decision_repo.obtenir_par_id(decision_id, profil.id)
    if decision is None:
        raise HTTPException(status_code=404, detail="Décision introuvable.")

    # 2. Calculer l'impact_net (probabilite + temps)
    impact_net = 0.0
    if decision.probabilite_apres is not None and decision.probabilite_avant is not None:
        impact_net = decision.probabilite_apres - decision.probabilite_avant

    impact_temps = 0.0
    if decision.temps_gagne_apres is not None and decision.temps_gagne_avant is not None:
        impact_temps = decision.temps_gagne_apres - decision.temps_gagne_avant

    # 2b. Reverser la progression du sous-objectif.
    #
    # PROBLEME identifie en QA : la simple soustraction `progression -=
    # impact_sous_objectif` ne gere PAS le cas de l'overflow redistribution
    # (cf. evenement.py ligne 451-487). Si l'impact original de la decision
    # avait fait overflow le SO target a 100 et redistribue sur les autres
    # SO, la suppression ne reverse que le SO target — laissant les autres
    # SO avec leur progression boostee.
    #
    # FIX (Sprint QA pre-commercialisation) : si la decision avait potentiel
    # d'overflow (impact_so > seuil), on recompute TOUTES les SO progressions
    # en reappliquant chronologiquement les decisions restantes a partir de
    # leurs impact_sous_objectif stockes. Sinon on garde la simple soustraction.
    db = profil_repo._db
    if decision.sous_objectif_id and decision.impact_sous_objectif:
        try:
            so_row = db.conn.execute(
                "SELECT id, progression FROM sous_objectifs WHERE id = ?",
                (decision.sous_objectif_id,),
            ).fetchone()
            if so_row:
                # Heuristique : si impact_sous_objectif > 50%, l'overflow redistribution
                # a probablement ete declenchee. On recompute TOUS les SO.
                if abs(decision.impact_sous_objectif) > 50:
                    _recompute_so_progressions(db, profil.id, exclude_decision_id=decision_id)
                else:
                    new_prog = max(0, so_row["progression"] - decision.impact_sous_objectif)
                    db.conn.execute(
                        "UPDATE sous_objectifs SET progression = ? WHERE id = ?",
                        (new_prog, decision.sous_objectif_id),
                    )
                    db.conn.commit()
        except Exception:
            pass  # Best-effort : ne pas bloquer la suppression

    # 3. Supprimer la décision
    decision_repo.supprimer_par_id(decision_id, profil.id)

    # 4. Reverser l'impact temps de la décision supprimée
    profil.temps_gagne_jours = max(0, profil.temps_gagne_jours - impact_temps)

    # 5. Resync probabilite_actuelle sur progression (FIX C1).
    # Avant : on faisait probabilite_actuelle -= impact_net (IA delta), ce qui
    # divergait progressivement de progression (temps_gagne/temps_initial).
    # Apres : on calcule directement depuis temps_gagne_jours, garantissant
    # que les 2 valeurs restent toujours alignees.
    if profil.temps_initial_jours > 0:
        new_prob = round(
            (profil.temps_gagne_jours / profil.temps_initial_jours) * 100, 2
        )
    else:
        new_prob = max(PROB_MIN, min(PROB_MAX, profil.probabilite_actuelle - impact_net))
    profil.probabilite_actuelle = new_prob

    profil.marquer_modification()
    profil_repo.sauvegarder(profil)

    return {"detail": "Décision supprimée.", "probabilite_actuelle": new_prob, "temps_gagne_jours": profil.temps_gagne_jours}


@router.post("/recompute-so-progressions")
async def recompute_so_progressions_endpoint(
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Force le recalcul de toutes les progressions sous-objectifs pour
    l'utilisateur courant. Utile apres un DELETE qui aurait pu laisser
    des SO dans un etat incoherent (overflow redistribution non reverse).
    Strategy : sum(impact_sous_objectif) par SO depuis toutes les decisions
    restantes, clamped 0..100.
    """
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Profil introuvable.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    db = profil_repo._db
    _recompute_so_progressions(db, profil.id, exclude_decision_id=None)

    so_rows = db.conn.execute(
        "SELECT id, titre, progression FROM sous_objectifs WHERE user_id = ? ORDER BY ordre",
        (profil.id,),
    ).fetchall()
    return {
        "ok": True,
        "sous_objectifs": [
            {"id": r["id"], "titre": r["titre"], "progression": r["progression"]}
            for r in so_rows
        ],
    }
