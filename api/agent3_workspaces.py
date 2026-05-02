"""
Agent 3 — Workspaces multi-tenant.

Permet a des users de collaborer via workspaces partages :
  - Memoire partagee (opt-in : user promote une memory vers le workspace)
  - Skills ClawHub partages (installe une fois, dispo pour tous)
  - Audit log visible par tous les membres (optionnel via role)
  - Chat contexte separe par workspace (un user peut etre dans N workspaces)

Modele :
  workspaces (id, name, owner_id, plan_override, created_at, settings_json)
  workspace_members (workspace_id, user_id, role: owner|admin|member, joined_at)
  workspace_shared_memory (id, workspace_id, key, value, category, created_by, created_at)

Fonctionnement :
  - Chaque user a son workspace personnel implicite (id = user_id)
  - Il peut etre membre de N workspaces externes
  - `set_current_workspace(user_id, workspace_id)` change le scope par session

API :
  - create_workspace / delete_workspace
  - add_member / remove_member / list_members
  - list_user_workspaces
  - share_memory / get_workspace_memory
  - get_user_role(workspace_id, user_id)
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

logger = logging.getLogger("sylea.workspaces")


Role = Literal["owner", "admin", "member"]


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

_WORKSPACES_DDL = """
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL,
    plan_override TEXT,
    settings_json TEXT,
    created_at TEXT NOT NULL
)
"""

_MEMBERS_DDL = """
CREATE TABLE IF NOT EXISTS workspace_members (
    workspace_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member',
    joined_at TEXT NOT NULL,
    PRIMARY KEY (workspace_id, user_id)
)
"""

_SHARED_MEMORY_DDL = """
CREATE TABLE IF NOT EXISTS workspace_shared_memory (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def ensure_workspace_tables(db: Any) -> None:
    try:
        db.conn.execute(_WORKSPACES_DDL)
        db.conn.execute(_MEMBERS_DDL)
        db.conn.execute(_SHARED_MEMORY_DDL)
        db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ws_member_user ON workspace_members(user_id)"
        )
        db.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ws_shared_mem_ws "
            "ON workspace_shared_memory(workspace_id)"
        )
        db.conn.commit()
    except Exception as e:
        logger.debug(f"ensure_workspace_tables failed: {e}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────────────────────
# Workspace lifecycle
# ─────────────────────────────────────────────────────────────────────────────

def create_workspace(
    db: Any, owner_id: str, name: str, *, settings: dict | None = None,
) -> dict[str, Any]:
    """Cree un workspace + ajoute l'owner comme membre role=owner."""
    if not owner_id or not name.strip():
        return {"ok": False, "error": "owner_id + name requis"}
    ensure_workspace_tables(db)

    ws_id = str(uuid.uuid4())
    now = _now()
    settings_json = json.dumps(settings or {})
    try:
        db.conn.execute(
            "INSERT INTO workspaces (id, name, owner_id, settings_json, created_at) "
            "VALUES (?,?,?,?,?)",
            (ws_id, name.strip()[:100], owner_id, settings_json, now),
        )
        db.conn.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role, joined_at) "
            "VALUES (?,?,?,?)",
            (ws_id, owner_id, "owner", now),
        )
        db.conn.commit()
    except Exception as e:
        logger.warning(f"create_workspace failed: {e}")
        return {"ok": False, "error": str(e)}
    return {"ok": True, "workspace_id": ws_id, "name": name}


def delete_workspace(db: Any, workspace_id: str, requester_id: str) -> dict[str, Any]:
    """Seul l'owner peut supprimer."""
    ensure_workspace_tables(db)
    role = get_user_role(db, workspace_id, requester_id)
    if role != "owner":
        return {"ok": False, "error": "forbidden: owner only"}
    try:
        db.conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        db.conn.execute(
            "DELETE FROM workspace_members WHERE workspace_id = ?", (workspace_id,)
        )
        db.conn.execute(
            "DELETE FROM workspace_shared_memory WHERE workspace_id = ?", (workspace_id,)
        )
        db.conn.commit()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def get_workspace(db: Any, workspace_id: str) -> dict[str, Any] | None:
    ensure_workspace_tables(db)
    try:
        row = db.conn.execute(
            "SELECT id, name, owner_id, settings_json, created_at "
            "FROM workspaces WHERE id = ?",
            (workspace_id,),
        ).fetchone()
    except Exception:
        return None
    if not row:
        return None
    settings = {}
    if row[3]:
        try:
            settings = json.loads(row[3])
        except Exception:
            pass
    return {
        "id": row[0],
        "name": row[1],
        "owner_id": row[2],
        "settings": settings,
        "created_at": row[4],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Members
# ─────────────────────────────────────────────────────────────────────────────

def add_member(
    db: Any, workspace_id: str, user_id: str, role: Role,
    *, requester_id: str,
) -> dict[str, Any]:
    """Seul owner/admin peut inviter."""
    ensure_workspace_tables(db)
    req_role = get_user_role(db, workspace_id, requester_id)
    if req_role not in ("owner", "admin"):
        return {"ok": False, "error": "forbidden: owner/admin only"}
    if role not in ("owner", "admin", "member"):
        return {"ok": False, "error": f"invalid role: {role}"}

    try:
        existing = db.conn.execute(
            "SELECT role FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user_id),
        ).fetchone()
        if existing:
            db.conn.execute(
                "UPDATE workspace_members SET role = ? "
                "WHERE workspace_id = ? AND user_id = ?",
                (role, workspace_id, user_id),
            )
        else:
            db.conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role, joined_at) "
                "VALUES (?,?,?,?)",
                (workspace_id, user_id, role, _now()),
            )
        db.conn.commit()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "user_id": user_id, "role": role}


def remove_member(
    db: Any, workspace_id: str, user_id: str, *, requester_id: str,
) -> dict[str, Any]:
    """owner/admin peut kick. Ne peut pas remove l'owner."""
    ensure_workspace_tables(db)
    req_role = get_user_role(db, workspace_id, requester_id)
    if req_role not in ("owner", "admin"):
        return {"ok": False, "error": "forbidden"}

    target_role = get_user_role(db, workspace_id, user_id)
    if target_role == "owner":
        return {"ok": False, "error": "cannot remove owner"}

    try:
        db.conn.execute(
            "DELETE FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user_id),
        )
        db.conn.commit()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def list_members(db: Any, workspace_id: str) -> list[dict[str, Any]]:
    ensure_workspace_tables(db)
    try:
        rows = db.conn.execute(
            "SELECT user_id, role, joined_at FROM workspace_members "
            "WHERE workspace_id = ? ORDER BY joined_at",
            (workspace_id,),
        ).fetchall()
    except Exception:
        return []
    return [{"user_id": r[0], "role": r[1], "joined_at": r[2]} for r in rows]


def list_user_workspaces(db: Any, user_id: str) -> list[dict[str, Any]]:
    ensure_workspace_tables(db)
    try:
        rows = db.conn.execute(
            "SELECT w.id, w.name, w.owner_id, w.created_at, m.role "
            "FROM workspaces w INNER JOIN workspace_members m ON w.id = m.workspace_id "
            "WHERE m.user_id = ? ORDER BY w.created_at DESC",
            (user_id,),
        ).fetchall()
    except Exception:
        return []
    return [
        {"id": r[0], "name": r[1], "owner_id": r[2], "created_at": r[3], "my_role": r[4]}
        for r in rows
    ]


def get_user_role(db: Any, workspace_id: str, user_id: str) -> Role | None:
    ensure_workspace_tables(db)
    try:
        row = db.conn.execute(
            "SELECT role FROM workspace_members "
            "WHERE workspace_id = ? AND user_id = ?",
            (workspace_id, user_id),
        ).fetchone()
    except Exception:
        return None
    return row[0] if row else None


def is_member(db: Any, workspace_id: str, user_id: str) -> bool:
    return get_user_role(db, workspace_id, user_id) is not None


# ─────────────────────────────────────────────────────────────────────────────
# Shared memory
# ─────────────────────────────────────────────────────────────────────────────

def share_memory(
    db: Any, workspace_id: str, user_id: str,
    *, key: str, value: str, category: str = "general",
) -> dict[str, Any]:
    """Ajoute une entree de memoire partagee au workspace.

    Le user doit etre membre. Role member suffit.
    """
    ensure_workspace_tables(db)
    if not is_member(db, workspace_id, user_id):
        return {"ok": False, "error": "forbidden: not a member"}
    if not key.strip() or not value.strip():
        return {"ok": False, "error": "key + value requis"}

    mem_id = str(uuid.uuid4())
    try:
        db.conn.execute(
            "INSERT INTO workspace_shared_memory "
            "(id, workspace_id, key, value, category, created_by, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (mem_id, workspace_id, key[:200], value[:4000], category, user_id, _now()),
        )
        db.conn.commit()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "memory_id": mem_id}


def get_workspace_memory(
    db: Any, workspace_id: str, *, limit: int = 50,
) -> list[dict[str, Any]]:
    ensure_workspace_tables(db)
    try:
        rows = db.conn.execute(
            "SELECT id, key, value, category, created_by, created_at "
            "FROM workspace_shared_memory WHERE workspace_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (workspace_id, max(1, min(int(limit), 200))),
        ).fetchall()
    except Exception:
        return []
    return [
        {
            "id": r[0],
            "key": r[1],
            "value": r[2],
            "category": r[3],
            "created_by": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]


def format_workspace_memory_for_prompt(
    db: Any, workspace_id: str, *, limit: int = 20,
) -> str:
    """Bloc pour injection dans system_prompt quand user acting in workspace."""
    items = get_workspace_memory(db, workspace_id, limit=limit)
    if not items:
        return ""
    ws = get_workspace(db, workspace_id)
    ws_name = ws["name"] if ws else "?"
    lines = [f"=== MEMOIRE PARTAGEE DU WORKSPACE '{ws_name}' ==="]
    for it in items:
        lines.append(f"- [{it['category']}] {it['key']} : {it['value'][:150]}")
    lines.append(
        "Tu as acces a cette memoire partagee par les membres du workspace."
    )
    return "\n".join(lines)


__all__ = [
    "ensure_workspace_tables",
    "create_workspace",
    "delete_workspace",
    "get_workspace",
    "add_member",
    "remove_member",
    "list_members",
    "list_user_workspaces",
    "get_user_role",
    "is_member",
    "share_memory",
    "get_workspace_memory",
    "format_workspace_memory_for_prompt",
]
