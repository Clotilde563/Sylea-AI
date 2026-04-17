"""
Agent 3 — TodoWrite Live Tracker.

State machine pour le suivi en temps reel des taches dans le chat.
Chaque tache transite : pending -> running -> done | failed | skipped.

Inspire de TodoWrite de Claude Code : le frontend recoit des SSE events
a chaque transition, et affiche une checklist live animee.

Usage :
    tracker = TodoTracker(user_id)
    tracker.create("Recherche web", "Recherche les donnees", group="analyse")
    tracker.start("Recherche web")       # -> running
    tracker.complete("Recherche web")    # -> done
    # Le caller yield les events SSE a chaque transition
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("sylea.agent3.todo_tracker")


class TodoStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"

    @property
    def is_terminal(self) -> bool:
        return self in (TodoStatus.DONE, TodoStatus.FAILED, TodoStatus.SKIPPED)


@dataclass
class TodoItem:
    """Un element de todo avec state machine."""

    id: str
    title: str                          # Forme imperative ("Rechercher les donnees")
    active_form: str = ""               # Forme progressive ("Recherche en cours...")
    status: TodoStatus = TodoStatus.PENDING
    group: str = ""                     # Regroupement logique (optionnel)
    result: str = ""                    # Message de resultat
    error: str = ""                     # Message d'erreur si failed
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "active_form": self.active_form or self.title,
            "status": self.status.value,
            "group": self.group,
            "result": self.result,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 1),
        }


@dataclass
class TodoTransition:
    """Evenement de transition a envoyer via SSE."""

    item_id: str
    title: str
    active_form: str
    old_status: str
    new_status: str
    result: str = ""
    error: str = ""
    duration_ms: float = 0.0
    progress: float = 0.0              # 0.0 - 100.0 (% du tracker)

    def to_sse_data(self) -> dict:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "active_form": self.active_form,
            "old_status": self.old_status,
            "new_status": self.new_status,
            "result": self.result,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 1),
            "progress": round(self.progress, 1),
        }


class TodoTracker:
    """Tracker de taches avec state machine et events SSE."""

    def __init__(self, user_id: str = "default"):
        self.user_id = user_id
        self._items: dict[str, TodoItem] = {}  # id -> item
        self._order: list[str] = []            # insertion order
        self._created_at = time.time()

    # ── Creation ──

    def create(
        self,
        title: str,
        active_form: str = "",
        group: str = "",
        item_id: str = "",
    ) -> TodoItem:
        """Cree un nouveau todo item en status PENDING."""
        if not item_id:
            item_id = f"todo_{uuid.uuid4().hex[:8]}"
        item = TodoItem(
            id=item_id,
            title=title,
            active_form=active_form or title,
            group=group,
        )
        self._items[item_id] = item
        self._order.append(item_id)
        return item

    def create_batch(self, items: list[dict]) -> list[TodoItem]:
        """Cree plusieurs todos d'un coup.

        items: [{"title": "...", "active_form": "...", "group": "..."}, ...]
        """
        created = []
        for spec in items:
            item = self.create(
                title=spec.get("title", spec.get("content", "?")),
                active_form=spec.get("active_form", spec.get("activeForm", "")),
                group=spec.get("group", ""),
            )
            created.append(item)
        return created

    # ── Transitions ──

    def start(self, item_id: str) -> Optional[TodoTransition]:
        """Transition: pending -> running."""
        item = self._items.get(item_id)
        if not item or item.status != TodoStatus.PENDING:
            return None
        old = item.status.value
        item.status = TodoStatus.RUNNING
        item.started_at = time.perf_counter()
        return TodoTransition(
            item_id=item.id,
            title=item.title,
            active_form=item.active_form,
            old_status=old,
            new_status="running",
            progress=self.progress,
        )

    def complete(self, item_id: str, result: str = "") -> Optional[TodoTransition]:
        """Transition: running -> done."""
        item = self._items.get(item_id)
        if not item or item.status != TodoStatus.RUNNING:
            return None
        old = item.status.value
        item.status = TodoStatus.DONE
        item.result = result
        item.completed_at = time.perf_counter()
        if item.started_at:
            item.duration_ms = (item.completed_at - item.started_at) * 1000
        return TodoTransition(
            item_id=item.id,
            title=item.title,
            active_form=item.active_form,
            old_status=old,
            new_status="done",
            result=result,
            duration_ms=item.duration_ms,
            progress=self.progress,
        )

    def fail(self, item_id: str, error: str = "") -> Optional[TodoTransition]:
        """Transition: running -> failed."""
        item = self._items.get(item_id)
        if not item or item.status != TodoStatus.RUNNING:
            return None
        old = item.status.value
        item.status = TodoStatus.FAILED
        item.error = error
        item.completed_at = time.perf_counter()
        if item.started_at:
            item.duration_ms = (item.completed_at - item.started_at) * 1000
        return TodoTransition(
            item_id=item.id,
            title=item.title,
            active_form=item.active_form,
            old_status=old,
            new_status="failed",
            error=error,
            duration_ms=item.duration_ms,
            progress=self.progress,
        )

    def skip(self, item_id: str, reason: str = "") -> Optional[TodoTransition]:
        """Transition: pending -> skipped."""
        item = self._items.get(item_id)
        if not item or item.status != TodoStatus.PENDING:
            return None
        old = item.status.value
        item.status = TodoStatus.SKIPPED
        item.result = reason
        return TodoTransition(
            item_id=item.id,
            title=item.title,
            active_form=item.active_form,
            old_status=old,
            new_status="skipped",
            result=reason,
            progress=self.progress,
        )

    # ── Queries ──

    @property
    def progress(self) -> float:
        """Progression globale 0.0 - 100.0."""
        if not self._items:
            return 100.0
        terminal = sum(1 for it in self._items.values() if it.status.is_terminal)
        return (terminal / len(self._items)) * 100.0

    @property
    def current_running(self) -> Optional[TodoItem]:
        """Retourne l'item en cours d'execution (ou None)."""
        for iid in self._order:
            it = self._items[iid]
            if it.status == TodoStatus.RUNNING:
                return it
        return None

    @property
    def is_complete(self) -> bool:
        return all(it.status.is_terminal for it in self._items.values())

    def get_summary(self) -> dict:
        counts = {"pending": 0, "running": 0, "done": 0, "failed": 0, "skipped": 0}
        for it in self._items.values():
            counts[it.status.value] += 1
        return {
            "total": len(self._items),
            "progress": round(self.progress, 1),
            "counts": counts,
            "items": [self._items[iid].to_dict() for iid in self._order],
            "is_complete": self.is_complete,
        }

    def to_sse_snapshot(self) -> dict:
        """Snapshot complet pour l'event SSE 'todo_snapshot'."""
        return self.get_summary()


# ── Registry singleton ──

_trackers: dict[str, TodoTracker] = {}


def get_todo_tracker(user_id: str, create: bool = True) -> Optional[TodoTracker]:
    if user_id not in _trackers and create:
        _trackers[user_id] = TodoTracker(user_id)
    return _trackers.get(user_id)


def reset_todo_tracker(user_id: str) -> None:
    _trackers.pop(user_id, None)
