"""
Router FastAPI -- Sous-objectifs, taches quotidiennes, personnalite IA.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException

from sylea.core.storage.repositories import ProfilRepository
from api.schemas import (
    SousObjectifOut,
    TachesOut, TachesCheckOut, TacheItem,
    CompleterTacheIn, CompleterTacheOut,
    SousObjectifUpdateIn,
    PersonnaliteOut,
    GenererSousObjectifsIn, GenererTachesIn,
)
from api.dependencies import get_profil_repo, get_db, get_optional_user
from api.context_helper import format_device_context, build_full_user_context

router = APIRouter(tags=["objectifs"])


def _get_claude_client():
    import anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY absente")
    return anthropic.Anthropic(api_key=key)


async def _call_claude_json(prompt: str, max_tokens: int = 1500) -> dict:
    client = _get_claude_client()
    msg = await asyncio.to_thread(
        lambda: client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    )
    text = msg.content[0].text.strip()
    match = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
    if not match:
        raise ValueError("JSON invalide")
    return json.loads(match.group())


def _build_profil_context(profil) -> str:
    obj = profil.objectif
    obj_desc = obj.description if obj else "Non defini"
    prob_calc = getattr(obj, "probabilite_calculee", 0) if obj else 0
    prob_tot = max(0.01, min(99.99, prob_calc + profil.probabilite_actuelle))
    parts = []
    parts.append(f"Nom: {profil.nom}, {profil.age} ans, {profil.profession}, {profil.ville}")
    parts.append(f"Situation: {profil.situation_familiale}")
    comps = ", ".join(profil.competences) if profil.competences else "aucune"
    parts.append(f"Competences: {comps}")
    dipls = ", ".join(profil.diplomes) if profil.diplomes else "aucun"
    parts.append(f"Diplomes: {dipls}")
    langs = ", ".join(profil.langues) if profil.langues else "non renseigne"
    parts.append(f"Langues: {langs}")
    parts.append(f"Revenu annuel: {profil.revenu_annuel:.0f} EUR")
    parts.append(f"Heures disponibles pour l'objectif: {profil.heures_objectif:.1f}h/jour")
    parts.append(f"Sante {profil.niveau_sante}/10, Stress {profil.niveau_stress}/10, Energie {profil.niveau_energie}/10, Bonheur {profil.niveau_bonheur}/10")
    parts.append(f"Objectif: {obj_desc}")
    parts.append(f"Probabilite actuelle: {prob_tot:.1f}%")
    return "\n".join(parts)




def _get_past_task_descriptions(db, user_id: str, days: int = 60) -> list[dict]:
    """Recupere les taches deja proposees avec date et statut (derniers N jours)."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = db.conn.execute(
        "SELECT date, taches_json FROM taches_quotidiennes "
        "WHERE user_id = ? AND date >= ? ORDER BY date DESC",
        (user_id, cutoff),
    ).fetchall()
    tasks = []
    for row in rows:
        try:
            taches = json.loads(row["taches_json"])
            for t in taches:
                desc = t.get("description", "").strip()
                if desc:
                    tasks.append({
                        "description": desc,
                        "completee": t.get("completee", False),
                        "date": row["date"],
                    })
        except (json.JSONDecodeError, TypeError):
            continue
    return tasks


# == Sous-objectifs ========================================================

@router.get("/api/sous-objectifs", response_model=list[SousObjectifOut])
async def liste_sous_objectifs(
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    db=Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")
    rows = db.conn.execute(
        "SELECT * FROM sous_objectifs WHERE user_id = ? ORDER BY ordre",
        (profil.id,),
    ).fetchall()
    return [
        SousObjectifOut(
            id=r["id"], titre=r["titre"], description=r["description"],
            progression=r["progression"], ordre=r["ordre"],
            temps_estime=r["temps_estime"] if "temps_estime" in r.keys() else 0.0,
        )
        for r in rows
    ]


@router.post("/api/sous-objectifs/generer", response_model=list[SousObjectifOut])
async def generer_sous_objectifs(
    data: GenererSousObjectifsIn,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    db=Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None or not profil.objectif:
        raise HTTPException(status_code=400, detail="Profil ou objectif manquant.")
    # Verifier si des sous-objectifs existent deja -> ne jamais regenerer
    existing = db.conn.execute(
        "SELECT * FROM sous_objectifs WHERE user_id = ? ORDER BY ordre",
        (profil.id,),
    ).fetchall()
    if existing:
        return [
            SousObjectifOut(
                id=r["id"], titre=r["titre"], description=r["description"],
                progression=r["progression"], ordre=r["ordre"],
                temps_estime=r["temps_estime"] if "temps_estime" in r.keys() else 0.0,
            )
            for r in existing
        ]
    ctx = build_full_user_context(db, user_id, profil)
    prompt = (
        "Tu es un coach de vie strategique. Analyse ce profil et son objectif de vie, "
        "puis genere exactement 4 sous-objectifs LARGES et strategiques pour atteindre "
        "l'objectif principal. Chaque sous-objectif doit representer une GRANDE PHASE "
        "du parcours.\n\n"
        "PERSONNALISATION:\n"
        "Le profil contient les reponses de l'utilisateur a des questions personnalisees "
        "(section apres '--- Contexte personnalise ---'). "
        "Adapte les sous-objectifs au NIVEAU REEL de l'utilisateur. "
        "Si l'utilisateur possede deja des connaissances ou competences dans le domaine, "
        "NE CREE PAS de sous-objectif sur l'apprentissage des bases. "
        "Commence directement par des phases d'action concrete adaptees a son niveau. "
        "Exemple : si l'utilisateur connait deja le freelance, ne propose pas "
        "'Apprendre les bases' mais plutot 'Creer son portfolio et lancer son activite'.\n\n"
        "IMPORTANT: Distribue le temps total proportionnellement entre les sous-objectifs. "
        "Le temps total estime pour l'objectif sera la SOMME des temps de chaque sous-objectif.\n\n"
        f"PROFIL:\n{ctx}\n\n"
        "Reponds UNIQUEMENT avec du JSON valide (pas de markdown):\n"
        '[{"titre": "...", "description": "...", "temps_estime_jours": <int>}, ...]\n'
        "Exactement 4 sous-objectifs, du plus immediat au plus lointain. "
        "temps_estime_jours est le nombre de jours estimes pour accomplir ce sous-objectif. "
        "Les titres doivent etre courts et larges (phase strategique, pas micro-tache)."
        + format_device_context(data.contexte_appareil)
    )
    try:
        raw = await _call_claude_json(prompt)
    except Exception:
        raw = [
            {"titre": "Preparation", "description": "Rassembler les ressources necessaires", "temps_estime_jours": 180},
            {"titre": "Formation", "description": "Acquerir les competences manquantes", "temps_estime_jours": 365},
            {"titre": "Action", "description": "Mettre en oeuvre le plan", "temps_estime_jours": 365},
            {"titre": "Consolidation", "description": "Stabiliser et perenniser les acquis", "temps_estime_jours": 180},
        ]
    now = datetime.now().isoformat()
    results = []
    for i, item in enumerate(raw[:4]):
        so_id = str(uuid.uuid4())
        titre = str(item.get("titre", f"Etape {i+1}"))
        desc = str(item.get("description", ""))
        temps_est = float(item.get("temps_estime_jours", 0))
        db.conn.execute(
            "INSERT INTO sous_objectifs (id, user_id, titre, description, progression, ordre, cree_le, temps_estime) "
            "VALUES (?, ?, ?, ?, 0.0, ?, ?, ?)",
            (so_id, profil.id, titre, desc, i, now, temps_est),
        )
        results.append(SousObjectifOut(
            id=so_id, titre=titre, description=desc, progression=0.0, ordre=i,
            temps_estime=temps_est,
        ))
    db.conn.commit()
    return results


# == Taches quotidiennes ===================================================

@router.get("/api/taches/aujourd-hui", response_model=TachesCheckOut)
async def check_taches_aujourdhui(
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    db=Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")
    today = date.today().isoformat()
    row = db.conn.execute(
        "SELECT * FROM taches_quotidiennes WHERE user_id = ? AND date = ?",
        (profil.id, today),
    ).fetchone()
    if row:
        taches = json.loads(row["taches_json"])
        return TachesCheckOut(
            exists=True,
            taches=TachesOut(
                id=row["id"], date=row["date"],
                taches=[TacheItem(**t) for t in taches],
                deadline=row["deadline"], statut=row["statut"],
                cree_le=row["cree_le"],
            ),
        )
    return TachesCheckOut(exists=False)


@router.post("/api/taches/generer", response_model=TachesOut)
async def generer_taches(
    data: GenererTachesIn,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    db=Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None or not profil.objectif:
        raise HTTPException(status_code=400, detail="Profil ou objectif manquant.")
    today = date.today().isoformat()
    existing = db.conn.execute(
        "SELECT * FROM taches_quotidiennes WHERE user_id = ? AND date = ?",
        (profil.id, today),
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Taches deja generees pour aujourd'hui.")
    # Recuperer le sous-objectif actif pour generer des taches ciblees
    active_so = db.conn.execute(
        "SELECT titre, progression FROM sous_objectifs WHERE user_id = ? AND progression < 100 ORDER BY ordre LIMIT 1",
        (profil.id,),
    ).fetchone()
    so_rows = db.conn.execute(
        "SELECT titre, progression FROM sous_objectifs WHERE user_id = ? ORDER BY ordre",
        (profil.id,),
    ).fetchall()
    so_ctx = "\n".join(
        f"- {r['titre']} ({r['progression']:.0f}%)" + (" [ACTIF]" if active_so and r['titre'] == active_so['titre'] else "") for r in so_rows
    ) if so_rows else "Aucun sous-objectif"
    ctx = build_full_user_context(db, user_id, profil)
    active_label = active_so['titre'] if active_so else "objectif principal"
    so_prioritaire = active_so['titre'] if active_so else "objectif principal"
    # Recuperer les infos collectees par l'agent compagnon
    collected_context = ""
    if profil.id:
        try:
            rows = db.conn.execute(
                "SELECT field, value FROM agent_collected_info WHERE user_id = ? ORDER BY collected_at DESC LIMIT 20",
                (profil.id,),
            ).fetchall()
            if rows:
                collected_context = "\nINFOS COLLECTEES:\n" + "\n".join(f"  {r['field']}: {r['value']}" for r in rows)
        except Exception:
            pass
    # Recuperer l'historique des taches passees pour eviter les doublons
    past_tasks = _get_past_task_descriptions(db, profil.id, days=60)
    past_ctx = ""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    # Taches non completees d'hier -> a reproposer automatiquement
    uncompleted_yesterday = [
        t for t in past_tasks
        if not t["completee"] and t["date"] == yesterday
    ]
    if past_tasks:
        completed = [t for t in past_tasks if t["completee"]]
        lines = []
        if completed:
            lines.append("TACHES COMPLETEES (ne pas repeter a l'identique, mais tu peux proposer la SUITE logique) :")
            for t in completed[-20:]:
                lines.append(f"  [{t['date']}] {t['description']}")
        if uncompleted_yesterday:
            lines.append("TACHES NON COMPLETEES HIER (REPROPOSE-LES A L'IDENTIQUE, ce sont les priorites du jour) :")
            for t in uncompleted_yesterday:
                lines.append(f"  {t['description']}")
        past_ctx = "\n" + "\n".join(lines) + "\n"
    device_context = format_device_context(data.contexte_appareil)
    prompt = (
        "Tu es un coach de vie expert. Genere un plan d'action CONCRET pour aujourd'hui "
        "avec des VRAIES RESSOURCES GRATUITES pour aider l'utilisateur a avancer vers son objectif.\n\n"
        f"PROFIL: {profil.nom}, {profil.age} ans, {profil.profession}\n"
        f"OBJECTIF: {profil.objectif.description if profil.objectif else 'Non defini'}\n"
        f"SOUS-OBJECTIF ACTUEL (a prioriser): {so_prioritaire}\n"
        f"PROGRESSION: {profil.probabilite_actuelle:.1f}%\n"
        f"{collected_context}\n"
        f"{device_context}\n\n"
        f"PROFIL COMPLET:\n{ctx}\n\n"
        f"SOUS-OBJECTIFS:\n{so_ctx}\n\n"
        "REGLES STRICTES:\n"
        "1. Genere 4 a 5 taches VARIEES avec un MIX OBLIGATOIRE de ces types:\n\n"
        '   \U0001F3A5 TYPE "video" — Regarder un tutoriel video (OBLIGATOIRE: au moins 1)\n'
        "     Propose des VRAIES videos YouTube de chaines populaires et reconnues:\n"
        "     - freeCodeCamp (anglais, cours complets gratuits)\n"
        "     - Traversy Media (anglais, tutoriels pratiques)\n"
        "     - The Net Ninja (anglais, series structurees)\n"
        "     - Grafikart (francais, dev web et plus)\n"
        "     - Fireship (anglais, explications rapides)\n"
        "     - Web Dev Simplified (anglais)\n"
        "     - Melvynx (francais, React/Next.js)\n"
        "     - Benjamin Code (francais, dev web)\n"
        "     Donne le VRAI lien YouTube (https://www.youtube.com/watch?v=ID ou https://youtu.be/ID)\n"
        "     Donne le VRAI titre de la video et le nom de la chaine\n\n"
        '   \U0001F4D6 TYPE "lecture" — Lire un article ou documentation (OBLIGATOIRE: au moins 1)\n'
        "     Propose des VRAIS liens vers:\n"
        "     - MDN Web Docs (https://developer.mozilla.org/...)\n"
        "     - dev.to articles populaires (https://dev.to/...)\n"
        "     - Documentation officielle du langage/framework\n"
        "     - freeCodeCamp articles (https://www.freecodecamp.org/news/...)\n"
        "     - OpenClassrooms cours gratuits (https://openclassrooms.com/fr/courses/...)\n\n"
        '   \U0001F4BB TYPE "pratique" — Pratiquer sur une plateforme interactive\n'
        "     Propose des VRAIS exercices sur:\n"
        "     - Codewars (https://www.codewars.com/kata/...)\n"
        "     - HackerRank (https://www.hackerrank.com/challenges/...)\n"
        "     - LeetCode (https://leetcode.com/problems/...)\n"
        "     - freeCodeCamp exercices (https://www.freecodecamp.org/learn/...)\n"
        "     - Exercism (https://exercism.org/tracks/...)\n"
        "     - Codecademy gratuit (https://www.codecademy.com/learn/...)\n\n"
        '   \U0001F9E0 TYPE "reflexion" — Reflechir, planifier, journaliser (pas de lien necessaire)\n'
        "     Exemple: ecrire ses objectifs, faire un bilan, definir des priorites\n\n"
        '   \U0001F91D TYPE "reseau" — Reseauter, se connecter, partager\n'
        "     Exemple: poster sur LinkedIn, rejoindre un Discord/Slack, contacter un mentor\n"
        "     Liens possibles: LinkedIn, meetup.com, communautes Discord\n\n"
        "2. Chaque tache DOIT avoir:\n"
        '   - "titre": titre court et motivant (pas "Exercice 1", mais le vrai titre de la ressource)\n'
        '   - "description": 1-2 phrases expliquant POURQUOI cette tache aide le sous-objectif actuel\n'
        '   - "duree": duree estimee realiste (ex: "20 min", "45 min", "1h")\n'
        '   - "lien": URL REEL et VALIDE vers la ressource (sauf pour reflexion)\n'
        '   - "type": un des types ci-dessus (video, lecture, pratique, reflexion, reseau)\n'
        '   - "icone": emoji selon le type (\U0001F3A5, \U0001F4D6, \U0001F4BB, \U0001F9E0, \U0001F91D)\n\n'
        "3. QUALITE DES LIENS — C'est CRUCIAL:\n"
        "   - Donne UNIQUEMENT des liens vers des ressources qui EXISTENT REELLEMENT\n"
        "   - Prefere les ressources GRATUITES et POPULAIRES\n"
        "   - Pour YouTube, donne des liens vers des videos SPECIFIQUES (pas juste la chaine)\n"
        "   - Pour les cours, donne le lien vers le MODULE SPECIFIQUE pertinent\n"
        "   - Si tu n'es pas sur qu'un lien existe, donne le lien vers la PAGE PRINCIPALE\n"
        "     de la plateforme (ex: https://www.freecodecamp.org/learn/) plutot qu'un faux lien\n\n"
        "4. Les taches doivent etre CONCRETES et REALISABLES aujourd'hui\n"
        "5. Adapte au niveau et a la situation de l'utilisateur\n"
        "6. Varie les types — JAMAIS 3 taches du meme type, mixe obligatoirement\n\n"
        "PERSONNALISATION IMPORTANTE:\n"
        "- COMPETENCES et DIPLOMES: adapte le niveau de difficulte des ressources\n"
        "- LANGUES: si l'utilisateur parle francais, prefere les ressources en francais\n"
        "  (Grafikart, OpenClassrooms, Melvynx) sinon en anglais\n"
        "- TEMPS DISPONIBLE (heures/jour): si peu de temps, propose des micro-taches (15-20 min)\n"
        "- REVENU ANNUEL: si l'utilisateur a les moyens, suggere aussi des formations payantes\n"
        "  (Udemy, Formation en ligne, livres) en plus des gratuites\n"
        "- Si l'utilisateur a deja des connaissances avancees, propose des ressources avancees\n\n"
        "CONTINUITE DES TACHES:\n"
        "1. Si des TACHES NON COMPLETEES HIER sont listees, REPROPOSE-LES A L'IDENTIQUE "
        "(copie exacte de la description). Ce sont les priorites du jour.\n"
        "2. Complete avec de nouvelles taches pour arriver a 4-5 au total.\n"
        "3. Pour les nouvelles taches, regarde les taches COMPLETEES et propose la SUITE LOGIQUE.\n\n"
        f"{past_ctx}\n"
        "Reponds UNIQUEMENT en JSON valide (pas de markdown, pas de commentaires):\n"
        '[{"titre": "...", "description": "...", "duree": "30 min", "type": "video", '
        '"lien": "https://www.youtube.com/watch?v=...", "icone": "\U0001F3A5"}, ...]'
    )
    try:
        raw = await _call_claude_json(prompt, max_tokens=2500)
    except Exception:
        raw = [
            {"titre": "Definir vos priorites", "description": "Definir 3 actions prioritaires pour votre objectif", "duree": "15 min", "type": "reflexion", "lien": "", "icone": "\U0001F4A1"},
            {"titre": "Se former 30 min", "description": "Consacrer 30 min a la formation ou recherche", "duree": "30 min", "type": "apprentissage", "lien": "", "icone": "\U0001F393"},
            {"titre": "Developper son reseau", "description": "Contacter une personne cle de votre reseau", "duree": "20 min", "type": "reseau", "lien": "", "icone": "\U0001F91D"},
            {"titre": "Planifier la semaine", "description": "Planifier les prochaines etapes de la semaine", "duree": "15 min", "type": "action", "lien": "", "icone": "\U0001F3AF"},
        ]
    now = datetime.now()
    deadline = datetime(now.year, now.month, now.day, 23, 59, 59).isoformat()
    taches = []
    for item in raw[:5]:
        taches.append({
            "id": str(uuid.uuid4()),
            "description": str(item.get("description", "Tache")),
            "completee": False,
            "titre": str(item.get("titre", "")),
            "duree": str(item.get("duree", "")),
            "type": str(item.get("type", "action")),
            "lien": str(item.get("lien", "")),
            "icone": str(item.get("icone", "")),
        })
    taches_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT OR REPLACE INTO taches_quotidiennes "
        "(id, user_id, date, taches_json, deadline, statut, cree_le) "
        "VALUES (?, ?, ?, ?, ?, 'en_cours', ?)",
        (taches_id, profil.id, today, json.dumps(taches, ensure_ascii=False),
         deadline, now.isoformat()),
    )
    db.conn.commit()
    return TachesOut(
        id=taches_id, date=today,
        taches=[TacheItem(**t) for t in taches],
        deadline=deadline, statut="en_cours",
        cree_le=now.isoformat(),
    )


@router.post("/api/taches/completer", response_model=CompleterTacheOut)
async def completer_tache(
    data: CompleterTacheIn,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    db=Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")
    today = date.today().isoformat()
    row = db.conn.execute(
        "SELECT * FROM taches_quotidiennes WHERE user_id = ? AND date = ? AND statut = 'en_cours'",
        (profil.id, today),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Aucune tache en cours.")
    taches = json.loads(row["taches_json"])
    tache_trouvee = None
    for t in taches:
        if t["id"] == data.tache_id:
            t["completee"] = True
            tache_trouvee = t
            break
    if not tache_trouvee:
        raise HTTPException(status_code=404, detail="Tache non trouvee.")
    impact = 0.05
    profil.probabilite_actuelle = min(99.9, profil.probabilite_actuelle + impact)
    profil.marquer_modification()
    profil_repo.sauvegarder(profil)
    # Mettre a jour SEULEMENT le sous-objectif actif (premier avec progression < 100)
    active_so = db.conn.execute(
        "SELECT id, titre, progression, temps_estime FROM sous_objectifs "
        "WHERE user_id = ? AND progression < 100 ORDER BY ordre LIMIT 1",
        (profil.id,),
    ).fetchone()
    impacts_so = []
    so_impacte = None
    if active_so:
        te = max(30, active_so["temps_estime"] if active_so["temps_estime"] else 180)
        task_so_impact = 50.0 / (te * 4)  # tasks = 50% du progres sur temps_estime
        new_prog = min(100, active_so["progression"] + task_so_impact)
        db.conn.execute(
            "UPDATE sous_objectifs SET progression = ? WHERE id = ?",
            (new_prog, active_so["id"]),
        )
        impacts_so.append(SousObjectifUpdateIn(id=active_so["id"], progression=new_prog))
        so_impacte = active_so["titre"]
    db.conn.execute(
        "UPDATE taches_quotidiennes SET taches_json = ? WHERE id = ?",
        (json.dumps(taches, ensure_ascii=False), row["id"]),
    )
    if all(t["completee"] for t in taches):
        db.conn.execute(
            "UPDATE taches_quotidiennes SET statut = 'terminee' WHERE id = ?",
            (row["id"],),
        )
    db.conn.commit()
    # Sauvegarder comme Decision dans l historique
    from sylea.core.models.decision import Decision, OptionDilemme
    from sylea.core.storage.repositories import DecisionRepository
    desc_str = tache_trouvee["description"]
    opt = OptionDilemme(
        description=f"[Tache] {desc_str}",
        impact_score=impact,
        explication_impact="Tache quotidienne completee",
    )
    decision = Decision(
        user_id=profil.id,
        question=f"[Tache] {desc_str}",
        options=[opt],
        probabilite_avant=profil.probabilite_actuelle - impact,
        option_choisie_id=opt.id,
        probabilite_apres=profil.probabilite_actuelle,
    )
    if active_so:
        decision.sous_objectif_id = active_so["id"]
        decision.impact_sous_objectif = task_so_impact
    dec_repo = DecisionRepository(db)
    dec_repo.sauvegarder(decision)
    return CompleterTacheOut(
        tache=TacheItem(**tache_trouvee),
        impact_principal=impact,
        impacts_sous_objectifs=impacts_so,
        sous_objectif_impacte=so_impacte,
    )


@router.post("/api/taches/abandonner")
async def abandonner_taches(
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    db=Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")
    today = date.today().isoformat()
    db.conn.execute(
        "UPDATE taches_quotidiennes SET statut = 'abandonnee' "
        "WHERE user_id = ? AND date = ? AND statut = 'en_cours'",
        (profil.id, today),
    )
    db.conn.commit()
    return {"detail": "Taches abandonnees."}


# == Personnalite IA =======================================================

@router.get("/api/profil/personnalite", response_model=PersonnaliteOut)
async def get_personnalite(
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    db=Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouve.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")
    # Verifier si la phrase est deja stockee en DB (generee une seule fois)
    row = db.conn.execute(
        "SELECT phrase_personnalite FROM profil_utilisateur WHERE id = ?",
        (profil.id,),
    ).fetchone()
    if row and row["phrase_personnalite"]:
        return PersonnaliteOut(phrase=row["phrase_personnalite"])
    # Generer une seule fois via Claude
    ctx = build_full_user_context(db, user_id, profil)
    prompt = (
        "Tu es SYLEA, une IA bienveillante et perspicace. "
        "En UNE SEULE phrase poetique et inspirante (max 15 mots), "
        "decris ce que tu penses de cette PERSONNE (pas de son objectif). "
        "Parle de sa personnalite, de son energie, de ce qui la rend unique. "
        "Sois authentique et chaleureux. Utilise le tutoiement.\n\n"
        f"PROFIL:\n{ctx}\n\n"
        'Reponds UNIQUEMENT avec du JSON: {"phrase": "ta phrase ici"}'
    )
    try:
        data = await _call_claude_json(prompt, max_tokens=100)
        phrase = str(data.get("phrase", "Une ame determinee en quete de grandeur."))
    except Exception:
        phrase = "Une ame determinee en quete de grandeur."
    # Stocker definitivement en DB
    db.conn.execute(
        "UPDATE profil_utilisateur SET phrase_personnalite = ? WHERE id = ?",
        (phrase, profil.id),
    )
    db.conn.commit()
    return PersonnaliteOut(phrase=phrase)
