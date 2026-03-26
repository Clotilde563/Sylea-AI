"""
Router FastAPI — Profil utilisateur.

Routes :
  GET  /api/profil               → charge le profil existant
  POST /api/profil               → crée ou met à jour le profil
  POST /api/profil/probabilite   → recalcule la probabilité (local + IA si dispo)
  DELETE /api/profil             → supprime le profil
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException

from sylea.core.models.user import ProfilUtilisateur, Objectif
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
from sylea.core.engine.probability import MoteurProbabilite

from api.schemas import ProfilIn, ProfilOut, ObjectifOut, ProbabiliteOut, ProbabiliteIn, JourneeIn, BienEtreScoresOut, QuestionsObjectifIn
from api.dependencies import get_profil_repo, get_decision_repo, get_moteur, get_agent, get_optional_user, get_db
from api.context_helper import format_device_context, build_full_user_context
from sylea.core.storage.database import DatabaseManager

router = APIRouter(prefix="/api/profil", tags=["profil"])


def _to_profil_out(profil: ProfilUtilisateur) -> ProfilOut:
    """Convertit un ProfilUtilisateur en ProfilOut Pydantic."""
    obj_out: Optional[ObjectifOut] = None
    if profil.objectif:
        obj_out = ObjectifOut(
            description=profil.objectif.description,
            categorie=profil.objectif.categorie,
            deadline=(
                profil.objectif.deadline.strftime("%Y-%m-%d")
                if profil.objectif.deadline else None
            ),
            probabilite_base=profil.objectif.probabilite_base,
            probabilite_calculee=profil.objectif.probabilite_calculee,
        )
    return ProfilOut(
        id=profil.id,
        nom=profil.nom,
        age=profil.age,
        profession=profil.profession,
        ville=profil.ville,
        situation_familiale=profil.situation_familiale,
        revenu_annuel=profil.revenu_annuel,
        patrimoine_estime=profil.patrimoine_estime,
        charges_mensuelles=profil.charges_mensuelles,
        objectif_financier=profil.objectif_financier,
        heures_travail=profil.heures_travail,
        heures_sommeil=profil.heures_sommeil,
        heures_loisirs=profil.heures_loisirs,
        heures_transport=profil.heures_transport,
        heures_objectif=profil.heures_objectif,
        niveau_sante=profil.niveau_sante,
        niveau_stress=profil.niveau_stress,
        niveau_energie=profil.niveau_energie,
        niveau_bonheur=profil.niveau_bonheur,
        competences=profil.competences,
        diplomes=profil.diplomes,
        langues=profil.langues,
        objectif=obj_out,
        probabilite_actuelle=profil.probabilite_actuelle,
        cree_le=profil.cree_le.isoformat(),
        mis_a_jour_le=profil.mis_a_jour_le.isoformat(),
        objectif_modifie_le=profil.objectif_modifie_le.isoformat() if profil.objectif_modifie_le else None,
    )


def _profil_in_to_model(data: ProfilIn, existing: Optional[ProfilUtilisateur] = None) -> ProfilUtilisateur:
    """Construit un ProfilUtilisateur depuis un ProfilIn Pydantic."""
    from datetime import datetime

    objectif = None
    if data.objectif:
        deadline = None
        if data.objectif.deadline:
            try:
                deadline = datetime.strptime(data.objectif.deadline, "%Y-%m-%d")
            except ValueError:
                try:
                    deadline = datetime.fromisoformat(data.objectif.deadline)
                except ValueError:
                    pass
        objectif = Objectif(
            description=data.objectif.description,
            categorie=data.objectif.categorie,
            deadline=deadline,
            probabilite_base=data.objectif.probabilite_base,
        )

    profil = ProfilUtilisateur(
        nom=data.nom,
        age=data.age,
        profession=data.profession,
        ville=data.ville,
        situation_familiale=data.situation_familiale,
        revenu_annuel=data.revenu_annuel,
        patrimoine_estime=data.patrimoine_estime,
        charges_mensuelles=data.charges_mensuelles,
        objectif_financier=data.objectif_financier,
        heures_travail=data.heures_travail,
        heures_sommeil=data.heures_sommeil,
        heures_loisirs=data.heures_loisirs,
        heures_transport=data.heures_transport,
        heures_objectif=data.heures_objectif,
        niveau_sante=data.niveau_sante,
        niveau_stress=data.niveau_stress,
        niveau_energie=data.niveau_energie,
        niveau_bonheur=data.niveau_bonheur,
        competences=data.competences,
        diplomes=data.diplomes,
        langues=data.langues,
        objectif=objectif,
        probabilite_actuelle=(existing.probabilite_actuelle if existing else 0.0),
    )

    # Conserver l'ID existant si mise à jour
    if existing:
        profil.id = existing.id
        profil.cree_le = existing.cree_le
        # Conserver objectif_modifie_le existant (ecrase par reset_historique si besoin)
        profil.objectif_modifie_le = existing.objectif_modifie_le
    else:
        # Nouveau profil : demarrer le chrono maintenant
        from datetime import datetime as _dt2
        profil.objectif_modifie_le = _dt2.now()

    return profil


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=ProfilOut)
async def get_profil(
    repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Retourne le profil existant (404 si aucun profil)."""
    if not repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")
    profil = repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")
    return _to_profil_out(profil)


@router.post("", response_model=ProfilOut)
async def upsert_profil(
    data: ProfilIn,
    repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Crée un nouveau profil ou met à jour l'existant."""
    existing = repo.charger(auth_user_id=user_id) if repo.existe(auth_user_id=user_id) else None
    try:
        profil = _profil_in_to_model(data, existing)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Réinitialise l’historique si l’objectif de vie a changé
    if data.reset_historique and existing:
        decision_repo.effacer_decisions_utilisateur(existing.id)
        profil.probabilite_actuelle = 0.0
        from datetime import datetime as _dt
        profil.objectif_modifie_le = _dt.now()
        # Supprimer aussi les sous-objectifs et tâches (reset complet)
        try:
            db = repo._db
            db.conn.execute("DELETE FROM sous_objectifs WHERE user_id = ?", (existing.id,))
            db.conn.execute("DELETE FROM taches_quotidiennes WHERE user_id = ?", (existing.id,))
            db.conn.commit()
        except Exception:
            pass

    profil.marquer_modification()
    repo.sauvegarder(profil, auth_user_id=user_id)
    return _to_profil_out(profil)


@router.post("/probabilite", response_model=ProbabiliteOut)
async def recalculer_probabilite(
    data: ProbabiliteIn,
    repo: ProfilRepository = Depends(get_profil_repo),
    moteur: MoteurProbabilite = Depends(get_moteur),
    agent=Depends(get_agent),
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """
    Recalcule la probabilité de réussite.

    1. Calcul déterministe local (MoteurProbabilite)
    2. Enrichissement IA si l'agent Claude est disponible
    """
    if not repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")
    profil = repo.charger(auth_user_id=user_id)
    if profil is None or not profil.objectif:
        raise HTTPException(status_code=400, detail="Profil ou objectif manquant.")

    # Calcul local (synchrone mais rapide)
    prob_locale = moteur.calculer_probabilite_initiale(profil)
    full_ctx = build_full_user_context(db, user_id, profil)

    if agent is not None:
        try:
            # Appel bloquant → thread séparé
            device_context = format_device_context(data.contexte_appareil)
            analyse = await asyncio.to_thread(
                agent.analyser_probabilite, profil, prob_locale,
                device_context=device_context,
                full_context=full_ctx,
            )
            # Stocker dans probabilite_calculee (interne pour calcul temps)
            profil.objectif.probabilite_calculee = analyse.probabilite
            profil.objectif.probabilite_base = 0.1  # cosmetique (jauge)
            profil.marquer_modification()
            repo.sauvegarder(profil)
            return ProbabiliteOut(
                probabilite=analyse.probabilite,
                resume=analyse.resume,
                points_forts=analyse.points_forts,
                points_faibles=analyse.points_faibles,
                facteurs_cles=analyse.facteurs_cles,
                conseil_prioritaire=analyse.conseil_prioritaire,
            )
        except Exception:
            pass  # Fallback sur calcul local

    # Fallback local
    profil.objectif.probabilite_calculee = prob_locale
    profil.objectif.probabilite_base = 0.1  # cosmetique (jauge)
    profil.marquer_modification()
    repo.sauvegarder(profil)
    return ProbabiliteOut(
        probabilite=prob_locale,
        resume="Probabilité calculée localement (mode sans IA).",
        points_forts=[],
        points_faibles=[],
        facteurs_cles=[],
        conseil_prioritaire="Configurez votre clé ANTHROPIC_API_KEY pour une analyse approfondie.",
    )




# ── Génération de questions personnalisées ────────────────────────────────────

_QUESTIONS_FALLBACK = [
    "Depuis combien de temps travaillez-vous sur cet objectif ?",
    "Quelles comp\u00e9tences ou ressources poss\u00e9dez-vous d\u00e9j\u00e0 pour l'atteindre ?",
    "Quels sont les principaux obstacles que vous anticipez ?",
    "Avez-vous d\u00e9j\u00e0 tent\u00e9 d'atteindre un objectif similaire ? Qu'est-ce qui a bloqu\u00e9 ?",
    "Combien d'heures par semaine pouvez-vous consacrer \u00e0 cet objectif ?",
    "Avez-vous un r\u00e9seau ou des alli\u00e9s qui peuvent vous soutenir ?",
    "Quelles ressources (financi\u00e8res, mat\u00e9rielles, humaines) vous manquent ?",
    "Comment votre entourage per\u00e7oit-il cet objectif ?",
    "Quel impact cet objectif aura-t-il sur les autres domaines de votre vie ?",
    "Qu'est-ce qui vous a emp\u00each\u00e9 d'agir plus t\u00f4t ?",
    "Comment mesurerez-vous que vous avez atteint votre objectif ?",
    "Quel est votre plan de secours si vous ne l'atteignez pas dans les d\u00e9lais ?",
]


async def _generer_questions_claude(description: str, device_context: str = "", full_context: str = "") -> list:
    """G\u00e9n\u00e8re 12 questions personnalis\u00e9es via Claude Haiku."""
    import os, json, re as _re
    import anthropic as _anthropic

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY absente")

    client = _anthropic.Anthropic(api_key=key)
    prompt = (
        f'Tu es un coach de vie expert. L\'utilisateur a cet objectif de vie :\n"{description}"\n\n'
        "G\u00e9n\u00e8re exactement 12 questions ouvertes et personnalis\u00e9es pour mieux comprendre sa situation "
        "et l'aider \u00e0 atteindre cet objectif. Explore : ses ressources actuelles, ses obstacles, "
        "son historique avec cet objectif, son r\u00e9seau de soutien, ses motivations profondes, "
        "les risques potentiels et les prochaines \u00e9tapes concrètes.\n\n"
        "R\u00e9ponds UNIQUEMENT avec un tableau JSON de 12 cha\u00eenes en fran\u00e7ais, sans aucun markdown.\n"
        'Format exact : ["question 1", "question 2", ..., "question 12"]'
        f'\n{full_context}'
        f'{device_context}'
    )
    msg = await asyncio.to_thread(
        lambda: client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
    )
    text = msg.content[0].text.strip()
    match = _re.search(r'\[.*\]', text, _re.DOTALL)
    if not match:
        raise ValueError("JSON invalide")
    questions = json.loads(match.group())
    if not isinstance(questions, list) or len(questions) < 6:
        raise ValueError("R\u00e9ponse invalide")
    return [str(q) for q in questions[:12]]


@router.post("/generer-questions", response_model=List[str])
async def generer_questions(
    data: QuestionsObjectifIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """G\u00e9n\u00e8re 12 questions personnalis\u00e9es bas\u00e9es sur l'objectif de l'utilisateur."""
    full_ctx = build_full_user_context(db, user_id)
    try:
        return await _generer_questions_claude(
            data.description,
            device_context=format_device_context(data.contexte_appareil),
            full_context=full_ctx,
        )
    except Exception:
        return _QUESTIONS_FALLBACK


# ── Analyse journée ───────────────────────────────────────────────────────────

def _analyser_journee_heuristique(description: str) -> dict:
    """Analyse heuristique de la journée basée sur les mots-clés."""
    import unicodedata

    def strip_accents(s: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFD", s)
            if unicodedata.category(c) != "Mn"
        )

    desc = strip_accents(description.lower())

    stress_pos  = ["stresse", "anxieux", "nerveux", "angoiss", "pression", "debord", "surcharg"]
    stress_neg  = ["calme", "serein", "tranquill", "detend", "relax"]
    energie_pos = ["dynamique", "motiv", "energie", "actif", "productif"]
    energie_neg = ["fatigu", "epuis", "endorm", "las", "lent"]
    sante_pos   = ["en forme", "bonne sante", "bien physiquement"]
    sante_neg   = ["malade", "douleur", "blesse", "fievre", "souffr"]
    bonheur_pos = ["heureux", "joyeux", "content", "satisfait", "super", "positif"]
    bonheur_neg = ["triste", "deprim", "malheur", "difficile"]

    def score(pos, neg, base):
        s = float(base)
        for w in pos:
            if strip_accents(w) in desc:
                s = min(10.0, s + 1.5)
        for w in neg:
            if strip_accents(w) in desc:
                s = max(1.0, s - 1.5)
        return max(1, min(10, round(s)))

    return {
        "niveau_sante":   score(sante_pos,   sante_neg,   7),
        "niveau_stress":  score(stress_pos,  stress_neg,  5),
        "niveau_energie": score(energie_pos, energie_neg, 6),
        "niveau_bonheur": score(bonheur_pos, bonheur_neg, 6),
    }


async def _analyser_journee_claude(description: str, device_context: str = "", full_context: str = "") -> dict:
    """Analyse par Claude Haiku (nécessite ANTHROPIC_API_KEY)."""
    import os, json, re
    import anthropic as _anthropic

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY absente")

    client = _anthropic.Anthropic(api_key=key)
    prompt = (
        "Analyse cette description de journée et évalue 4 indicateurs de 1 à 10.\n"
        "Réponds UNIQUEMENT avec du JSON valide, sans aucun markdown.\n\n"
        f'Journée : "{description}"\n\n'
        'Format exact : {"niveau_sante": X, "niveau_stress": X, "niveau_energie": X, "niveau_bonheur": X}\n'
        "(1=très mauvais, 10=excellent ; stress élevé = score élevé)"
        f'\n{full_context}'
        f'{device_context}'
    )
    msg = await asyncio.to_thread(
        lambda: client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
    )
    text = msg.content[0].text.strip()
    match = re.search(r"\{[^}]+\}", text)
    if not match:
        raise ValueError("JSON invalide")
    scores = json.loads(match.group())
    return {
        "niveau_sante":   max(1, min(10, int(scores.get("niveau_sante",   7)))),
        "niveau_stress":  max(1, min(10, int(scores.get("niveau_stress",  5)))),
        "niveau_energie": max(1, min(10, int(scores.get("niveau_energie", 6)))),
        "niveau_bonheur": max(1, min(10, int(scores.get("niveau_bonheur", 6)))),
    }


@router.post("/analyser-journee", response_model=BienEtreScoresOut)
async def analyser_journee(
    data: JourneeIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Analyse la description d'une journée et retourne des scores bien-être (1-10)."""
    full_ctx = build_full_user_context(db, user_id)
    try:
        scores = await _analyser_journee_claude(
            data.description,
            device_context=format_device_context(data.contexte_appareil),
            full_context=full_ctx,
        )
        return BienEtreScoresOut(**scores)
    except Exception:
        return BienEtreScoresOut(**_analyser_journee_heuristique(data.description))

@router.delete("")
async def supprimer_profil(
    repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Supprime le profil et toutes ses décisions."""
    if not repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil à supprimer.")
    profil = repo.charger(auth_user_id=user_id)
    if profil:
        repo.supprimer(profil.id, auth_user_id=user_id)
    return {"detail": "Profil supprimé."}
