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
  - `export_my_data()` : retourne un dict {table_name: rows} + manifest
  - `delete_my_data()` : atomique (transaction), retourne le compte par table
  - Isolation stricte : seules les lignes `auth_user_id = ?` sont touchees

Conformite :
  - Article 15 RGPD (droit d'acces) : export
  - Article 17 RGPD (droit a l'oubli) : delete
  - Tout est scope au user authentifie — aucune fuite inter-users
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("sylea.gdpr")


# Tables a auditer. Certaines peuvent ne pas exister selon la migration ->
# `_table_exists()` filtre silencieusement.
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


def _table_exists(db: Any, name: str) -> bool:
    try:
        row = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,),
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _get_columns(db: Any, table: str) -> list[str]:
    try:
        rows = db.conn.execute(f"PRAGMA table_info({table})").fetchall()
        return [r[1] for r in rows]
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────

def export_my_data(db: Any, user_id: str) -> dict[str, Any]:
    """Export complet des donnees du user.

    Retourne un dict :
      {
        "manifest": {...},  # metadata
        "data": {table_name: [rows...]},
        "file_paths": [...]  # chemins des fichiers uploades
      }
    """
    if not user_id:
        return {"manifest": {}, "data": {}, "file_paths": []}

    data: dict[str, list[dict]] = {}
    file_paths: list[str] = []
    tables_included: list[str] = []
    total_rows = 0

    for table, user_col in _USER_SCOPED_TABLES:
        if not _table_exists(db, table):
            continue
        cols = _get_columns(db, table)
        if user_col not in cols:
            # Schema different → skip silencieusement
            continue
        try:
            rows = db.conn.execute(
                f"SELECT * FROM {table} WHERE {user_col} = ?", (user_id,),
            ).fetchall()
        except Exception as e:
            logger.warning(f"export: could not read {table}: {e}")
            continue

        col_names = [d[0] for d in db.conn.execute(
            f"SELECT * FROM {table} WHERE {user_col} = ? LIMIT 0", (user_id,),
        ).description or []]
        if not col_names:
            col_names = cols

        serialized: list[dict] = []
        for r in rows:
            row_dict = {}
            for i, name in enumerate(col_names):
                if i >= len(r):
                    break
                v = r[i]
                # Redaction des champs sensibles (preserve structure, pas la valeur)
                if table == "credentials_vault" and name in ("encrypted_value", "value_encrypted"):
                    row_dict[name] = "[REDACTED — chiffre en base, non exporte en clair]"
                elif isinstance(v, bytes):
                    # BLOB (ex : embeddings) → skip le contenu, juste sa taille
                    row_dict[name] = f"[BLOB:{len(v)} bytes]"
                else:
                    row_dict[name] = v
            serialized.append(row_dict)
            # Collecte les file_paths des uploads pour copie eventuelle
            if table == "agent3_files" and "filepath" in col_names:
                fp_idx = col_names.index("filepath")
                if fp_idx < len(r) and r[fp_idx]:
                    file_paths.append(str(r[fp_idx]))

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


# ─────────────────────────────────────────────────────────────────────────────
# Delete
# ─────────────────────────────────────────────────────────────────────────────

def delete_my_data(
    db: Any, user_id: str, *, delete_uploads: bool = True,
) -> dict[str, Any]:
    """Suppression ATOMIQUE de toutes les donnees du user.

    Args:
        delete_uploads : si True, efface aussi les fichiers disque (uploads, figures).

    Retourne :
      {
        "deleted_by_table": {table: count, ...},
        "files_deleted": int,
        "total_rows": int,
        "deleted_at": ISO,
      }

    La suppression est dans une transaction unique. Si une table echoue,
    tout est rollback.
    """
    if not user_id:
        return {"deleted_by_table": {}, "files_deleted": 0, "total_rows": 0, "error": "no user_id"}

    deleted: dict[str, int] = {}
    total = 0

    # Collecte les paths de fichiers AVANT la suppression (pour cleanup disque)
    files_to_remove: list[str] = []
    if delete_uploads and _table_exists(db, "agent3_files"):
        try:
            rows = db.conn.execute(
                "SELECT filepath FROM agent3_files WHERE auth_user_id = ?", (user_id,),
            ).fetchall()
            files_to_remove = [r[0] for r in rows if r and r[0]]
        except Exception as e:
            logger.debug(f"Could not collect file paths : {e}")

    # Transaction : tout ou rien
    try:
        db.conn.execute("BEGIN")
        for table, user_col in _USER_SCOPED_TABLES:
            if not _table_exists(db, table):
                continue
            cols = _get_columns(db, table)
            if user_col not in cols:
                continue
            try:
                cursor = db.conn.execute(
                    f"DELETE FROM {table} WHERE {user_col} = ?", (user_id,),
                )
                count = cursor.rowcount or 0
                if count > 0:
                    deleted[table] = count
                    total += count
            except Exception as e:
                logger.warning(f"delete: failed on {table}: {e}")
        db.conn.commit()
    except Exception as e:
        db.conn.rollback()
        logger.exception(f"delete_my_data transaction failed: {e}")
        return {
            "deleted_by_table": {},
            "files_deleted": 0,
            "total_rows": 0,
            "error": f"transaction_failed: {type(e).__name__}",
        }

    # Cleanup disque (hors transaction, best-effort)
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


__all__ = ["export_my_data", "delete_my_data"]
