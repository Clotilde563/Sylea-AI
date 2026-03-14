"""
Router FastAPI -- Enregistrement d'evenements.

Routes :
  POST /api/evenement/analyser   -> analyse l'impact d'un evenement via IA
  POST /api/evenement/confirmer  -> enregistre l'evenement comme Decision
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException

from sylea.core.models.decision import Decision, OptionDilemme
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository

from api.schemas import (
    EvenementIn,
    AnalyseEvenementOut,
    ConfirmerEvenementIn,
    DecisionOut,
    OptionDilemmeOut,
)
from api.dependencies import get_profil_repo, get_decision_repo

router = APIRouter(prefix="/api/evenement", tags=["evenement"])


# -- Helpers ----------------------------------------------------------------

def _decision_to_out(d: Decision, sous_objectif_impacte: str | None = None) -> DecisionOut:
    opts = [
        OptionDilemmeOut(
            id=o.id,
            description=o.description,
            impact_score=o.impact_score,
            explication_impact=o.explication_impact,
            est_delegable=o.est_delegable,
            temps_estime=o.temps_estime,
        )
        for o in d.options
    ]
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


# -- Analyse heuristique locale (fallback) ----------------------------------

def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


def _analyser_evenement_local(description: str, objectif_desc: str) -> dict:
    """Heuristique simple par mots-cles."""
    desc = _strip_accents(description.lower())

    positifs = [
        "promotion", "augmentation", "formation", "diplome", "certif",
        "investis", "economis", "epargn", "gagne", "reussi", "accept",
        "embauche", "contrat", "partenariat", "mentor", "opportunit",
        "progres", "amelior", "rencontr", "reseau", "lance", "cree",
        "marathon", "sport", "sante", "gueris", "termine",
    ]
    negatifs = [
        "licencie", "vire", "perdu", "echec", "refuse", "rejet",
        "dette", "depense", "accident", "maladie", "bless",
        "rupture", "divorce", "conflit", "demission", "burn",
        "stress", "abandon", "annul", "retard",
    ]

    score_pos = sum(1 for w in positifs if w in desc)
    score_neg = sum(1 for w in negatifs if w in desc)

    if score_pos > score_neg:
        impact = min(1.5, 0.1 + score_pos * 0.3)
        resume = "Evenement positif detecte."
        explication = "Cet evenement semble favorable a votre objectif."
        conseil = "Capitalisez sur cet elan positif."
    elif score_neg > score_pos:
        impact = max(-1.5, -(0.1 + score_neg * 0.3))
        resume = "Evenement negatif detecte."
        explication = "Cet evenement pourrait ralentir votre progression."
        conseil = "Ne vous decouragez pas, chaque obstacle est une lecon."
    else:
        impact = 0.1  # leger positif par defaut
        resume = "Impact neutre detecte."
        explication = "L'impact de cet evenement est difficile a evaluer automatiquement."
        conseil = "Configurez votre cle API Anthropic pour une analyse approfondie."

    return {
        "resume": resume,
        "impact_probabilite": round(impact, 2),
        "explication": explication,
        "conseil": conseil,
    }


# -- Analyse Claude --------------------------------------------------------

async def _analyser_evenement_claude(
    description: str,
    objectif_desc: str,
    objectif_cat: str,
    prob_actuelle: float,
    prob_calculee: float = 0.0,
    profession: str = "",
) -> dict:
    """Analyse via Claude Haiku."""
    import anthropic as _anthropic

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY absente")

    client = _anthropic.Anthropic(api_key=key)
    # Calculer le temps estime
    prob_totale = max(0.01, min(99.99, prob_actuelle + prob_calculee))
    temps_j = min(73000, max(1, round(900 * ((100 - prob_totale) / prob_totale) ** 0.675)))
    temps_ans = temps_j // 365
    temps_mois = (temps_j % 365) // 30
    temps_str = f"{temps_ans} ans {temps_mois} mois" if temps_ans > 0 else f"{temps_mois} mois"

    prompt = (
        "Tu es un analyste expert en developpement personnel et objectifs de vie.\n\n"
        "CONTEXTE :\n"
        f"- Objectif de vie : \"{objectif_desc}\"\n"
        f"- Categorie : {objectif_cat}\n"
        f"- Profession : {profession}\n"
        f"- Temps estime restant : {temps_str}\n"
        f"- Progression actuelle (jauge) : {prob_actuelle:.1f}%\n\n"
        f"EVENEMENT RAPPORTE :\n\"{description}\"\n\n"
        "REGLES D'ANALYSE :\n"
        "1. REALISATION DE L'OBJECTIF : Si l'utilisateur declare que l'objectif "
        "est ATTEINT ou realise, tu DOIS donner un impact_probabilite entre "
        f"+{max(90, round(99 - prob_actuelle))} et +{max(95, round(99.5 - prob_actuelle))} "
        "pour que la jauge atteigne quasi 100%. C'est OBLIGATOIRE.\n"
        f"2. PROPORTIONNALITE : L'impact doit etre proportionnel au temps restant ({temps_str}) :\n"
        "   - Evenement mineur/quotidien : +/-0.05 a +/-0.3\n"
        "   - Evenement significatif (promotion, certification, etc.) : +/-0.3 a +/-2.0\n"
        "   - Evenement majeur (financement, changement de carriere) : +/-2.0 a +/-5.0\n"
        "3. COHERENCE : Un petit evenement ne peut pas avoir un impact de plusieurs "
        f"pourcents sur un objectif estime a {temps_str}.\n\n"
        "Reponds UNIQUEMENT avec du JSON valide, sans aucun markdown :\n"
        '{"resume": "...", "impact_probabilite": <float>, "explication": "...", "conseil": "..."}'
    )

    msg = await asyncio.to_thread(
        lambda: client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
    )
    text = msg.content[0].text.strip()
    match = re.search(r"\{[^}]+\}", text, re.DOTALL)
    if not match:
        raise ValueError("JSON invalide")
    data = json.loads(match.group())
    return {
        "resume": str(data.get("resume", "")),
        "impact_probabilite": float(data.get("impact_probabilite", 0.5)),
        "explication": str(data.get("explication", "")),
        "conseil": str(data.get("conseil", "")),
    }


# -- Routes ----------------------------------------------------------------

@router.post("/analyser", response_model=AnalyseEvenementOut)
async def analyser_evenement(
    data: EvenementIn,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
):
    """Analyse l'impact d'un evenement sur l'objectif de vie."""
    if not profil_repo.existe():
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger()
    if profil is None or not profil.objectif:
        raise HTTPException(status_code=400, detail="Profil ou objectif manquant.")

    try:
        result = await _analyser_evenement_claude(
            description=data.description,
            objectif_desc=profil.objectif.description,
            objectif_cat=profil.objectif.categorie,
            prob_actuelle=profil.probabilite_actuelle,
            prob_calculee=profil.objectif.probabilite_calculee,
            profession=profil.profession or "",
        )
        return AnalyseEvenementOut(**result)
    except Exception:
        result = _analyser_evenement_local(data.description, profil.objectif.description)
        return AnalyseEvenementOut(**result)


@router.post("/confirmer", response_model=DecisionOut)
async def confirmer_evenement(
    data: ConfirmerEvenementIn,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
):
    """Enregistre l'evenement et met a jour la probabilite."""
    if not profil_repo.existe():
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger()
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    # Creer une option unique representant l'evenement
    opt_event = OptionDilemme(
        description=data.description,
        impact_score=data.impact_probabilite,
        explication_impact=data.resume,
    )

    prob_avant = profil.probabilite_actuelle
    prob_apres = prob_avant + data.impact_probabilite
    prob_apres = max(0.01, min(99.9, prob_apres))

    # Creer la decision (type evenement = question prefixee)
    decision = Decision(
        user_id=profil.id,
        question=f"[Evenement] {data.description}",
        options=[opt_event],
        probabilite_avant=prob_avant,
        option_choisie_id=opt_event.id,
        probabilite_apres=prob_apres,
    )

    decision_repo.sauvegarder(decision)

    # Mettre a jour le profil
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
            impact_so = abs(data.impact_probabilite) * 5
            new_prog = min(100, max(0, so_actif["progression"] + impact_so))
            db.conn.execute(
                "UPDATE sous_objectifs SET progression = ? WHERE id = ?",
                (new_prog, so_actif["id"]),
            )
            db.conn.commit()
            so_titre_impacte = so_actif["titre"]
    except Exception:
        pass

    return _decision_to_out(decision, sous_objectif_impacte=so_titre_impacte)
