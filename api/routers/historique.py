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


async def _recompute_so_progressions_async(
    session, profil_id: str,
    exclude_decision_id: str | None = None,
    temps_gagne_override: float | None = None,
) -> None:
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

    Migration PG (2026-05-12) : version async utilisant SQLAlchemy text() —
    compatible SQLite ET PostgreSQL. La caller est responsable du commit.

    BUG FIX (2026-05-13) : ajout de `temps_gagne_override` pour utiliser la
    valeur POST-mutation au lieu de relire la DB (qui a la valeur PRE-mutation
    si la caller n'a pas encore commit le profil). Sans cet override, le DELETE
    flow recompute les SO avec l'ancien temps_gagne → drift de `impact_temps`
    jours dans l'invariant Dashboard. Avec l'override, l'invariant tient
    exactement apres DELETE.
    """
    from sqlalchemy import text

    # Charger profil pour temps_initial et (optionnellement) temps_gagne
    result = await session.execute(
        text(
            "SELECT temps_initial_jours, temps_gagne_jours "
            "FROM profil_utilisateur WHERE id = :pid"
        ),
        {"pid": profil_id},
    )
    profil_row = result.mappings().first()
    if not profil_row:
        return
    temps_initial = profil_row["temps_initial_jours"] or 0
    if temps_gagne_override is not None:
        # Cas DELETE : le caller a deja calcule le nouveau temps_gagne
        # post-mutation mais ne l'a pas encore commit. On l'utilise pour
        # garantir que l'invariant Dashboard tient exactement post-DELETE.
        temps_gagne = float(temps_gagne_override)
    else:
        temps_gagne = profil_row["temps_gagne_jours"] or 0

    # Charger les SO avec leurs temps_estime
    result = await session.execute(
        text("SELECT id, temps_estime FROM sous_objectifs WHERE user_id = :uid"),
        {"uid": profil_id},
    )
    so_rows = result.mappings().all()
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
        "WHERE user_id = :uid AND sous_objectif_id IS NOT NULL "
    )
    params: dict = {"uid": profil_id}
    if exclude_decision_id:
        query += "AND id != :exc "
        params["exc"] = exclude_decision_id
    query += "ORDER BY cree_le ASC"
    result = await session.execute(text(query), params)
    for r in result.mappings().all():
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
        await session.execute(
            text("UPDATE sous_objectifs SET progression = :prog WHERE id = :sid"),
            {"prog": prog, "sid": sid},
        )
    # Note : pas de commit ici — la caller gere la transaction.


_STOPWORDS_FR = {
    "le", "la", "les", "de", "des", "du", "un", "une", "et", "ou", "que",
    "qui", "quoi", "dont", "pour", "par", "sur", "dans", "avec", "sans",
    "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses", "ce", "cet",
    "cette", "ces", "il", "elle", "ils", "elles", "je", "tu", "nous", "vous",
    "moi", "toi", "lui", "leur", "leurs", "est", "ete", "etre", "avoir",
    "ai", "as", "ont", "avait", "avais", "avaient", "fait", "faite", "fais",
    "etait", "etais", "etaient", "plus", "moins", "aussi", "donc", "alors",
    "evenement", "tache", "dilemme", "decision", "action", "chose", "truc",
    "jour", "jours", "semaine", "mois", "annee", "an", "ans", "aujourd",
    "hui", "demain", "hier", "tous", "tout", "toute", "toutes", "rien",
    "pas", "ne", "non", "oui", "si", "tres", "trop", "peu", "beaucoup",
}


def _extract_keywords(text: str, min_len: int = 4) -> set[str]:
    """Extrait les mots clés significatifs d'un texte (>= min_len lettres,
    non stop-words). Insensible aux accents et a la casse.
    """
    import unicodedata, re
    if not text:
        return set()
    # Normaliser : minuscules + suppression accents
    norm = unicodedata.normalize("NFKD", text.lower())
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    # Tokens alphanumeriques (garde aussi les chiffres pour matcher "50000")
    tokens = re.findall(r"\w+", norm)
    return {
        t for t in tokens
        if len(t) >= min_len and t not in _STOPWORDS_FR
    }


async def _cleanup_collected_info_for_decision_async(
    session, profil_id: str, user_id: str | None, decision
) -> None:
    """Supprime les rows agent_collected_info qui partagent suffisamment de mots
    clés significatifs avec la décision supprimée. Heuristique : >=2 keywords
    communs OU >=1 keyword "fort" (chiffre, mot >7 lettres).

    Évite que l'Agent 1 continue à relancer un sujet (ex: "héritage 50k€")
    après que l'utilisateur ait supprimé l'événement correspondant.

    Migration PG (2026-05-12) : version async via SQLAlchemy text(). La caller
    gere le commit.
    """
    if not user_id:
        return
    from sqlalchemy import text as sql_text
    # Source : description de la decision + descriptions d'options
    text_parts = [decision.question or ""]
    for opt in (decision.options or []):
        text_parts.append(opt.description or "")
        text_parts.append(opt.explication_impact or "")
    decision_keywords = _extract_keywords(" ".join(text_parts))
    if not decision_keywords:
        return

    # Mots "forts" : chiffres OU mots longs (>7 lettres) → 1 seul match suffit
    strong = {k for k in decision_keywords if k.isdigit() or len(k) > 7}

    result = await session.execute(
        sql_text(
            "SELECT id, field, value FROM agent_collected_info WHERE user_id = :uid"
        ),
        {"uid": user_id},
    )
    rows = result.mappings().all()

    ids_to_delete: list[int] = []
    for r in rows:
        row_text = f"{r['field']} {r['value']}"
        row_keywords = _extract_keywords(row_text)
        common = decision_keywords & row_keywords
        common_strong = strong & row_keywords
        # Match si >=2 keywords communs OU >=1 keyword "fort" partagé
        if len(common) >= 2 or len(common_strong) >= 1:
            ids_to_delete.append(r["id"])

    for rid in ids_to_delete:
        await session.execute(
            sql_text("DELETE FROM agent_collected_info WHERE id = :rid"),
            {"rid": rid},
        )


async def _cleanup_agent_messages_for_decision_async(
    session, user_id: str | None, decision
) -> None:
    """Supprime les rows des tables de memoire agent qui mentionnent les mots
    cles forts de la decision :
      - agent_messages    : historique chat Agent 1
      - agent2_messages   : historique chat Agent 2
      - agent3_memory     : memoire partagee (cle/valeur) entre tous les agents

    Evite que l'agent continue a se souvenir du sujet apres suppression.
    Heuristique conservatrice : >= 1 mot-cle fort partage suffit pour delete.

    Migration PG (2026-05-12) : version async via SQLAlchemy text(). La caller
    gere le commit. SECURITE : les noms de tables/colonnes sont en whitelist
    statique pour eviter toute SQL injection (jamais derive de l'input user).
    """
    if not user_id:
        return
    from sqlalchemy import text as sql_text
    text_parts = [decision.question or ""]
    for opt in (decision.options or []):
        text_parts.append(opt.description or "")
        text_parts.append(opt.explication_impact or "")
    decision_keywords = _extract_keywords(" ".join(text_parts))
    strong = {k for k in decision_keywords if k.isdigit() or len(k) > 7}
    if not strong:
        return

    def _match(content: str | None) -> bool:
        return bool(strong & _extract_keywords(content or ""))

    # Tables (table_name, content_columns_to_check) — whitelist statique
    targets = [
        ('agent_messages', ['content']),
        ('agent2_messages', ['content']),
        ('agent3_memory', ['key', 'value']),  # memoire partagee : cle ET valeur
    ]
    for table, cols in targets:
        try:
            sel_cols = 'id, ' + ', '.join(cols)
            result = await session.execute(
                sql_text(f"SELECT {sel_cols} FROM {table} WHERE auth_user_id = :uid"),
                {"uid": user_id},
            )
            rows = result.mappings().all()
        except Exception:
            continue
        ids_to_delete: list[str] = []
        for r in rows:
            combined = ' '.join((r[c] or '') for c in cols)
            if _match(combined):
                ids_to_delete.append(r['id'])
        for rid in ids_to_delete:
            try:
                await session.execute(
                    sql_text(f"DELETE FROM {table} WHERE id = :rid"),
                    {"rid": rid},
                )
            except Exception:
                # Best-effort par row : ne pas casser le cleanup global
                continue


async def _cleanup_pending_for_decision_async(
    session, user_id: str | None, decision_id: str
) -> None:
    """Marque les pending_actions liées à cette décision comme abandonnées.

    Utile si l'utilisateur supprime l'evenement avant le check final : le
    pending_action ne doit plus revenir le harceler.

    Migration PG (2026-05-12) : version async via SQLAlchemy text(). La caller
    gere le commit.
    """
    if not user_id or not decision_id:
        return
    from sqlalchemy import text as sql_text
    try:
        await session.execute(
            sql_text(
                "UPDATE pending_actions SET statut = 'abandoned' "
                "WHERE auth_user_id = :uid AND source_id = :sid "
                "AND statut IN ('pending', 'in_progress')"
            ),
            {"uid": user_id, "sid": decision_id},
        )
    except Exception:
        # Table peut ne pas exister selon le schema en cours
        return


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
        rappels=getattr(d, "rappels", None),
    )


@router.get("", response_model=List[DecisionOut])
async def get_historique(
    limite: int = Query(default=20, ge=1, le=1000),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Retourne les N dernieres decisions de l'utilisateur.

    Migration PG (2026-05-12) : utilise SQLAlchemy text() pour etre compatible
    SQLite ET PostgreSQL. La syntaxe `:name` au lieu de `?` est portable.

    Le profil_repo reste sync (charge depuis le DatabaseManager raw) — c'est
    une migration progressive : on remplace les requetes SQL une par une.
    """
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    # ── Migration SQLAlchemy ────────────────────────────────────────────
    # Avant : decision_repo.lister_pour_utilisateur(profil.id, limite=limite)
    # Apres : SQLAlchemy async avec text() — fonctionne sur SQLite et PG.
    from sqlalchemy import text
    from api.database import get_session_factory
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(
            text(
                "SELECT * FROM decisions WHERE user_id = :uid "
                "ORDER BY cree_le DESC LIMIT :limite"
            ),
            {"uid": profil.id, "limite": limite},
        )
        rows = result.mappings().all()

    # Decision.from_dict attend un dict avec les bonnes cles
    decisions = [Decision.from_dict(dict(r)) for r in rows]
    return [_decision_to_out(d) for d in decisions]


@router.get("/pagine", response_model=HistoriquePagineOut)
async def get_historique_pagine(
    page: int = Query(default=1, ge=1),
    par_page: int = Query(default=10, ge=1, le=50),
    tri: str = Query(default="recent"),
    recherche: str = Query(default=""),
    profil_repo: ProfilRepository = Depends(get_profil_repo),
    user_id: str | None = Depends(get_optional_user),
):
    """Retourne les decisions paginees avec tri et recherche.

    Migration PG : utilise SQLAlchemy text() — compatible SQLite + PG.
    """
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    rech = recherche.strip() or None
    import math
    from sqlalchemy import text
    from api.database import get_session_factory

    # Tri whitelist (eviter SQL injection sur la clause ORDER BY)
    order_clause = {
        "recent": "cree_le DESC",
        "ancien": "cree_le ASC",
        "impact": "ABS(COALESCE(probabilite_apres, probabilite_avant) - probabilite_avant) DESC",
    }.get(tri, "cree_le DESC")

    offset = (max(1, page) - 1) * par_page
    params: dict = {"uid": profil.id, "limite": par_page, "offset": offset}

    where_clause = "user_id = :uid"
    if rech:
        where_clause += " AND question LIKE :rech"
        params["rech"] = f"%{rech}%"

    factory = get_session_factory()
    async with factory() as session:
        # COUNT total
        count_sql = f"SELECT COUNT(*) FROM decisions WHERE {where_clause}"
        count_params = {k: v for k, v in params.items() if k in ('uid', 'rech')}
        total = (await session.execute(text(count_sql), count_params)).scalar() or 0

        # SELECT paginated
        list_sql = (
            f"SELECT * FROM decisions WHERE {where_clause} "
            f"ORDER BY {order_clause} LIMIT :limite OFFSET :offset"
        )
        result = await session.execute(text(list_sql), params)
        rows = result.mappings().all()

    decisions = [Decision.from_dict(dict(r)) for r in rows]
    pages_total = max(1, math.ceil(total / par_page))
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
    user_id: str | None = Depends(get_optional_user),
):
    """Retourne le rapport des actions effectuees par l'agent.

    Migration PG : utilise SQLAlchemy text() — compatible SQLite + PG.
    Optimisation : on filtre directement les rows ayant action_agent_json non-null
    (skip celles sans action).
    """
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT * FROM decisions WHERE user_id = :uid "
                "AND action_agent_json IS NOT NULL "
                "ORDER BY cree_le DESC LIMIT 50"
            ),
            {"uid": profil.id},
        )
        rows = result.mappings().all()

    decisions = [Decision.from_dict(dict(r)) for r in rows]
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
    """Supprime une décision et recalcule la probabilité actuelle.

    Migration PG (2026-05-12) : tous les writes liés à la décision (recompute
    SO, cleanup contexte agent, DELETE decision) passent par UNE seule session
    SQLAlchemy async — atomique, compatible SQLite + PostgreSQL.

    Le profil_repo.sauvegarder reste en sync (transaction séparée) car il
    cascade sur des modèles complexes (objectif, etc.) — migration différée
    à la phase ProfilRepository.
    """
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Aucun profil trouvé.")

    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    # 1. Charger la décision AVANT suppression pour connaître son impact
    #    (utilise encore le sync repo : lecture rapide, pas dans la transaction
    #    écriture)
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
    # Refonte robustesse : on appelle TOUJOURS _recompute_so_progressions
    # (au lieu d'un seuil > 50% sur impact_sous_objectif). Raison : detecter
    # un cascade overflow apres-coup est impossible — meme un applied_delta
    # de 25% peut avoir cascade jusqu'a 5+ SOs. Recompute global est le seul
    # moyen sur de preserver l'invariant Dashboard.
    #
    # BUG FIX (2026-05-13) : on calcule le nouveau temps_gagne AVANT le
    # recompute, et on le passe en override. Sans ca, le recompute lit le
    # temps_gagne PRE-DELETE depuis la DB → drift de `impact_temps` jours
    # dans l'invariant Dashboard. Avec l'override, l'invariant tient
    # exactement post-DELETE.
    new_temps_gagne_jours = max(0, profil.temps_gagne_jours - impact_temps)

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            # 2b. Recompute SO progressions (invariant Dashboard).
            # On recompute des qu'il y a un impact temps (pas seulement quand
            # sous_objectif_id est defini) : les decisions issues du TRACKING ont
            # sous_objectif_id=None mais un impact temps reel qui a cascade sur
            # les SO. Sans recompute, supprimer une telle decision baisse
            # temps_gagne sans rajuster les SO -> drift de l'invariant Dashboard
            # ("Desynchronisation detectee"). Le recompute est global+idempotent
            # et no-op s'il n'y a aucun SO.
            if decision.sous_objectif_id or abs(impact_temps) > 0.001:
                try:
                    await _recompute_so_progressions_async(
                        session, profil.id,
                        exclude_decision_id=decision_id,
                        temps_gagne_override=new_temps_gagne_jours,
                    )
                except Exception:
                    pass  # Best-effort : ne pas bloquer la suppression

            # 3a. Nettoyer le contexte agent lié à cette décision :
            #   - agent_collected_info : matching heuristique mots-cles
            #   - agent_messages / agent2_messages / agent3_memory : mots forts
            #   - pending_actions : marquees abandoned
            try:
                await _cleanup_collected_info_for_decision_async(
                    session, profil.id, user_id, decision
                )
                await _cleanup_agent_messages_for_decision_async(
                    session, user_id, decision
                )
                await _cleanup_pending_for_decision_async(
                    session, user_id, decision_id
                )
            except Exception:
                pass  # Best-effort : ne pas bloquer la suppression

            # 3. Supprimer la décision (dans la meme transaction que les
            #    cleanups + recompute SO — atomique)
            await session.execute(
                text("DELETE FROM decisions WHERE id = :did AND user_id = :uid"),
                {"did": decision_id, "uid": profil.id},
            )

            await session.commit()
        except Exception:
            await session.rollback()
            raise

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

    Migration PG (2026-05-12) : utilise SQLAlchemy async — compatible
    SQLite + PostgreSQL.
    """
    if not profil_repo.existe(auth_user_id=user_id):
        raise HTTPException(status_code=404, detail="Profil introuvable.")
    profil = profil_repo.charger(auth_user_id=user_id)
    if profil is None:
        raise HTTPException(status_code=404, detail="Profil introuvable.")

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            await _recompute_so_progressions_async(
                session, profil.id, exclude_decision_id=None
            )
            await session.commit()
        except Exception:
            await session.rollback()
            raise

        result = await session.execute(
            text(
                "SELECT id, titre, progression FROM sous_objectifs "
                "WHERE user_id = :uid ORDER BY ordre"
            ),
            {"uid": profil.id},
        )
        so_rows = result.mappings().all()

    return {
        "ok": True,
        "sous_objectifs": [
            {"id": r["id"], "titre": r["titre"], "progression": r["progression"]}
            for r in so_rows
        ],
    }
