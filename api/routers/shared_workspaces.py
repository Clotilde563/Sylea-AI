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
    """Partage la vue du dashboard avec un autre utilisateur.

    Migration PG (2026-05-13) : DELETE+INSERT portable (au lieu de
    `INSERT OR REPLACE` SQLite-specific).
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")
    if data.target_user_id == user_id:
        raise HTTPException(status_code=400, detail="Impossible de partager avec soi-meme")
    if data.role not in ("viewer", "editor"):
        raise HTTPException(status_code=400, detail="Role invalide (viewer ou editor)")

    _ensure_shared_tables(db)
    now = datetime.now(timezone.utc).isoformat()
    share_id = str(uuid.uuid4())

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            # Upsert portable : DELETE existing (UNIQUE constraint) + INSERT
            await session.execute(
                text(
                    "DELETE FROM shared_workspaces "
                    "WHERE owner_id = :owner AND shared_with = :target"
                ),
                {"owner": user_id, "target": data.target_user_id},
            )
            await session.execute(
                text(
                    "INSERT INTO shared_workspaces "
                    "(id, owner_id, shared_with, role, created_at) "
                    "VALUES (:id, :owner, :target, :role, :now)"
                ),
                {
                    "id": share_id, "owner": user_id,
                    "target": data.target_user_id,
                    "role": data.role, "now": now,
                },
            )
            await session.commit()
            return {"id": share_id, "shared_with": data.target_user_id, "role": data.role}
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/workspace")
async def list_shared_workspaces(
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Liste les workspaces partages (donnes et recus).

    Migration PG (2026-05-13) : SELECTs via SQLAlchemy text() async.
    """
    if not user_id:
        return {"shared_by_me": [], "shared_with_me": []}

    _ensure_shared_tables(db)

    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        # Partages que j'ai crees
        result = await session.execute(
            text(
                "SELECT id, shared_with, role, created_at FROM shared_workspaces "
                "WHERE owner_id = :uid"
            ),
            {"uid": user_id},
        )
        given = result.mappings().all()
        # Partages recus
        result = await session.execute(
            text(
                "SELECT id, owner_id, role, created_at FROM shared_workspaces "
                "WHERE shared_with = :uid"
            ),
            {"uid": user_id},
        )
        received = result.mappings().all()

    return {
        "shared_by_me": [
            {"id": r["id"], "shared_with": r["shared_with"],
             "role": r["role"], "created_at": r["created_at"]}
            for r in given
        ],
        "shared_with_me": [
            {"id": r["id"], "owner_id": r["owner_id"],
             "role": r["role"], "created_at": r["created_at"]}
            for r in received
        ],
    }


@router.delete("/workspace/{share_id}")
async def revoke_share(
    share_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Revoque un partage de workspace.

    Migration PG (2026-05-13) : DELETE via SQLAlchemy text() async.
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    _ensure_shared_tables(db)
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await session.execute(
                text(
                    "DELETE FROM shared_workspaces "
                    "WHERE id = :sid AND owner_id = :uid"
                ),
                {"sid": share_id, "uid": user_id},
            )
            rowcount = result.rowcount or 0
            await session.commit()
        except Exception:
            await session.rollback()
            raise
    if rowcount == 0:
        raise HTTPException(status_code=404, detail="Partage non trouve")
    return {"ok": True}


@router.get("/workspace/{owner_id}/dashboard")
async def view_shared_dashboard(
    owner_id: str,
    db: DatabaseManager = Depends(get_db),
    user_id: str | None = Depends(get_optional_user),
):
    """Voir le dashboard d'un utilisateur qui a partage avec moi.

    Migration PG (2026-05-13) : SELECTs via SQLAlchemy text() async.
    """
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentification requise")

    _ensure_shared_tables(db)
    from sqlalchemy import text
    from api.database import get_session_factory
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            text(
                "SELECT role FROM shared_workspaces "
                "WHERE owner_id = :owner AND shared_with = :uid"
            ),
            {"owner": owner_id, "uid": user_id},
        )
        share = result.first()

    if not share:
        raise HTTPException(status_code=403, detail="Acces non autorise")

    from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
    repo = ProfilRepository(db)
    if not repo.existe(auth_user_id=owner_id):
        raise HTTPException(status_code=404, detail="Profil non trouve")

    profil = repo.charger(auth_user_id=owner_id)

    # Sous-objectifs (async)
    sous_objectifs = []
    try:
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT titre, progression FROM sous_objectifs "
                    "WHERE user_id = (SELECT id FROM profil_utilisateur "
                    "WHERE auth_user_id = :uid LIMIT 1)"
                ),
                {"uid": owner_id},
            )
            sous_objectifs = [
                {"titre": r["titre"], "progression": r["progression"]}
                for r in result.mappings().all()
            ]
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
