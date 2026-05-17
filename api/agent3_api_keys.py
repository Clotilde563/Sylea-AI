"""
Agent 3 — API keys utilisateur pour l'API publique B2B.

Permet a un user de generer une/plusieurs API keys pour appeler `/api/v1/...`
hors contexte browser (scripts, serveurs tiers).

Modele :
  api_keys :
    id TEXT PK
    user_id TEXT (fk users)
    name TEXT (label user-friendly)
    key_hash TEXT (sha256 du token — stockage securise)
    key_prefix TEXT (8 premiers chars, pour identification UI sans exposer le reste)
    scopes_json TEXT ([\"chat:read\", \"chat:write\"])
    last_used_at TEXT
    created_at TEXT
    revoked_at TEXT

Format token : `sk-sylea-<32 random chars>`.

Flow :
  1. `create_api_key(user_id, name, scopes)` -> (key_id, plaintext_token)
  2. User stocke plaintext_token (shown ONCE)
  3. Requete entrante : header `Authorization: Bearer sk-sylea-...`
     -> `validate_api_key(token)` retourne user_id + scopes
  4. `revoke_api_key(key_id, user_id)` desactive

Securite :
  - Token plaintext jamais stocke en DB (hash sha256 only)
  - Prefix visible en UI pour identification
  - Scopes restrictifs (chat:read, chat:write, admin)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("sylea.api_keys")


_API_KEYS_DDL = """
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    scopes_json TEXT,
    last_used_at TEXT,
    created_at TEXT NOT NULL,
    revoked_at TEXT
)
"""

_TOKEN_PREFIX = "sk-sylea-"
_TOKEN_SECRET_LEN = 32


def ensure_api_keys_table(db: Any) -> None:
    try:
        db.conn.execute(_API_KEYS_DDL)
        db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id)"
        )
        db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)"
        )
        db.conn.commit()
    except Exception as e:
        logger.debug(f"ensure_api_keys_table failed: {e}")


def _hash_token(token: str) -> str:
    """SHA-256 hash — deterministic pour lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────

VALID_SCOPES = {"chat:read", "chat:write", "memory:read", "memory:write", "admin"}


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

async def create_api_key_async(
    user_id: str, name: str,
    *, scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Version async — PG-compatible."""
    if not user_id or not name.strip():
        return {"ok": False, "error": "user_id + name requis"}

    from sqlalchemy import text
    from api.database import get_session_factory

    raw = secrets.token_urlsafe(_TOKEN_SECRET_LEN)[: _TOKEN_SECRET_LEN]
    token = f"{_TOKEN_PREFIX}{raw}"
    key_hash = _hash_token(token)
    prefix = token[: len(_TOKEN_PREFIX) + 8]

    scopes = [s for s in (scopes or ["chat:read", "chat:write"]) if s in VALID_SCOPES]
    if not scopes:
        scopes = ["chat:read"]

    key_id = str(uuid.uuid4())
    factory = get_session_factory()
    try:
        async with factory() as session:
            try:
                await session.execute(
                    text(
                        "INSERT INTO api_keys "
                        "(id, user_id, name, key_hash, key_prefix, scopes_json, created_at) "
                        "VALUES (:id, :uid, :name, :hash, :prefix, :scopes, :now)"
                    ),
                    {
                        "id": key_id, "uid": user_id,
                        "name": name.strip()[:100], "hash": key_hash,
                        "prefix": prefix, "scopes": json.dumps(scopes),
                        "now": _now(),
                    },
                )
                await session.commit()
            except Exception as e:
                await session.rollback()
                logger.warning(f"create_api_key_async failed: {e}")
                return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "key_id": key_id,
        "token": token,
        "prefix": prefix,
        "scopes": scopes,
        "warning": "Copie ce token maintenant. Il ne sera plus jamais affiche.",
    }


async def validate_api_key_async(token: str) -> dict[str, Any] | None:
    """Version async — PG-compatible."""
    if not token or not token.startswith(_TOKEN_PREFIX):
        return None
    from sqlalchemy import text
    from api.database import get_session_factory

    key_hash = _hash_token(token)
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT id, user_id, scopes_json, revoked_at "
                    "FROM api_keys WHERE key_hash = :hash"
                ),
                {"hash": key_hash},
            )
            row = result.first()
    except Exception:
        return None
    if not row:
        return None
    if row[3]:  # revoked
        return None

    # Update last_used_at best-effort
    try:
        async with factory() as session:
            try:
                await session.execute(
                    text("UPDATE api_keys SET last_used_at = :now WHERE id = :id"),
                    {"now": _now(), "id": row[0]},
                )
                await session.commit()
            except Exception:
                await session.rollback()
    except Exception:
        pass

    scopes: list[str] = []
    if row[2]:
        try:
            scopes = json.loads(row[2]) or []
        except Exception:
            pass

    return {"key_id": row[0], "user_id": row[1], "scopes": scopes}


async def list_api_keys_async(user_id: str) -> list[dict[str, Any]]:
    """Version async — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT id, name, key_prefix, scopes_json, last_used_at, "
                    "created_at, revoked_at FROM api_keys "
                    "WHERE user_id = :uid ORDER BY created_at DESC"
                ),
                {"uid": user_id},
            )
            rows = result.mappings().all()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        scopes = []
        if r["scopes_json"]:
            try:
                scopes = json.loads(r["scopes_json"])
            except Exception:
                pass
        out.append({
            "id": r["id"], "name": r["name"], "prefix": r["key_prefix"],
            "scopes": scopes, "last_used_at": r["last_used_at"],
            "created_at": r["created_at"], "revoked": bool(r["revoked_at"]),
            "revoked_at": r["revoked_at"],
        })
    return out


async def revoke_api_key_async(key_id: str, user_id: str) -> dict[str, Any]:
    """Version async — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    try:
        async with factory() as session:
            result = await session.execute(
                text("SELECT user_id FROM api_keys WHERE id = :id"),
                {"id": key_id},
            )
            row = result.first()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not row:
        return {"ok": False, "error": "not found"}
    if row[0] != user_id:
        return {"ok": False, "error": "forbidden"}

    try:
        async with factory() as session:
            try:
                await session.execute(
                    text("UPDATE api_keys SET revoked_at = :now WHERE id = :id"),
                    {"now": _now(), "id": key_id},
                )
                await session.commit()
            except Exception as e:
                await session.rollback()
                return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


__all__ = [
    "VALID_SCOPES",
    "ensure_api_keys_table",
    "create_api_key_async",
    "validate_api_key_async",
    "list_api_keys_async",
    "revoke_api_key_async",
]
