"""Shared Workspaces — partage de vision entre utilisateurs Sylea."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.dependencies import get_db, get_optional_user
from sylea.core.storage.database import DatabaseManager

router = APIRouter(prefix="/api/shared", tags=["shared"])


class ShareWorkspaceIn(BaseModel):
    target_user_id: str
    role: str = "viewer"  # "viewer" or "editor"


class SharedWorkspaceOut(BaseModel):
    id: str
    owner_id: str
    shared_with: str
    role: str
    created_at: str


def _ensure_shared_tables(db):
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS shared_workspaces (
            id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            shared_with TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at TEXT NOT NULL,
            UNIQUE(owner_id, shared_with)
        )
    """)
    db.conn.commit()


@router.post("/workspace")
async def share_workspace(
    data: ShareWorkspaceIn,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Partage la vue du dashboard avec un autre utilisateur."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")
    if data.target_user_id == user_id:
        raise HTTPException(status_code=400, detail="Impossible de partager avec soi-meme")
    if data.role not in ("viewer", "editor"):
        raise HTTPException(status_code=400, detail="Role invalide (viewer ou editor)")

    _ensure_shared_tables(db)
    now = datetime.now(timezone.utc).isoformat()
    share_id = str(uuid.uuid4())

    try:
        db.conn.execute(
            "INSERT OR REPLACE INTO shared_workspaces (id, owner_id, shared_with, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (share_id, user_id, data.target_user_id, data.role, now),
        )
        db.conn.commit()
        return {"id": share_id, "shared_with": data.target_user_id, "role": data.role}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/workspace")
async def list_shared_workspaces(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Liste les workspaces partages (donnes et recus)."""
    if not user_id:
        return {"shared_by_me": [], "shared_with_me": []}

    _ensure_shared_tables(db)

    # Partages que j'ai crees
    given = db.conn.execute(
        "SELECT id, shared_with, role, created_at FROM shared_workspaces WHERE owner_id = ?",
        (user_id,),
    ).fetchall()

    # Partages recus
    received = db.conn.execute(
        "SELECT id, owner_id, role, created_at FROM shared_workspaces WHERE shared_with = ?",
        (user_id,),
    ).fetchall()

    return {
        "shared_by_me": [{"id": r[0], "shared_with": r[1], "role": r[2], "created_at": r[3]} for r in given],
        "shared_with_me": [{"id": r[0], "owner_id": r[1], "role": r[2], "created_at": r[3]} for r in received],
    }


@router.delete("/workspace/{share_id}")
async def revoke_share(
    share_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Revoque un partage de workspace."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    _ensure_shared_tables(db)
    result = db.conn.execute(
        "DELETE FROM shared_workspaces WHERE id = ? AND owner_id = ?",
        (share_id, user_id),
    )
    db.conn.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Partage non trouve")
    return {"ok": True}


@router.get("/workspace/{owner_id}/dashboard")
async def view_shared_dashboard(
    owner_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Voir le dashboard d'un utilisateur qui a partage avec moi."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    _ensure_shared_tables(db)
    share = db.conn.execute(
        "SELECT role FROM shared_workspaces WHERE owner_id = ? AND shared_with = ?",
        (owner_id, user_id),
    ).fetchone()

    if not share:
        raise HTTPException(status_code=403, detail="Acces non autorise")

    from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
    repo = ProfilRepository(db)
    if not repo.existe(auth_user_id=owner_id):
        raise HTTPException(status_code=404, detail="Profil non trouve")

    profil = repo.charger(auth_user_id=owner_id)

    # Sous-objectifs
    sous_objectifs = []
    try:
        cursor = db.conn.execute(
            "SELECT titre, progression FROM sous_objectifs WHERE profil_id = (SELECT id FROM profil_utilisateur WHERE auth_user_id = ? LIMIT 1)",
            (owner_id,),
        )
        sous_objectifs = [{"titre": r[0], "progression": r[1]} for r in cursor.fetchall()]
    except Exception:
        pass

    return {
        "role": share[0],
        "profil": {
            "nom": profil.nom,
            "objectif": profil.objectif.description if profil.objectif else None,
            "probabilite": profil.probabilite_actuelle,
        },
        "sous_objectifs": sous_objectifs,
    }
