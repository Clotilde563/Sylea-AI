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
import base64
import os
import uuid as _uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sylea.core.models.user import ProfilUtilisateur, Objectif
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
from sylea.core.engine.probability import MoteurProbabilite

from api.schemas import ProfilIn, ProfilOut, ObjectifOut, ProbabiliteOut, ProbabiliteIn, JourneeIn, BienEtreScoresOut, QuestionsObjectifIn
from api.dependencies import get_profil_repo, get_decision_repo, get_moteur, get_agent, get_optional_user, get_db
from api.context_helper import format_device_context, build_full_user_context
from sylea.core.storage.database import DatabaseManager

router = APIRouter(prefix="/api/profil", tags=["profil"])

# Photos uploads dir (gitignore via /data ?)
_PHOTOS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "profil_photos"
_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
_ALLOWED_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


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
        temps_initial_jours=profil.temps_initial_jours,
        temps_gagne_jours=profil.temps_gagne_jours,
        cree_le=profil.cree_le.isoformat(),
        mis_a_jour_le=profil.mis_a_jour_le.isoformat(),
        objectif_modifie_le=profil.objectif_modifie_le.isoformat() if profil.objectif_modifie_le else None,
        photo_url=getattr(profil, "photo_url", None),
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
        temps_initial_jours=(existing.temps_initial_jours if existing else 0),
        temps_gagne_jours=(existing.temps_gagne_jours if existing else 0.0),
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
        profil.temps_initial_jours = 0
        profil.temps_gagne_jours = 0.0
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


def _insert_recalc_marker(db: DatabaseManager, profil_id: str, prob_actuelle: float) -> None:
    """Insere une decision-marker pour combler le gap entre la derniere decision
    historique (qui peut etre vieille) et la prob_actuelle apres recalc.

    Logique : verifier la derniere decision pour ce profil. Si son
    probabilite_apres differe de prob_actuelle, inserer un marker.

    Permet a Stats Chart2 de converger vers prob_actuelle (alignment
    Dashboard <-> Stats).
    """
    try:
        last = db.conn.execute(
            "SELECT probabilite_apres FROM decisions WHERE user_id = ? "
            "ORDER BY cree_le DESC LIMIT 1",
            (profil_id,),
        ).fetchone()
        last_apres = float(last[0]) if last and last[0] is not None else 0.0
        if abs(prob_actuelle - last_apres) < 0.01:
            return  # Pas de gap, skip
        import uuid
        from datetime import datetime as _dt, timezone as _tz
        db.conn.execute(
            "INSERT INTO decisions (id, user_id, question, options_json, "
            "probabilite_avant, option_choisie_id, probabilite_apres, "
            "action_agent_json, cree_le, impact_temporel_jours) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                profil_id,
                "[Recalcul probabilite]",
                "[]",
                last_apres,
                None,
                prob_actuelle,
                None,
                _dt.now(_tz.utc).isoformat(),
                None,
            ),
        )
        db.conn.commit()
    except Exception:
        pass


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
    3. Insere un marker dans l'historique pour cohérence visualisation
    """
    if not repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")
    profil = repo.charger(auth_user_id=user_id)
    if profil is None or not profil.objectif:
        raise HTTPException(status_code=400, detail="Profil ou objectif manquant.")

    # Snapshot ancienne prob pour marker historique (cohérence Stats Chart2)
    _prob_avant_recalc = profil.probabilite_actuelle or 0.0

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
            # Stocker le résultat IA dans probabilite_actuelle (valeur totale unique)
            # probabilite_calculee garde la base IA (invisible au frontend, utilisé pour recalcul historique)
            profil.probabilite_actuelle = analyse.probabilite
            profil.objectif.probabilite_calculee = analyse.probabilite
            profil.objectif.probabilite_base = 0
            # Convert probability to initial time estimate (one last use of the formula)
            prob_for_time = max(0.01, min(99.99, analyse.probabilite))
            temps_initial = round(900 * ((100 - prob_for_time) / prob_for_time) ** 0.675)
            old_initial = profil.temps_initial_jours or 0
            profil.temps_initial_jours = temps_initial
            # Scale temps_gagne proportionally to keep the same gauge percentage
            if old_initial > 0 and profil.temps_gagne_jours:
                ratio = profil.temps_gagne_jours / old_initial
                profil.temps_gagne_jours = round(ratio * temps_initial, 1)
            elif profil.temps_gagne_jours is None:
                profil.temps_gagne_jours = 0.0
            profil.marquer_modification()
            repo.sauvegarder(profil, auth_user_id=user_id)
            # Marker historique pour Stats Chart2 (sinon courbe reste sur ancienne valeur)
            _insert_recalc_marker(db, profil.id, analyse.probabilite)
            return ProbabiliteOut(
                probabilite=analyse.probabilite,
                temps_initial_jours=temps_initial,
                resume=analyse.resume,
                points_forts=analyse.points_forts,
                points_faibles=analyse.points_faibles,
                facteurs_cles=analyse.facteurs_cles,
                conseil_prioritaire=analyse.conseil_prioritaire,
            )
        except Exception:
            pass  # Fallback sur calcul local

    # Fallback local — stocker dans probabilite_actuelle
    # probabilite_calculee garde la base (invisible au frontend, utilisé pour recalcul historique)
    profil.probabilite_actuelle = prob_locale
    profil.objectif.probabilite_calculee = prob_locale
    profil.objectif.probabilite_base = 0
    # Convert probability to initial time estimate (one last use of the formula)
    prob_for_time_local = max(0.01, min(99.99, prob_locale))
    temps_initial_local = round(900 * ((100 - prob_for_time_local) / prob_for_time_local) ** 0.675)
    old_initial_local = profil.temps_initial_jours or 0
    profil.temps_initial_jours = temps_initial_local
    # Scale temps_gagne proportionally to keep the same gauge percentage
    if old_initial_local > 0 and profil.temps_gagne_jours:
        ratio = profil.temps_gagne_jours / old_initial_local
        profil.temps_gagne_jours = round(ratio * temps_initial_local, 1)
    elif profil.temps_gagne_jours is None:
        profil.temps_gagne_jours = 0.0
    profil.marquer_modification()
    repo.sauvegarder(profil, auth_user_id=user_id)
    # Marker historique pour cohérence (fallback local)
    _insert_recalc_marker(db, profil.id, prob_locale)
    return ProbabiliteOut(
        probabilite=prob_locale,
        temps_initial_jours=temps_initial_local,
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


# ─────────────────────────────────────────────────────────────────────────────
# Backfill snapshots historiques (FIX C3 — Sprint QA pre-commercialisation)
#
# Probleme : les decisions creees avant la migration `temps_gagne_avant/apres`
# (ou avec un bug de population) ont leurs snapshots a 0. Du coup la page
# Historique affiche "0j -> 0j" partout et le Chart 2 etait plat avant le
# fix Sprint 4. On reconstruit les snapshots chronologiquement en simulant
# l'enchainement des impacts.
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/backfill-snapshots")
async def backfill_decision_snapshots(
    repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Ré-écrit chronologiquement temps_gagne_avant et temps_gagne_apres pour
    toutes les décisions de l'utilisateur.

    Algo :
      1. Charge toutes les decisions, ordre chronologique ascendant.
      2. Pour chaque decision i :
         - tg_avant = somme des impact_jours des decisions [0..i-1]
         - tg_apres = tg_avant + impact_jours_i
         (impact_jours est dérivé de impact_net + temps_initial si nécessaire)
      3. Sauvegarde chaque decision.
      4. Recalcule profil.probabilite_actuelle = tg_total / temps_initial * 100
         pour synchroniser (FIX C1).

    Idempotent : appelable plusieurs fois sans degradation.
    """
    if not repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Profil introuvable.")
    profil = repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    # Charge TOUTES les decisions (limit elevee pour eviter la pagination ici)
    db = repo._db
    rows = db.conn.execute(
        "SELECT * FROM decisions WHERE user_id = ? ORDER BY cree_le ASC",
        (profil.id,),
    ).fetchall()

    if not rows:
        return {
            "ok": True,
            "decisions_traitees": 0,
            "decisions_total": 0,
            "decisions_corrigees": 0,
            "temps_gagne_final": profil.temps_gagne_jours,
            "probabilite_finale": profil.probabilite_actuelle,
            "progression_pct": round(
                (profil.temps_gagne_jours / (profil.temps_initial_jours or 1)) * 100, 2
            ) if profil.temps_initial_jours else 0.0,
        }

    temps_initial = profil.temps_initial_jours or 0
    target_total = float(profil.temps_gagne_jours or 0)
    n = len(rows)

    # Calcul des poids par decision : utilise probabilite_apres - probabilite_avant
    # (delta IA en %) comme signal. Si tous les deltas sont 0, on distribue
    # equitablement sur les decisions.
    weights: list[float] = []
    for r in rows:
        try:
            pa = float(r["probabilite_avant"] or 0)
            pap = float(r["probabilite_apres"] or 0)
            delta_prob = pap - pa
        except (KeyError, TypeError):
            delta_prob = 0.0
        # Convert delta_prob (%) en jours equivalents ; on prend la valeur
        # absolue car on ne veut pas de poids negatifs (le scaling final
        # gere le signe via target_total).
        w = abs(delta_prob) * temps_initial / 100.0 if temps_initial > 0 else 0.0
        weights.append(w)

    sum_w = sum(weights)
    if sum_w > 0:
        # Scale les weights pour que la somme = target_total
        scale = target_total / sum_w
        impacts = [w * scale for w in weights]
    else:
        # Distribution equitable
        per = (target_total / n) if n > 0 else 0.0
        impacts = [per] * n

    cumul_temps = 0.0
    n_corrigees = 0
    for row, impact in zip(rows, impacts):
        tg_avant_new = round(cumul_temps, 2)
        tg_apres_new = round(cumul_temps + impact, 2)
        # Clamp dans [0, temps_initial]
        if temps_initial > 0:
            tg_avant_new = max(0.0, min(float(temps_initial), tg_avant_new))
            tg_apres_new = max(0.0, min(float(temps_initial), tg_apres_new))

        # Detecter si la mise a jour est necessaire
        old_avant = float(row["temps_gagne_avant"] or 0)
        old_apres = float(row["temps_gagne_apres"] or 0)
        if abs(old_avant - tg_avant_new) > 0.01 or abs(old_apres - tg_apres_new) > 0.01:
            db.conn.execute(
                "UPDATE decisions SET temps_gagne_avant = ?, temps_gagne_apres = ? "
                "WHERE id = ?",
                (tg_avant_new, tg_apres_new, row["id"]),
            )
            n_corrigees += 1

        cumul_temps += impact

    db.conn.commit()

    # Re-sync profil sur la valeur target (qui est deja temps_gagne_jours)
    if temps_initial > 0:
        profil.probabilite_actuelle = round(
            (target_total / temps_initial) * 100, 2
        )
    profil.marquer_modification()
    repo.sauvegarder(profil)

    return {
        "ok": True,
        "decisions_total": n,
        "decisions_traitees": n,
        "decisions_corrigees": n_corrigees,
        "temps_gagne_final": round(target_total, 2),
        "probabilite_finale": profil.probabilite_actuelle,
        "progression_pct": round(
            (target_total / temps_initial) * 100, 2
        ) if temps_initial > 0 else 0.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Photo de profil
# ─────────────────────────────────────────────────────────────────────────────

class PhotoUploadOut(BaseModel):
    photo_url: str
    filename: str


@router.post("/photo", response_model=PhotoUploadOut)
async def upload_photo(
    file: UploadFile = File(...),
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Upload de la photo de profil utilisateur.

    Restrictions :
      - Auth requise
      - Extensions autorisees : jpg, jpeg, png, webp, gif
      - Max 5 MB
      - Stockee dans data/profil_photos/{user_id}_{uuid}.{ext}
      - Retourne l'URL relative pour servir via GET /api/profil/photo/{filename}
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    # Validation extension
    fname = file.filename or "photo"
    ext = os.path.splitext(fname)[1].lower()
    if ext not in _ALLOWED_PHOTO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Extension non autorisee. Autorisees : {', '.join(sorted(_ALLOWED_PHOTO_EXTS))}",
        )

    # Read content + check size
    content = await file.read()
    if len(content) > _MAX_PHOTO_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Fichier trop volumineux. Max {_MAX_PHOTO_SIZE_BYTES // 1024 // 1024} MB",
        )
    if len(content) < 32:
        raise HTTPException(status_code=400, detail="Fichier vide ou invalide")

    # Generate unique filename
    safe_uid = "".join(c for c in user_id if c.isalnum() or c in "-_")[:20]
    new_name = f"{safe_uid}_{_uuid.uuid4().hex[:12]}{ext}"
    target = _PHOTOS_DIR / new_name
    try:
        target.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur ecriture fichier : {e}")

    # Get profil id + delete old photo if exists
    try:
        row = db.conn.execute(
            "SELECT id, photo_url FROM profil_utilisateur WHERE auth_user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Profil introuvable")
        profil_id, old_photo = row[0], row[1]
        # Delete old file if exists
        if old_photo:
            try:
                old_name = old_photo.rsplit("/", 1)[-1]
                old_path = _PHOTOS_DIR / old_name
                if old_path.exists() and old_path.is_file():
                    old_path.unlink()
            except Exception:
                pass
        # Store new URL relative
        photo_url = f"/api/profil/photo/{new_name}"
        db.conn.execute(
            "UPDATE profil_utilisateur SET photo_url = ? WHERE id = ?",
            (photo_url, profil_id),
        )
        db.conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur DB : {e}")

    return PhotoUploadOut(photo_url=photo_url, filename=new_name)


@router.get("/photo/{filename}")
async def get_photo(filename: str):
    """Sert le fichier photo (public — l'URL est unique par UUID, suffisamment opaque)."""
    # Path traversal protection
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Filename invalide")
    target = _PHOTOS_DIR / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Photo introuvable")
    return FileResponse(target)


@router.delete("/photo")
async def delete_photo(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Supprime la photo de profil de l'utilisateur courant."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")
    try:
        row = db.conn.execute(
            "SELECT photo_url FROM profil_utilisateur WHERE auth_user_id = ?",
            (user_id,),
        ).fetchone()
        if row and row[0]:
            try:
                old_name = row[0].rsplit("/", 1)[-1]
                old_path = _PHOTOS_DIR / old_name
                if old_path.exists() and old_path.is_file():
                    old_path.unlink()
            except Exception:
                pass
        db.conn.execute(
            "UPDATE profil_utilisateur SET photo_url = NULL WHERE auth_user_id = ?",
            (user_id,),
        )
        db.conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"deleted": True}
