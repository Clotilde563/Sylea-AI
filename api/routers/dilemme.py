"""
Router FastAPI — Dilemme décisionnel.

Routes :
  POST /api/dilemme/analyser  → analyse question + options A/B (Claude IA)
  POST /api/dilemme/choisir   → commit du choix → sauvegarde Decision
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from sylea.core.models.user import ProfilUtilisateur
from sylea.core.models.decision import Decision, OptionDilemme
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository

from api.schemas import (
    DilemmeIn,
    ChoixIn,
    AnalyseDilemmeOut,
    AnalyseOptionOut,
    DecisionOut,
    OptionDilemmeOut,
)
from api.dependencies import get_profil_repo, get_decision_repo, get_agent

router = APIRouter(prefix="/api/dilemme", tags=["dilemme"])


def _option_to_out(opt: OptionDilemme) -> OptionDilemmeOut:
    return OptionDilemmeOut(
        id=opt.id,
        description=opt.description,
        impact_score=opt.impact_score,
        explication_impact=opt.explication_impact,
        est_delegable=opt.est_delegable,
        temps_estime=opt.temps_estime,
    )


def _decision_to_out(d: Decision, sous_objectif_impacte: str | None = None) -> DecisionOut:
    opts = [_option_to_out(o) for o in d.options]
    chosen = d.get_option_choisie()
    return DecisionOut(
        id=d.id,
        user_id=d.user_id,
        question=d.question,
        options=opts,
        probabilite_avant=d.probabilite_avant,
        option_choisie_id=d.option_choisie_id,
        probabilite_apres=d.probabilite_apres,
        action_agent=None,
        cree_le=d.cree_le.isoformat(),
        option_choisie_description=chosen.description if chosen else None,
        impact_net=(
            (d.probabilite_apres - d.probabilite_avant)
            if d.probabilite_apres is not None else None
        ),
        sous_objectif_impacte=sous_objectif_impacte,
    )


@router.post("/analyser", response_model=AnalyseDilemmeOut)
async def analyser_dilemme(
    data: DilemmeIn,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    agent=Depends(get_agent),
):
    """
    Analyse un dilemme via l'IA Claude.

    Retourne pros/cons + impact sur la probabilité pour N options.
    Si pas d'agent Claude disponible, retourne une analyse basique locale.
    """
    if not profil_repo.existe():
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil: ProfilUtilisateur = profil_repo.charger()
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    # Rétrocompat : si option_a/option_b fournis, les convertir en options
    options_list = list(data.options) if data.options else []
    if not options_list and data.option_a and data.option_b:
        options_list = [data.option_a, data.option_b]
    if len(options_list) < 2:
        raise HTTPException(status_code=400, detail="Au moins 2 options requises.")

    lettres = [chr(65 + i) for i in range(len(options_list))]

    if agent is not None:
        try:
            analyse = await asyncio.to_thread(
                agent.analyser_dilemme,
                profil,
                data.question,
                options_list,
            )
            out_options = []
            for i, (l, desc) in enumerate(zip(lettres, options_list)):
                opt = analyse.options[i] if i < len(analyse.options) else None
                out_options.append(AnalyseOptionOut(
                    lettre=l,
                    description=desc,
                    pros=opt.pros if opt else [],
                    cons=opt.cons if opt else [],
                    impact_probabilite=opt.impact_probabilite if opt else 0.0,
                    resume=opt.resume if opt else "",
                ))
            return AnalyseDilemmeOut(
                question=data.question,
                options=out_options,
                verdict=analyse.verdict,
                option_recommandee=analyse.option_recommandee,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Analyse IA indisponible : {exc}",
            ) from exc

    # Mode sans IA : analyse locale neutre
    out_options = []
    for l, desc in zip(lettres, options_list):
        out_options.append(AnalyseOptionOut(
            lettre=l,
            description=desc,
            pros=["Option à explorer"],
            cons=["Analyse IA non disponible"],
            impact_probabilite=0.0,
            resume="Configurez votre clé API pour une analyse détaillée.",
        ))
    return AnalyseDilemmeOut(
        question=data.question,
        options=out_options,
        verdict="Aucune clé API Anthropic configurée. Basez votre choix sur votre intuition.",
        option_recommandee="A",
    )


@router.post("/choisir", response_model=DecisionOut)
async def choisir_option(
    data: ChoixIn,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
):
    """
    Enregistre le choix de l'utilisateur et met à jour sa probabilité.

    Crée une Decision dans la base, met à jour probabilite_actuelle du profil.
    """
    if not profil_repo.existe():
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil: ProfilUtilisateur = profil_repo.charger()
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    # Trouver l'option choisie par lettre
    analyse_choisie = None
    for opt in data.options:
        if opt.lettre == data.choix:
            analyse_choisie = opt
            break
    if analyse_choisie is None:
        raise HTTPException(status_code=400, detail=f"Option '{data.choix}' non trouvée.")

    # Construire les OptionDilemme
    all_opts = []
    opt_choisie_id = None
    for opt in data.options:
        od = OptionDilemme(
            description=opt.description,
            impact_score=opt.impact_probabilite,
            explication_impact=opt.resume,
        )
        if opt.lettre == data.choix:
            opt_choisie_id = od.id
        all_opts.append(od)

    prob_avant = profil.probabilite_actuelle
    prob_apres = prob_avant + analyse_choisie.impact_probabilite
    prob_apres = max(0.01, min(99.9, prob_apres))

    # Créer la décision
    decision = Decision(
        user_id=profil.id,
        question=data.question,
        options=all_opts,
        probabilite_avant=prob_avant,
        option_choisie_id=opt_choisie_id,
        probabilite_apres=prob_apres,
    )

    # Sauvegarder
    decision_repo.sauvegarder(decision)

    # Mettre à jour le profil
    profil.probabilite_actuelle = prob_apres
    profil.marquer_modification()
    profil_repo.sauvegarder(profil)

    # Mettre a jour le sous-objectif actif uniquement
    so_titre_impacte = None
    try:
        db = profil_repo._db
        so_actif = db.conn.execute(
            "SELECT id, titre, progression FROM sous_objectifs WHERE user_id = ? AND progression < 100 ORDER BY ordre LIMIT 1",
            (profil.id,),
        ).fetchone()
        if so_actif:
            impact_so = abs(analyse_choisie.impact_probabilite) * 5
            new_prog = min(100, max(0, so_actif["progression"] + impact_so))
            db.conn.execute(
                "UPDATE sous_objectifs SET progression = ? WHERE id = ?",
                (new_prog, so_actif["id"]),
            )
            db.conn.commit()
            so_titre_impacte = so_actif["titre"]
    except Exception:
        pass  # Ne pas bloquer si la table n'existe pas encore

    return _decision_to_out(decision, sous_objectif_impacte=so_titre_impacte)
