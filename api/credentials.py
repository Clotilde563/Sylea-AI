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

# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════
#
# Toutes les fonctions ont une signature compatible : `db` reste accepte
# pour compat de signature mais n'est plus utilise — on passe par
# get_session_factory(). Le param `db` peut etre supprime apres migration.

async def _log_access_async(
    user_id: str, provider: str, field: str, action: str, context: str = "",
) -> None:
    """Version async de _log_access — best-effort."""
    from sqlalchemy import text
    from api.database import get_session_factory
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text(
                    "INSERT INTO credential_access_log "
                    "(id, auth_user_id, provider_slug, field_key, action, context, created_at) "
                    "VALUES (:id, :uid, :prov, :field, :act, :ctx, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "uid": user_id or "",
                    "prov": provider, "field": field, "act": action,
                    "ctx": (context or "")[:500],
                    "now": datetime.now(timezone.utc).isoformat(),
                },
            )
            await session.commit()
    except Exception as e:
        logger.debug(f"credential access log async failed: {e}")


async def save_credential_async(
    user_id: str,
    provider_slug: str,
    field_key: str,
    value: str,
    *,
    metadata: dict | None = None,
    expires_at: str | None = None,
    test_ok: bool | None = None,
) -> str:
    """Version async — PG-compatible. Upsert portable."""
    if not user_id:
        raise ValueError("user_id required")
    if not provider_slug or not field_key:
        raise ValueError("provider_slug and field_key required")
    if not isinstance(value, str) or not value:
        raise ValueError("value must be a non-empty string")

    from sqlalchemy import text
    from api.database import get_session_factory
    now = datetime.now(timezone.utc).isoformat()
    preview = mask_credential_value(value)
    encrypted = _fernet().encrypt(value.encode("utf-8"))
    meta_json = json.dumps(metadata, ensure_ascii=False) if metadata else None
    test_ok_int = 1 if test_ok else (0 if test_ok is False else None)
    test_at = now if test_ok is not None else None

    factory = get_session_factory()
    cid: str
    action = "create"
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT id FROM user_credentials "
                    "WHERE auth_user_id = :uid AND provider_slug = :prov "
                    "AND field_key = :field"
                ),
                {"uid": user_id, "prov": provider_slug, "field": field_key},
            )
            existing = result.first()
            if existing:
                cid = existing[0]
                action = "update"
                await session.execute(
                    text(
                        "UPDATE user_credentials SET "
                        "encrypted_value = :enc, metadata_json = :meta, "
                        "preview = :preview, updated_at = :now, "
                        "expires_at = :exp, last_tested_at = :test_at, "
                        "last_test_ok = :test_ok WHERE id = :cid"
                    ),
                    {
                        "enc": encrypted, "meta": meta_json,
                        "preview": preview, "now": now,
                        "exp": expires_at, "test_at": test_at,
                        "test_ok": test_ok_int, "cid": cid,
                    },
                )
            else:
                cid = str(uuid.uuid4())
                await session.execute(
                    text(
                        "INSERT INTO user_credentials "
                        "(id, auth_user_id, provider_slug, field_key, encrypted_value, "
                        "metadata_json, preview, created_at, updated_at, "
                        "last_tested_at, last_test_ok, expires_at) "
                        "VALUES (:id, :uid, :prov, :field, :enc, :meta, :preview, "
                        ":now, :now, :test_at, :test_ok, :exp)"
                    ),
                    {
                        "id": cid, "uid": user_id, "prov": provider_slug,
                        "field": field_key, "enc": encrypted,
                        "meta": meta_json, "preview": preview, "now": now,
                        "test_at": test_at, "test_ok": test_ok_int,
                        "exp": expires_at,
                    },
                )
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    await _log_access_async(user_id, provider_slug, field_key, action)
    return cid


async def get_credential_async(
    user_id: str, provider_slug: str, field_key: str,
    *, context: str = "",
) -> str | None:
    """Version async — PG-compatible."""
    if not user_id:
        return None
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT id, encrypted_value FROM user_credentials "
                "WHERE auth_user_id = :uid AND provider_slug = :prov "
                "AND field_key = :field"
            ),
            {"uid": user_id, "prov": provider_slug, "field": field_key},
        )
        row = result.first()
    if not row:
        return None
    cid, encrypted = row[0], row[1]
    try:
        # Si encrypted vient de PG (memoryview/bytes), .decrypt l'accepte
        value = _fernet().decrypt(bytes(encrypted)).decode("utf-8")
    except InvalidToken:
        logger.error(f"Invalid Fernet token for credential {cid}")
        return None

    now = datetime.now(timezone.utc).isoformat()
    try:
        async with factory() as session:
            try:
                await session.execute(
                    text("UPDATE user_credentials SET last_used_at = :now WHERE id = :cid"),
                    {"now": now, "cid": cid},
                )
                await session.commit()
            except Exception:
                await session.rollback()
    except Exception:
        pass

    await _log_access_async(user_id, provider_slug, field_key, "read", context=context)
    return value


async def list_credentials_async(user_id: str) -> list[dict]:
    """Version async — PG-compatible. Valeurs MASQUEES."""
    if not user_id:
        return []
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT provider_slug, field_key, preview, metadata_json, "
                "created_at, updated_at, last_used_at, last_tested_at, "
                "last_test_ok, expires_at FROM user_credentials "
                "WHERE auth_user_id = :uid "
                "ORDER BY provider_slug, field_key"
            ),
            {"uid": user_id},
        )
        rows = result.mappings().all()
    out = []
    for r in rows:
        meta = None
        if r["metadata_json"]:
            try:
                meta = json.loads(r["metadata_json"])
            except Exception:
                meta = None
        out.append({
            "provider_slug": r["provider_slug"],
            "field_key": r["field_key"],
            "preview": r["preview"] or "",
            "metadata": meta,
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "last_used_at": r["last_used_at"],
            "last_tested_at": r["last_tested_at"],
            "last_test_ok": (
                bool(r["last_test_ok"]) if r["last_test_ok"] is not None else None
            ),
            "expires_at": r["expires_at"],
        })
    return out


async def delete_credential_async(
    user_id: str, provider_slug: str, field_key: str,
) -> bool:
    """Version async — PG-compatible."""
    if not user_id:
        return False
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "DELETE FROM user_credentials "
                    "WHERE auth_user_id = :uid AND provider_slug = :prov "
                    "AND field_key = :field"
                ),
                {"uid": user_id, "prov": provider_slug, "field": field_key},
            )
            deleted = (result.rowcount or 0) > 0
            await session.commit()
        except Exception:
            await session.rollback()
            return False
    if deleted:
        await _log_access_async(user_id, provider_slug, field_key, "delete")
    return deleted


async def delete_all_credentials_async(user_id: str) -> int:
    """Version async — PG-compatible (RGPD right-to-forget)."""
    if not user_id:
        return 0
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text("DELETE FROM user_credentials WHERE auth_user_id = :uid"),
                {"uid": user_id},
            )
            await session.commit()
            return result.rowcount or 0
        except Exception:
            await session.rollback()
            return 0


async def has_credential_async(
    user_id: str, provider_slug: str, field_key: str,
) -> bool:
    """Version async — PG-compatible."""
    if not user_id:
        return False
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT 1 FROM user_credentials "
                "WHERE auth_user_id = :uid AND provider_slug = :prov "
                "AND field_key = :field LIMIT 1"
            ),
            {"uid": user_id, "prov": provider_slug, "field": field_key},
        )
        return result.first() is not None


async def get_provider_credentials_bundle_async(
    user_id: str, provider_slug: str,
) -> dict[str, str]:
    """Version async — PG-compatible."""
    if not user_id:
        return {}
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT field_key, encrypted_value FROM user_credentials "
                "WHERE auth_user_id = :uid AND provider_slug = :prov"
            ),
            {"uid": user_id, "prov": provider_slug},
        )
        rows = result.mappings().all()
    out: dict[str, str] = {}
    for r in rows:
        try:
            out[r["field_key"]] = _fernet().decrypt(
                bytes(r["encrypted_value"])
            ).decode("utf-8")
        except InvalidToken:
            logger.error(f"Invalid Fernet for {user_id}/{provider_slug}/{r['field_key']}")
    if out:
        await _log_access_async(user_id, provider_slug, "*", "bundle_read")
    return out


__all__ = [
    "ensure_credentials_tables",
    "mask_credential_value",
    "save_credential_async",
    "get_credential_async",
    "list_credentials_async",
    "delete_credential_async",
    "delete_all_credentials_async",
    "has_credential_async",
    "get_provider_credentials_bundle_async",
]
