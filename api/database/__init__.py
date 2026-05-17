"""
Package api.database — couche d'abstraction SQLAlchemy.

Permet de switcher entre SQLite (dev) et PostgreSQL (prod) via la variable
d'environnement DATABASE_URL :
  - sqlite+aiosqlite:///./data/sylea.db        (default, dev)
  - postgresql+asyncpg://user:pass@host/db     (prod)

Pas encore utilise par les routers existants — sera adopte progressivement
lors de la migration. Cf. docs/MIGRATION_POSTGRESQL.md pour le plan.
"""

from api.database.engine import (
    get_engine,
    get_session_factory,
    get_session,
    Base,
    DATABASE_URL,
    is_postgres,
    is_sqlite,
)

__all__ = [
    'get_engine',
    'get_session_factory',
    'get_session',
    'Base',
    'DATABASE_URL',
    'is_postgres',
    'is_sqlite',
]
