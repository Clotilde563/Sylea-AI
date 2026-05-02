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

def _detect_usage_patterns(db: Any, user_id: str, now: datetime) -> list[str]:
    """Analyse les 30 derniers jours pour detecter des habitudes recurrentes.

    Ex : "tous les lundis matin tu fais X", "moyenne 5 messages/jour".
    Pas de ML, juste des heuristiques simples.
    """
    observations: list[str] = []
    try:
        # Nombre de messages agent par jour (moyenne sur 30j)
        cutoff = (now - timedelta(days=30)).isoformat()
        row = db.conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT DATE(created_at)) "
            "FROM agent3_messages WHERE auth_user_id = ? AND created_at >= ? "
            "AND role = 'user'",
            (user_id, cutoff),
        ).fetchone()
        if row and row[0]:
            total, days = row[0], row[1] or 1
            avg = total / days
            if avg >= 0.5:
                observations.append(
                    f"- **Activite** : ~{avg:.1f} interactions par jour "
                    f"({total} sur {days} jours actifs)"
                )
    except Exception as e:
        logger.debug(f"patterns messages failed: {e}")

    # Pattern heure du jour : est-ce qu'il nous parle souvent a cette heure ?
    try:
        current_hour = now.hour
        row = db.conn.execute(
            "SELECT COUNT(*) FROM agent3_messages "
            "WHERE auth_user_id = ? AND role = 'user' "
            "AND CAST(strftime('%H', created_at) AS INTEGER) BETWEEN ? AND ?",
            (user_id, max(0, current_hour - 1), min(23, current_hour + 1)),
        ).fetchone()
        if row and row[0] and row[0] >= 5:
            observations.append(
                f"- **Pattern horaire** : tu me parles souvent autour de {current_hour}h "
                f"({row[0]} fois ces derniers mois)"
            )
    except Exception as e:
        logger.debug(f"patterns hour failed: {e}")

    return observations


# ─────────────────────────────────────────────────────────────────────────────
# Bien-etre recent
# ─────────────────────────────────────────────────────────────────────────────

def _recent_wellbeing(db: Any, user_id: str) -> list[str]:
    """Derniers scores de bien-etre.

    Source : table `bilans_quotidiens` joinee a `profil_utilisateur` via auth_user_id.
    Schema : niveau_sante/stress/energie/bonheur (INTEGER 1-10) + date.
    Fallback : si aucun bilan recent, lit les scores courants sur profil_utilisateur.
    """
    out: list[str] = []
    try:
        # 1) Dernier bilan quotidien (table dediee, dataset historique)
        row = db.conn.execute(
            "SELECT b.date, b.niveau_sante, b.niveau_stress, "
            "       b.niveau_energie, b.niveau_bonheur "
            "FROM bilans_quotidiens b "
            "JOIN profil_utilisateur p ON p.id = b.user_id "
            "WHERE p.auth_user_id = ? "
            "ORDER BY b.date DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if row:
            date_iso, sante, stress, energie, bonheur = row
            scores = {
                "sante": sante, "stress": stress,
                "energie": energie, "bonheur": bonheur,
            }
            items = [(k, v) for k, v in scores.items() if isinstance(v, (int, float))]
            if items:
                items.sort(key=lambda x: x[1])
                low = items[0]
                high = items[-1]
                out.append(
                    f"- **Dernier bilan** ({date_iso}) : "
                    f"point faible {low[0]}={low[1]}/10, "
                    f"point fort {high[0]}={high[1]}/10"
                )
                return out
        # 2) Fallback : scores courants stockes sur le profil
        prow = db.conn.execute(
            "SELECT niveau_sante, niveau_stress, niveau_energie, niveau_bonheur "
            "FROM profil_utilisateur WHERE auth_user_id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
        if prow:
            scores = {
                "sante": prow[0], "stress": prow[1],
                "energie": prow[2], "bonheur": prow[3],
            }
            items = [(k, v) for k, v in scores.items() if isinstance(v, (int, float)) and v]
            if items:
                items.sort(key=lambda x: x[1])
                low = items[0]
                high = items[-1]
                out.append(
                    f"- **Bien-etre actuel** : "
                    f"point faible {low[0]}={low[1]}/10, "
                    f"point fort {high[0]}={high[1]}/10"
                )
    except Exception as e:
        logger.debug(f"wellbeing failed: {e}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Objectif de vie
# ─────────────────────────────────────────────────────────────────────────────

def _objective_snapshot(db: Any, user_id: str) -> list[str]:
    """Resume de l'objectif de vie (depuis profil_utilisateur)."""
    out: list[str] = []
    try:
        row = db.conn.execute(
            "SELECT objectif_description, objectif_categorie, objectif_deadline, probabilite_actuelle "
            "FROM profil_utilisateur WHERE auth_user_id = ? LIMIT 1",
            (user_id,),
        ).fetchone()
        if row and row[0]:
            desc = str(row[0])[:150]
            cat = row[1] or ""
            deadline = row[2]  # ISO date string (ex: "2026-12-31")
            prob = row[3]
            bits = [f"'{desc}'"]
            if cat:
                bits.append(f"cat: {cat}")
            if deadline:
                bits.append(f"deadline: {deadline}")
            if prob is not None:
                bits.append(f"proba actuelle: {prob:.1f}%")
            out.append(f"- **Objectif de vie** : {' | '.join(bits)}")
    except Exception as e:
        logger.debug(f"objective failed: {e}")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Main assembly
# ─────────────────────────────────────────────────────────────────────────────

def build_awareness_block(db: Any, user_id: str | None) -> str:
    """Construit le bloc de contexte a injecter dans le system prompt.

    Cached 10min par user.
    """
    if not user_id or db is None:
        return ""

    # Check cache
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
    lines.extend(_objective_snapshot(db, user_id))
    lines.extend(_recent_wellbeing(db, user_id))
    lines.extend(_detect_usage_patterns(db, user_id, now))

    if len(lines) <= 1:
        # Rien d'interessant a signaler — pas la peine d'alourdir le prompt
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


def invalidate_awareness_cache(user_id: str | None = None) -> None:
    """Force le refresh. Utile apres un changement d'objectif ou bilan."""
    with _awareness_lock:
        if user_id is None:
            _awareness_cache.clear()
        else:
            _awareness_cache.pop(user_id, None)


__all__ = ["build_awareness_block", "invalidate_awareness_cache"]
