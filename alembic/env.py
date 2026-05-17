"""
Alembic environment script — utilise DATABASE_URL et notre Base SQLAlchemy.

Usage :
  alembic revision --autogenerate -m "description"   # genere une migration
  alembic upgrade head                               # applique
  alembic downgrade -1                               # rollback
  alembic history --verbose                          # historique
"""

from logging.config import fileConfig
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# Permettre d'importer notre code applicatif
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '..'))
sys.path.insert(0, _ROOT)

# Charger Base + tous les modeles pour qu'autogenerate les detecte
from api.database.engine import Base, DATABASE_URL  # noqa: E402
import api.database.models  # noqa: F401, E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _to_sync_url(url: str) -> str:
    """Alembic ne supporte pas les drivers async. On convertit :
        sqlite+aiosqlite://    → sqlite://
        postgresql+asyncpg://  → postgresql+psycopg2://
    Le user doit `pip install psycopg2-binary` pour PostgreSQL avec Alembic.
    """
    if url.startswith('sqlite+aiosqlite'):
        return url.replace('sqlite+aiosqlite', 'sqlite', 1)
    if url.startswith('postgresql+asyncpg'):
        return url.replace('postgresql+asyncpg', 'postgresql+psycopg2', 1)
    return url


sync_url = _to_sync_url(DATABASE_URL)
config.set_main_option('sqlalchemy.url', sync_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Mode offline : genere du SQL sans se connecter a la DB."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Mode online : applique les migrations a la DB live."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
