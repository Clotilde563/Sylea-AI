"""
Agent 3 — Retention policies + auto-cleanup scheduler.

Configurable par user via preferences (keys `retention_*`) ou defaut.

Defauts :
  - messages : 180 jours
  - events clawhub : 180 jours
  - figures matplotlib : 30 jours
  - uploads : 90 jours
  - audit log : 365 jours

Hook dans `api/scheduler.py` : la `SyleaScheduler` appelle `run_retention_pass()`
une fois par jour. Si inactif (test, scheduler off), peut etre trigger manuel
via endpoint `/api/agent3/retention/run`.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("sylea.retention")


# Defaults en jours (override via pref user ou env)
DEFAULT_RETENTION_DAYS: dict[str, int] = {
    "messages": int(os.getenv("SYLEA_RETENTION_MESSAGES_DAYS", "180")),
    "events": int(os.getenv("SYLEA_RETENTION_EVENTS_DAYS", "180")),
    "figures": int(os.getenv("SYLEA_RETENTION_FIGURES_DAYS", "30")),
    "uploads": int(os.getenv("SYLEA_RETENTION_UPLOADS_DAYS", "90")),
    "audit_log": int(os.getenv("SYLEA_RETENTION_AUDIT_DAYS", "365")),
}


# Tracking du dernier run (idempotent)
_last_run_at_lock = threading.Lock()
_last_run_at: float = 0.0
_RETENTION_MIN_INTERVAL_S = 60 * 60 * 6  # 6h min entre runs pour eviter boucles


def _cutoff_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _cutoff_timestamp(days: int) -> float:
    return time.time() - days * 86400


def _user_retention_days(db: Any, user_id: str, key: str, fallback: int) -> int:
    """Lit la pref user ou fallback."""
    try:
        row = db.conn.execute(
            "SELECT prefs_json FROM agent3_preferences WHERE auth_user_id = ?",
            (user_id,),
        ).fetchone()
        if row and row[0]:
            import json
            prefs = json.loads(row[0]) or {}
            val = prefs.get(f"retention_{key}_days")
            if isinstance(val, (int, float)) and val > 0:
                return int(val)
    except Exception:
        pass
    return fallback


# ─────────────────────────────────────────────────────────────────────────────
# Operations de cleanup
# ─────────────────────────────────────────────────────────────────────────────

def cleanup_messages(db: Any, days: int) -> int:
    """Supprime les messages > days. Retourne le count."""
    try:
        cursor = db.conn.execute(
            "DELETE FROM agent3_messages WHERE created_at < ?",
            (_cutoff_iso(days),),
        )
        db.conn.commit()
        return cursor.rowcount or 0
    except Exception as e:
        logger.debug(f"cleanup_messages failed: {e}")
        return 0


def cleanup_events(db: Any, days: int) -> int:
    """Supprime les clawhub events > days."""
    try:
        cursor = db.conn.execute(
            "DELETE FROM agent3_clawhub_events WHERE created_at < ?",
            (_cutoff_iso(days),),
        )
        db.conn.commit()
        return cursor.rowcount or 0
    except Exception as e:
        logger.debug(f"cleanup_events failed: {e}")
        return 0


def cleanup_audit_log(db: Any, days: int) -> int:
    try:
        cursor = db.conn.execute(
            "DELETE FROM agent3_audit_log WHERE created_at < ?",
            (_cutoff_iso(days),),
        )
        db.conn.commit()
        return cursor.rowcount or 0
    except Exception as e:
        logger.debug(f"cleanup_audit_log failed: {e}")
        return 0


def cleanup_figures(days: int, figures_dir: Path | None = None) -> int:
    """Supprime les figures matplotlib > days (sur disque)."""
    if figures_dir is None:
        figures_dir = Path(__file__).resolve().parent.parent / "data" / "sandbox_figures"
    if not figures_dir.exists() or not figures_dir.is_dir():
        return 0

    cutoff = _cutoff_timestamp(days)
    deleted = 0
    try:
        for sub in figures_dir.iterdir():
            try:
                if sub.is_dir():
                    # Le nom de dossier est le run_id uniquement — on regarde mtime
                    if sub.stat().st_mtime < cutoff:
                        shutil.rmtree(sub, ignore_errors=True)
                        deleted += 1
                elif sub.is_file():
                    if sub.stat().st_mtime < cutoff:
                        sub.unlink()
                        deleted += 1
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"cleanup_figures iter failed: {e}")
    return deleted


def cleanup_uploads(db: Any, days: int) -> int:
    """Supprime les uploads > days (DB + disque)."""
    cutoff = _cutoff_iso(days)
    try:
        rows = db.conn.execute(
            "SELECT id, filepath FROM agent3_files WHERE created_at < ?",
            (cutoff,),
        ).fetchall()
    except Exception as e:
        logger.debug(f"cleanup_uploads read failed: {e}")
        return 0

    ids_to_delete = []
    files_removed = 0
    for row in rows:
        try:
            fp = row[1]
            if fp:
                p = Path(fp)
                if p.exists() and p.is_file():
                    p.unlink()
                    files_removed += 1
            ids_to_delete.append(row[0])
        except Exception:
            continue

    if ids_to_delete:
        placeholders = ",".join("?" * len(ids_to_delete))
        try:
            db.conn.execute(
                f"DELETE FROM agent3_files WHERE id IN ({placeholders})",
                tuple(ids_to_delete),
            )
            db.conn.commit()
        except Exception as e:
            logger.debug(f"cleanup_uploads delete failed: {e}")

    return files_removed


# ─────────────────────────────────────────────────────────────────────────────
# Pass unique (appele par le scheduler)
# ─────────────────────────────────────────────────────────────────────────────

def run_retention_pass(db: Any, *, force: bool = False) -> dict[str, Any]:
    """Execute tous les cleanups d'un coup.

    Respecte _RETENTION_MIN_INTERVAL_S (6h) sauf si force=True.
    Retourne un resume {table: count_deleted, duration_s}.
    """
    global _last_run_at
    now = time.time()
    with _last_run_at_lock:
        if not force and (now - _last_run_at) < _RETENTION_MIN_INTERVAL_S:
            remaining = _RETENTION_MIN_INTERVAL_S - (now - _last_run_at)
            return {"skipped": True, "next_run_in_s": int(remaining)}
        _last_run_at = now

    start = time.time()
    results: dict[str, int] = {}

    # Defaults — on applique les defauts globaux (par user serait trop lent ici)
    results["messages"] = cleanup_messages(db, DEFAULT_RETENTION_DAYS["messages"])
    results["events"] = cleanup_events(db, DEFAULT_RETENTION_DAYS["events"])
    results["audit_log"] = cleanup_audit_log(db, DEFAULT_RETENTION_DAYS["audit_log"])
    results["figures"] = cleanup_figures(DEFAULT_RETENTION_DAYS["figures"])
    results["uploads"] = cleanup_uploads(db, DEFAULT_RETENTION_DAYS["uploads"])

    duration = time.time() - start
    total = sum(results.values())
    logger.info(
        f"retention_pass: deleted {total} items in {duration:.2f}s — "
        + ", ".join(f"{k}={v}" for k, v in results.items())
    )
    return {
        "deleted_by_category": results,
        "total_deleted": total,
        "duration_s": round(duration, 3),
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "skipped": False,
    }


def get_last_run_info() -> dict[str, Any]:
    with _last_run_at_lock:
        if _last_run_at == 0:
            return {"last_run_at": None, "ever_ran": False}
        age_s = time.time() - _last_run_at
        return {
            "last_run_at": _last_run_at,
            "last_run_at_iso": datetime.fromtimestamp(_last_run_at, tz=timezone.utc).isoformat(),
            "age_s": round(age_s, 1),
            "next_run_in_s": max(0, int(_RETENTION_MIN_INTERVAL_S - age_s)),
            "ever_ran": True,
        }


def reset_retention_tracker() -> None:
    """Pour tests : reset le rate limiter interne."""
    global _last_run_at
    with _last_run_at_lock:
        _last_run_at = 0.0


__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "cleanup_messages",
    "cleanup_events",
    "cleanup_audit_log",
    "cleanup_figures",
    "cleanup_uploads",
    "run_retention_pass",
    "get_last_run_info",
    "reset_retention_tracker",
]
