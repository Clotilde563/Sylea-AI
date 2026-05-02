"""
Credential Vault — stockage chiffre des cles API tierces de l'utilisateur.

Architecture :
  - Table `user_credentials` : {user_id, provider_slug, field_key, encrypted_value, ...}
  - Chiffrement symetrique Fernet (AES-128-CBC + HMAC-SHA256) via cryptography.
  - Master key depuis env var `SYLEA_CREDENTIALS_MASTER_KEY`.
  - Aucun log de valeurs, meme tronquees. Lecture uniquement a l'injection runtime.
  - Table `credential_access_log` : audit trail qui a lu quelle cle quand.

API publique :
  - `save_credential(db, user_id, provider, field, value, metadata=None)`
  - `get_credential(db, user_id, provider, field) -> str | None`
  - `list_credentials(db, user_id) -> list[dict]`   # valeurs MASQUEES
  - `delete_credential(db, user_id, provider, field)`
  - `mask_credential_value(value) -> str`           # 'sk_***...xy78'

Complementaire a `api/routers/integrations.py` qui gere les OAuth Google/GitHub.
Ce module est pour les API keys generiques (Stripe, OpenAI, Notion, Slack, etc.).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("sylea.credentials")


# ─────────────────────────────────────────────────────────────────────────────
# Master key + Fernet
# ─────────────────────────────────────────────────────────────────────────────

def _get_master_fernet() -> Fernet:
    """Instancie un Fernet a partir du master secret serveur.

    Le master key peut etre :
      - Une Fernet key valide (32 bytes url-safe base64) dans SYLEA_CREDENTIALS_MASTER_KEY
      - OU un passphrase arbitraire : on la derive en Fernet key via SHA-256 + base64.

    Si absent, derive depuis SECRET_KEY (fallback — a PAS utiliser en prod).
    """
    raw = os.environ.get("SYLEA_CREDENTIALS_MASTER_KEY", "").strip()
    if not raw:
        # Fallback dev : derive depuis SECRET_KEY (utilise par auth).
        fallback = os.environ.get("SECRET_KEY", "sylea-dev-not-for-prod")
        logger.warning(
            "SYLEA_CREDENTIALS_MASTER_KEY absent, fallback derive depuis SECRET_KEY. "
            "A NE PAS utiliser en production."
        )
        raw = fallback

    # Essayer d'abord comme Fernet key directe (44 chars base64)
    try:
        import base64
        key_bytes = raw.encode("utf-8")
        # Fernet key = 32 bytes url-safe base64 = 44 chars incluant '=' padding
        if len(key_bytes) == 44 and key_bytes.endswith(b"="):
            return Fernet(key_bytes)
    except Exception:
        pass

    # Derivation : SHA-256 de la passphrase, encode url-safe base64
    import base64
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    derived_key = base64.urlsafe_b64encode(digest)
    return Fernet(derived_key)


# Singleton (cree a la premiere utilisation).
_fernet_instance: Fernet | None = None


def _fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        _fernet_instance = _get_master_fernet()
    return _fernet_instance


# ─────────────────────────────────────────────────────────────────────────────
# Schema DB
# ─────────────────────────────────────────────────────────────────────────────

_CREDENTIALS_DDL = """
CREATE TABLE IF NOT EXISTS user_credentials (
    id TEXT PRIMARY KEY,
    auth_user_id TEXT NOT NULL,
    provider_slug TEXT NOT NULL,
    field_key TEXT NOT NULL,
    encrypted_value BLOB NOT NULL,
    metadata_json TEXT,
    preview TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT,
    last_tested_at TEXT,
    last_test_ok INTEGER,
    expires_at TEXT,
    UNIQUE(auth_user_id, provider_slug, field_key)
)
"""

_CREDENTIALS_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_credentials_user "
    "ON user_credentials(auth_user_id, provider_slug)"
)

_ACCESS_LOG_DDL = """
CREATE TABLE IF NOT EXISTS credential_access_log (
    id TEXT PRIMARY KEY,
    auth_user_id TEXT NOT NULL,
    provider_slug TEXT NOT NULL,
    field_key TEXT NOT NULL,
    action TEXT NOT NULL,
    context TEXT,
    created_at TEXT NOT NULL
)
"""

_ACCESS_LOG_INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_cred_access_user_time "
    "ON credential_access_log(auth_user_id, created_at DESC)"
)


def ensure_credentials_tables(db: Any) -> None:
    """Cree les tables credentials + access log si absentes (safe to call)."""
    try:
        db.conn.execute(_CREDENTIALS_DDL)
        db.conn.execute(_CREDENTIALS_INDEX_DDL)
        db.conn.execute(_ACCESS_LOG_DDL)
        db.conn.execute(_ACCESS_LOG_INDEX_DDL)
        db.conn.commit()
    except Exception as e:
        logger.warning(f"ensure_credentials_tables failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Masquage (pour UI, jamais la valeur en clair)
# ─────────────────────────────────────────────────────────────────────────────

def mask_credential_value(value: str) -> str:
    """Retourne un apercu masque, ex: 'sk_live_***...xY78' (8 premiers, 4 derniers)."""
    if not value:
        return ""
    n = len(value)
    if n <= 12:
        return "***" + value[-2:]
    # Prefixe visible (utile pour identifier Stripe live vs test par ex.)
    prefix = value[:8]
    suffix = value[-4:]
    return f"{prefix}…{suffix}"


# ─────────────────────────────────────────────────────────────────────────────
# Audit log
# ─────────────────────────────────────────────────────────────────────────────

def _log_access(
    db: Any, user_id: str, provider: str, field: str, action: str, context: str = "",
) -> None:
    try:
        db.conn.execute(
            "INSERT INTO credential_access_log "
            "(id, auth_user_id, provider_slug, field_key, action, context, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                user_id or "",
                provider,
                field,
                action,
                (context or "")[:500],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        db.conn.commit()
    except Exception as e:
        logger.debug(f"credential access log failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# API publique
# ─────────────────────────────────────────────────────────────────────────────

def save_credential(
    db: Any,
    user_id: str,
    provider_slug: str,
    field_key: str,
    value: str,
    *,
    metadata: dict | None = None,
    expires_at: str | None = None,
    test_ok: bool | None = None,
) -> str:
    """Chiffre et stocke (ou met a jour) une credential. Retourne l'id."""
    if not user_id:
        raise ValueError("user_id required")
    if not provider_slug or not field_key:
        raise ValueError("provider_slug and field_key required")
    if not isinstance(value, str) or not value:
        raise ValueError("value must be a non-empty string")

    ensure_credentials_tables(db)
    now = datetime.now(timezone.utc).isoformat()
    preview = mask_credential_value(value)
    encrypted = _fernet().encrypt(value.encode("utf-8"))
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None

    # UPSERT manuel (SQLite ne supporte pas nativement INSERT OR UPDATE avec tous les champs)
    existing = db.conn.execute(
        "SELECT id FROM user_credentials "
        "WHERE auth_user_id = ? AND provider_slug = ? AND field_key = ?",
        (user_id, provider_slug, field_key),
    ).fetchone()

    if existing:
        cid = existing[0]
        db.conn.execute(
            "UPDATE user_credentials SET "
            "encrypted_value = ?, metadata_json = ?, preview = ?, "
            "updated_at = ?, expires_at = ?, "
            "last_tested_at = ?, last_test_ok = ? "
            "WHERE id = ?",
            (
                encrypted, meta_json, preview, now, expires_at,
                now if test_ok is not None else None,
                1 if test_ok else (0 if test_ok is False else None),
                cid,
            ),
        )
        _log_access(db, user_id, provider_slug, field_key, "update")
    else:
        cid = str(uuid.uuid4())
        db.conn.execute(
            "INSERT INTO user_credentials "
            "(id, auth_user_id, provider_slug, field_key, encrypted_value, "
            " metadata_json, preview, created_at, updated_at, "
            " last_tested_at, last_test_ok, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cid, user_id, provider_slug, field_key, encrypted,
                meta_json, preview, now, now,
                now if test_ok is not None else None,
                1 if test_ok else (0 if test_ok is False else None),
                expires_at,
            ),
        )
        _log_access(db, user_id, provider_slug, field_key, "create")

    db.conn.commit()
    return cid


def get_credential(
    db: Any, user_id: str, provider_slug: str, field_key: str,
    *, context: str = "",
) -> str | None:
    """Dechiffre et retourne la valeur (ou None si absente). Incrementes last_used_at."""
    if not user_id:
        return None
    ensure_credentials_tables(db)
    row = db.conn.execute(
        "SELECT id, encrypted_value FROM user_credentials "
        "WHERE auth_user_id = ? AND provider_slug = ? AND field_key = ?",
        (user_id, provider_slug, field_key),
    ).fetchone()
    if not row:
        return None
    cid, encrypted = row[0], row[1]
    try:
        value = _fernet().decrypt(encrypted).decode("utf-8")
    except InvalidToken:
        logger.error(f"Invalid Fernet token for credential {cid} (master key rotated?)")
        return None

    # Update last_used_at
    now = datetime.now(timezone.utc).isoformat()
    try:
        db.conn.execute(
            "UPDATE user_credentials SET last_used_at = ? WHERE id = ?",
            (now, cid),
        )
        db.conn.commit()
    except Exception:
        pass

    _log_access(db, user_id, provider_slug, field_key, "read", context=context)
    return value


def list_credentials(db: Any, user_id: str) -> list[dict]:
    """Liste des credentials du user avec valeurs MASQUEES (jamais les vraies valeurs)."""
    if not user_id:
        return []
    ensure_credentials_tables(db)
    rows = db.conn.execute(
        "SELECT provider_slug, field_key, preview, metadata_json, "
        "created_at, updated_at, last_used_at, last_tested_at, last_test_ok, expires_at "
        "FROM user_credentials WHERE auth_user_id = ? "
        "ORDER BY provider_slug, field_key",
        (user_id,),
    ).fetchall()
    out = []
    for r in rows:
        meta = None
        if r[3]:
            try:
                meta = json.loads(r[3])
            except Exception:
                meta = None
        out.append({
            "provider_slug": r[0],
            "field_key": r[1],
            "preview": r[2] or "",
            "metadata": meta,
            "created_at": r[4],
            "updated_at": r[5],
            "last_used_at": r[6],
            "last_tested_at": r[7],
            "last_test_ok": bool(r[8]) if r[8] is not None else None,
            "expires_at": r[9],
        })
    return out


def delete_credential(
    db: Any, user_id: str, provider_slug: str, field_key: str,
) -> bool:
    """Supprime une credential. Retourne True si quelque chose a ete supprime."""
    if not user_id:
        return False
    ensure_credentials_tables(db)
    cursor = db.conn.execute(
        "DELETE FROM user_credentials "
        "WHERE auth_user_id = ? AND provider_slug = ? AND field_key = ?",
        (user_id, provider_slug, field_key),
    )
    db.conn.commit()
    if cursor.rowcount > 0:
        _log_access(db, user_id, provider_slug, field_key, "delete")
        return True
    return False


def delete_all_credentials(db: Any, user_id: str) -> int:
    """Purge toutes les credentials d'un user (RGPD right-to-forget). Retourne le nombre supprime."""
    if not user_id:
        return 0
    ensure_credentials_tables(db)
    cursor = db.conn.execute(
        "DELETE FROM user_credentials WHERE auth_user_id = ?",
        (user_id,),
    )
    db.conn.commit()
    return cursor.rowcount or 0


def has_credential(db: Any, user_id: str, provider_slug: str, field_key: str) -> bool:
    """Check rapide sans dechiffrer."""
    if not user_id:
        return False
    ensure_credentials_tables(db)
    row = db.conn.execute(
        "SELECT 1 FROM user_credentials "
        "WHERE auth_user_id = ? AND provider_slug = ? AND field_key = ? LIMIT 1",
        (user_id, provider_slug, field_key),
    ).fetchone()
    return row is not None


def get_provider_credentials_bundle(
    db: Any, user_id: str, provider_slug: str,
) -> dict[str, str]:
    """Retourne toutes les credentials d'un provider (dict field_key -> value)."""
    if not user_id:
        return {}
    ensure_credentials_tables(db)
    rows = db.conn.execute(
        "SELECT field_key, encrypted_value FROM user_credentials "
        "WHERE auth_user_id = ? AND provider_slug = ?",
        (user_id, provider_slug),
    ).fetchall()
    out: dict[str, str] = {}
    for r in rows:
        try:
            out[r[0]] = _fernet().decrypt(r[1]).decode("utf-8")
        except InvalidToken:
            logger.error(f"Invalid Fernet for {user_id}/{provider_slug}/{r[0]}")
    if out:
        _log_access(db, user_id, provider_slug, "*", "bundle_read")
    return out


__all__ = [
    "ensure_credentials_tables",
    "mask_credential_value",
    "save_credential",
    "get_credential",
    "list_credentials",
    "delete_credential",
    "delete_all_credentials",
    "has_credential",
    "get_provider_credentials_bundle",
]
