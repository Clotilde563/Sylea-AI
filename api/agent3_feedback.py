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


__all__ = [
    "ensure_feedback_table",
    # Async versions (migration PG, 2026-05-13)
    "ensure_feedback_table_async",
    "record_feedback_async",
    "get_recent_feedback_async",
    "get_feedback_stats_async",
    "get_feedback_comments_for_prompt_async",
    "format_feedback_context_async",
]


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

async def ensure_feedback_table_async() -> None:
    """Version async de ensure_feedback_table — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(text(_FEEDBACK_DDL))
            await session.execute(text(_FEEDBACK_INDEX_DDL))
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.debug(f"ensure_feedback_table_async failed: {e}")


async def record_feedback_async(
    user_id: str,
    *,
    vote: str,
    message_id: str | None = None,
    comment: str | None = None,
    agent_response: str | None = None,
) -> dict[str, Any]:
    """Version async de record_feedback — PG-compatible.

    Plus de parametre `db` : utilise get_session_factory() directement.
    """
    from sqlalchemy import text
    from api.database import get_session_factory

    if not user_id:
        return {"ok": False, "error": "no user_id"}
    if vote not in ("up", "down"):
        return {"ok": False, "error": f"invalid vote: {vote}"}

    await ensure_feedback_table_async()

    feedback_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    snapshot = (agent_response or "")[:4000]
    comment_clean = (comment or "")[:2000] if comment else None

    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO agent3_feedback "
                    "(id, auth_user_id, message_id, vote, comment, agent_response, created_at) "
                    "VALUES (:id, :uid, :mid, :vote, :comment, :resp, :now)"
                ),
                {
                    "id": feedback_id,
                    "uid": user_id,
                    "mid": message_id,
                    "vote": vote,
                    "comment": comment_clean,
                    "resp": snapshot,
                    "now": now,
                },
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.warning(f"record_feedback_async insert failed: {e}")
            return {"ok": False, "error": f"db_error: {type(e).__name__}"}

    return {"ok": True, "feedback_id": feedback_id, "created_at": now}


async def get_recent_feedback_async(
    user_id: str, *, limit: int = 20,
) -> list[dict[str, Any]]:
    """Version async de get_recent_feedback — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory

    if not user_id:
        return []
    await ensure_feedback_table_async()
    limit = max(1, min(int(limit), 200))

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT id, message_id, vote, comment, agent_response, created_at "
                    "FROM agent3_feedback WHERE auth_user_id = :uid "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                {"uid": user_id, "lim": limit},
            )
            rows = result.mappings().all()
        except Exception as e:
            logger.debug(f"get_recent_feedback_async failed: {e}")
            return []
    return [
        {
            "id": r["id"],
            "message_id": r["message_id"],
            "vote": r["vote"],
            "comment": r["comment"],
            "agent_response": r["agent_response"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


async def get_feedback_stats_async(user_id: str) -> dict[str, Any]:
    """Version async de get_feedback_stats — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory

    if not user_id:
        return {"thumbs_up": 0, "thumbs_down": 0, "total": 0, "ratio": 0.0}
    await ensure_feedback_table_async()

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT "
                    " SUM(CASE WHEN vote='up' THEN 1 ELSE 0 END) AS ups, "
                    " SUM(CASE WHEN vote='down' THEN 1 ELSE 0 END) AS downs, "
                    " COUNT(*) AS total "
                    "FROM agent3_feedback WHERE auth_user_id = :uid"
                ),
                {"uid": user_id},
            )
            row = result.first()
        except Exception as e:
            logger.debug(f"get_feedback_stats_async failed: {e}")
            return {"thumbs_up": 0, "thumbs_down": 0, "total": 0, "ratio": 0.0}

    if row is None:
        return {"thumbs_up": 0, "thumbs_down": 0, "total": 0, "ratio": 0.0}
    up, down, total = row[0] or 0, row[1] or 0, row[2] or 0
    ratio = (up / total) if total > 0 else 0.0
    return {
        "thumbs_up": int(up),
        "thumbs_down": int(down),
        "total": int(total),
        "ratio": round(ratio, 3),
    }


async def get_feedback_comments_for_prompt_async(
    user_id: str, *, limit: int = 5,
) -> list[str]:
    """Version async de get_feedback_comments_for_prompt — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory

    if not user_id:
        return []
    await ensure_feedback_table_async()

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT comment, agent_response FROM agent3_feedback "
                    "WHERE auth_user_id = :uid AND vote = 'down' "
                    "AND comment IS NOT NULL AND LENGTH(comment) > 10 "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                {"uid": user_id, "lim": max(1, min(int(limit), 20))},
            )
            rows = result.mappings().all()
        except Exception as e:
            logger.debug(f"get_feedback_comments_for_prompt_async failed: {e}")
            return []
    return [r["comment"] for r in rows if r["comment"]]


async def format_feedback_context_async(user_id: str) -> str:
    """Version async de format_feedback_context — PG-compatible."""
    if not user_id:
        return ""
    stats = await get_feedback_stats_async(user_id)
    if stats["total"] < 3:
        return ""

    parts: list[str] = ["=== FEEDBACK UTILISATEUR (historique) ==="]
    parts.append(
        f"- Score : {stats['thumbs_up']} 👍 / {stats['thumbs_down']} 👎 "
        f"(ratio {stats['ratio'] * 100:.0f}%)"
    )

    if stats["thumbs_down"] > 0:
        negatives = await get_feedback_comments_for_prompt_async(user_id, limit=3)
        if negatives:
            parts.append("- Corrections recentes a prendre en compte :")
            for c in negatives:
                parts.append(f"  * \"{c[:150]}\"")

    parts.append(
        "Utilise ces retours pour eviter les erreurs passees. "
        "Si ratio < 50%, redouble d'attention sur la precision et le format."
    )
    return "\n".join(parts)
