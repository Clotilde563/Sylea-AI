"""
Agent 3 — Feedback explicite (thumbs up/down) sur les reponses agent.

Complement de `FeedbackLearner` (corrections implicites) :
  - Ici, l'utilisateur click explicitement 👍 ou 👎 sur une reponse.
  - Stocke dans table dediee `agent3_feedback` (vs memoire sémantique).
  - Agrege en stats + reinjecte un resume dans le system prompt.

API :
  - `record_feedback(db, user_id, message_id, vote, comment)`
  - `get_recent_feedback(db, user_id, limit)`
  - `get_feedback_stats(db, user_id)` -> {thumbs_up, thumbs_down, ratio}
  - `format_feedback_context(stats, recent)` -> str pour system prompt

Table schema (auto-creee) :
  agent3_feedback (
    id TEXT PRIMARY KEY,
    auth_user_id TEXT NOT NULL,
    message_id TEXT,           -- id du message agent concerne (optionnel)
    vote TEXT NOT NULL,         -- "up" | "down"
    comment TEXT,               -- commentaire libre du user
    agent_response TEXT,        -- snapshot (pour context futur)
    created_at TEXT NOT NULL
  )
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger("sylea.feedback")


_FEEDBACK_DDL = """
CREATE TABLE IF NOT EXISTS agent3_feedback (
    id TEXT PRIMARY KEY,
    auth_user_id TEXT NOT NULL,
    message_id TEXT,
    vote TEXT NOT NULL,
    comment TEXT,
    agent_response TEXT,
    created_at TEXT NOT NULL
)
"""

_FEEDBACK_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_feedback_user_date "
    "ON agent3_feedback(auth_user_id, created_at DESC)"
)


def ensure_feedback_table(db: Any) -> None:
    try:
        db.conn.execute(_FEEDBACK_DDL)
        db.conn.execute(_FEEDBACK_INDEX_DDL)
        db.conn.commit()
    except Exception as e:
        logger.debug(f"ensure_feedback_table failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Write
# ─────────────────────────────────────────────────────────────────────────────

VoteType = Literal["up", "down"]


def record_feedback(
    db: Any,
    user_id: str,
    *,
    vote: str,
    message_id: str | None = None,
    comment: str | None = None,
    agent_response: str | None = None,
) -> dict[str, Any]:
    """Enregistre un vote explicite.

    vote doit etre "up" ou "down". Comment et message_id sont optionnels.
    """
    if not user_id:
        return {"ok": False, "error": "no user_id"}
    if vote not in ("up", "down"):
        return {"ok": False, "error": f"invalid vote: {vote}"}

    ensure_feedback_table(db)

    feedback_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    snapshot = (agent_response or "")[:4000]  # cap snapshot size
    comment_clean = (comment or "")[:2000] if comment else None

    try:
        db.conn.execute(
            "INSERT INTO agent3_feedback "
            "(id, auth_user_id, message_id, vote, comment, agent_response, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (feedback_id, user_id, message_id, vote, comment_clean, snapshot, now),
        )
        db.conn.commit()
    except Exception as e:
        logger.warning(f"record_feedback insert failed: {e}")
        return {"ok": False, "error": f"db_error: {type(e).__name__}"}

    return {"ok": True, "feedback_id": feedback_id, "created_at": now}


# ─────────────────────────────────────────────────────────────────────────────
# Read
# ─────────────────────────────────────────────────────────────────────────────

def get_recent_feedback(
    db: Any, user_id: str, *, limit: int = 20,
) -> list[dict[str, Any]]:
    """Derniers feedbacks du user."""
    if not user_id:
        return []
    ensure_feedback_table(db)
    limit = max(1, min(int(limit), 200))
    try:
        rows = db.conn.execute(
            "SELECT id, message_id, vote, comment, agent_response, created_at "
            "FROM agent3_feedback WHERE auth_user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    except Exception as e:
        logger.debug(f"get_recent_feedback failed: {e}")
        return []
    return [
        {
            "id": r[0],
            "message_id": r[1],
            "vote": r[2],
            "comment": r[3],
            "agent_response": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]


def get_feedback_stats(db: Any, user_id: str) -> dict[str, Any]:
    """Aggregat : thumbs_up, thumbs_down, ratio, total."""
    if not user_id:
        return {"thumbs_up": 0, "thumbs_down": 0, "total": 0, "ratio": 0.0}
    ensure_feedback_table(db)
    try:
        row = db.conn.execute(
            "SELECT "
            " SUM(CASE WHEN vote='up' THEN 1 ELSE 0 END), "
            " SUM(CASE WHEN vote='down' THEN 1 ELSE 0 END), "
            " COUNT(*) "
            "FROM agent3_feedback WHERE auth_user_id = ?",
            (user_id,),
        ).fetchone()
    except Exception as e:
        logger.debug(f"get_feedback_stats failed: {e}")
        return {"thumbs_up": 0, "thumbs_down": 0, "total": 0, "ratio": 0.0}
    up, down, total = row[0] or 0, row[1] or 0, row[2] or 0
    ratio = (up / total) if total > 0 else 0.0
    return {
        "thumbs_up": int(up),
        "thumbs_down": int(down),
        "total": int(total),
        "ratio": round(ratio, 3),
    }


def get_feedback_comments_for_prompt(
    db: Any, user_id: str, *, limit: int = 5,
) -> list[str]:
    """Derniers commentaires avec vote down (utile pour apprendre des erreurs)."""
    if not user_id:
        return []
    ensure_feedback_table(db)
    try:
        rows = db.conn.execute(
            "SELECT comment, agent_response FROM agent3_feedback "
            "WHERE auth_user_id = ? AND vote = 'down' "
            "AND comment IS NOT NULL AND LENGTH(comment) > 10 "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, max(1, min(int(limit), 20))),
        ).fetchall()
    except Exception as e:
        logger.debug(f"get_feedback_comments_for_prompt failed: {e}")
        return []
    return [r[0] for r in rows if r[0]]


def format_feedback_context(db: Any, user_id: str) -> str:
    """Bloc a injecter dans le system prompt.

    Retourne "" si pas assez de feedback pour etre utile.
    """
    if not user_id:
        return ""
    stats = get_feedback_stats(db, user_id)
    if stats["total"] < 3:
        return ""

    parts: list[str] = ["=== FEEDBACK UTILISATEUR (historique) ==="]
    parts.append(
        f"- Score : {stats['thumbs_up']} 👍 / {stats['thumbs_down']} 👎 "
        f"(ratio {stats['ratio'] * 100:.0f}%)"
    )

    if stats["thumbs_down"] > 0:
        negatives = get_feedback_comments_for_prompt(db, user_id, limit=3)
        if negatives:
            parts.append("- Corrections recentes a prendre en compte :")
            for c in negatives:
                parts.append(f"  * \"{c[:150]}\"")

    parts.append(
        "Utilise ces retours pour eviter les erreurs passees. "
        "Si ratio < 50%, redouble d'attention sur la precision et le format."
    )
    return "\n".join(parts)


__all__ = [
    "ensure_feedback_table",
    "record_feedback",
    "get_recent_feedback",
    "get_feedback_stats",
    "get_feedback_comments_for_prompt",
    "format_feedback_context",
]
