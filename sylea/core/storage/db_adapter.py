"""
DB Adapter — Wrapper portable SQLite ↔ PostgreSQL (Migration 2026-05-15).

Permet au code legacy qui utilise `db.conn.execute(sql, params)` (style sqlite3)
de fonctionner aussi avec PostgreSQL via SQLAlchemy sync engine.

Le `RawDBProxy` mimick l'API minimale de `sqlite3.Connection` :
  - execute(sql, params) → CursorProxy avec .fetchone(), .fetchall(), .rowcount, .description
  - commit()
  - rollback()
  - close()

Conversion automatique des placeholders :
  - sqlite3 utilise `?` : `SELECT * FROM users WHERE id = ?`
  - PostgreSQL via SQLAlchemy text() utilise `:name` : `SELECT * FROM users WHERE id = :p0`
  - Le proxy detecte les `?` et les remplace par `:p0, :p1, ...` automatiquement

Usage :
    from sylea.core.storage.db_adapter import RawDBProxy
    proxy = RawDBProxy.from_url("postgresql://user:pass@host/db")
    proxy.execute("SELECT * FROM users WHERE id = ?", ("u_123",))
    row = cursor.fetchone()

Si DATABASE_URL pointe sur SQLite, on retourne le sqlite3.Connection natif
pour la perf (pas d'overhead).
"""

from __future__ import annotations

import os
import re
import threading
from typing import Any, Iterable, Optional, Sequence

import sqlite3

try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Engine, Connection
    _SQLALCHEMY_AVAILABLE = True
except ImportError:
    _SQLALCHEMY_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# Conversion `?` placeholders -> `:p0, :p1, ...` pour SQLAlchemy text()
# ─────────────────────────────────────────────────────────────────────────────

def _convert_placeholders(sql: str, params: Sequence | dict | None) -> tuple[str, dict]:
    """Convertit les `?` placeholders sqlite3 en `:p0, :p1, ...` SQLAlchemy.

    Args:
        sql: SQL avec `?` (style sqlite3) ou `:name` (style SQLAlchemy/PG)
        params: tuple/list (style positionnel) ou dict (style nomme)

    Returns:
        (sql_converted, params_dict) pour usage avec SQLAlchemy text()
    """
    if params is None:
        return sql, {}

    if isinstance(params, dict):
        # Deja en mode nomme — on retourne tel quel
        return sql, params

    # Mode positionnel : convertir `?` en `:p0, :p1, ...`
    # ATTENTION : il faut eviter de toucher les `?` dans les strings literals.
    # Simple parser : on suit les guillemets et on ne convertit que hors-string.
    out_parts: list[str] = []
    param_idx = 0
    in_single_quote = False
    in_double_quote = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        # Gestion escape (basique)
        if ch == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            out_parts.append(ch)
        elif ch == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            out_parts.append(ch)
        elif ch == '?' and not in_single_quote and not in_double_quote:
            out_parts.append(f":p{param_idx}")
            param_idx += 1
        else:
            out_parts.append(ch)
        i += 1

    converted_sql = ''.join(out_parts)
    params_dict = {f"p{i}": v for i, v in enumerate(params)}
    return converted_sql, params_dict


# ─────────────────────────────────────────────────────────────────────────────
# CursorProxy — Mimick sqlite3.Cursor avec SQLAlchemy CursorResult
# ─────────────────────────────────────────────────────────────────────────────

class CursorProxy:
    """Proxy minimal qui expose `.fetchone()`, `.fetchall()`, `.rowcount`, `.description`."""

    def __init__(self, result):
        self._result = result
        self._rows_cache: Optional[list] = None
        # Try to fetch keys/columns for `description`
        try:
            self._keys = list(result.keys()) if hasattr(result, 'keys') else []
        except Exception:
            self._keys = []

    def _ensure_rows(self):
        if self._rows_cache is None:
            try:
                self._rows_cache = list(self._result.fetchall())
            except Exception:
                self._rows_cache = []

    def fetchone(self):
        """Retourne la premiere ligne ou None."""
        # SQLAlchemy CursorResult supports fetchone directly
        try:
            row = self._result.fetchone()
            if row is None:
                return None
            # Wrap pour acces par index ET par cle (style sqlite3.Row)
            return _RowProxy(row, self._keys)
        except Exception:
            return None

    def fetchall(self):
        """Retourne toutes les lignes."""
        self._ensure_rows()
        return [_RowProxy(r, self._keys) for r in self._rows_cache]

    @property
    def rowcount(self):
        """Nombre de lignes affectees (INSERT/UPDATE/DELETE)."""
        return getattr(self._result, 'rowcount', -1)

    @property
    def lastrowid(self):
        """ID de la derniere ligne inseree (auto-increment)."""
        return getattr(self._result, 'lastrowid', None)

    @property
    def description(self):
        """Tuple (name, ...) par colonne — style sqlite3."""
        if not self._keys:
            return []
        # sqlite3 description = ((name, None, None, None, None, None, None), ...)
        return tuple((k, None, None, None, None, None, None) for k in self._keys)


class _RowProxy:
    """Mimick sqlite3.Row : acces par index ET par cle."""

    def __init__(self, row, keys):
        if isinstance(row, sqlite3.Row):
            # Already sqlite3 Row, just wrap
            self._row = row
            self._keys = list(row.keys())
        else:
            # SQLAlchemy Row
            self._row = row
            self._keys = keys or list(getattr(row, '_mapping', {}).keys())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._row[key]
        # Access by name
        if hasattr(self._row, '_mapping'):
            return self._row._mapping[key]
        # Fallback : sqlite3.Row supports str key directly
        return self._row[key]

    def __len__(self):
        return len(self._keys)

    def __iter__(self):
        if hasattr(self._row, '_mapping'):
            for k in self._keys:
                yield self._row._mapping[k]
        else:
            for v in self._row:
                yield v

    def keys(self):
        return list(self._keys)


# ─────────────────────────────────────────────────────────────────────────────
# RawDBProxy — Wrapper unifie SQLite ↔ PostgreSQL
# ─────────────────────────────────────────────────────────────────────────────

class RawDBProxy:
    """Connexion DB unifiee qui mimick sqlite3.Connection.

    En mode SQLite : on retourne directement le sqlite3.Connection (pas de wrapper, perf).
    En mode PostgreSQL : on wrap SQLAlchemy sync Connection.
    """

    def __init__(self, engine: Engine):
        if not _SQLALCHEMY_AVAILABLE:
            raise RuntimeError("SQLAlchemy required for non-SQLite connections")
        self._engine = engine
        self._conn: Optional[Connection] = None
        self._txn = None
        self._lock = threading.RLock()

    @classmethod
    def from_url(cls, url: str) -> Any:
        """Cree un proxy selon l'URL.

        - sqlite:// ou path local → retourne sqlite3.Connection direct (pas de wrap)
        - postgresql:// ou autre → retourne RawDBProxy avec SQLAlchemy
        """
        if url.startswith(("postgresql://", "postgresql+", "postgres://")):
            # Normaliser postgres:// vers postgresql:// (PG 12+ requirement SA)
            if url.startswith("postgres://"):
                url = "postgresql://" + url[len("postgres://"):]
            engine = create_engine(url, pool_pre_ping=True)
            return cls(engine)
        # SQLite : retourner sqlite3.Connection direct (pas de wrap)
        # Extraction du path
        if url.startswith("sqlite://"):
            db_path = url[len("sqlite:///"):]
        else:
            db_path = url
        conn = sqlite3.connect(
            db_path, timeout=10.0, check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_conn(self) -> Connection:
        """Assure qu'on a une connexion active (lazy)."""
        with self._lock:
            if self._conn is None or self._conn.closed:
                self._conn = self._engine.connect()
                self._txn = self._conn.begin()
            return self._conn

    def execute(self, sql: str, params: Sequence | dict | None = None):
        """Execute une requete SQL (style sqlite3, conversion auto)."""
        conn = self._ensure_conn()
        converted_sql, params_dict = _convert_placeholders(sql, params)
        try:
            result = conn.execute(text(converted_sql), params_dict)
            return CursorProxy(result)
        except Exception:
            # Rollback automatique en cas d'erreur (style sqlite3 transactionnel)
            try:
                if self._txn:
                    self._txn.rollback()
                    self._txn = None
            except Exception:
                pass
            self._conn = None
            raise

    def executemany(self, sql: str, params_list: Iterable):
        """Execute une requete plusieurs fois (batch insert)."""
        conn = self._ensure_conn()
        for params in params_list:
            converted_sql, params_dict = _convert_placeholders(sql, params)
            conn.execute(text(converted_sql), params_dict)

    def commit(self):
        """Commit la transaction courante."""
        with self._lock:
            if self._txn:
                try:
                    self._txn.commit()
                except Exception:
                    pass
                self._txn = None
            if self._conn and not self._conn.closed:
                try:
                    self._conn.close()
                except Exception:
                    pass
            self._conn = None

    def rollback(self):
        """Rollback la transaction courante."""
        with self._lock:
            if self._txn:
                try:
                    self._txn.rollback()
                except Exception:
                    pass
                self._txn = None
            if self._conn and not self._conn.closed:
                try:
                    self._conn.close()
                except Exception:
                    pass
            self._conn = None

    def close(self):
        """Ferme la connexion (alias rollback + dispose engine)."""
        self.rollback()

    def __enter__(self):
        self._ensure_conn()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()


def is_postgres_url(url: str | None) -> bool:
    """Detecte si DATABASE_URL pointe sur PostgreSQL."""
    if not url:
        return False
    return url.startswith(("postgresql://", "postgresql+", "postgres://"))


def get_database_url() -> str:
    """Retourne DATABASE_URL ou fallback SQLite local."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    # Fallback : SQLite local path
    from sylea.config.settings import get_database_path
    return f"sqlite:///{get_database_path()}"


__all__ = [
    "RawDBProxy",
    "CursorProxy",
    "is_postgres_url",
    "get_database_url",
    "_convert_placeholders",  # exposed for tests
]
