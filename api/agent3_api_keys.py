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


def create_api_key(
    db: Any, user_id: str, name: str,
    *, scopes: list[str] | None = None,
) -> dict[str, Any]:
    """Cree une nouvelle API key. Retourne le plaintext_token (a afficher UNE FOIS).

    Retour : {ok, key_id, token, prefix, scopes}.
    """
    if not user_id or not name.strip():
        return {"ok": False, "error": "user_id + name requis"}
    ensure_api_keys_table(db)

    raw = secrets.token_urlsafe(_TOKEN_SECRET_LEN)[: _TOKEN_SECRET_LEN]
    token = f"{_TOKEN_PREFIX}{raw}"
    key_hash = _hash_token(token)
    prefix = token[: len(_TOKEN_PREFIX) + 8]

    scopes = [s for s in (scopes or ["chat:read", "chat:write"]) if s in VALID_SCOPES]
    if not scopes:
        scopes = ["chat:read"]

    key_id = str(uuid.uuid4())
    try:
        db.conn.execute(
            "INSERT INTO api_keys "
            "(id, user_id, name, key_hash, key_prefix, scopes_json, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (key_id, user_id, name.strip()[:100], key_hash, prefix,
             json.dumps(scopes), _now()),
        )
        db.conn.commit()
    except Exception as e:
        logger.warning(f"create_api_key failed: {e}")
        return {"ok": False, "error": str(e)}

    return {
        "ok": True,
        "key_id": key_id,
        "token": token,  # SHOWN ONCE
        "prefix": prefix,
        "scopes": scopes,
        "warning": "Copie ce token maintenant. Il ne sera plus jamais affiche.",
    }


def validate_api_key(db: Any, token: str) -> dict[str, Any] | None:
    """Verifie un token entrant. Retourne {user_id, scopes, key_id} ou None."""
    if not token or not token.startswith(_TOKEN_PREFIX):
        return None
    ensure_api_keys_table(db)

    key_hash = _hash_token(token)
    try:
        row = db.conn.execute(
            "SELECT id, user_id, scopes_json, revoked_at "
            "FROM api_keys WHERE key_hash = ?",
            (key_hash,),
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    if row[3]:  # revoked
        return None

    # Update last_used_at (async, best-effort)
    try:
        db.conn.execute(
            "UPDATE api_keys SET last_used_at = ? WHERE id = ?",
            (_now(), row[0]),
        )
        db.conn.commit()
    except Exception:
        pass

    scopes: list[str] = []
    if row[2]:
        try:
            scopes = json.loads(row[2]) or []
        except Exception:
            pass

    return {"key_id": row[0], "user_id": row[1], "scopes": scopes}


def list_api_keys(db: Any, user_id: str) -> list[dict[str, Any]]:
    """Liste des API keys du user (sans le token plaintext — juste prefix)."""
    ensure_api_keys_table(db)
    try:
        rows = db.conn.execute(
            "SELECT id, name, key_prefix, scopes_json, last_used_at, created_at, revoked_at "
            "FROM api_keys WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        scopes = []
        if r[3]:
            try:
                scopes = json.loads(r[3])
            except Exception:
                pass
        out.append({
            "id": r[0],
            "name": r[1],
            "prefix": r[2],
            "scopes": scopes,
            "last_used_at": r[4],
            "created_at": r[5],
            "revoked": bool(r[6]),
            "revoked_at": r[6],
        })
    return out


def revoke_api_key(db: Any, key_id: str, user_id: str) -> dict[str, Any]:
    """Revoque une key. User doit etre owner."""
    ensure_api_keys_table(db)
    try:
        row = db.conn.execute(
            "SELECT user_id FROM api_keys WHERE id = ?", (key_id,),
        ).fetchone()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if not row:
        return {"ok": False, "error": "not found"}
    if row[0] != user_id:
        return {"ok": False, "error": "forbidden"}
    try:
        db.conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ?", (_now(), key_id),
        )
        db.conn.commit()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


__all__ = [
    "VALID_SCOPES",
    "ensure_api_keys_table",
    "create_api_key",
    "validate_api_key",
    "list_api_keys",
    "revoke_api_key",
]
