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
from api.context_helper import format_device_context, build_full_user_context_async

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
    # Compute impact_net from temps fields if available, fallback to prob fields
    if d.temps_gagne_apres and d.temps_gagne_avant is not None:
        impact_net = d.temps_gagne_apres - d.temps_gagne_avant
    elif d.probabilite_apres is not None:
        impact_net = d.probabilite_apres - d.probabilite_avant
    else:
        impact_net = None
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
        impact_net=impact_net,
        sous_objectif_impacte=sous_objectif_impacte,
        temps_gagne_avant=d.temps_gagne_avant,
        temps_gagne_apres=d.temps_gagne_apres,
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

    # Migration PG : lectures async via SQLAlchemy text() (compat SQLite + PG).
    from sqlalchemy import text as _sa_text
    from api.database import get_session_factory as _gsf

    # Chercher UNIQUEMENT les messages agent pertinents aux options du dilemme
    collected_context = ""
    msg_rows: list[tuple] = []
    try:
        _factory = _gsf()
        async with _factory() as _session:
            _result = await _session.execute(
                _sa_text(
                    "SELECT role, content FROM agent_messages "
                    "WHERE auth_user_id = :uid "
                    "ORDER BY created_at DESC LIMIT 30"
                ),
                {"uid": user_id or ""},
            )
            msg_rows = [(r["role"], r["content"]) for r in _result.mappings().all()]
    except Exception:
        msg_rows = []
    if msg_rows:
        try:
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
        except Exception:
            pass  # Message extraction failed — continue without agent context

    # Aussi charger les infos collectées par l'agent (agent_collected_info)
    info_rows: list[tuple] = []
    try:
        _factory = _gsf()
        async with _factory() as _session:
            _result = await _session.execute(
                _sa_text(
                    "SELECT field, value FROM agent_collected_info "
                    "WHERE user_id = :uid "
                    "ORDER BY collected_at DESC LIMIT 20"
                ),
                {"uid": user_id or ""},
            )
            info_rows = [(r["field"], r["value"]) for r in _result.mappings().all()]
    except Exception:
        info_rows = []
    if info_rows:
        try:
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

    device_ctx = format_device_context(data.contexte_appareil)
    full_ctx = await build_full_user_context_async(db, user_id, profil)

    if agent is not None:
        try:
            analyse = await asyncio.to_thread(
                agent.analyser_dilemme,
                profil,
                data.question,
                options_list,
                impact_temporel_jours=data.impact_temporel_jours,
                device_context=device_ctx,
                collected_context=collected_context,
                full_context=full_ctx,
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
                    impact_jours=getattr(opt, 'impact_jours_brut', 0.0) if opt else 0.0,
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
            impact_jours=0.0,
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

    # Quota quotidien d'actions IA (free: 10/j, pro/avance: 30/j, team: illimite).
    # Migration PG (2026-05-13) : utilise les versions async des quota helpers.
    if user_id:
        try:
            from api.daily_action_limit import check_daily_action_quota_async
            from api.agent3_quotas import get_user_plan_async
            try:
                plan_info = await get_user_plan_async(user_id)
                plan_name = plan_info.get('name', 'free')
            except Exception:
                plan_name = 'free'
            ok, count, limit = await check_daily_action_quota_async(
                profil.id, user_id, plan_name,
            )
            if not ok:
                raise HTTPException(
                    status_code=429,
                    detail=(
                        f"Quota quotidien atteint ({count}/{limit} actions aujourd'hui). "
                        f"{'Passe a Avance pour 30 actions/jour.' if plan_name == 'free' else 'Reessaie demain.'}"
                    ),
                )
        except HTTPException:
            raise
        except Exception:
            pass

    # Trouver l'option choisie par lettre
    analyse_choisie = None
    for opt in data.options:
        if opt.lettre == data.choix:
            analyse_choisie = opt
            break
    if analyse_choisie is None:
        raise HTTPException(status_code=400, detail=f"Option '{data.choix}' non trouvée.")

    # Anti-doublon: meme dilemme dans la periode d'impact temporel
    # Migration PG (2026-05-12) : SELECT via SQLAlchemy text() async.
    if data.impact_temporel_jours and data.impact_temporel_jours > 0:
        from datetime import datetime as _dt, timedelta as _td
        from sqlalchemy import text as _sql_text
        from api.database import get_session_factory as _gsf
        cutoff = (_dt.now() - _td(days=data.impact_temporel_jours)).isoformat()
        options_normalized = sorted([opt.description.strip().lower() for opt in data.options])

        _factory = _gsf()
        async with _factory() as _session:
            _result = await _session.execute(
                _sql_text(
                    "SELECT options_json, cree_le, impact_temporel_jours FROM decisions "
                    "WHERE user_id = :uid AND cree_le > :cutoff "
                    "AND question NOT LIKE '[Evenement]%' ORDER BY cree_le DESC"
                ),
                {"uid": profil.id, "cutoff": cutoff},
            )
            recent = _result.mappings().all()
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

    # Time-based: compute impact in days
    temps_gagne_avant = profil.temps_gagne_jours
    # Use impact_jours if available, otherwise convert from impact_probabilite
    impact_jours = analyse_choisie.impact_jours
    if impact_jours == 0.0 and analyse_choisie.impact_probabilite != 0.0 and profil.temps_initial_jours > 0:
        impact_jours = round(analyse_choisie.impact_probabilite * profil.temps_initial_jours / 100, 1)
    temps_gagne_apres = temps_gagne_avant + impact_jours
    temps_gagne_apres = max(0, min(profil.temps_initial_jours, temps_gagne_apres))

    # Créer la décision
    decision = Decision(
        user_id=profil.id,
        question=data.question,
        options=all_opts,
        probabilite_avant=prob_avant,
        option_choisie_id=opt_choisie_id,
        probabilite_apres=prob_apres,
        impact_temporel_jours=data.impact_temporel_jours,
        temps_gagne_avant=temps_gagne_avant,
        temps_gagne_apres=temps_gagne_apres,
    )

    # Sauvegarder
    decision_repo.sauvegarder(decision)

    # Mettre à jour le profil
    # FIX C1 (Sprint QA pre-commercialisation) : on aligne probabilite_actuelle
    # sur la progression reelle (temps_gagne / temps_initial * 100) pour eviter
    # 2 chiffres divergents pour la meme notion (probabilite IA atténuée vs
    # progression temps). Le frontend affiche deja progression dans la card
    # PROGRESSION ; cette ligne garantit que profil.probabilite_actuelle
    # (encore lu dans certaines pages) reste coherent.
    profil.temps_gagne_jours = temps_gagne_apres
    if profil.temps_initial_jours > 0:
        profil.probabilite_actuelle = round(
            (temps_gagne_apres / profil.temps_initial_jours) * 100, 2
        )
    else:
        profil.probabilite_actuelle = prob_apres
    profil.marquer_modification()
    profil_repo.sauvegarder(profil)

    # Identifier et mettre a jour le sous-objectif pertinent via IA.
    # Migration PG (2026-05-12) : SELECT sous_objectifs + apply_impact_invariant_safe
    # via async (compat SQLite + PG). Tout dans UNE seule transaction.
    so_titre_impacte = None
    try:
        from sqlalchemy import text as _sql_text2
        from api.database import get_session_factory as _gsf2
        from api.so_invariant import apply_impact_invariant_safe_async

        _factory2 = _gsf2()
        async with _factory2() as _session2:
            try:
                _so_result = await _session2.execute(
                    _sql_text2(
                        "SELECT id, titre, progression, ordre, temps_estime "
                        "FROM sous_objectifs WHERE user_id = :uid ORDER BY ordre"
                    ),
                    {"uid": profil.id},
                )
                all_so_all = list(_so_result.mappings().all())
                all_so = [so for so in all_so_all if (so["progression"] or 0) < 100]
                if all_so:
                    choix_desc = f"{data.question} - Choix: {analyse_choisie.description}"
                    so_cible = await _identifier_so_pertinent(choix_desc, all_so)
                    if so_cible is None:
                        so_cible = all_so[0]

                    target_id_used, applied_delta_pct = await apply_impact_invariant_safe_async(
                        _session2, profil.id, so_cible["id"], impact_jours,
                        profil.temps_initial_jours,
                    )
                    so_titre_impacte = so_cible["titre"]
                    decision.sous_objectif_id = target_id_used or so_cible["id"]
                    decision.impact_sous_objectif = applied_delta_pct
                    # Note : sauvegarde decision via sync repo, hors de la
                    # transaction async — best-effort (l'invariant SO est deja
                    # commit dans la transaction async).
                await _session2.commit()
            except Exception:
                await _session2.rollback()
                raise
        # Mise a jour de la decision avec sous_objectif_id / impact (sync)
        if so_titre_impacte:
            decision_repo.sauvegarder(decision)
    except Exception:
        pass

    return _decision_to_out(decision, sous_objectif_impacte=so_titre_impacte)
