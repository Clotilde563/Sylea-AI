"""
Awareness contextuelle proactive d'Agent 3.

Construit un bloc "contexte actuel" injecte en debut de system prompt pour que
l'agent ait conscience de :
  - La date/heure + timezone
  - Le jour de la semaine + moment (matin/apres-midi/soir)
  - Patterns temporels detectes (via historique agent3_messages)
  - Prochains evenements calendrier (si Google connecte)
  - Humeur / bien-etre recent (via ProfilRepository bilans)

Cache TTL 10min par user pour eviter de recalculer a chaque requete.

Usage :
    from api.agent3_awareness import build_awareness_block
    block = build_awareness_block(db, user_id)
    system_prompt = block + "\n\n" + core_prompt
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone, timedelta
from typing import Any

logger = logging.getLogger("sylea.awareness")


_AWARENESS_CACHE_TTL_S = 600.0   # 10 minutes
_awareness_cache: dict[str, tuple[float, str]] = {}
_awareness_lock = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers temps
# ─────────────────────────────────────────────────────────────────────────────

def _current_moment(now: datetime) -> str:
    h = now.hour
    if h < 6:
        return "nuit"
    if h < 12:
        return "matin"
    if h < 14:
        return "midi"
    if h < 18:
        return "apres-midi"
    if h < 22:
        return "soir"
    return "nuit"


_WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _format_now_block(now: datetime) -> list[str]:
    weekday = _WEEKDAYS_FR[now.weekday()]
    moment = _current_moment(now)
    date_fr = now.strftime("%d/%m/%Y")
    return [
        f"- **Moment** : {weekday} {date_fr}, {now.strftime('%Hh%M')} ({moment})",
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Patterns historiques
# ─────────────────────────────────────────────────────────────────────────────

def invalidate_awareness_cache(user_id: str | None = None) -> None:
    """Force le refresh. Utile apres un changement d'objectif ou bilan."""
    with _awareness_lock:
        if user_id is None:
            _awareness_cache.clear()
        else:
            _awareness_cache.pop(user_id, None)


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════
#
# PORTABILITE : SQLite strftime() → on parse en Python (cross-DB).

async def _detect_usage_patterns_async(user_id: str, now: datetime) -> list[str]:
    """Version async — PG-compatible. Parse les timestamps en Python pour
    eviter SQLite-specific strftime()."""
    from sqlalchemy import text
    from api.database import get_session_factory
    observations: list[str] = []
    factory = get_session_factory()
    try:
        async with factory() as session:
            cutoff = (now - timedelta(days=30)).isoformat()
            # Average messages per active day
            try:
                result = await session.execute(
                    text(
                        "SELECT created_at FROM agent3_messages "
                        "WHERE auth_user_id = :uid AND created_at >= :cutoff "
                        "AND role = 'user'"
                    ),
                    {"uid": user_id, "cutoff": cutoff},
                )
                rows = result.mappings().all()
                total = len(rows)
                days_set = set()
                hour_match = 0
                current_hour = now.hour
                for r in rows:
                    try:
                        ts = datetime.fromisoformat(
                            str(r["created_at"]).replace("Z", "+00:00")
                        )
                        days_set.add(ts.date().isoformat())
                        if abs(ts.hour - current_hour) <= 1:
                            hour_match += 1
                    except Exception:
                        continue
                days = max(1, len(days_set))
                if total:
                    avg = total / days
                    if avg >= 0.5:
                        observations.append(
                            f"- **Activite** : ~{avg:.1f} interactions par jour "
                            f"({total} sur {days} jours actifs)"
                        )
                if hour_match >= 5:
                    observations.append(
                        f"- **Pattern horaire** : tu me parles souvent autour de "
                        f"{current_hour}h ({hour_match} fois ces derniers mois)"
                    )
            except Exception as e:
                logger.debug(f"patterns async failed: {e}")
    except Exception:
        pass
    return observations


async def _recent_wellbeing_async(user_id: str) -> list[str]:
    """Version async — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    out: list[str] = []
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT b.date, b.niveau_sante, b.niveau_stress, "
                    "b.niveau_energie, b.niveau_bonheur "
                    "FROM bilans_quotidiens b "
                    "JOIN profil_utilisateur p ON p.id = b.user_id "
                    "WHERE p.auth_user_id = :uid "
                    "ORDER BY b.date DESC LIMIT 1"
                ),
                {"uid": user_id},
            )
            row = result.mappings().first()
            if row:
                date_iso = row["date"]
                scores = {
                    "sante": row["niveau_sante"], "stress": row["niveau_stress"],
                    "energie": row["niveau_energie"], "bonheur": row["niveau_bonheur"],
                }
                items = [(k, v) for k, v in scores.items()
                         if isinstance(v, (int, float))]
                if items:
                    items.sort(key=lambda x: x[1])
                    low, high = items[0], items[-1]
                    out.append(
                        f"- **Dernier bilan** ({date_iso}) : "
                        f"point faible {low[0]}={low[1]}/10, "
                        f"point fort {high[0]}={high[1]}/10"
                    )
                    return out
            # Fallback : scores courants sur profil
            result = await session.execute(
                text(
                    "SELECT niveau_sante, niveau_stress, niveau_energie, niveau_bonheur "
                    "FROM profil_utilisateur WHERE auth_user_id = :uid LIMIT 1"
                ),
                {"uid": user_id},
            )
            prow = result.mappings().first()
            if prow:
                scores = {
                    "sante": prow["niveau_sante"], "stress": prow["niveau_stress"],
                    "energie": prow["niveau_energie"], "bonheur": prow["niveau_bonheur"],
                }
                items = [(k, v) for k, v in scores.items()
                         if isinstance(v, (int, float)) and v]
                if items:
                    items.sort(key=lambda x: x[1])
                    low, high = items[0], items[-1]
                    out.append(
                        f"- **Bien-etre actuel** : "
                        f"point faible {low[0]}={low[1]}/10, "
                        f"point fort {high[0]}={high[1]}/10"
                    )
    except Exception as e:
        logger.debug(f"wellbeing async failed: {e}")
    return out


async def _objective_snapshot_async(user_id: str) -> list[str]:
    """Version async — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    out: list[str] = []
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT objectif_description, objectif_categorie, objectif_deadline, "
                    "temps_initial_jours, temps_gagne_jours "
                    "FROM profil_utilisateur WHERE auth_user_id = :uid LIMIT 1"
                ),
                {"uid": user_id},
            )
            row = result.mappings().first()
            if row and row["objectif_description"]:
                desc = str(row["objectif_description"])[:150]
                cat = row["objectif_categorie"] or ""
                deadline = row["objectif_deadline"]
                t_init = row["temps_initial_jours"] or 0
                t_gagne = row["temps_gagne_jours"] or 0
                progression = (t_gagne / t_init * 100) if t_init > 0 else 0
                bits = [f"'{desc}'"]
                if cat:
                    bits.append(f"cat: {cat}")
                if deadline:
                    bits.append(f"deadline: {deadline}")
                bits.append(f"progression: {progression:.1f}%")
                out.append(f"- **Objectif de vie** : {' | '.join(bits)}")
    except Exception as e:
        logger.debug(f"objective async failed: {e}")
    return out


async def build_awareness_block_async(user_id: str | None) -> str:
    """Version async de build_awareness_block — PG-compatible.

    Plus de parametre `db` : utilise get_session_factory().
    Cache 10min identique a la version sync.
    """
    if not user_id:
        return ""

    # Check cache (partage avec la version sync)
    with _awareness_lock:
        cached = _awareness_cache.get(user_id)
        if cached and (time.time() - cached[0] < _AWARENESS_CACHE_TTL_S):
            return cached[1]

    try:
        now = datetime.now(timezone.utc).astimezone()
    except Exception:
        now = datetime.utcnow()

    lines: list[str] = ["=== CONTEXTE ACTUEL (awareness) ==="]
    lines.extend(_format_now_block(now))
    lines.extend(await _objective_snapshot_async(user_id))
    lines.extend(await _recent_wellbeing_async(user_id))
    lines.extend(await _detect_usage_patterns_async(user_id, now))

    if len(lines) <= 1:
        block = ""
    else:
        lines.append(
            "\nUtilise ce contexte pour personnaliser ta reponse. Exemples : "
            "saluer par le prenom si tu le connais, adapter le ton a l'heure "
            "(moins enthousiaste en nuit), rappeler l'objectif si pertinent, "
            "proposer des choses coherentes avec le pattern horaire."
        )
        block = "\n".join(lines) + "\n"

    with _awareness_lock:
        _awareness_cache[user_id] = (time.time(), block)
    return block


__all__ = [
    "build_awareness_block_async",
    "invalidate_awareness_cache",
]
