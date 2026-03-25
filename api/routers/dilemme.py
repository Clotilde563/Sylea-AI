"""
Router FastAPI — Dilemme décisionnel.

Routes :
  POST /api/dilemme/analyser  → analyse question + options A/B (Claude IA)
  POST /api/dilemme/choisir   → commit du choix → sauvegarde Decision
"""

from __future__ import annotations

import asyncio
import os
import re

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
from api.dependencies import get_profil_repo, get_decision_repo, get_agent, get_optional_user, get_db
from sylea.core.storage.database import DatabaseManager
from api.context_helper import format_device_context

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
    db: DatabaseManager = Depends(get_db),
    agent=Depends(get_agent),
    user_id: str | None = Depends(get_optional_user),
):
    """
    Analyse un dilemme via l'IA Claude.

    Retourne pros/cons + impact sur la probabilité pour N options.
    Si pas d'agent Claude disponible, retourne une analyse basique locale.
    """
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil: ProfilUtilisateur = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    # Rétrocompat : si option_a/option_b fournis, les convertir en options
    options_list = list(data.options) if data.options else []
    if not options_list and data.option_a and data.option_b:
        options_list = [data.option_a, data.option_b]
    if len(options_list) < 2:
        raise HTTPException(status_code=400, detail="Au moins 2 options requises.")

    lettres = [chr(65 + i) for i in range(len(options_list))]

    # Chercher UNIQUEMENT les messages agent pertinents aux options du dilemme
    collected_context = ""
    try:
        msg_rows = db.conn.execute(
            "SELECT role, content FROM agent_messages WHERE auth_user_id = ? ORDER BY created_at DESC LIMIT 30",
            (user_id or "",),
        ).fetchall()
        if msg_rows:
            relevant_msgs = []
            seen = set()
            for r in msg_rows:
                content_lower = r[1].lower()
                for opt in options_list:
                    for word in opt.split():
                        if len(word) > 3 and word.lower() in content_lower:
                            key = r[1][:50]
                            if key not in seen:
                                seen.add(key)
                                relevant_msgs.append(f"{'Utilisateur' if r[0] == 'user' else 'Agent'}: {r[1][:300]}")
                            break
                    else:
                        continue
                    break
            if relevant_msgs:
                collected_context = (
                    "\n\n=== INFORMATIONS CRITIQUES SUR LES PERSONNES MENTIONNEES ===\n"
                    "L'utilisateur a precedemment partage ces informations via l'Agent Sylea 1.\n"
                    "Tu DOIS les utiliser dans ton analyse :\n\n"
                    + "\n".join(f"  {m}" for m in relevant_msgs[:5])
                    + "\n\n=== FIN DES INFORMATIONS CRITIQUES ===\n"
                )
    except Exception as e:
        with open("debug_dilemme_error.txt", "w", encoding="utf-8") as ef:
            ef.write(f"ERROR in message extraction: {e}\nuser_id: {user_id}\n")

    # Aussi charger les infos collectées par l'agent (agent_collected_info)
    try:
        info_rows = db.conn.execute(
            "SELECT field, value FROM agent_collected_info WHERE user_id = ? ORDER BY collected_at DESC LIMIT 20",
            (user_id or "",),
        ).fetchall()
        if info_rows:
            # Filtrer les infos pertinentes aux options du dilemme
            relevant_infos = []
            for field, value in info_rows:
                value_lower = value.lower()
                for opt in options_list:
                    for word in opt.split():
                        if len(word) > 3 and word.lower() in value_lower:
                            relevant_infos.append(f"  {field}: {value[:300]}")
                            break
                    else:
                        continue
                    break
            if relevant_infos:
                collected_context += (
                    "\n\n=== CONTEXTE SUPPLEMENTAIRE COLLECTE ===\n"
                    + "\n".join(relevant_infos[:10])
                    + "\n=== FIN DU CONTEXTE SUPPLEMENTAIRE ===\n"
                )
    except Exception:
        pass

    device_ctx = format_device_context(data.contexte_appareil) + collected_context

    if agent is not None:
        try:
            analyse = await asyncio.to_thread(
                agent.analyser_dilemme,
                profil,
                data.question,
                options_list,
                impact_temporel_jours=data.impact_temporel_jours,
                device_context=device_ctx,
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
                    impact_jours_brut=opt.impact_jours_brut if opt else 0.0,
                    resume=opt.resume if opt else "",
                ))
            return AnalyseDilemmeOut(
                question=data.question,
                options=out_options,
                verdict=analyse.verdict,
                option_recommandee=analyse.option_recommandee,
                etude_scientifique=getattr(analyse, 'etude_scientifique', ''),
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




async def _identifier_so_pertinent(description: str, sous_objectifs: list) -> dict | None:
    """Utilise Claude pour identifier le sous-objectif le plus pertinent."""
    if len(sous_objectifs) <= 1:
        return sous_objectifs[0] if sous_objectifs else None

    try:
        import anthropic as _anthropic
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None

        client = _anthropic.Anthropic(api_key=key)
        so_list = "\n".join(
            f"{i+1}. {so['titre']}" for i, so in enumerate(sous_objectifs)
        )
        prompt = (
            "Voici une action/choix d'un utilisateur :\n"
            f'"{description}"\n\n'
            f"Voici ses sous-objectifs en cours :\n{so_list}\n\n"
            "Quel sous-objectif (numero) est le PLUS DIRECTEMENT impacte "
            "par cette action ? Reponds UNIQUEMENT avec le numero (ex: 1, 2, 3...)."
        )

        msg = await asyncio.to_thread(
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )
        )
        text = msg.content[0].text.strip()
        num_match = re.search(r"(\d+)", text)
        if num_match:
            idx = int(num_match.group(1)) - 1
            if 0 <= idx < len(sous_objectifs):
                return sous_objectifs[idx]
    except Exception:
        pass
    return None

@router.post("/choisir", response_model=DecisionOut)
async def choisir_option(
    data: ChoixIn,
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    decision_repo: DecisionRepository = Depends(get_decision_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """
    Enregistre le choix de l'utilisateur et met à jour sa probabilité.

    Crée une Decision dans la base, met à jour probabilite_actuelle du profil.
    """
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil: ProfilUtilisateur = profil_repo.charger(auth_user_id=user_id)
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

    # Anti-doublon: meme dilemme dans la periode d'impact temporel
    if data.impact_temporel_jours and data.impact_temporel_jours > 0:
        from datetime import datetime as _dt, timedelta as _td
        cutoff = (_dt.now() - _td(days=data.impact_temporel_jours)).isoformat()
        options_normalized = sorted([opt.description.strip().lower() for opt in data.options])
        recent = profil_repo._db.conn.execute(
            "SELECT options_json, cree_le, impact_temporel_jours FROM decisions "
            "WHERE user_id = ? AND cree_le > ? AND question NOT LIKE '[Evenement]%' "
            "ORDER BY cree_le DESC",
            (profil.id, cutoff),
        ).fetchall()
        import json as _json
        for row in recent:
            try:
                row_opts = _json.loads(row["options_json"])
                row_opts_norm = sorted([o["description"].strip().lower() for o in row_opts])
                if row_opts_norm == options_normalized:
                    created = _dt.fromisoformat(row["cree_le"])
                    itj = row["impact_temporel_jours"] or data.impact_temporel_jours
                    unlock = created + _td(days=itj)
                    remaining = max(1, (unlock - _dt.now()).days)
                    raise HTTPException(
                        status_code=409,
                        detail=f"Ce dilemme a deja ete soumis. Reessayez dans {remaining} jour(s).",
                    )
            except (_json.JSONDecodeError, KeyError, TypeError):
                continue


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
        impact_temporel_jours=data.impact_temporel_jours,
    )

    # Sauvegarder
    decision_repo.sauvegarder(decision)

    # Mettre à jour le profil
    profil.probabilite_actuelle = prob_apres
    profil.marquer_modification()
    profil_repo.sauvegarder(profil)

    # Identifier et mettre a jour le sous-objectif pertinent via IA
    so_titre_impacte = None
    try:
        db = profil_repo._db
        all_so = db.conn.execute(
            "SELECT id, titre, progression, ordre, temps_estime FROM sous_objectifs WHERE user_id = ? AND progression < 100 ORDER BY ordre",
            (profil.id,),
        ).fetchall()
        if all_so:
            # Construire la description du choix pour le matching
            choix_desc = f"{data.question} - Choix: {analyse_choisie.description}"
            so_cible = await _identifier_so_pertinent(choix_desc, all_so)
            if so_cible is None:
                so_cible = all_so[0]  # fallback: premier par ordre
            total_te = sum(max(30, so["temps_estime"] or 180) for so in all_so)
            te = max(30, so_cible["temps_estime"] if so_cible["temps_estime"] else 180)
            impact_so = analyse_choisie.impact_probabilite * (total_te / te)  # signé : positif = progression, négatif = régression
            new_prog = min(100, max(0, so_cible["progression"] + impact_so))
            db.conn.execute(
                "UPDATE sous_objectifs SET progression = ? WHERE id = ?",
                (new_prog, so_cible["id"]),
            )
            db.conn.commit()
            so_titre_impacte = so_cible["titre"]
            # Persister le lien SO dans la décision
            decision.sous_objectif_id = so_cible["id"]
            decision.impact_sous_objectif = impact_so
            decision_repo.sauvegarder(decision)
    except Exception:
        pass

    return _decision_to_out(decision, sous_objectif_impacte=so_titre_impacte)
