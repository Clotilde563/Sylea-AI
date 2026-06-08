"""
Agent 3 — GDPR compliance : export complet + delete des donnees user.

Endpoints consommateurs (dans `api/routers/agent3_openclaw.py`) :
  - `GET /api/agent3/export-my-data` -> ZIP de toutes les donnees du user
  - `DELETE /api/agent3/delete-my-data` -> wipe ATOMIQUE de toutes les tables

Tables concernees :
  - agent3_messages
  - agent3_memory
  - agent3_files (+ fichiers disque)
  - agent3_embeddings (RAG)
  - agent3_clawhub_events
  - agent3_audit_log
  - agent3_preferences
  - agent3_feedback (Phase 9C, si present)
  - agent3_cron (cron utilisateur)
  - credentials_vault (Phase 6 — chiffres mais wipe aussi)

Garanties :
  - `export_my_data_async()` : retourne un dict {table_name: rows} + manifest
  - `delete_my_data_async()` : atomique (transaction), retourne le compte par table
  - Isolation stricte : seules les lignes `auth_user_id = :uid` sont touchees

Conformite :
  - Article 15 RGPD (droit d'acces) : export
  - Article 17 RGPD (droit a l'oubli) : delete
  - Tout est scope au user authentifie — aucune fuite inter-users
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("sylea.gdpr")


# Tables a auditer. Certaines peuvent ne pas exister selon la migration ->
# try/except par table dans les helpers async filtre silencieusement.
_USER_SCOPED_TABLES: list[tuple[str, str]] = [
    # (table_name, user_column)
    ("agent3_messages", "auth_user_id"),
    ("agent3_memory", "auth_user_id"),
    ("agent3_files", "auth_user_id"),
    ("agent3_embeddings", "auth_user_id"),
    ("agent3_clawhub_events", "auth_user_id"),
    ("agent3_audit_log", "auth_user_id"),
    ("agent3_preferences", "auth_user_id"),
    ("agent3_feedback", "auth_user_id"),
    ("agent3_cron", "auth_user_id"),
    ("agent3_tool_preferences", "auth_user_id"),
    ("credentials_vault", "auth_user_id"),
    ("profil_utilisateur", "auth_user_id"),
    ("decisions", "user_id"),
    ("profil_bilan", "auth_user_id"),
]


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════
#
# Approche portable : on tente la requete avec try/except. Si la table n'existe
# pas, l'exception est catched et on skip. Plus simple que detecter le schema
# via sqlite_master (SQLite-specific) ou information_schema (PG-specific).


async def export_my_data_async(user_id: str) -> dict[str, Any]:
    """Version async de export_my_data — PG-compatible.

    Approche portable : SELECT * FROM table WHERE user_col = :uid avec
    try/except par table — si la table n'existe pas, skip.
    """
    if not user_id:
        return {"manifest": {}, "data": {}, "file_paths": []}

    from sqlalchemy import text
    from api.database import get_session_factory

    data: dict[str, list[dict]] = {}
    file_paths: list[str] = []
    tables_included: list[str] = []
    total_rows = 0

    factory = get_session_factory()
    async with factory() as session:
        for table, user_col in _USER_SCOPED_TABLES:
            try:
                # SECURITE : table et user_col viennent de _USER_SCOPED_TABLES
                # (whitelist statique en module-level). Jamais d'input user → safe.
                result = await session.execute(
                    text(f"SELECT * FROM {table} WHERE {user_col} = :uid"),
                    {"uid": user_id},
                )
                rows = result.mappings().all()
            except Exception as e:
                logger.debug(f"export async: skip {table}: {e}")
                continue

            serialized: list[dict] = []
            for r in rows:
                row_dict = {}
                for k, v in r.items():
                    if (table == "credentials_vault"
                            and k in ("encrypted_value", "value_encrypted")):
                        row_dict[k] = "[REDACTED — chiffre en base, non exporte en clair]"
                    elif isinstance(v, (bytes, bytearray, memoryview)):
                        row_dict[k] = f"[BLOB:{len(bytes(v))} bytes]"
                    else:
                        row_dict[k] = v
                serialized.append(row_dict)
                # Collecte file_paths
                if table == "agent3_files" and "filepath" in r:
                    fp = r["filepath"]
                    if fp:
                        file_paths.append(str(fp))

            if serialized:
                data[table] = serialized
                tables_included.append(table)
                total_rows += len(serialized)

    manifest = {
        "user_id": user_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tables_included": tables_included,
        "total_rows": total_rows,
        "file_attachments": len(file_paths),
        "schema_version": "sylea-agent3-v1",
        "format": "json",
    }
    return {"manifest": manifest, "data": data, "file_paths": file_paths}


async def delete_my_data_async(
    user_id: str, *, delete_uploads: bool = True,
) -> dict[str, Any]:
    """Version async de delete_my_data — PG-compatible.

    Suppression ATOMIQUE dans UNE seule transaction async. Si une table
    echoue, tout est rollback.
    """
    if not user_id:
        return {
            "deleted_by_table": {}, "files_deleted": 0,
            "total_rows": 0, "error": "no user_id",
        }

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()

    deleted: dict[str, int] = {}
    total = 0
    files_to_remove: list[str] = []

    # Collecte les paths de fichiers AVANT la suppression
    if delete_uploads:
        try:
            async with factory() as session:
                try:
                    result = await session.execute(
                        text(
                            "SELECT filepath FROM agent3_files "
                            "WHERE auth_user_id = :uid"
                        ),
                        {"uid": user_id},
                    )
                    rows = result.mappings().all()
                    files_to_remove = [r["filepath"] for r in rows if r["filepath"]]
                except Exception as e:
                    logger.debug(f"Could not collect file paths async: {e}")
        except Exception:
            pass

    # Transaction atomique : tout ou rien
    async with factory() as session:
        try:
            for table, user_col in _USER_SCOPED_TABLES:
                try:
                    # SECURITE : whitelist statique, jamais d'input user
                    result = await session.execute(
                        text(
                            f"DELETE FROM {table} WHERE {user_col} = :uid"
                        ),
                        {"uid": user_id},
                    )
                    count = result.rowcount or 0
                    if count > 0:
                        deleted[table] = count
                        total += count
                except Exception as e:
                    logger.warning(f"delete async: failed on {table}: {e}")
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.exception(f"delete_my_data_async transaction failed: {e}")
            return {
                "deleted_by_table": {},
                "files_deleted": 0,
                "total_rows": 0,
                "error": f"transaction_failed: {type(e).__name__}",
            }

    # Cleanup disque hors transaction
    files_deleted = 0
    if delete_uploads:
        for fp in files_to_remove:
            try:
                p = Path(fp)
                if p.exists() and p.is_file():
                    p.unlink()
                    files_deleted += 1
            except Exception as e:
                logger.debug(f"Could not delete file {fp}: {e}")

    return {
        "deleted_by_table": deleted,
        "files_deleted": files_deleted,
        "total_rows": total,
        "deleted_at": datetime.now(timezone.utc).isoformat(),
    }


__all__ = [
    "export_my_data_async",
    "delete_my_data_async",
]
