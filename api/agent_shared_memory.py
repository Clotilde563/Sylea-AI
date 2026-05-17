"""
Memoire partagee entre les 3 agents Sylea (Agent 1 / 2 / 3).

Pourquoi : un user a UNE seule memoire — pas une par agent. Cela evite
les redondances ("Lucas habite a Lyon" repete 3 fois) et permet aux
agents de partager le contexte (ex: Agent 3 apprend un fait, Agent 2
en beneficie).

Architecture :
  - Table SQL existante : `agent3_memory` (gardee pour backward compat,
    les data sont deja per-user, pas per-agent).
  - Helpers exposes : save_memory, load_memories, search_memories,
    format_memories, cleanup_old_memories.
  - Recherche semantique : TF-IDF cosine via api.agent3_memory_extractor.semantic_search

Usage :
    from api.agent_shared_memory import (
        save_memory_async, load_memories_async, format_memories,
    )
    await save_memory_async(user_id, "ville", "Lyon", category="profil")
    memories = await load_memories_async(user_id, limit=50)
    block = format_memories(memories)
    system_prompt = block + "\\n\\n" + core_prompt
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("sylea.shared_memory")


# ─────────────────────────────────────────────────────────────────────────────
# Schema (idempotent, safe a appeler plusieurs fois)
# ─────────────────────────────────────────────────────────────────────────────

def ensure_memory_table(db: Any) -> None:
    """Cree la table memoire partagee si absente.

    Reuse `agent3_memory` (deja per-user, pas per-agent — donc shared
    naturellement par auth_user_id).
    """
    try:
        db.conn.execute("""
            CREATE TABLE IF NOT EXISTS agent3_memory (
                id TEXT PRIMARY KEY,
                auth_user_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        db.conn.commit()
    except Exception as e:
        logger.debug(f"ensure_memory_table failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Format pour system prompt
# ─────────────────────────────────────────────────────────────────────────────

def format_memories(memories: list[dict], max_items: int = 30) -> str:
    """Formate les souvenirs pour injection dans system prompt."""
    if not memories:
        return ""
    lines = ["=== MEMOIRE PARTAGEE (sessions precedentes, tous agents) ==="]
    for m in memories[:max_items]:
        cat = m.get("category", "general")
        key = m.get("key", "")
        value = (m.get("value") or "")[:200]
        lines.append(f"  [{cat}] {key}: {value}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-extraction post-chat (reutilise extracteur Agent 3)
# ─────────────────────────────────────────────────────────────────────────────

async def auto_extract_from_turns(
    db: Any,
    user_id: str,
    turns: list[dict],
    *,
    force: bool = False,
    agent_label: str = "agent",
) -> list:
    """Extrait des facts apres une conversation et les sauvegarde.

    Reutilise MemoryExtractor (Haiku) + ExtractionScheduler (rate limit
    par char/turns). Echec silencieux pour ne pas casser le chat.

    Args:
        turns: liste de {"role": "user"|"agent", "content": str}
        force: True = ignore le rate limit
        agent_label: label pour log debug ("agent1" / "agent2" / "agent3")

    Returns:
        liste de ExtractedFact saves (peut etre vide).
    """
    if not user_id or not turns:
        return []
    import os
    try:
        from api.agent3_memory_extractor import (
            MemoryExtractor, get_extraction_scheduler,
        )
    except Exception as e:
        logger.debug(f"extractor unavailable: {e}")
        return []

    scheduler = get_extraction_scheduler()
    total_chars = sum(len(str(t.get("content", ""))) for t in turns)
    # Le dernier message user est le candidat le plus probable pour fact-rich override
    last_user_text = ""
    for t in reversed(turns):
        if t.get("role") == "user" and t.get("content"):
            last_user_text = str(t["content"])
            break
    if not force and not scheduler.should_extract(
        user_id,
        conversation_chars=total_chars,
        last_text=last_user_text,
    ):
        return []

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return []
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
    except Exception:
        return []

    existing = await load_memories_async(user_id, limit=80)
    extractor = MemoryExtractor(client)
    try:
        facts = await extractor.extract(turns, existing_memories=existing)
    except Exception as e:
        logger.debug(f"[{agent_label}] extract failed: {e}")
        return []

    saved = []
    for f in facts:
        try:
            await save_memory_async(user_id, f.key, f.value, category=f.category)
            saved.append(f)
        except Exception:
            continue

    if saved:
        logger.info(f"[{agent_label}] extracted {len(saved)} memories for user {user_id[:8]}")
        scheduler.force_reset(user_id)
    return saved


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

async def save_memory_async(
    user_id: str, key: str, value: str, category: str = "general",
) -> None:
    """Version async de save_memory — PG-compatible (upsert portable)."""
    if not user_id or not key:
        return
    from sqlalchemy import text
    from api.database import get_session_factory
    now = datetime.now(timezone.utc).isoformat()
    factory = get_session_factory()
    async with factory() as session:
        try:
            # Upsert : SELECT puis UPDATE/INSERT (portable)
            result = await session.execute(
                text(
                    "SELECT id FROM agent3_memory "
                    "WHERE auth_user_id = :uid AND key = :key"
                ),
                {"uid": user_id, "key": key},
            )
            existing = result.first()
            if existing:
                await session.execute(
                    text(
                        "UPDATE agent3_memory SET value = :val, updated_at = :now "
                        "WHERE id = :id"
                    ),
                    {"val": value, "now": now, "id": existing[0]},
                )
            else:
                await session.execute(
                    text(
                        "INSERT INTO agent3_memory "
                        "(id, auth_user_id, key, value, category, created_at, updated_at) "
                        "VALUES (:id, :uid, :key, :val, :cat, :now, :now)"
                    ),
                    {
                        "id": str(uuid.uuid4()), "uid": user_id, "key": key,
                        "val": value, "cat": category, "now": now,
                    },
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def load_memories_async(user_id: str, limit: int = 50) -> list[dict]:
    """Version async de load_memories — PG-compatible."""
    if not user_id:
        return []
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT key, value, category, updated_at FROM agent3_memory "
                    "WHERE auth_user_id = :uid ORDER BY updated_at DESC LIMIT :lim"
                ),
                {"uid": user_id, "lim": max(1, min(int(limit), 500))},
            )
            rows = result.mappings().all()
        return [
            {"key": r["key"], "value": r["value"], "category": r["category"],
             "updated_at": r["updated_at"]}
            for r in rows
        ]
    except Exception as e:
        logger.debug(f"load_memories_async failed: {e}")
        return []


async def delete_memory_async(user_id: str, key: str) -> bool:
    """Version async — PG-compatible."""
    if not user_id or not key:
        return False
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    try:
        async with factory() as session:
            try:
                await session.execute(
                    text(
                        "DELETE FROM agent3_memory "
                        "WHERE auth_user_id = :uid AND key = :key"
                    ),
                    {"uid": user_id, "key": key},
                )
                await session.commit()
                return True
            except Exception:
                await session.rollback()
                return False
    except Exception:
        return False


__all__ = [
    "ensure_memory_table",
    "save_memory_async",
    "load_memories_async",
    "delete_memory_async",
    "format_memories",
    "auto_extract_from_turns",
]
