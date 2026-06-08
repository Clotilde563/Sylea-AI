"""
Engine SQLAlchemy unifie : SQLite (dev) ou PostgreSQL (prod).

Lecture du backend via env var DATABASE_URL. Defaut : SQLite local.

Examples:
  # Dev local SQLite
  DATABASE_URL="sqlite+aiosqlite:///./data/sylea.db"

  # Production PostgreSQL (asyncpg driver)
  DATABASE_URL="postgresql+asyncpg://sylea:secret@db.host:5432/sylea_prod"

  # Read replica (pour scale lecture, optionnel)
  DATABASE_URL_READ="postgresql+asyncpg://sylea_ro:secret@db-replica:5432/sylea_prod"

Connection pool :
  - SQLite : NullPool (chaque connection ouvre/ferme — recommande)
  - PostgreSQL : pool_size=10, max_overflow=20, recycle=3600s
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool


# ─────────────────────────────────────────────────────────────────────────────
#  Configuration
# ─────────────────────────────────────────────────────────────────────────────

def _default_db_url() -> str:
    """SQLite local par defaut, dans data/sylea.db."""
    # Trouve la racine du projet : remonter depuis api/database/
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(here, '..', '..'))
    db_path = os.path.join(project_root, 'data', 'sylea.db')
    # SQLAlchemy aiosqlite veut un path normalise avec / forward slashes
    db_path_url = db_path.replace('\\', '/')
    return f"sqlite+aiosqlite:///{db_path_url}"


DATABASE_URL: str = os.environ.get('DATABASE_URL', _default_db_url())
DATABASE_URL_READ: str | None = os.environ.get('DATABASE_URL_READ')  # optionnel

# Detection backend
is_sqlite = DATABASE_URL.startswith('sqlite')
is_postgres = DATABASE_URL.startswith('postgresql')


# ─────────────────────────────────────────────────────────────────────────────
#  Base ORM
# ─────────────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Base SQLAlchemy declarative pour tous les modeles."""
    pass


# ─────────────────────────────────────────────────────────────────────────────
#  Engine factory (singleton)
# ─────────────────────────────────────────────────────────────────────────────

_engine: AsyncEngine | None = None
_engine_read: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine(url: str, is_read_replica: bool = False) -> AsyncEngine:
    """Cree un engine SQLAlchemy async optimal selon le backend.

    SQLite : NullPool (pas de pool persistant — sqlite handle bien la
             reconnexion rapide en WAL mode).
    PG     : pool_size=10, max_overflow=20, recycle=3600s, pre_ping=True
             (verifie que la connection est vivante avant chaque check-out).
    """
    if url.startswith('sqlite'):
        engine = create_async_engine(
            url,
            poolclass=NullPool,  # sqlite ne supporte pas le pool en async
            echo=False,
            connect_args={'check_same_thread': False, 'timeout': 10.0},
        )
        # FIX P2 (2026-06) : SQLite desactive les FK par defaut a CHAQUE
        # connexion. Le PRAGMA du chemin sync (database.py) ne se propage PAS
        # aux connexions aiosqlite des sessions API → les contraintes FK
        # etaient silencieusement OFF cote async. On force le PRAGMA sur
        # chaque nouvelle connexion DBAPI via l'event "connect".
        from sqlalchemy import event as _sa_event

        @_sa_event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _rec):  # pragma: no cover (infra)
            try:
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
            except Exception:
                pass  # best-effort : ne pas casser la connexion sur un PRAGMA

        return engine
    # PostgreSQL
    return create_async_engine(
        url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,  # recycle connections apres 1h pour eviter idle timeouts
        # Pour read replicas : lecture seule, on peut etre plus agressif
        **({'pool_size': 20, 'max_overflow': 40} if is_read_replica else {}),
    )


def get_engine() -> AsyncEngine:
    """Engine principal (write + read par defaut). Singleton lazy."""
    global _engine
    if _engine is None:
        _engine = _build_engine(DATABASE_URL)
    return _engine


def get_engine_read() -> AsyncEngine:
    """Engine read replica si configure, sinon retourne l'engine principal.

    Permet de router les SELECT vers une replica pour scale lecture, tout
    en gardant les writes sur le primary. Usage type :
        async with get_session_read() as session:
            result = await session.execute(select(...))
    """
    global _engine_read
    if _engine_read is None:
        if DATABASE_URL_READ and DATABASE_URL_READ != DATABASE_URL:
            _engine_read = _build_engine(DATABASE_URL_READ, is_read_replica=True)
        else:
            _engine_read = get_engine()  # fallback : reuse primary
    return _engine_read


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Factory de sessions async lies au primary engine."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,  # garde les objets utilisables apres commit
        )
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency FastAPI : fournit une session async par requete.

    Usage :
        @app.get("/users/{user_id}")
        async def read_user(user_id: str, db: AsyncSession = Depends(get_session)):
            ...
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def dispose_engines() -> None:
    """Ferme tous les engines (shutdown handler)."""
    global _engine, _engine_read, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    if _engine_read is not None and _engine_read is not _engine:
        await _engine_read.dispose()
        _engine_read = None
    _session_factory = None
