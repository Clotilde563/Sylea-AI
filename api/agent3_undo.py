"""
Agent 3 — Reversible Undo / Snapshot-Rollback.

Systeme de snapshots qui permet d'annuler les actions de l'agent.
Chaque action reversible cree un snapshot AVANT execution.
L'utilisateur peut demander "annule" ou "undo" pour revenir en arriere.

Inspire du undo system de Claude Code (fichier + state rollback).

Types de snapshots :
  - memory  : sauvegarde/suppression de memoire
  - file    : creation/modification de fichier
  - message : message envoye
  - cron    : tache planifiee creee
  - task    : tache multi-etapes creee
  - setting : changement de preference

Usage :
    undo = UndoManager(user_id, db)
    sid = undo.snapshot("memory", key="budget_mensuel", before_value="5000",
                        after_value="6000", rollback_fn=lambda: ...)
    # Plus tard :
    success = await undo.rollback(sid)
    # Ou : rollback du dernier :
    success = await undo.undo_last()
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("sylea.agent3.undo")


@dataclass
class Snapshot:
    """Capture d'etat avant une action reversible."""

    id: str
    user_id: str
    action_type: str                     # memory, file, message, cron, task, setting
    description: str                     # Description humaine de l'action
    before_state: dict                   # Etat avant l'action
    after_state: dict                    # Etat apres l'action
    rollback_info: dict = field(default_factory=dict)  # Infos necessaires au rollback
    created_at: float = field(default_factory=time.time)
    rolled_back: bool = False
    rolled_back_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "description": self.description,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "created_at": self.created_at,
            "rolled_back": self.rolled_back,
            "age_seconds": int(time.time() - self.created_at),
        }


class UndoManager:
    """Gestionnaire d'undo avec snapshots en memoire + rollback DB."""

    MAX_SNAPSHOTS_PER_USER = 50
    MAX_UNDO_AGE_SECONDS = 3600  # 1 heure max pour un undo

    def __init__(self, user_id: str, db=None):
        self.user_id = user_id
        self.db = db
        self._snapshots: list[Snapshot] = []

    def snapshot(
        self,
        action_type: str,
        description: str = "",
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
        rollback_info: Optional[dict] = None,
    ) -> str:
        """Cree un snapshot et retourne son ID."""
        sid = f"snap_{uuid.uuid4().hex[:10]}"
        snap = Snapshot(
            id=sid,
            user_id=self.user_id,
            action_type=action_type,
            description=description or f"Action {action_type}",
            before_state=before_state or {},
            after_state=after_state or {},
            rollback_info=rollback_info or {},
        )
        self._snapshots.append(snap)

        # Limiter la taille
        while len(self._snapshots) > self.MAX_SNAPSHOTS_PER_USER:
            self._snapshots.pop(0)

        logger.debug(f"Snapshot created: {sid} ({action_type}: {description})")
        return sid

    # ── Convenience snapshots pour les types courants ──

    def snapshot_memory(
        self,
        key: str,
        before_value: str = "",
        after_value: str = "",
        category: str = "general",
    ) -> str:
        return self.snapshot(
            action_type="memory",
            description=f"Memoire '{key}' : '{before_value[:50]}' -> '{after_value[:50]}'",
            before_state={"key": key, "value": before_value, "category": category},
            after_state={"key": key, "value": after_value, "category": category},
            rollback_info={"table": "agent3_memory", "key": key, "restore_value": before_value},
        )

    def snapshot_file(self, filename: str, was_new: bool = True) -> str:
        return self.snapshot(
            action_type="file",
            description=f"Fichier {'cree' if was_new else 'modifie'} : {filename}",
            before_state={"existed": not was_new},
            after_state={"filename": filename},
            rollback_info={"filename": filename, "was_new": was_new},
        )

    def snapshot_cron(self, cron_id: str, label: str) -> str:
        return self.snapshot(
            action_type="cron",
            description=f"Tache planifiee creee : {label}",
            before_state={},
            after_state={"cron_id": cron_id, "label": label},
            rollback_info={"cron_id": cron_id},
        )

    def snapshot_task(self, task_id: str, title: str) -> str:
        return self.snapshot(
            action_type="task",
            description=f"Tache creee : {title}",
            before_state={},
            after_state={"task_id": task_id, "title": title},
            rollback_info={"task_id": task_id},
        )

    def snapshot_setting(self, key: str, old_value: Any, new_value: Any) -> str:
        return self.snapshot(
            action_type="setting",
            description=f"Preference '{key}' : {old_value} -> {new_value}",
            before_state={"key": key, "value": old_value},
            after_state={"key": key, "value": new_value},
            rollback_info={"key": key, "restore_value": old_value},
        )

    # ── Rollback ──

    async def rollback(self, snapshot_id: str) -> tuple[bool, str]:
        """Annule un snapshot specifique. Retourne (success, message)."""
        snap = next((s for s in self._snapshots if s.id == snapshot_id), None)
        if not snap:
            return False, f"Snapshot {snapshot_id} introuvable"
        if snap.rolled_back:
            return False, f"Snapshot {snapshot_id} deja annule"
        if time.time() - snap.created_at > self.MAX_UNDO_AGE_SECONDS:
            return False, f"Snapshot trop ancien ({int(time.time() - snap.created_at)}s > {self.MAX_UNDO_AGE_SECONDS}s)"

        try:
            success = await self._execute_rollback(snap)
            if success:
                snap.rolled_back = True
                snap.rolled_back_at = time.time()
                logger.info(f"Rollback successful: {snapshot_id} ({snap.action_type})")
                return True, f"Annule : {snap.description}"
            return False, f"Echec du rollback pour {snap.action_type}"
        except Exception as e:
            logger.error(f"Rollback failed for {snapshot_id}: {e}")
            return False, f"Erreur rollback : {e}"

    async def undo_last(self) -> tuple[bool, str]:
        """Annule la derniere action non-annulee."""
        for snap in reversed(self._snapshots):
            if not snap.rolled_back and not snap.action_type == "message":
                return await self.rollback(snap.id)
        return False, "Rien a annuler"

    async def undo_last_n(self, n: int = 1) -> list[tuple[bool, str]]:
        """Annule les N dernieres actions."""
        results = []
        count = 0
        for snap in reversed(self._snapshots):
            if count >= n:
                break
            if not snap.rolled_back:
                result = await self.rollback(snap.id)
                results.append(result)
                count += 1
        return results

    async def _execute_rollback(self, snap: Snapshot) -> bool:
        """Execute le rollback dans la base de donnees (version async)."""
        info = snap.rollback_info
        at = snap.action_type

        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()

        try:
            if at == "memory":
                key = info.get("key", "")
                restore = info.get("restore_value", "")
                async with factory() as session:
                    try:
                        if restore:
                            await session.execute(
                                text(
                                    "UPDATE agent3_memory SET value = :val "
                                    "WHERE auth_user_id = :uid AND key = :key"
                                ),
                                {"val": restore, "uid": self.user_id, "key": key},
                            )
                        else:
                            await session.execute(
                                text(
                                    "DELETE FROM agent3_memory "
                                    "WHERE auth_user_id = :uid AND key = :key"
                                ),
                                {"uid": self.user_id, "key": key},
                            )
                        await session.commit()
                        return True
                    except Exception:
                        await session.rollback()
                        raise

            elif at == "cron":
                cron_id = info.get("cron_id", "")
                if cron_id:
                    async with factory() as session:
                        try:
                            await session.execute(
                                text(
                                    "DELETE FROM agent3_cron "
                                    "WHERE id = :id AND auth_user_id = :uid"
                                ),
                                {"id": cron_id, "uid": self.user_id},
                            )
                            await session.commit()
                            return True
                        except Exception:
                            await session.rollback()
                            raise

            elif at == "task":
                task_id = info.get("task_id", "")
                if task_id:
                    async with factory() as session:
                        try:
                            await session.execute(
                                text(
                                    "DELETE FROM agent3_tasks "
                                    "WHERE id = :id AND auth_user_id = :uid"
                                ),
                                {"id": task_id, "uid": self.user_id},
                            )
                            await session.commit()
                            return True
                        except Exception:
                            await session.rollback()
                            raise

            elif at == "file":
                filename = info.get("filename", "")
                was_new = info.get("was_new", True)
                if was_new and filename:
                    import os
                    if os.path.exists(filename):
                        os.remove(filename)
                        return True
                    return True  # Already gone
                # Modification de fichier existant : pas de rollback (pas de backup du contenu)
                return False

            elif at == "setting":
                key = info.get("key", "")
                restore = info.get("restore_value")
                if key and restore is not None:
                    import json
                    async with factory() as session:
                        try:
                            result = await session.execute(
                                text(
                                    "SELECT preferences_json FROM agent3_preferences "
                                    "WHERE auth_user_id = :uid"
                                ),
                                {"uid": self.user_id},
                            )
                            row = result.first()
                            if row:
                                prefs = json.loads(row[0] or "{}")
                                prefs[key] = restore
                                await session.execute(
                                    text(
                                        "UPDATE agent3_preferences "
                                        "SET preferences_json = :prefs "
                                        "WHERE auth_user_id = :uid"
                                    ),
                                    {"prefs": json.dumps(prefs), "uid": self.user_id},
                                )
                                await session.commit()
                                return True
                        except Exception:
                            await session.rollback()
                            raise

            return False

        except Exception as e:
            logger.error(f"Rollback execution failed for {at}: {e}")
            return False

    # ── Queries ──

    def get_history(self, limit: int = 20) -> list[dict]:
        """Retourne l'historique des snapshots (recents d'abord)."""
        return [
            s.to_dict()
            for s in reversed(self._snapshots[-limit:])
            if not s.rolled_back
        ]

    def get_all_history(self, limit: int = 50) -> list[dict]:
        """Retourne tout l'historique (y compris rollbacks)."""
        return [s.to_dict() for s in reversed(self._snapshots[-limit:])]

    @property
    def undoable_count(self) -> int:
        now = time.time()
        return sum(
            1 for s in self._snapshots
            if not s.rolled_back
            and (now - s.created_at) <= self.MAX_UNDO_AGE_SECONDS
        )


# ── Singleton registry ──

_managers: dict[str, UndoManager] = {}


def get_undo_manager(user_id: str, db=None) -> UndoManager:
    if user_id not in _managers:
        _managers[user_id] = UndoManager(user_id, db)
    elif db and not _managers[user_id].db:
        _managers[user_id].db = db
    return _managers[user_id]


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

async def _execute_rollback_async(snap: Snapshot, user_id: str) -> bool:
    """Version async/PG-compatible de UndoManager._execute_rollback.

    Plus de parametre `db` : utilise get_session_factory() directement.
    Encapsule la logique SQL pour les types `memory`, `cron`, `task`, `file`
    et `setting`. Retourne True si le rollback a reussi, False sinon.
    """
    import json as _json
    from sqlalchemy import text
    from api.database import get_session_factory

    info = snap.rollback_info
    at = snap.action_type
    factory = get_session_factory()

    try:
        if at == "memory":
            key = info.get("key", "")
            restore = info.get("restore_value", "")
            async with factory() as session:
                try:
                    if restore:
                        await session.execute(
                            text(
                                "UPDATE agent3_memory SET value = :val "
                                "WHERE auth_user_id = :uid AND key = :key"
                            ),
                            {"val": restore, "uid": user_id, "key": key},
                        )
                    else:
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
                    raise

        elif at == "cron":
            cron_id = info.get("cron_id", "")
            if cron_id:
                async with factory() as session:
                    try:
                        await session.execute(
                            text(
                                "DELETE FROM agent3_cron "
                                "WHERE id = :id AND auth_user_id = :uid"
                            ),
                            {"id": cron_id, "uid": user_id},
                        )
                        await session.commit()
                        return True
                    except Exception:
                        await session.rollback()
                        raise

        elif at == "task":
            task_id = info.get("task_id", "")
            if task_id:
                async with factory() as session:
                    try:
                        await session.execute(
                            text(
                                "DELETE FROM agent3_tasks "
                                "WHERE id = :id AND auth_user_id = :uid"
                            ),
                            {"id": task_id, "uid": user_id},
                        )
                        await session.commit()
                        return True
                    except Exception:
                        await session.rollback()
                        raise

        elif at == "file":
            filename = info.get("filename", "")
            was_new = info.get("was_new", True)
            if was_new and filename:
                import os
                if os.path.exists(filename):
                    os.remove(filename)
                    return True
                return True
            return False

        elif at == "setting":
            key = info.get("key", "")
            restore = info.get("restore_value")
            if key and restore is not None:
                async with factory() as session:
                    try:
                        result = await session.execute(
                            text(
                                "SELECT preferences_json FROM agent3_preferences "
                                "WHERE auth_user_id = :uid"
                            ),
                            {"uid": user_id},
                        )
                        row = result.first()
                        if row:
                            prefs = _json.loads(row[0] or "{}")
                            prefs[key] = restore
                            await session.execute(
                                text(
                                    "UPDATE agent3_preferences "
                                    "SET preferences_json = :json "
                                    "WHERE auth_user_id = :uid"
                                ),
                                {"json": _json.dumps(prefs), "uid": user_id},
                            )
                            await session.commit()
                            return True
                    except Exception:
                        await session.rollback()
                        raise

        return False

    except Exception as e:
        logger.error(f"Rollback async execution failed for {at}: {e}")
        return False


async def rollback_async(
    manager: UndoManager, snapshot_id: str,
) -> tuple[bool, str]:
    """Version PG-compatible de UndoManager.rollback.

    Identique en logique mais delegue le SQL au helper _execute_rollback_async,
    qui utilise SQLAlchemy text() au lieu de db.conn.execute (compat SQLite + PG).
    """
    snap = next((s for s in manager._snapshots if s.id == snapshot_id), None)
    if not snap:
        return False, f"Snapshot {snapshot_id} introuvable"
    if snap.rolled_back:
        return False, f"Snapshot {snapshot_id} deja annule"
    if time.time() - snap.created_at > manager.MAX_UNDO_AGE_SECONDS:
        return False, (
            f"Snapshot trop ancien ({int(time.time() - snap.created_at)}s > "
            f"{manager.MAX_UNDO_AGE_SECONDS}s)"
        )

    try:
        success = await _execute_rollback_async(snap, manager.user_id)
        if success:
            snap.rolled_back = True
            snap.rolled_back_at = time.time()
            logger.info(f"Rollback async successful: {snapshot_id} ({snap.action_type})")
            return True, f"Annule : {snap.description}"
        return False, f"Echec du rollback pour {snap.action_type}"
    except Exception as e:
        logger.error(f"Rollback async failed for {snapshot_id}: {e}")
        return False, f"Erreur rollback : {e}"


async def undo_last_async(manager: UndoManager) -> tuple[bool, str]:
    """Version async de UndoManager.undo_last — PG-compatible."""
    for snap in reversed(manager._snapshots):
        if not snap.rolled_back and not snap.action_type == "message":
            return await rollback_async(manager, snap.id)
    return False, "Rien a annuler"


async def undo_last_n_async(
    manager: UndoManager, n: int = 1,
) -> list[tuple[bool, str]]:
    """Version async de UndoManager.undo_last_n — PG-compatible."""
    results: list[tuple[bool, str]] = []
    count = 0
    for snap in reversed(manager._snapshots):
        if count >= n:
            break
        if not snap.rolled_back:
            result = await rollback_async(manager, snap.id)
            results.append(result)
            count += 1
    return results
