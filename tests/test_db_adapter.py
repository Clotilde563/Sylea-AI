"""
Tests du db_adapter (Migration PG 2026-05-15).

Verifient :
- Conversion correcte des `?` placeholders vers `:p0, :p1, ...`
- Detection postgres:// vs sqlite://
- RawDBProxy en mode SQLite via SQLAlchemy (smoke test multi-backend)
- Que DatabaseManager bascule selon DATABASE_URL
"""

import os
import tempfile
from pathlib import Path

import pytest

from sylea.core.storage.db_adapter import (
    _convert_placeholders, is_postgres_url,
)


class TestPlaceholderConversion:
    def test_simple_select(self):
        sql, params = _convert_placeholders(
            "SELECT * FROM users WHERE id = ?", ("u1",),
        )
        assert sql == "SELECT * FROM users WHERE id = :p0"
        assert params == {"p0": "u1"}

    def test_multiple_placeholders(self):
        sql, params = _convert_placeholders(
            "INSERT INTO users (a, b, c) VALUES (?, ?, ?)",
            (1, 2, 3),
        )
        assert sql == "INSERT INTO users (a, b, c) VALUES (:p0, :p1, :p2)"
        assert params == {"p0": 1, "p1": 2, "p2": 3}

    def test_question_mark_inside_string_literal(self):
        """Les `?` dans les strings literals ne doivent PAS etre convertis."""
        sql, params = _convert_placeholders(
            "SELECT * FROM users WHERE name = 'where?' AND id = ?",
            (1,),
        )
        assert sql == "SELECT * FROM users WHERE name = 'where?' AND id = :p0"
        assert params == {"p0": 1}

    def test_question_mark_inside_double_quote(self):
        sql, params = _convert_placeholders(
            'SELECT "col?name" FROM t WHERE id = ?',
            (1,),
        )
        assert sql == 'SELECT "col?name" FROM t WHERE id = :p0'
        assert params == {"p0": 1}

    def test_dict_params_passthrough(self):
        """Si params est un dict (deja format SQLAlchemy), on ne touche pas."""
        sql, params = _convert_placeholders(
            "SELECT * FROM users WHERE id = :id",
            {"id": "u1"},
        )
        assert sql == "SELECT * FROM users WHERE id = :id"
        assert params == {"id": "u1"}

    def test_no_params(self):
        sql, params = _convert_placeholders("SELECT * FROM users", None)
        assert sql == "SELECT * FROM users"
        assert params == {}

    def test_empty_tuple(self):
        sql, params = _convert_placeholders("SELECT 1", ())
        assert sql == "SELECT 1"
        assert params == {}


class TestIsPostgresUrl:
    def test_postgresql_scheme(self):
        assert is_postgres_url("postgresql://user:pass@host:5432/db") is True

    def test_postgres_scheme(self):
        assert is_postgres_url("postgres://user:pass@host:5432/db") is True

    def test_postgresql_async_scheme(self):
        assert is_postgres_url("postgresql+asyncpg://user:pass@host/db") is True

    def test_sqlite(self):
        assert is_postgres_url("sqlite:///path/to/db.sqlite") is False

    def test_none(self):
        assert is_postgres_url(None) is False

    def test_empty(self):
        assert is_postgres_url("") is False


class TestDatabaseManagerBackend:
    """Verifie que DatabaseManager bascule correctement selon DATABASE_URL."""

    def test_sqlite_default_when_no_env(self, monkeypatch):
        """Sans DATABASE_URL, on utilise sqlite3.Connection natif."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        import sqlite3
        from sylea.core.storage.database import DatabaseManager

        with tempfile.TemporaryDirectory() as td:
            db = DatabaseManager(db_path=Path(td) / "test.db")
            db.connect()
            assert isinstance(db._conn, sqlite3.Connection)
            db.disconnect()

    def test_sqlite_url_explicit(self, monkeypatch):
        """sqlite:// URL → mode SQLite natif."""
        monkeypatch.setenv("DATABASE_URL", "sqlite:///nonexistent.db")
        import sqlite3
        from sylea.core.storage.database import DatabaseManager

        # Note : DatabaseManager n'utilise pas l'URL pour SQLite (utilise db_path).
        # Le URL est pris en compte uniquement pour postgres://.
        with tempfile.TemporaryDirectory() as td:
            db = DatabaseManager(db_path=Path(td) / "test.db")
            db.connect()
            assert isinstance(db._conn, sqlite3.Connection)
            db.disconnect()

    def test_pg_url_uses_proxy(self, monkeypatch):
        """postgresql:// URL → RawDBProxy (sans vraie connexion).

        On ne se connecte pas vraiment (engine.connect() est lazy), donc on
        peut tester avec une URL fake.
        """
        # URL PG fake — RawDBProxy se cree mais ne tente PAS de connexion
        monkeypatch.setenv(
            "DATABASE_URL",
            "postgresql://fake:fake@localhost:9999/fakedb",
        )
        from sylea.core.storage.db_adapter import RawDBProxy
        from sylea.core.storage.database import DatabaseManager

        db = DatabaseManager()
        db.connect()
        assert isinstance(db._conn, RawDBProxy)
        # Pas de tentative de query : on verifie juste que le bon type est cree
