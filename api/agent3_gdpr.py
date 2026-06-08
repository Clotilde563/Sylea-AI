"""
RGPD — export complet + suppression des donnees d'un utilisateur.

Endpoints consommateurs (dans `api/routers/agent3_openclaw.py`) :
  - `GET    /api/agent3/export-my-data`  -> ZIP de toutes les donnees du user
  - `DELETE /api/agent3/delete-my-data`  -> wipe ATOMIQUE de toutes ses donnees

Conformite :
  - Article 15 / 20 RGPD (acces / portabilite) : export complet
  - Article 17 RGPD (droit a l'oubli)          : suppression complete + compte

═══════════════════════════════════════════════════════════════════════════
 DECOUVERTE DYNAMIQUE DES TABLES (2026-06)
═══════════════════════════════════════════════════════════════════════════
Auparavant une whitelist statique listait les tables a purger. Probleme : la
plupart des tables sont creees PARESSEUSEMENT (ensure_*_tables, modules agent3,
quotas, integrations, dilemmes_tracking, ...) ou via Alembic cote PostgreSQL —
elles n'apparaissaient PAS dans la whitelist. Resultat : les donnees les plus
sensibles (journaux sante, chats agents, tokens OAuth, et la ligne `users`
elle-meme) survivaient a une "suppression de compte". Violation Art. 17.

Desormais on INTROSPECTE la base reellement connectee (SQLite dev ou PostgreSQL
prod) et on traite TOUTE table possedant une colonne rattachant une ligne a un
utilisateur. Auto-complet, zero derive, identique dev/prod. Un test verifie
qu'aucune table user-scoped n'echappe a la purge.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("sylea.gdpr")


# Colonnes qui rattachent une ligne a un utilisateur : une ligne "appartient" au
# user (ou le reference) si l'une de ces colonnes vaut son id. On purge toute
# ligne referencant le user pour une erasure complete (aucune trace residuelle).
_OWNER_COLUMNS = (
    "auth_user_id",
    "user_id",
    "owner_user_id",
    "shared_with_user_id",
    "target_user_id",
)

# Tables a NE jamais purger via la decouverte, meme si elles ont une colonne
# user-like (tables globales / techniques). `users` est geree separement (par sa
# colonne `id`, et supprimee en DERNIER pour respecter les FK).
_DISCOVERY_DENYLIST = {
    "users",
    "alembic_version",
    "stripe_processed_events",  # idempotence webhooks (pas de PII user)
}

# Colonnes a NE jamais exporter en clair (secrets / hashes / tokens).
_REDACT_SUBSTRINGS = ("encrypted", "password", "secret", "token", "code_hash", "hashed")


async def _discover_user_tables(session) -> list[tuple[str, list[str]]]:
    """Introspecte la base CONNECTEE et retourne [(table, [colonnes-proprietaire])]
    pour toutes les tables rattachant une ligne a un utilisateur.

    Portable SQLite + PostgreSQL via l'inspecteur SQLAlchemy. Couvre les tables
    creees paresseusement -> aucune derive possible.
    """
    from sqlalchemy import inspect as _sa_inspect

    def _inspect(sync_conn) -> list[tuple[str, list[str]]]:
        insp = _sa_inspect(sync_conn)
        out: list[tuple[str, list[str]]] = []
        for tname in insp.get_table_names():
            if tname in _DISCOVERY_DENYLIST:
                continue
            try:
                cols = [c["name"] for c in insp.get_columns(tname)]
            except Exception:
                continue
            owner_cols = [c for c in _OWNER_COLUMNS if c in cols]
            if owner_cols:
                out.append((tname, owner_cols))
        return out

    # run_sync : l'inspecteur a besoin d'une connexion synchrone (dans la meme
    # transaction que le caller).
    return await session.run_sync(lambda s: _inspect(s.connection()))


def _delete_order_key(item: tuple[str, list[str]]) -> tuple[int, str]:
    """Ordre de suppression FK-safe : enfants d'abord, `profil_utilisateur`
    juste avant `users` (qui est supprimee a part, tout a la fin)."""
    table = item[0]
    return (1 if table == "profil_utilisateur" else 0, table)


async def export_my_data_async(user_id: str) -> dict[str, Any]:
    """Export RGPD complet (Art. 15 / 20). Decouvre dynamiquement toutes les
    tables user-scoped + la ligne `users`. Redacte secrets/tokens/hashes."""
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
        tables = await _discover_user_tables(session)
        # Ajoute la ligne `users` (le compte lui-meme) a l'export.
        targets: list[tuple[str, list[str]]] = tables + [("users", ["id"])]

        for table, owner_cols in targets:
            where = " OR ".join(f"{c} = :uid" for c in owner_cols)
            try:
                result = await session.execute(
                    text(f"SELECT * FROM {table} WHERE {where}"),  # noqa: S608 (table/col = whitelist introspectee, jamais d'input user)
                    {"uid": user_id},
                )
                rows = result.mappings().all()
            except Exception as e:
                logger.debug(f"export: skip {table}: {e}")
                continue

            serialized: list[dict] = []
            for r in rows:
                row_dict: dict[str, Any] = {}
                for k, v in r.items():
                    kl = k.lower()
                    if any(sub in kl for sub in _REDACT_SUBSTRINGS):
                        row_dict[k] = "[REDACTED — secret/hash non exporte en clair]"
                    elif isinstance(v, (bytes, bytearray, memoryview)):
                        row_dict[k] = f"[BLOB:{len(bytes(v))} bytes]"
                    else:
                        row_dict[k] = v
                serialized.append(row_dict)
                if table == "agent3_files" and r.get("filepath"):
                    file_paths.append(str(r["filepath"]))

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
        "schema_version": "sylea-rgpd-v2-dynamic",
        "format": "json",
    }
    return {"manifest": manifest, "data": data, "file_paths": file_paths}


async def delete_my_data_async(
    user_id: str, *, delete_uploads: bool = True,
) -> dict[str, Any]:
    """Suppression RGPD complete (Art. 17), ATOMIQUE (une transaction).

    Decouvre dynamiquement toutes les tables user-scoped, supprime toute ligne
    referencant le user, PUIS la ligne `users` (le compte) en dernier. Si quoi
    que ce soit echoue, tout est rollback (rien de partiel).
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

    async with factory() as session:
        try:
            tables = await _discover_user_tables(session)
            tables.sort(key=_delete_order_key)

            # Collecte les chemins de fichiers AVANT suppression (best-effort).
            if delete_uploads:
                for table, owner_cols in tables:
                    if table != "agent3_files":
                        continue
                    where = " OR ".join(f"{c} = :uid" for c in owner_cols)
                    try:
                        res = await session.execute(
                            text(f"SELECT filepath FROM {table} WHERE {where}"),  # noqa: S608
                            {"uid": user_id},
                        )
                        files_to_remove = [r["filepath"] for r in res.mappings().all() if r["filepath"]]
                    except Exception as e:
                        logger.debug(f"collect filepaths: {e}")

            # Suppression : enfants -> profil_utilisateur (FK-safe via l'ordre).
            for table, owner_cols in tables:
                where = " OR ".join(f"{c} = :uid" for c in owner_cols)
                result = await session.execute(
                    text(f"DELETE FROM {table} WHERE {where}"),  # noqa: S608 (whitelist introspectee)
                    {"uid": user_id},
                )
                count = result.rowcount or 0
                if count > 0:
                    deleted[table] = count
                    total += count

            # Enfin : la ligne `users` (le compte lui-meme), supprimee en dernier
            # pour respecter les FK enfants -> users.
            res_u = await session.execute(
                text("DELETE FROM users WHERE id = :uid"),
                {"uid": user_id},
            )
            uc = res_u.rowcount or 0
            if uc > 0:
                deleted["users"] = uc
                total += uc

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

    # Cleanup disque hors transaction (best-effort).
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
