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
        save_memory, load_memories, format_memories,
    )
    save_memory(db, user_id, "ville", "Lyon", category="profil")
    memories = load_memories(db, user_id, limit=50)
    block = format_memories(memories)
    system_prompt = block + "\\n\\n" + core_prompt
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone, timedelta
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
# CRUD
# ─────────────────────────────────────────────────────────────────────────────

def save_memory(db: Any, user_id: str, key: str, value: str, category: str = "general") -> None:
    """Sauvegarde un fait en memoire (upsert sur user_id+key)."""
    if not user_id or not key:
        return
    ensure_memory_table(db)
    now = datetime.now(timezone.utc).isoformat()
    existing = db.conn.execute(
        "SELECT id FROM agent3_memory WHERE auth_user_id = ? AND key = ?",
        (user_id, key),
    ).fetchone()
    if existing:
        db.conn.execute(
            "UPDATE agent3_memory SET value = ?, updated_at = ? WHERE id = ?",
            (value, now, existing[0]),
        )
    else:
        db.conn.execute(
            "INSERT INTO agent3_memory (id, auth_user_id, key, value, category, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, key, value, category, now, now),
        )
    db.conn.commit()


def load_memories(db: Any, user_id: str, limit: int = 50) -> list[dict]:
    """Charge les souvenirs recents pour ce user (tous agents confondus)."""
    if not user_id:
        return []
    ensure_memory_table(db)
    try:
        rows = db.conn.execute(
            "SELECT key, value, category, updated_at FROM agent3_memory "
            "WHERE auth_user_id = ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, max(1, min(int(limit), 500))),
        ).fetchall()
        return [
            {"key": r[0], "value": r[1], "category": r[2], "updated_at": r[3]}
            for r in rows
        ]
    except Exception as e:
        logger.debug(f"load_memories failed: {e}")
        return []


def delete_memory(db: Any, user_id: str, key: str) -> bool:
    """Supprime un fait specifique."""
    if not user_id or not key:
        return False
    try:
        db.conn.execute(
            "DELETE FROM agent3_memory WHERE auth_user_id = ? AND key = ?",
            (user_id, key),
        )
        db.conn.commit()
        return True
    except Exception:
        return False


def cleanup_old_memories(db: Any, user_id: str, days: int = 90) -> int:
    """Supprime les memoires de faible valeur > X jours.

    Preserve les memoires liees aux decisions a fort impact (>= 30j).
    """
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    try:
        # Chercher mots-cles des decisions a fort impact (a preserver)
        try:
            high_impact_rows = db.conn.execute(
                "SELECT question FROM decisions WHERE user_id IN "
                "(SELECT id FROM profil_utilisateur WHERE auth_user_id = ?) "
                "AND ABS(COALESCE(impact_temporel_jours, 0)) >= 30",
                (user_id,),
            ).fetchall()
            preserve_keywords = set()
            for row in high_impact_rows:
                for word in row[0].lower().split():
                    if len(word) > 3:
                        preserve_keywords.add(word)
        except Exception:
            preserve_keywords = set()

        old_rows = db.conn.execute(
            "SELECT key, value FROM agent3_memory WHERE auth_user_id = ? AND created_at < ?",
            (user_id, cutoff),
        ).fetchall()
        deleted = 0
        for key, value in old_rows:
            text = f"{key} {value}".lower()
            if not any(kw in text for kw in preserve_keywords):
                db.conn.execute(
                    "DELETE FROM agent3_memory WHERE auth_user_id = ? AND key = ?",
                    (user_id, key),
                )
                deleted += 1
        if deleted:
            db.conn.commit()
        return deleted
    except Exception:
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Recherche
# ─────────────────────────────────────────────────────────────────────────────

def search_memories(db: Any, user_id: str, query: str, top_k: int = 10) -> list:
    """Recherche TF-IDF dans les souvenirs (fallback mots-cles)."""
    try:
        from api.agent3_memory_extractor import semantic_search
    except Exception:
        return []
    all_memories = load_memories(db, user_id, limit=500)
    if not all_memories:
        return []
    try:
        return semantic_search(query, all_memories, top_k=top_k)
    except Exception:
        return []


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

    existing = load_memories(db, user_id, limit=80)
    extractor = MemoryExtractor(client)
    try:
        facts = await extractor.extract(turns, existing_memories=existing)
    except Exception as e:
        logger.debug(f"[{agent_label}] extract failed: {e}")
        return []

    saved = []
    for f in facts:
        try:
            save_memory(db, user_id, f.key, f.value, category=f.category)
            saved.append(f)
        except Exception:
            continue

    if saved:
        logger.info(f"[{agent_label}] extracted {len(saved)} memories for user {user_id[:8]}")
        scheduler.force_reset(user_id)
    return saved


__all__ = [
    "ensure_memory_table",
    "save_memory",
    "load_memories",
    "delete_memory",
    "cleanup_old_memories",
    "search_memories",
    "format_memories",
    "auto_extract_from_turns",
]
