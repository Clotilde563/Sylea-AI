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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    # Versions async (PG-compatible)
    "ensure_workspace_tables_async",
    "create_workspace_async",
    "delete_workspace_async",
    "get_workspace_async",
    "add_member_async",
    "remove_member_async",
    "list_members_async",
    "list_user_workspaces_async",
    "get_user_role_async",
    "is_member_async",
    "share_memory_async",
    "get_workspace_memory_async",
    "format_workspace_memory_for_prompt_async",
]


# ═══════════════════════════════════════════════════════════════════════════
#  Versions async (migration PG, 2026-05-13) — compat SQLite + PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════

async def ensure_workspace_tables_async() -> None:
    """Version async — cree les tables workspaces / members / shared_memory.

    Best-effort : si la creation echoue (privileges, conflit), on log debug
    et on continue (les autres fonctions feront un try/except sur leurs
    SELECT/INSERT).
    """
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(text(_WORKSPACES_DDL))
            await session.execute(text(_MEMBERS_DDL))
            await session.execute(text(_SHARED_MEMORY_DDL))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_ws_member_user "
                "ON workspace_members(user_id)"
            ))
            await session.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_ws_shared_mem_ws "
                "ON workspace_shared_memory(workspace_id)"
            ))
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.debug(f"ensure_workspace_tables_async failed: {e}")


async def create_workspace_async(
    owner_id: str, name: str, *, settings: dict | None = None,
) -> dict[str, Any]:
    """Version async de create_workspace — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    if not owner_id or not name.strip():
        return {"ok": False, "error": "owner_id + name requis"}
    await ensure_workspace_tables_async()

    ws_id = str(uuid.uuid4())
    now = _now()
    settings_json = json.dumps(settings or {})
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO workspaces "
                    "(id, name, owner_id, settings_json, created_at) "
                    "VALUES (:id, :name, :owner_id, :settings_json, :created_at)"
                ),
                {
                    "id": ws_id,
                    "name": name.strip()[:100],
                    "owner_id": owner_id,
                    "settings_json": settings_json,
                    "created_at": now,
                },
            )
            await session.execute(
                text(
                    "INSERT INTO workspace_members "
                    "(workspace_id, user_id, role, joined_at) "
                    "VALUES (:workspace_id, :user_id, :role, :joined_at)"
                ),
                {
                    "workspace_id": ws_id,
                    "user_id": owner_id,
                    "role": "owner",
                    "joined_at": now,
                },
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.warning(f"create_workspace_async failed: {e}")
            return {"ok": False, "error": str(e)}
    return {"ok": True, "workspace_id": ws_id, "name": name}


async def delete_workspace_async(
    workspace_id: str, requester_id: str,
) -> dict[str, Any]:
    """Version async de delete_workspace — seul l'owner peut supprimer."""
    from sqlalchemy import text
    from api.database import get_session_factory
    await ensure_workspace_tables_async()
    role = await get_user_role_async(workspace_id, requester_id)
    if role != "owner":
        return {"ok": False, "error": "forbidden: owner only"}
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text("DELETE FROM workspaces WHERE id = :wid"),
                {"wid": workspace_id},
            )
            await session.execute(
                text(
                    "DELETE FROM workspace_members WHERE workspace_id = :wid"
                ),
                {"wid": workspace_id},
            )
            await session.execute(
                text(
                    "DELETE FROM workspace_shared_memory WHERE workspace_id = :wid"
                ),
                {"wid": workspace_id},
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            return {"ok": False, "error": str(e)}
    return {"ok": True}


async def get_workspace_async(workspace_id: str) -> dict[str, Any] | None:
    """Version async de get_workspace — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    await ensure_workspace_tables_async()
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT id, name, owner_id, settings_json, created_at "
                    "FROM workspaces WHERE id = :wid"
                ),
                {"wid": workspace_id},
            )
            row = result.mappings().first()
        except Exception:
            return None
    if not row:
        return None
    settings = {}
    if row["settings_json"]:
        try:
            settings = json.loads(row["settings_json"])
        except Exception:
            pass
    return {
        "id": row["id"],
        "name": row["name"],
        "owner_id": row["owner_id"],
        "settings": settings,
        "created_at": row["created_at"],
    }


async def add_member_async(
    workspace_id: str, user_id: str, role: Role,
    *, requester_id: str,
) -> dict[str, Any]:
    """Version async de add_member — seul owner/admin peut inviter."""
    from sqlalchemy import text
    from api.database import get_session_factory
    await ensure_workspace_tables_async()
    req_role = await get_user_role_async(workspace_id, requester_id)
    if req_role not in ("owner", "admin"):
        return {"ok": False, "error": "forbidden: owner/admin only"}
    if role not in ("owner", "admin", "member"):
        return {"ok": False, "error": f"invalid role: {role}"}

    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT role FROM workspace_members "
                    "WHERE workspace_id = :wid AND user_id = :uid"
                ),
                {"wid": workspace_id, "uid": user_id},
            )
            existing = result.first()
            if existing:
                await session.execute(
                    text(
                        "UPDATE workspace_members SET role = :role "
                        "WHERE workspace_id = :wid AND user_id = :uid"
                    ),
                    {"role": role, "wid": workspace_id, "uid": user_id},
                )
            else:
                await session.execute(
                    text(
                        "INSERT INTO workspace_members "
                        "(workspace_id, user_id, role, joined_at) "
                        "VALUES (:wid, :uid, :role, :joined_at)"
                    ),
                    {
                        "wid": workspace_id,
                        "uid": user_id,
                        "role": role,
                        "joined_at": _now(),
                    },
                )
            await session.commit()
        except Exception as e:
            await session.rollback()
            return {"ok": False, "error": str(e)}
    return {"ok": True, "user_id": user_id, "role": role}


async def remove_member_async(
    workspace_id: str, user_id: str, *, requester_id: str,
) -> dict[str, Any]:
    """Version async de remove_member — owner/admin only, ne touche pas l'owner."""
    from sqlalchemy import text
    from api.database import get_session_factory
    await ensure_workspace_tables_async()
    req_role = await get_user_role_async(workspace_id, requester_id)
    if req_role not in ("owner", "admin"):
        return {"ok": False, "error": "forbidden"}

    target_role = await get_user_role_async(workspace_id, user_id)
    if target_role == "owner":
        return {"ok": False, "error": "cannot remove owner"}

    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "DELETE FROM workspace_members "
                    "WHERE workspace_id = :wid AND user_id = :uid"
                ),
                {"wid": workspace_id, "uid": user_id},
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            return {"ok": False, "error": str(e)}
    return {"ok": True}


async def list_members_async(workspace_id: str) -> list[dict[str, Any]]:
    """Version async de list_members — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    await ensure_workspace_tables_async()
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT user_id, role, joined_at FROM workspace_members "
                    "WHERE workspace_id = :wid ORDER BY joined_at"
                ),
                {"wid": workspace_id},
            )
            rows = result.mappings().all()
        except Exception:
            return []
    return [
        {"user_id": r["user_id"], "role": r["role"], "joined_at": r["joined_at"]}
        for r in rows
    ]


async def list_user_workspaces_async(user_id: str) -> list[dict[str, Any]]:
    """Version async de list_user_workspaces — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    await ensure_workspace_tables_async()
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT w.id AS id, w.name AS name, w.owner_id AS owner_id, "
                    "w.created_at AS created_at, m.role AS role "
                    "FROM workspaces w "
                    "INNER JOIN workspace_members m ON w.id = m.workspace_id "
                    "WHERE m.user_id = :uid ORDER BY w.created_at DESC"
                ),
                {"uid": user_id},
            )
            rows = result.mappings().all()
        except Exception:
            return []
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "owner_id": r["owner_id"],
            "created_at": r["created_at"],
            "my_role": r["role"],
        }
        for r in rows
    ]


async def get_user_role_async(
    workspace_id: str, user_id: str,
) -> Role | None:
    """Version async de get_user_role — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    await ensure_workspace_tables_async()
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT role FROM workspace_members "
                    "WHERE workspace_id = :wid AND user_id = :uid"
                ),
                {"wid": workspace_id, "uid": user_id},
            )
            row = result.first()
        except Exception:
            return None
    return row[0] if row else None


async def is_member_async(workspace_id: str, user_id: str) -> bool:
    """Version async de is_member — PG-compatible."""
    return (await get_user_role_async(workspace_id, user_id)) is not None


async def share_memory_async(
    workspace_id: str, user_id: str,
    *, key: str, value: str, category: str = "general",
) -> dict[str, Any]:
    """Version async de share_memory — PG-compatible.

    Le user doit etre membre. Role member suffit.
    """
    from sqlalchemy import text
    from api.database import get_session_factory
    await ensure_workspace_tables_async()
    if not await is_member_async(workspace_id, user_id):
        return {"ok": False, "error": "forbidden: not a member"}
    if not key.strip() or not value.strip():
        return {"ok": False, "error": "key + value requis"}

    mem_id = str(uuid.uuid4())
    factory = get_session_factory()
    async with factory() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO workspace_shared_memory "
                    "(id, workspace_id, key, value, category, created_by, created_at) "
                    "VALUES (:id, :wid, :key, :value, :category, :created_by, :created_at)"
                ),
                {
                    "id": mem_id,
                    "wid": workspace_id,
                    "key": key[:200],
                    "value": value[:4000],
                    "category": category,
                    "created_by": user_id,
                    "created_at": _now(),
                },
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            return {"ok": False, "error": str(e)}
    return {"ok": True, "memory_id": mem_id}


async def get_workspace_memory_async(
    workspace_id: str, *, limit: int = 50,
) -> list[dict[str, Any]]:
    """Version async de get_workspace_memory — PG-compatible."""
    from sqlalchemy import text
    from api.database import get_session_factory
    await ensure_workspace_tables_async()
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "SELECT id, key, value, category, created_by, created_at "
                    "FROM workspace_shared_memory WHERE workspace_id = :wid "
                    "ORDER BY created_at DESC LIMIT :lim"
                ),
                {
                    "wid": workspace_id,
                    "lim": max(1, min(int(limit), 200)),
                },
            )
            rows = result.mappings().all()
        except Exception:
            return []
    return [
        {
            "id": r["id"],
            "key": r["key"],
            "value": r["value"],
            "category": r["category"],
            "created_by": r["created_by"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


async def format_workspace_memory_for_prompt_async(
    workspace_id: str, *, limit: int = 20,
) -> str:
    """Version async — bloc pour injection dans system_prompt."""
    items = await get_workspace_memory_async(workspace_id, limit=limit)
    if not items:
        return ""
    ws = await get_workspace_async(workspace_id)
    ws_name = ws["name"] if ws else "?"
    lines = [f"=== MEMOIRE PARTAGEE DU WORKSPACE '{ws_name}' ==="]
    for it in items:
        lines.append(f"- [{it['category']}] {it['key']} : {it['value'][:150]}")
    lines.append(
        "Tu as acces a cette memoire partagee par les membres du workspace."
    )
    return "\n".join(lines)
