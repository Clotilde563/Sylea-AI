"""
RAG — Retrieval Augmented Generation pour Agent 3.

Fournit une memoire semantique vraie (vs LIKE %query% de MEMORY_SEARCH) :
  - Ingestion auto de docs longs (WEB_FETCH, FILE_READ, uploads)
  - Chunking intelligent (paragraphes, preservation des limites phrase)
  - Embeddings via OpenAI text-embedding-3-small (fallback local hash si pas de cle)
  - Retrieval top-k par similarite cosine
  - Isolation stricte par user_id + scopes (session / global / shared)

Table `agent3_embeddings` :
  - id, auth_user_id, scope, source_type, source_ref, chunk_idx
  - content_text, embedding (BLOB float32), metadata_json
  - created_at, token_count (approximatif)

Fonctions principales :
  - ingest_text(db, user_id, text, *, source_type, source_ref, scope)
  - semantic_search(db, user_id, query, *, top_k, scope)
  - delete_by_source_async(user_id, source_type, source_ref)

Strategie embedding :
  1. Si OPENAI_API_KEY dispo : OpenAI text-embedding-3-small (1536 dims, ~$0.02/M tokens)
  2. Sinon : hash-based fallback (TF-IDF-like via hashing trick, 256 dims).
     Moins precis mais marche hors ligne sans dependance.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import struct
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger("sylea.rag")


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

_OPENAI_EMBED_MODEL = "text-embedding-3-small"
_OPENAI_EMBED_DIMS = 1536
_FALLBACK_DIMS = 256
_CHUNK_SIZE_CHARS = 800         # ~200 tokens, bonne granularite
_CHUNK_OVERLAP_CHARS = 100      # overlap entre chunks pour ne pas perdre le contexte
_MIN_INGEST_CHARS = 200         # en dessous, pas la peine d'ingerer
_MAX_CHUNKS_PER_SOURCE = 200    # safety : gros doc = max 200 chunks


# ─────────────────────────────────────────────────────────────────────────────
# Schema DB
# ─────────────────────────────────────────────────────────────────────────────

_EMBEDDINGS_DDL = """
CREATE TABLE IF NOT EXISTS agent3_embeddings (
    id TEXT PRIMARY KEY,
    auth_user_id TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'global',
    source_type TEXT NOT NULL,
    source_ref TEXT,
    chunk_idx INTEGER NOT NULL DEFAULT 0,
    content_text TEXT NOT NULL,
    embedding BLOB NOT NULL,
    embedding_dims INTEGER NOT NULL,
    embedding_model TEXT,
    metadata_json TEXT,
    token_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
)
"""

_EMBEDDINGS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_rag_user_scope "
    "ON agent3_embeddings(auth_user_id, scope, created_at DESC)"
)

_EMBEDDINGS_SOURCE_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_rag_source "
    "ON agent3_embeddings(auth_user_id, source_type, source_ref)"
)


def ensure_rag_tables(db: Any) -> None:
    try:
        db.conn.execute(_EMBEDDINGS_DDL)
        db.conn.execute(_EMBEDDINGS_INDEX_DDL)
        db.conn.execute(_EMBEDDINGS_SOURCE_INDEX_DDL)
        db.conn.commit()
    except Exception as e:
        logger.debug(f"ensure_rag_tables failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────────────────────────────────────────

_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def chunk_text(
    text: str,
    *,
    size: int = _CHUNK_SIZE_CHARS,
    overlap: int = _CHUNK_OVERLAP_CHARS,
) -> list[str]:
    """Decoupe le texte en chunks de ~`size` chars avec overlap.

    Strategie :
      - Prefere couper aux fins de phrases (. ! ?) puis paragraphes
      - Si impossible, coupe arbitrairement
      - Overlap pour preserver le contexte entre chunks
    """
    text = (text or "").strip()
    if len(text) <= size:
        return [text] if text else []

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            # Cherche la derniere fin de phrase/paragraphe proche
            window = text[start:end]
            # Essayer paragraphe d'abord
            para_end = window.rfind("\n\n")
            if para_end > size * 0.5:
                end = start + para_end + 2
            else:
                # Fin de phrase
                matches = list(_SENTENCE_END_RE.finditer(window))
                if matches and matches[-1].end() > size * 0.5:
                    end = start + matches[-1].end()
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks[:_MAX_CHUNKS_PER_SOURCE]


# ─────────────────────────────────────────────────────────────────────────────
# Embedding strategies
# ─────────────────────────────────────────────────────────────────────────────

def _embedding_to_blob(vec: list[float]) -> bytes:
    """Serialize float32 array -> bytes (efficient stockage SQLite)."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _blob_to_embedding(blob: bytes, dims: int) -> list[float]:
    return list(struct.unpack(f"<{dims}f", blob))


async def _embed_openai(
    texts: list[str], api_key: str,
) -> tuple[list[list[float]], str]:
    """Embedding via OpenAI API. Retourne (vectors, model_name)."""
    if not texts:
        return [], _OPENAI_EMBED_MODEL
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"input": texts, "model": _OPENAI_EMBED_MODEL},
            )
            if resp.status_code != 200:
                logger.warning(f"OpenAI embeddings failed: {resp.status_code} {resp.text[:200]}")
                raise RuntimeError(f"OpenAI embeddings HTTP {resp.status_code}")
            data = resp.json()
            vectors = [item["embedding"] for item in data.get("data", [])]
            return vectors, _OPENAI_EMBED_MODEL
    except Exception as e:
        logger.warning(f"OpenAI embeddings exception: {e}")
        raise


def _embed_fallback(texts: list[str]) -> tuple[list[list[float]], str]:
    """Fallback : hashing trick sur les n-grams (pas de dep externe).

    Pas aussi puissant que les vrais embeddings neuraux mais :
      - Marche hors ligne
      - Capture les co-occurrences de mots
      - Cosine similarity donne un signal utilisable
    """
    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * _FALLBACK_DIMS
        # Tokens lowercase + bigrams
        words = re.findall(r"\w+", text.lower())
        tokens = list(words)
        tokens.extend(f"{words[i]}_{words[i+1]}" for i in range(len(words) - 1))
        for tok in tokens:
            # Hash → bucket index + signed weight
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            idx = h % _FALLBACK_DIMS
            sign = 1.0 if (h >> 8) & 1 else -1.0
            vec[idx] += sign
        # L2 normalize
        norm = sum(v * v for v in vec) ** 0.5
        if norm > 0:
            vec = [v / norm for v in vec]
        vectors.append(vec)
    return vectors, "hash-fallback-v1"


async def embed_texts(texts: list[str]) -> tuple[list[list[float]], str]:
    """Retourne (vectors, model_name). Tente OpenAI, fallback hash si echec."""
    if not texts:
        return [], "none"
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        try:
            return await _embed_openai(texts, api_key)
        except Exception:
            logger.info("OpenAI embeddings indisponible, fallback hash")
    return _embed_fallback(texts)


# ─────────────────────────────────────────────────────────────────────────────
# Similarite cosine
# ─────────────────────────────────────────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


# ─────────────────────────────────────────────────────────────────────────────
# API publique
# ─────────────────────────────────────────────────────────────────────────────

async def ingest_text(
    db: Any,
    user_id: str,
    text: str,
    *,
    source_type: str,
    source_ref: str = "",
    scope: str = "global",
    metadata: dict | None = None,
    replace_existing: bool = True,
) -> dict[str, Any]:
    """Ingere un texte : chunk + embed + stocke.

    Migration PG (2026-05-13) : DELETE+INSERT via SQLAlchemy text() async,
    compatible SQLite + PostgreSQL. Le param `db` est garde pour compat de
    signature mais on utilise get_session_factory() en interne.
    """
    if not user_id:
        return {"ingested_chunks": 0, "total_chars": 0, "model": "none", "error": "no user_id"}
    text_str = (text or "").strip()
    if len(text_str) < _MIN_INGEST_CHARS:
        return {"ingested_chunks": 0, "total_chars": len(text_str), "model": "none", "skipped": "too_short"}

    ensure_rag_tables(db)

    from sqlalchemy import text as _sql_text
    from api.database import get_session_factory

    chunks = chunk_text(text_str)
    if not chunks:
        return {"ingested_chunks": 0, "total_chars": 0, "model": "none"}

    vectors, model = await embed_texts(chunks)
    if len(vectors) != len(chunks):
        logger.warning(f"Embedding mismatch: {len(vectors)} vs {len(chunks)} chunks")
        return {"ingested_chunks": 0, "total_chars": len(text_str), "model": model, "error": "mismatch"}

    dims = len(vectors[0]) if vectors else 0
    now = datetime.now(timezone.utc).isoformat()
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

    factory = get_session_factory()
    async with factory() as session:
        try:
            if replace_existing and source_ref:
                try:
                    await session.execute(
                        _sql_text(
                            "DELETE FROM agent3_embeddings "
                            "WHERE auth_user_id = :uid AND source_type = :stype "
                            "AND source_ref = :sref"
                        ),
                        {"uid": user_id, "stype": source_type, "sref": source_ref},
                    )
                except Exception as e:
                    logger.debug(f"delete_existing failed: {e}")

            for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
                try:
                    await session.execute(
                        _sql_text(
                            "INSERT INTO agent3_embeddings "
                            "(id, auth_user_id, scope, source_type, source_ref, "
                            "chunk_idx, content_text, embedding, embedding_dims, "
                            "embedding_model, metadata_json, token_count, created_at) "
                            "VALUES (:id, :uid, :scope, :stype, :sref, :idx, :content, "
                            ":embed, :dims, :model, :meta, :toks, :created_at)"
                        ),
                        {
                            "id": str(uuid.uuid4()), "uid": user_id, "scope": scope,
                            "stype": source_type, "sref": source_ref or "",
                            "idx": i, "content": chunk,
                            "embed": _embedding_to_blob(vec), "dims": dims,
                            "model": model, "meta": meta_json,
                            "toks": len(chunk) // 4, "created_at": now,
                        },
                    )
                except Exception as e:
                    logger.warning(f"RAG insert chunk {i} failed: {e}")
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return {
        "ingested_chunks": len(chunks),
        "total_chars": len(text_str),
        "model": model,
        "dims": dims,
    }


async def semantic_search(
    db: Any,
    user_id: str,
    query: str,
    *,
    top_k: int = 5,
    scope: str | None = None,
    source_types: list[str] | None = None,
    min_similarity: float = 0.15,
) -> list[dict[str, Any]]:
    """Recherche semantique top-k pour le user.

    Retourne liste de dicts : {content, source_type, source_ref, score, metadata, created_at}.

    Note : SQLite n'a pas d'index vectoriel — on fait du full-scan par user + cosine.
    Pour < 10k chunks par user c'est OK (<100ms). Au-dela, migrer vers Postgres+pgvector.
    """
    if not user_id or not query.strip():
        return []
    ensure_rag_tables(db)

    # Embed la query
    try:
        q_vectors, _ = await embed_texts([query])
        if not q_vectors:
            return []
        q_vec = q_vectors[0]
        q_dims = len(q_vec)
    except Exception as e:
        logger.warning(f"semantic_search embed failed: {e}")
        return []

    # Fetch les chunks compatibles via SQLAlchemy async (Migration PG)
    from sqlalchemy import text as _sql_text
    from api.database import get_session_factory
    sql = (
        "SELECT id, scope, source_type, source_ref, content_text, "
        "embedding, embedding_dims, metadata_json, created_at "
        "FROM agent3_embeddings WHERE auth_user_id = :uid AND embedding_dims = :dims"
    )
    params: dict[str, Any] = {"uid": user_id, "dims": q_dims}
    if scope is not None:
        sql += " AND scope = :scope"
        params["scope"] = scope
    if source_types:
        # Named expansion : :stype_0, :stype_1, ...
        named = [f":stype_{i}" for i in range(len(source_types))]
        sql += f" AND source_type IN ({','.join(named)})"
        for i, st in enumerate(source_types):
            params[f"stype_{i}"] = st
    sql += " ORDER BY created_at DESC LIMIT 10000"

    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(_sql_text(sql), params)
            rows = result.mappings().all()
    except Exception as e:
        logger.warning(f"semantic_search query failed: {e}")
        return []

    # Score chaque chunk
    scored: list[tuple[float, dict]] = []
    for r in rows:
        try:
            vec = _blob_to_embedding(r["embedding"], r["embedding_dims"])
            score = cosine_similarity(q_vec, vec)
            if score >= min_similarity:
                scored.append((score, dict(r)))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)

    out = []
    for score, r in scored[:top_k]:
        meta = None
        if r.get("metadata_json"):
            try:
                meta = json.loads(r["metadata_json"])
            except Exception:
                pass
        out.append({
            "content": r["content_text"],
            "source_type": r["source_type"],
            "source_ref": r["source_ref"] or "",
            "score": round(score, 4),
            "scope": r["scope"],
            "metadata": meta,
            "created_at": r["created_at"],
        })
    return out


async def delete_by_source_async(
    user_id: str, source_type: str, source_ref: str,
) -> int:
    """Version async — PG-compatible."""
    if not user_id:
        return 0
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "DELETE FROM agent3_embeddings "
                    "WHERE auth_user_id = :uid AND source_type = :stype "
                    "AND source_ref = :sref"
                ),
                {"uid": user_id, "stype": source_type, "sref": source_ref},
            )
            await session.commit()
            return result.rowcount or 0
        except Exception:
            await session.rollback()
            return 0


async def get_rag_stats_async(user_id: str) -> dict[str, Any]:
    """Version async — PG-compatible."""
    if not user_id:
        return {"total_chunks": 0}
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM agent3_embeddings WHERE auth_user_id = :uid"),
                {"uid": user_id},
            )
            total = int(result.scalar() or 0)
            result = await session.execute(
                text(
                    "SELECT source_type, COUNT(*) AS n FROM agent3_embeddings "
                    "WHERE auth_user_id = :uid GROUP BY source_type"
                ),
                {"uid": user_id},
            )
            by_type = {r["source_type"]: r["n"] for r in result.mappings().all()}
    except Exception:
        return {"total_chunks": 0}
    return {"total_chunks": total, "by_source_type": by_type}


__all__ = [
    "ensure_rag_tables",
    "chunk_text",
    "embed_texts",
    "cosine_similarity",
    "ingest_text",
    "semantic_search",
    "delete_by_source_async",
    "get_rag_stats",
    "get_rag_stats_async",
]
