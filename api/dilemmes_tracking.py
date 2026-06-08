"""
Dilemmes en mode TRACKING — nouveau systeme de suivi des decisions.

Difference avec l'ancien systeme (table `decisions`) :

  ANCIEN : analyse → user choisit option A/B/... → impact applique immediatement.
  NOUVEAU : analyse → user clique "Suivre cette decision" → tracking demarre.
            Pendant la duree de l'engagement :
              - durée ≤ 30j : 1 notif a la fin
              - durée > 30j : notif mensuelle (1× par mois jusqu'a la fin)
            Chaque notif demande : "as-tu fait Option A ? Option B ? Aucun ?"
            Quand toutes les periodes sont remplies → recap pondere → user valide
            → impact final applique (puis row decision creee pour l'historique).

Pourquoi ? L'utilisateur ne sait pas a l'avance s'il va REELLEMENT tenir son
engagement. L'ancien systeme appliquait l'impact comme si l'option choisie
etait certaine, ce qui faussait la jauge de probabilite. Le nouveau systeme
mesure ce qui s'est REELLEMENT passe, pondere par les choix mensuels, et
applique l'impact REEL au moment de la validation finale.

═══════════ Schema ═══════════

Table `dilemmes_tracking` :
  - id           : UUID
  - user_id      : auth_user_id du proprietaire
  - question     : texte du dilemme
  - options_json : [{description, impact_jours, pros, cons, resume}, ...]
  - verdict      : verdict initial Sylea
  - etude_scientifique : citation initiale
  - impact_temporel_jours : duree totale (1, 7, 30, 365, ...)
  - nb_periodes  : 1 si <=30j, sinon ceil(jours/30)
  - device_tz    : timezone du device au moment de la creation (ex: "Europe/Paris")
  - choices_json : [{periode_idx, choice, responded_at, retry_count}, ...]
                   choice = index option (0,1,...) ou 'none' ou null si pas encore repondu
  - status       : 'tracking' | 'awaiting_validation' | 'validated' | 'cancelled'
  - impact_final_jours : applique a la validation
  - impact_final_probabilite : delta de probabilite calcule
  - so_impactes_json : snapshot des sous-objectifs impactes
  - cancellation_mode : 'zero' | 'partial' | null
  - next_notif_at    : prochaine notif (UTC, calcule a partir de device_tz)
  - created_at, validated_at, cancelled_at

Conception async PG-compatible : tous les SELECT/UPDATE passent par
SQLAlchemy text() + get_session_factory() (cf. agent3_quotas.py).
"""

from __future__ import annotations

import json
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

logger = logging.getLogger("sylea.dilemmes_tracking")


# ─────────────────────────────────────────────────────────────────────────────
# Schema DDL — Compat SQLite + PostgreSQL
# ─────────────────────────────────────────────────────────────────────────────

_TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS dilemmes_tracking (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    question TEXT NOT NULL,
    options_json TEXT NOT NULL,
    verdict TEXT,
    etude_scientifique TEXT,
    impact_temporel_jours INTEGER NOT NULL,
    nb_periodes INTEGER NOT NULL,
    device_tz TEXT NOT NULL DEFAULT 'UTC',
    choices_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'tracking',
    impact_final_jours REAL,
    impact_final_probabilite REAL,
    so_impactes_json TEXT,
    cancellation_mode TEXT,
    next_notif_at TEXT,
    created_at TEXT NOT NULL,
    validated_at TEXT,
    cancelled_at TEXT
)
"""

_TRACKING_INDEX_USER = (
    "CREATE INDEX IF NOT EXISTS idx_tracking_user "
    "ON dilemmes_tracking(user_id, status)"
)

_TRACKING_INDEX_NOTIF = (
    "CREATE INDEX IF NOT EXISTS idx_tracking_next_notif "
    "ON dilemmes_tracking(next_notif_at) "
    "WHERE status = 'tracking'"
)


def ensure_tracking_tables(db: Any) -> None:
    """Cree la table et les indexes (idempotent)."""
    try:
        db.conn.execute(_TRACKING_DDL)
        db.conn.execute(_TRACKING_INDEX_USER)
        # L'index partiel "WHERE status = 'tracking'" n'est pas supporte par
        # SQLite < 3.8 — on retombe sur un index complet si echec.
        try:
            db.conn.execute(_TRACKING_INDEX_NOTIF)
        except Exception:
            db.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracking_next_notif "
                "ON dilemmes_tracking(next_notif_at)"
            )
        db.conn.commit()
    except Exception as e:
        logger.debug(f"ensure_tracking_tables failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers temporels
# ─────────────────────────────────────────────────────────────────────────────


def _compute_nb_periodes(impact_temporel_jours: int) -> int:
    """
    1 periode si la duree est <= 30 jours (notif unique a la fin).
    Sinon nb_periodes = round(jours / 30), minimum 1.

    Exemples :
        7 jours  -> 1 periode (1 notif a J+7)
        30 jours -> 1 periode
        45 jours -> round(45/30) = 2 (notifs a J+30 et J+45)
        90 jours -> 3 (mensuel)
        365 jours -> 12 (mensuel)
        1825 jours (5 ans) -> 61 (mensuel sur 5 ans)
    """
    if impact_temporel_jours <= 30:
        return 1
    return max(1, round(impact_temporel_jours / 30))


def _next_notif_at_utc(
    created_at_utc: datetime,
    periode_idx: int,
    impact_temporel_jours: int,
    nb_periodes: int,
    device_tz: str,
) -> datetime:
    """
    Calcule l'instant UTC de la prochaine notif pour une periode donnee.

    Regle : la notif arrive a 20h heure LOCALE de l'utilisateur, le dernier
    jour de la periode. Pour une duree courte (1 periode), c'est a la fin
    de impact_temporel_jours. Pour mensuel, c'est tous les 30 jours.

    periode_idx commence a 0. Pour 12 periodes :
      0 -> J+30 a 20h locale
      1 -> J+60 a 20h locale
      ...
      11 -> J+360 a 20h locale (et la 12e/derniere = J+impact_temporel_jours
            si impact_temporel_jours != 30 * nb_periodes)

    Pour la DERNIERE periode, on cale sur impact_temporel_jours exact.
    Pour les autres, sur 30 * (periode_idx + 1) jours.
    """
    if periode_idx >= nb_periodes - 1:
        # Derniere periode : sur l'echeance exacte du dilemme
        target_day_offset = impact_temporel_jours
    elif nb_periodes == 1:
        target_day_offset = impact_temporel_jours
    else:
        # Periode intermediaire : mensuel
        target_day_offset = 30 * (periode_idx + 1)

    # Construit le datetime cible a 20h heure locale du device
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(device_tz)
    except Exception:
        tz = timezone.utc

    # Date cible en heure locale = created_at converti dans tz + offset jours,
    # puis fixe a 20:00:00
    created_local = created_at_utc.astimezone(tz)
    target_local = (created_local + timedelta(days=target_day_offset)).replace(
        hour=20, minute=0, second=0, microsecond=0
    )
    # Si target_local est dans le passe (cas edge ou la creation s'est faite
    # apres 20h le jour J et target = jour J), on ajoute 1 jour pour eviter
    # une notif instantanee.
    if target_local <= created_local:
        target_local += timedelta(days=1)

    return target_local.astimezone(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# CRUD async
# ─────────────────────────────────────────────────────────────────────────────


async def create_tracking_async(
    user_id: str,
    question: str,
    options: list[dict],
    verdict: str,
    etude_scientifique: str,
    impact_temporel_jours: int,
    device_tz: str = "UTC",
) -> dict[str, Any]:
    """
    Cree un nouveau dilemme en tracking. Retourne le dict de la row creee.

    `options` doit etre une liste de dicts avec au minimum :
      [{"description": str, "impact_jours": float, "pros": list[str],
        "cons": list[str], "resume": str}, ...]
    """
    from api.database import get_session_factory

    tracking_id = uuid.uuid4().hex
    now_utc = datetime.now(timezone.utc)
    nb_periodes = _compute_nb_periodes(impact_temporel_jours)

    # Init choices_json avec une entree par periode (toutes vides)
    choices = [
        {
            "periode_idx": i,
            "choice": None,  # null = pas encore repondu
            "responded_at": None,
            "retry_count": 0,
        }
        for i in range(nb_periodes)
    ]

    # Prochaine notif = periode 0
    next_notif_utc = _next_notif_at_utc(
        now_utc, 0, impact_temporel_jours, nb_periodes, device_tz
    )

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text(
                "INSERT INTO dilemmes_tracking ("
                "id, user_id, question, options_json, verdict, etude_scientifique, "
                "impact_temporel_jours, nb_periodes, device_tz, choices_json, "
                "status, next_notif_at, created_at"
                ") VALUES ("
                ":id, :uid, :q, :opts, :verdict, :etude, "
                ":itj, :nbp, :tz, :choices, "
                "'tracking', :next_notif, :created"
                ")"
            ),
            {
                "id": tracking_id,
                "uid": user_id,
                "q": question,
                "opts": json.dumps(options, ensure_ascii=False),
                "verdict": verdict,
                "etude": etude_scientifique,
                "itj": impact_temporel_jours,
                "nbp": nb_periodes,
                "tz": device_tz,
                "choices": json.dumps(choices, ensure_ascii=False),
                "next_notif": next_notif_utc.isoformat(),
                "created": now_utc.isoformat(),
            },
        )
        await session.commit()

    return {
        "id": tracking_id,
        "nb_periodes": nb_periodes,
        "next_notif_at": next_notif_utc.isoformat(),
        "status": "tracking",
    }


async def get_tracking_async(tracking_id: str, user_id: str) -> dict | None:
    """Recupere un tracking. Verifie aussi le proprietaire (security)."""
    from api.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT id, user_id, question, options_json, verdict, etude_scientifique, "
                "impact_temporel_jours, nb_periodes, device_tz, choices_json, status, "
                "impact_final_jours, impact_final_probabilite, so_impactes_json, "
                "cancellation_mode, next_notif_at, created_at, validated_at, cancelled_at "
                "FROM dilemmes_tracking WHERE id = :id AND user_id = :uid"
            ),
            {"id": tracking_id, "uid": user_id},
        )
        row = result.mappings().first()

    if not row:
        return None

    return _row_to_dict(row)


async def list_tracking_async(
    user_id: str, status: str | None = None
) -> list[dict]:
    """Liste tous les trackings d'un user, filtrable par status."""
    from api.database import get_session_factory

    factory = get_session_factory()
    sql = (
        "SELECT id, user_id, question, options_json, verdict, etude_scientifique, "
        "impact_temporel_jours, nb_periodes, device_tz, choices_json, status, "
        "impact_final_jours, impact_final_probabilite, so_impactes_json, "
        "cancellation_mode, next_notif_at, created_at, validated_at, cancelled_at "
        "FROM dilemmes_tracking WHERE user_id = :uid"
    )
    params: dict[str, Any] = {"uid": user_id}
    if status:
        sql += " AND status = :st"
        params["st"] = status
    sql += " ORDER BY created_at DESC"

    async with factory() as session:
        result = await session.execute(text(sql), params)
        rows = result.mappings().all()

    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: Any) -> dict:
    """Convertit une row SQLAlchemy en dict avec JSON parse."""
    d = dict(row)
    for key in ("options_json", "choices_json", "so_impactes_json"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except Exception:
                d[key] = []
        elif key in d:
            d[key] = []
    return d


async def respond_to_period_async(
    tracking_id: str,
    user_id: str,
    periode_idx: int,
    choice: str,  # "0", "1", ..., ou "none"
    allow_early: bool = False,  # True = bypass time check (scheduler/auto_overdue)
) -> dict:
    """
    Enregistre une reponse de l'user pour une periode donnee.

    SECURITE TEMPORELLE : refuse de repondre a une periode dont la date de
    notification n'est PAS encore atteinte. Un user ne peut pas "completer"
    son engagement en quelques secondes via l'API. Override possible :
      - allow_early=True (parametre interne, scheduler)
      - env var SYLEA_TRACKING_BYPASS_TIME=true (tests E2E)

    Si toutes les periodes sont remplies, bascule le status a
    'awaiting_validation' et retourne all_responded=True.

    Idempotent : si la periode a deja ete repondue, on remplace par la
    nouvelle reponse (cas notif redondante OS + in-app).

    Retourne {
        ok: bool,
        all_responded: bool,
        nb_responded: int,
        nb_total: int,
        next_notif_at: ISO timestamp ou null si plus rien a notifier,
        error: 'periode_not_yet_due' si validation temporelle echoue,
    }
    """
    import os
    from api.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT choices_json, nb_periodes, impact_temporel_jours, "
                "device_tz, created_at, status "
                "FROM dilemmes_tracking WHERE id = :id AND user_id = :uid"
            ),
            {"id": tracking_id, "uid": user_id},
        )
        row = result.mappings().first()
        if not row:
            return {"ok": False, "error": "tracking_not_found"}
        if row["status"] not in ("tracking",):
            return {"ok": False, "error": f"status_invalid:{row['status']}"}

        choices = json.loads(row["choices_json"])
        if not (0 <= periode_idx < row["nb_periodes"]):
            return {"ok": False, "error": "periode_idx_out_of_range"}

        # ── Validation temporelle : la periode doit etre arrivee a echeance ──
        bypass_env = os.environ.get("SYLEA_TRACKING_BYPASS_TIME", "").strip().lower() in ("1", "true", "yes", "on")
        if not allow_early and not bypass_env:
            created_at_raw = datetime.fromisoformat(row["created_at"])
            if created_at_raw.tzinfo is None:
                created_at_raw = created_at_raw.replace(tzinfo=timezone.utc)
            expected_notif = _next_notif_at_utc(
                created_at_raw, periode_idx,
                row["impact_temporel_jours"], row["nb_periodes"], row["device_tz"],
            )
            now_utc = datetime.now(timezone.utc)
            if now_utc < expected_notif:
                return {
                    "ok": False,
                    "error": "periode_not_yet_due",
                    "expected_notif_at": expected_notif.isoformat(),
                    "periode_idx": periode_idx,
                }

        # Update du choix (idempotent — overwrite si deja set)
        now_iso = datetime.now(timezone.utc).isoformat()
        choices[periode_idx]["choice"] = choice
        choices[periode_idx]["responded_at"] = now_iso

        # Recalcule next_notif_at pour la PROCHAINE periode non repondue
        next_pending_idx = None
        for i, c in enumerate(choices):
            if c["choice"] is None:
                next_pending_idx = i
                break

        if next_pending_idx is None:
            # Tout repondu -> bascule awaiting_validation
            # next_notif_at = NOW + 3 jours (premiere relance avant auto-validate).
            # Le scheduler enverra une notif "valide ton recap" a J+3, puis
            # auto-valide a J+7 (cf. dilemmes_tracking_scheduler).
            new_status = "awaiting_validation"
            next_notif_iso = (
                datetime.now(timezone.utc) + timedelta(days=3)
            ).isoformat()
        else:
            new_status = "tracking"
            created_at = datetime.fromisoformat(row["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            next_notif = _next_notif_at_utc(
                created_at,
                next_pending_idx,
                row["impact_temporel_jours"],
                row["nb_periodes"],
                row["device_tz"],
            )
            next_notif_iso = next_notif.isoformat()

        await session.execute(
            text(
                "UPDATE dilemmes_tracking SET "
                "choices_json = :choices, status = :status, next_notif_at = :next_notif "
                "WHERE id = :id"
            ),
            {
                "choices": json.dumps(choices, ensure_ascii=False),
                "status": new_status,
                "next_notif": next_notif_iso,
                "id": tracking_id,
            },
        )
        await session.commit()

    return {
        "ok": True,
        "all_responded": new_status == "awaiting_validation",
        "nb_responded": sum(1 for c in choices if c["choice"] is not None),
        "nb_total": row["nb_periodes"],
        "next_notif_at": next_notif_iso,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Calcul du recap pondere
# ─────────────────────────────────────────────────────────────────────────────


def compute_recap(tracking: dict) -> dict:
    """
    Calcule l'impact final pondere en fonction des choix faits.

    Algorithme :
      Pour chaque option (A, B, ...) :
        nb_clicks = nombre de fois ou l'user l'a choisie
        impact_pondere = options[idx].impact_jours * (nb_clicks / nb_periodes)
      Pour 'none' :
        nb_clicks = nombre de fois "Aucun"
        impact_pondere = 0
      impact_total_jours = somme des impact_pondere

    Exemple (Anglais +150 / Italien -80 sur 12 periodes, 6×A 4×B 2×none) :
      Anglais : 150 * (6/12) = +75
      Italien : -80 * (4/12) = -26.67
      None    : 0
      Total = +48.33

    Retourne {
        breakdown: [
            {option, label, nb_clicks, percentage, impact_pondere}, ...
        ],
        impact_total_jours: float,
    }
    """
    options = tracking.get("options_json", [])
    choices = tracking.get("choices_json", [])
    nb_periodes = tracking.get("nb_periodes", 1)

    # Compte les clicks par option
    counts: dict[str, int] = {}
    for c in choices:
        ch = c.get("choice")
        if ch is None:
            continue
        counts[ch] = counts.get(ch, 0) + 1

    breakdown = []
    impact_total = 0.0

    # Une entree par option du dilemme
    for idx, opt in enumerate(options):
        key = str(idx)
        nb = counts.get(key, 0)
        weight = nb / nb_periodes if nb_periodes > 0 else 0
        impact_pondere = float(opt.get("impact_jours", 0)) * weight
        breakdown.append(
            {
                "option": key,
                "label": opt.get("description", f"Option {idx}"),
                "nb_clicks": nb,
                "percentage": round(weight * 100, 1),
                "impact_pondere": round(impact_pondere, 2),
            }
        )
        impact_total += impact_pondere

    # Entree pour "Aucun des deux"
    nb_none = counts.get("none", 0)
    breakdown.append(
        {
            "option": "none",
            "label": "Aucun des deux",
            "nb_clicks": nb_none,
            "percentage": round(nb_none / nb_periodes * 100, 1) if nb_periodes else 0,
            "impact_pondere": 0,
        }
    )

    return {
        "breakdown": breakdown,
        "impact_total_jours": round(impact_total, 2),
        "nb_periodes": nb_periodes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Enregistrement dans l'historique des decisions (validate / abandon)
# ─────────────────────────────────────────────────────────────────────────────


def _build_rappels_detail(tracking: dict, mode: str) -> dict:
    """Construit le detail periode-par-periode des rappels pour l'historique
    des decisions. `mode` = 'validated' | 'abandoned'."""
    options = tracking.get("options_json", []) or []
    choices = tracking.get("choices_json", []) or []
    nb_periodes = tracking.get("nb_periodes", len(choices) or 1)

    periodes: list[dict] = []
    nb_repondu = 0
    for c in choices:
        ch = c.get("choice")
        repondu = ch is not None
        if repondu:
            nb_repondu += 1
        if ch is None:
            label, description = "—", "Pas de reponse"
        elif ch == "none":
            label, description = "Aucun", "Aucune des options"
        else:
            try:
                opt = options[int(ch)]
                label = opt.get("lettre") or chr(65 + int(ch))
                description = opt.get("description", "")
            except (ValueError, IndexError, TypeError):
                label, description = str(ch), ""
        periodes.append({
            "index": int(c.get("periode_idx", 0)) + 1,
            "label": label,
            "description": description,
            "responded_at": c.get("responded_at"),
            "repondu": repondu,
        })

    return {
        "mode": mode,
        "nb_periodes": nb_periodes,
        "nb_repondu": nb_repondu,
        "periodes": periodes,
    }


async def _record_tracking_decision_async(
    session,
    tracking: dict,
    *,
    mode: str,  # 'validated' | 'abandoned'
    prob_before: float,
    prob_after: float,
    tg_before: float,
    tg_after: float,
    recap: dict,
    so_impactes: list[dict] | None = None,
) -> None:
    """Cree une row `decisions` (historique) a partir d'un tracking valide ou
    abandonne, avec le detail des rappels.

    IMPORTANT : n'applique AUCUN impact (deja applique par le caller via
    _apply_impact_with_cascade_async + _persist_profil_temps_in_session, dans la
    MEME transaction). On se contente d'ENREGISTRER l'evenement dans l'historique
    des decisions (cohérence : impact_net = temps_gagne_apres - temps_gagne_avant
    = impact reel applique, donc sum(decisions.impact_net) reste aligne sur
    profil.temps_gagne_jours). INSERT dans la session fournie -> atomique avec
    l'UPDATE du statut tracking.
    """
    from sylea.core.models.decision import Decision, OptionDilemme

    tr_options = tracking.get("options_json", []) or []
    options = [
        OptionDilemme(
            description=o.get("description", ""),
            impact_score=float(o.get("impact_jours", 0) or 0),
            explication_impact=o.get("resume", "") or "",
        )
        for o in tr_options
    ]

    # Option dominante (la plus cliquee, hors 'none') -> option_choisie de la
    # decision historique. None si l'user n'a jamais choisi d'option.
    chosen_id: str | None = None
    best_clicks = 0
    for b in (recap.get("breakdown", []) if recap else []):
        if b.get("option") == "none":
            continue
        try:
            idx = int(b.get("option"))
        except (ValueError, TypeError):
            continue
        if b.get("nb_clicks", 0) > best_clicks and 0 <= idx < len(options):
            best_clicks = b["nb_clicks"]
            chosen_id = options[idx].id

    # Sous-objectif cible (coherence Chart1 + recompute distribution) : on
    # rattache la decision au SO que la cascade a vise (est_cible), sinon au
    # premier SO impacte. Ainsi la decision suivie se comporte comme une
    # decision classique vis-a-vis des sous-objectifs (timeline + recompute).
    cible_so_id: str | None = None
    cible_impact = 0.0
    for it in (so_impactes or []):
        if it.get("est_cible"):
            cible_so_id = it.get("so_id")
            cible_impact = float(it.get("delta_pct", 0) or 0)
            break
    if cible_so_id is None and so_impactes:
        cible_so_id = so_impactes[0].get("so_id")
        cible_impact = float(so_impactes[0].get("delta_pct", 0) or 0)

    decision = Decision(
        user_id=tracking["user_id"],
        question=tracking.get("question", ""),
        options=options,
        probabilite_avant=round(prob_before, 2),
        option_choisie_id=chosen_id,
        probabilite_apres=round(prob_after, 2),
        impact_temporel_jours=tracking.get("impact_temporel_jours"),
        sous_objectif_id=cible_so_id,
        impact_sous_objectif=cible_impact,
        temps_gagne_avant=round(tg_before, 4),
        temps_gagne_apres=round(tg_after, 4),
        rappels=_build_rappels_detail(tracking, mode),
    )
    decision.cree_le = datetime.now(timezone.utc)

    data = decision.to_dict()
    cols = ", ".join(data.keys())
    placeholders = ", ".join(f":{k}" for k in data.keys())
    await session.execute(
        text(f"INSERT INTO decisions ({cols}) VALUES ({placeholders})"),
        data,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Validation finale (= applique l'impact)
# ─────────────────────────────────────────────────────────────────────────────


async def _apply_impact_with_cascade_async(
    profil_id: str,
    temps_initial_jours: float,
    impact_jours: float,
    session: Any = None,
) -> list[dict]:
    """
    Applique impact_jours sur les sous-objectifs du user et retourne la
    liste des SOs effectivement modifies (cible + cascade), formattee comme
    cascade_items dans evenement.py.

    Reutilise `apply_impact_invariant_safe_async` (cf. api/so_invariant.py)
    pour garder l'invariant Dashboard.

    Cible le PREMIER sous-objectif non-sature (l'IA n'est pas appelee ici
    car la cible reelle est determinee au moment de l'analyse initiale —
    le tracking n'a pas vocation a re-questionner les SO).

    Atomicite : si `session` est fourni, la cascade s'execute DANS cette
    session SANS commit (le caller gere la transaction -> validate/cancel
    appliquent cascade + profil + statut + decision en UNE transaction).
    Sinon, la fonction cree sa propre session et commit (comportement legacy).
    """
    from sqlalchemy import text as _sql_text
    from api.database import get_session_factory
    from api.so_invariant import apply_impact_invariant_safe_async

    if not impact_jours or abs(impact_jours) < 0.001:
        return []

    async def _do(sess) -> list[dict]:
        cascade_items: list[dict] = []
        # 1. SELECT sous_objectifs (snapshot AVANT)
        result = await sess.execute(
            _sql_text(
                "SELECT id, titre, progression, ordre, temps_estime "
                "FROM sous_objectifs WHERE user_id = :uid ORDER BY ordre"
            ),
            {"uid": profil_id},
        )
        all_so_all = list(result.mappings().all())
        if not all_so_all:
            return []

        prog_before: dict[str, tuple[str, float]] = {
            so["id"]: (so["titre"], float(so["progression"] or 0.0))
            for so in all_so_all
        }

        # Cible = premier SO non-sature dans la direction de l'impact.
        target_so_id = None
        if impact_jours >= 0:
            candidates = [
                so["id"] for so in all_so_all
                if (so["progression"] or 0.0) < 100
            ]
        else:
            candidates = [
                so["id"] for so in all_so_all
                if (so["progression"] or 0.0) > 0
            ]
        if candidates:
            target_so_id = candidates[0]

        # 2. Cascade invariant-safe (pas de commit : gere par le caller)
        target_id_used, _delta_pct = await apply_impact_invariant_safe_async(
            sess, profil_id, target_so_id, impact_jours, temps_initial_jours,
        )

        # 3. Snapshot APRES
        after = await sess.execute(
            _sql_text(
                "SELECT id, progression FROM sous_objectifs WHERE user_id = :uid"
            ),
            {"uid": profil_id},
        )
        prog_after = {
            r["id"]: float(r["progression"] or 0.0)
            for r in after.mappings().all()
        }

        for sid, (titre, p_before) in prog_before.items():
            p_after = prog_after.get(sid, p_before)
            delta = p_after - p_before
            if abs(delta) < 0.05:
                continue
            cascade_items.append({
                "so_id": sid,
                "titre": titre,
                "progression_avant": round(p_before, 2),
                "progression_apres": round(p_after, 2),
                "delta_pct": round(delta, 2),
                "est_cible": sid == (target_id_used or target_so_id),
                "est_complete": p_after >= 99.99,
            })

        cascade_items.sort(
            key=lambda i: (not i["est_cible"], -abs(i["delta_pct"]))
        )
        return cascade_items

    # Cas atomique : on rejoint la transaction du caller (pas de commit ici).
    if session is not None:
        return await _do(session)

    # Cas legacy : transaction autonome.
    factory = get_session_factory()
    async with factory() as own:
        try:
            items = await _do(own)
            await own.commit()
            return items
        except Exception:
            await own.rollback()
            raise


def _compute_delta_probabilite(prob_actuelle: float, impact_jours: float) -> float:
    """Convertit un impact_jours en delta de probabilite (formule inverse
    de la jauge Dashboard). Memes constantes que ailleurs dans l'app."""
    temps_estime_jours = max(
        1, round(900 * ((100 - prob_actuelle) / max(0.01, prob_actuelle)) ** 0.675)
    )
    temps_apres = max(1, temps_estime_jours - impact_jours)
    prob_apres = 100.0 / (1.0 + (temps_apres / 900.0) ** (1.0 / 0.675))
    return round(prob_apres - prob_actuelle, 4)


async def _persist_profil_temps_in_session(session, profil: Any, impact_jours: float) -> float:
    """Met a jour temps_gagne + probabilite_actuelle du profil DANS la session
    fournie (full UPDATE via to_dict, SANS commit) et met a jour l'objet profil
    en memoire. Retourne le temps_gagne APRES (clampe a [0, temps_initial]).

    Remplace l'ancien chemin sync (profil_repo.sauvegarder, hors transaction) :
    permet a validate/cancel d'appliquer cascade SO + profil + statut + decision
    dans UNE SEULE transaction atomique. Idempotence : un crash en plein vol
    roll back tout -> le tracking reste 'awaiting_validation' -> retry propre,
    jamais de double application ni de drift.

    NB : en mutation de temps_gagne, sauvegarder() saute de toute facon son
    alignement progressions->temps_gagne (detection mutation) ; on reproduit
    donc fidelement son effet (UPDATE de toutes les colonnes du profil) sans cet
    alignement. Compatible SQLite + PG (text() portable, pas de _run_async sync
    imbrique).
    """
    temps_initial = float(getattr(profil, "temps_initial_jours", 0) or 0)
    tg_before = float(getattr(profil, "temps_gagne_jours", 0) or 0)
    if not impact_jours or abs(impact_jours) < 0.001:
        return tg_before
    tg_after = max(0.0, min(temps_initial, tg_before + impact_jours))
    profil.temps_gagne_jours = tg_after
    if temps_initial > 0:
        profil.probabilite_actuelle = round((tg_after / temps_initial) * 100, 2)
    profil.marquer_modification()
    pdata = profil.to_dict()
    updates = ", ".join(f"{k} = :{k}" for k in pdata if k != "id")
    await session.execute(
        text(f"UPDATE profil_utilisateur SET {updates} WHERE id = :id"),
        pdata,
    )
    return tg_after


async def validate_tracking_async(
    tracking_id: str,
    user_id: str,
    profil: Any,
    profil_repo: Any,
) -> dict:
    """
    Marque le tracking comme valide et applique l'impact final.

    Etapes :
      1. Charge le tracking (verifie status='awaiting_validation' ou bypass)
      2. Calcule le recap pondere
      3. Applique l'impact via apply_impact_invariant_safe_async (memes
         mecaniques que les decisions actuelles -> cascade dans les SO)
      4. Met a jour profil.temps_gagne_jours + profil.probabilite_actuelle
      5. Met a jour le tracking : status='validated', impact_final_*, so_impactes
    """
    from api.database import get_session_factory

    tracking = await get_tracking_async(tracking_id, user_id)
    if not tracking:
        return {"ok": False, "error": "tracking_not_found"}
    if tracking["status"] not in ("awaiting_validation", "tracking"):
        return {"ok": False, "error": f"status_invalid:{tracking['status']}"}

    recap = compute_recap(tracking)
    impact_jours = float(recap["impact_total_jours"])  # valeur theorique (recap)
    prob_before = float(getattr(profil, "probabilite_actuelle", 0) or 0)
    tg_before = float(getattr(profil, "temps_gagne_jours", 0) or 0)
    temps_initial = float(getattr(profil, "temps_initial_jours", 0) or 0)
    delta_prob = _compute_delta_probabilite(prob_before, impact_jours)

    # ── Transaction UNIQUE (atomicite) ──────────────────────────────────────
    # cascade SO + profil + statut + decision commitent ENSEMBLE, ou rien. Un
    # crash en plein vol roll back tout -> le tracking reste
    # 'awaiting_validation' -> retry propre, jamais de double application ni de
    # drift d'invariant Dashboard.
    factory = get_session_factory()
    now_iso = datetime.now(timezone.utc).isoformat()
    so_impactes: list[dict] = []
    impact_reel = 0.0
    async with factory() as session:
        try:
            so_impactes = await _apply_impact_with_cascade_async(
                profil_id=profil.id,
                temps_initial_jours=temps_initial,
                impact_jours=impact_jours,
                session=session,
            )
            tg_after = await _persist_profil_temps_in_session(session, profil, impact_jours)
            # Impact REELLEMENT reflete sur temps_gagne (post-clamp). Peut
            # differer du recap si le profil est proche d'un bord (99.9%) ou si
            # les SO saturent.
            impact_reel = round(tg_after - tg_before, 4)

            await session.execute(
                text(
                    "UPDATE dilemmes_tracking SET status='validated', "
                    "impact_final_jours = :ij, impact_final_probabilite = :ip, "
                    "so_impactes_json = :so, validated_at = :v "
                    "WHERE id = :id"
                ),
                {
                    "ij": impact_jours,
                    "ip": delta_prob,
                    "so": json.dumps(so_impactes, ensure_ascii=False),
                    "v": now_iso,
                    "id": tracking_id,
                },
            )
            # Regle : enregistrement dans l'historique des decisions UNIQUEMENT
            # si la decision a un impact REEL sur le temps vers l'objectif
            # (impact_reel != 0). Validation sans impact -> aucune trace.
            if abs(impact_reel) > 0.001:
                await _record_tracking_decision_async(
                    session, tracking,
                    mode="validated",
                    prob_before=prob_before,
                    prob_after=prob_before + delta_prob,
                    tg_before=tg_before,
                    tg_after=tg_after,
                    recap=recap,
                    so_impactes=so_impactes,
                )
            await session.commit()
        except Exception as e:
            await session.rollback()
            # Transaction annulee : on restaure le profil en memoire pour qu'il
            # reste coherent avec la DB (rien n'a ete applique).
            profil.temps_gagne_jours = tg_before
            profil.probabilite_actuelle = prob_before
            logger.exception("validate_tracking_async atomic failed")
            return {"ok": False, "error": f"validate_failed: {e}"}

    # True si recap != reel applique (>0.5j) -> le front peut alerter l'user.
    divergence = abs(impact_jours - impact_reel) > 0.5
    return {
        "ok": True,
        "impact_jours_applique": impact_jours,       # recap (contrat historique)
        "impact_reel_temps_gagne": impact_reel,      # delta temps_gagne effectif
        "impact_clampe": divergence,                 # True si recap != reel (>0.5j)
        "delta_probabilite": delta_prob,
        "so_impactes": so_impactes,
        "recap": recap,
    }


async def cancel_tracking_async(
    tracking_id: str,
    user_id: str,
    mode: str,  # 'zero' ou 'partial'
    profil: Any,
    profil_repo: Any,
) -> dict:
    """
    Annule un tracking en cours.

    mode='zero' : impact 0, status='cancelled'
    mode='partial' : calcule l'impact partiel avec les choix deja faits
                    (sur la BASE des nb_periodes total, donc plus l'user a
                    repondu, plus l'impact est complet), applique, status='cancelled'
    """
    from api.database import get_session_factory

    tracking = await get_tracking_async(tracking_id, user_id)
    if not tracking:
        return {"ok": False, "error": "tracking_not_found"}
    if tracking["status"] not in ("tracking", "awaiting_validation"):
        return {"ok": False, "error": f"status_invalid:{tracking['status']}"}
    if mode not in ("zero", "partial"):
        return {"ok": False, "error": "mode_invalid"}

    # Recap toujours calcule (pur, sans effet de bord) : sert a l'enregistrement
    # de la decision dans l'historique (option dominante + detail des rappels).
    recap = compute_recap(tracking)
    prob_before = float(getattr(profil, "probabilite_actuelle", 0) or 0)
    tg_before = float(getattr(profil, "temps_gagne_jours", 0) or 0)
    temps_initial = float(getattr(profil, "temps_initial_jours", 0) or 0)
    impact_jours = float(recap["impact_total_jours"]) if mode == "partial" else 0.0
    delta_prob = (
        _compute_delta_probabilite(prob_before, impact_jours)
        if mode == "partial" else 0.0
    )

    # ── Transaction UNIQUE (atomicite) : cascade + profil + statut + decision
    # commitent ensemble, ou rien (cf. validate_tracking_async).
    factory = get_session_factory()
    now_iso = datetime.now(timezone.utc).isoformat()
    so_impactes: list[dict] = []
    impact_reel = 0.0
    async with factory() as session:
        try:
            if mode == "partial" and abs(impact_jours) > 0.001:
                so_impactes = await _apply_impact_with_cascade_async(
                    profil_id=profil.id,
                    temps_initial_jours=temps_initial,
                    impact_jours=impact_jours,
                    session=session,
                )
                tg_after = await _persist_profil_temps_in_session(
                    session, profil, impact_jours
                )
                impact_reel = round(tg_after - tg_before, 4)
            else:
                tg_after = tg_before

            await session.execute(
                text(
                    "UPDATE dilemmes_tracking SET status='cancelled', "
                    "cancellation_mode = :mode, "
                    "impact_final_jours = :ij, impact_final_probabilite = :ip, "
                    "so_impactes_json = :so, cancelled_at = :c "
                    "WHERE id = :id"
                ),
                {
                    "mode": mode,
                    "ij": impact_jours,
                    "ip": delta_prob,
                    "so": json.dumps(so_impactes, ensure_ascii=False),
                    "c": now_iso,
                    "id": tracking_id,
                },
            )
            # Regle : un abandon ne rejoint l'historique des decisions QUE s'il a
            # un impact REEL sur le temps (mode 'zero' ou periodes toutes "Aucun"
            # -> aucune trace, comme une suppression).
            if abs(impact_reel) > 0.001:
                await _record_tracking_decision_async(
                    session, tracking,
                    mode="abandoned",
                    prob_before=prob_before,
                    prob_after=prob_before + delta_prob,
                    tg_before=tg_before,
                    tg_after=tg_after,
                    recap=recap,
                    so_impactes=so_impactes,
                )
            await session.commit()
        except Exception as e:
            await session.rollback()
            profil.temps_gagne_jours = tg_before
            profil.probabilite_actuelle = prob_before
            logger.exception("cancel_tracking_async atomic failed")
            return {"ok": False, "error": f"cancel_failed: {e}"}

    return {
        "ok": True,
        "mode": mode,
        "impact_jours_applique": impact_jours,
        "delta_probabilite": delta_prob,
        "so_impactes": so_impactes,
        "recap": recap,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler : detection des notifs en retard
# ─────────────────────────────────────────────────────────────────────────────


async def find_pending_notifications_async(now_utc: datetime) -> list[dict]:
    """
    Recupere tous les trackings dont la prochaine notif est <= now_utc.

    Couvre 2 cas :
      - status='tracking' : notif de fin de periode (ou retry 7j si pas
        repondu la 1re fois)
      - status='awaiting_validation' : relance D+3 puis auto-validation D+7

    Joint la table profil_utilisateur pour recuperer auth_user_id (necessaire
    pour envoyer les notifs WS au bon user).
    """
    from api.database import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT t.id, t.user_id, t.question, t.options_json, t.choices_json, "
                "t.impact_temporel_jours, t.nb_periodes, t.device_tz, "
                "t.next_notif_at, t.created_at, t.status, "
                "p.auth_user_id AS auth_user_id "
                "FROM dilemmes_tracking t "
                "LEFT JOIN profil_utilisateur p ON p.id = t.user_id "
                "WHERE t.status IN ('tracking', 'awaiting_validation') "
                "AND t.next_notif_at IS NOT NULL "
                "AND t.next_notif_at <= :now"
            ),
            {"now": now_utc.isoformat()},
        )
        rows = result.mappings().all()

    return [_row_to_dict(r) for r in rows]


async def mark_notif_sent_async(
    tracking_id: str,
    retry_after_days: int = 7,
) -> None:
    """
    Apres envoi d'une notif, on programme un retry dans `retry_after_days`
    jours (7 par defaut). Si au prochain retry l'user n'a toujours pas
    repondu, le scheduler marquera la periode comme 'none' automatiquement
    (cf. auto_overdue_async).
    """
    from api.database import get_session_factory

    factory = get_session_factory()
    next_retry = datetime.now(timezone.utc) + timedelta(days=retry_after_days)
    async with factory() as session:
        await session.execute(
            text(
                "UPDATE dilemmes_tracking SET next_notif_at = :n WHERE id = :id"
            ),
            {"n": next_retry.isoformat(), "id": tracking_id},
        )
        await session.commit()


async def auto_overdue_async(tracking_id: str, user_id: str) -> dict:
    """
    Si la periode courante a deja eu 1 retry et que l'user n'a toujours
    pas repondu apres 7 jours -> on la marque automatiquement comme 'none'
    et on passe a la periode suivante.

    Le scheduler appelle ca apres avoir verifie qu'on a deja envoye 2 notifs
    (initial + retry) sans reponse.
    """
    tracking = await get_tracking_async(tracking_id, user_id)
    if not tracking:
        return {"ok": False, "error": "not_found"}

    choices = tracking["choices_json"]
    # Trouve la premiere periode pending et la marque 'none'
    for c in choices:
        if c["choice"] is None:
            # Scheduler legitime : bypass validation temporelle (le scheduler
            # a deja verifie que la periode etait due + retry 7j sans reponse).
            return await respond_to_period_async(
                tracking_id, user_id, c["periode_idx"], "none",
                allow_early=True,
            )

    return {"ok": True, "all_responded": True}


async def delete_tracking_async(tracking_id: str, user_id: str) -> dict:
    """
    Supprime DEFINITIVEMENT un tracking de la DB.

    Difference avec cancel(mode='zero') :
      - cancel : status='cancelled' (trace conservee dans l'historique)
      - delete : DELETE de la row (aucune trace, comme s'il n'avait jamais existe)

    Aucun impact applique sur le profil/SO. Si l'user veut conserver l'impact
    partiel des periodes deja repondues, il doit utiliser cancel('partial')
    AVANT de pouvoir delete (ou simplement ne pas appeler delete et garder
    l'historique 'cancelled').
    """
    from api.database import get_session_factory

    tracking = await get_tracking_async(tracking_id, user_id)
    if not tracking:
        return {"ok": False, "error": "tracking_not_found"}

    factory = get_session_factory()
    async with factory() as session:
        await session.execute(
            text("DELETE FROM dilemmes_tracking WHERE id = :id AND user_id = :uid"),
            {"id": tracking_id, "uid": user_id},
        )
        await session.commit()

    return {"ok": True, "deleted": True, "tracking_id": tracking_id}


__all__ = [
    "ensure_tracking_tables",
    "create_tracking_async",
    "get_tracking_async",
    "list_tracking_async",
    "respond_to_period_async",
    "compute_recap",
    "validate_tracking_async",
    "cancel_tracking_async",
    "delete_tracking_async",
    "find_pending_notifications_async",
    "mark_notif_sent_async",
    "auto_overdue_async",
]
