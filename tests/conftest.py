"""Conftest racine — options, markers globaux pytest, et helpers DB partages.

Le marker `e2e` et le flag `--no-e2e` sont définis ici pour être disponibles
sur l'ensemble du test suite (pas seulement dans tests/e2e/).

Helpers DB partages (migration PG 2026-05-13) :
  - `make_shared_db(tmp_path, monkeypatch)` : retourne un DatabaseManager backed
    par un fichier SQLite temp, AVEC le `api.database.engine` monkey-patche pour
    pointer sur la meme DB (async session_factory). Permet aux tests legacy
    qui utilisaient `:memory:` de passer sans modification importante.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Désactivation par défaut des middlewares de sécurité dans les tests.
# Chaque module de test ciblé (test_csrf_middleware, test_ip_rate_limiter,
# test_security_headers) override ces flags via monkeypatch dans ses fixtures.
# Sans ça, les tests legacy qui appellent POST sans token CSRF échouent en 403.
#
# Doit être appliqué AVANT que `api.main` ne soit importé par un test, donc
# au top-level du conftest (importé en premier par pytest).
# ─────────────────────────────────────────────────────────────────────────────
os.environ.setdefault("SYLEA_DISABLE_CSRF", "true")
os.environ.setdefault("SYLEA_DISABLE_IP_RATELIMIT", "true")
os.environ.setdefault("SYLEA_DISABLE_SECURITY_HEADERS", "true")
# Tests E2E des dilemmes en mode tracking : sans ce flag, les tests doivent
# attendre J+30 entre chaque /respond. Override permet de tester la chaine
# complete en quelques secondes.
os.environ.setdefault("SYLEA_TRACKING_BYPASS_TIME", "true")


def pytest_configure(config):
    """Enregistre les markers custom."""
    config.addinivalue_line(
        "markers",
        "e2e: Tests end-to-end qui lancent un mock Gateway local "
        "(skip avec --no-e2e pour executions rapides).",
    )


def pytest_addoption(parser):
    parser.addoption(
        "--no-e2e",
        action="store_true",
        default=False,
        help="Skip tests marked as e2e (utile en CI sans reseau ou pour dev rapide).",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--no-e2e"):
        skip_e2e = pytest.mark.skip(reason="--no-e2e flag passe")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_e2e)


# ═══════════════════════════════════════════════════════════════════════════
#  Shared DB helpers (migration PG 2026-05-13)
# ═══════════════════════════════════════════════════════════════════════════

def make_shared_db(tmp_path, monkeypatch) -> Any:
    """Cree une DB SQLite temp + monkeypatch `api.database.engine` pour
    qu'async session_factory et sync DatabaseManager partagent le meme fichier.

    Le caller doit appeler `_dispose_shared_db()` au teardown (ou utiliser
    la fixture `shared_db` qui s'en occupe automatiquement).
    """
    from sylea.core.storage.database import DatabaseManager

    db_path = tmp_path / "test_sylea.db"
    db_path_str = str(db_path).replace("\\", "/")

    db = DatabaseManager(db_path)
    db._conn = sqlite3.connect(str(db_path), check_same_thread=False)
    db._conn.row_factory = sqlite3.Row
    db._conn.execute("PRAGMA journal_mode=WAL;")
    db._conn.execute("PRAGMA foreign_keys=ON;")
    db._initialiser_schema()

    # Reconfigure async engine pour pointer sur le meme fichier
    import api.database.engine as engine_module
    new_url = f"sqlite+aiosqlite:///{db_path_str}"
    monkeypatch.setattr(engine_module, "DATABASE_URL", new_url)
    monkeypatch.setattr(engine_module, "is_sqlite", True)
    monkeypatch.setattr(engine_module, "is_postgres", False)
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(engine_module, "_engine_read", None)
    monkeypatch.setattr(engine_module, "_session_factory", None)

    return db


def dispose_shared_db(db) -> None:
    """Nettoie : dispose async engine + ferme connection sync.

    Important : `asyncio.run()` cree puis ferme un event loop, ce qui peut
    laisser le thread sans loop pour les tests suivants qui appellent
    `asyncio.get_event_loop().run_until_complete(...)`. Apres dispose on
    reinstalle donc un nouveau loop dans le thread courant.
    """
    try:
        from api.database.engine import dispose_engines
        asyncio.run(dispose_engines())
    except Exception:
        pass
    try:
        db._conn.close()
    except Exception:
        pass
    # Reinstalle un event loop frais pour ne pas casser les tests suivants
    # qui s'appuient sur `asyncio.get_event_loop()`.
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


@pytest.fixture()
def shared_db(tmp_path, monkeypatch):
    """Fixture pytest : DB SQLite temp partagee entre sync + async.

    Usage type :
        def test_foo(shared_db):
            db = shared_db
            # db.conn.execute(...) marche en sync
            # get_session_factory() pointe sur la meme DB
    """
    db = make_shared_db(tmp_path, monkeypatch)
    yield db
    dispose_shared_db(db)
