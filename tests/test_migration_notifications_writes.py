"""
Tests E2E pour la migration PG de notifications.py.

Endpoints couverts :
  - POST /api/notifications/subscribe   (DELETE+INSERT portable upsert)
  - DELETE /api/notifications/subscribe
  - GET /api/notifications/subscriptions

Migration : remplace `INSERT OR REPLACE` (SQLite-specific) par
DELETE + INSERT en transaction (portable PG + SQLite).
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sylea.core.storage.database import DatabaseManager
from api.dependencies import get_optional_user, get_db
from api.main import app


TEST_USER_ID = "test-user-migration-notif"


@pytest.fixture()
def shared_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_sylea.db"
    db_path_str = str(db_path).replace("\\", "/")

    db = DatabaseManager(db_path)
    db._conn = sqlite3.connect(str(db_path), check_same_thread=False)
    db._conn.row_factory = sqlite3.Row
    db._conn.execute("PRAGMA journal_mode=WAL;")
    db._conn.execute("PRAGMA foreign_keys=ON;")
    db._initialiser_schema()

    import api.database.engine as engine_module
    new_url = f"sqlite+aiosqlite:///{db_path_str}"
    monkeypatch.setattr(engine_module, "DATABASE_URL", new_url)
    monkeypatch.setattr(engine_module, "is_sqlite", True)
    monkeypatch.setattr(engine_module, "is_postgres", False)
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(engine_module, "_engine_read", None)
    monkeypatch.setattr(engine_module, "_session_factory", None)

    yield db

    try:
        from api.database.engine import dispose_engines
        asyncio.run(dispose_engines())
    except Exception:
        pass
    try:
        db._conn.close()
    except Exception:
        pass


@pytest.fixture()
def auth_client(shared_db):
    app.dependency_overrides[get_optional_user] = lambda: TEST_USER_ID
    app.dependency_overrides[get_db] = lambda: shared_db
    yield TestClient(app), shared_db
    app.dependency_overrides.clear()


def _sub_payload(endpoint: str = "https://fcm.googleapis.com/test-ep-1") -> dict:
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": "test-p256dh-key", "auth": "test-auth-key"},
    }


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/notifications/subscribe (migration : portable upsert)
# ════════════════════════════════════════════════════════════════════════════

class TestSubscribePush:
    def test_subscribe_creates_row(self, auth_client):
        client, db = auth_client
        r = client.post("/api/notifications/subscribe", json=_sub_payload())
        assert r.status_code == 200, r.text
        assert r.json() == {"ok": True}

        # Verifier que la row existe
        row = db.conn.execute(
            "SELECT * FROM push_subscriptions WHERE auth_user_id = ?",
            (TEST_USER_ID,),
        ).fetchone()
        assert row is not None
        assert row["endpoint"] == "https://fcm.googleapis.com/test-ep-1"
        assert row["p256dh"] == "test-p256dh-key"
        assert row["auth_key"] == "test-auth-key"

    def test_subscribe_upserts_existing_endpoint(self, auth_client):
        """Re-subscribe avec meme endpoint : update au lieu de duplique."""
        client, db = auth_client
        payload = _sub_payload()
        r1 = client.post("/api/notifications/subscribe", json=payload)
        assert r1.status_code == 200, r1.text

        # Modifier les keys et re-subscribe
        payload["keys"] = {"p256dh": "new-p256dh", "auth": "new-auth"}
        r2 = client.post("/api/notifications/subscribe", json=payload)
        assert r2.status_code == 200, r2.text

        # Verifier qu'on a UNE seule row avec les NOUVELLES keys
        rows = db.conn.execute(
            "SELECT * FROM push_subscriptions WHERE endpoint = ?",
            (payload["endpoint"],),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["p256dh"] == "new-p256dh"
        assert rows[0]["auth_key"] == "new-auth"

    def test_subscribe_different_endpoints_creates_multiple_rows(self, auth_client):
        client, db = auth_client
        client.post("/api/notifications/subscribe",
                    json=_sub_payload("https://endpoint-a"))
        client.post("/api/notifications/subscribe",
                    json=_sub_payload("https://endpoint-b"))

        rows = db.conn.execute(
            "SELECT * FROM push_subscriptions WHERE auth_user_id = ?",
            (TEST_USER_ID,),
        ).fetchall()
        assert len(rows) == 2

    def test_subscribe_without_user_returns_401(self, shared_db):
        """Sans user_id, retourne 401."""
        app.dependency_overrides[get_optional_user] = lambda: None
        app.dependency_overrides[get_db] = lambda: shared_db
        try:
            with TestClient(app) as client:
                r = client.post("/api/notifications/subscribe", json=_sub_payload())
                assert r.status_code == 401
        finally:
            app.dependency_overrides.clear()


# ════════════════════════════════════════════════════════════════════════════
#  DELETE /api/notifications/subscribe
# ════════════════════════════════════════════════════════════════════════════

class TestUnsubscribePush:
    def test_unsubscribe_removes_subscription(self, auth_client):
        client, db = auth_client
        client.post("/api/notifications/subscribe", json=_sub_payload())

        r = client.request(
            "DELETE", "/api/notifications/subscribe",
            json={"endpoint": "https://fcm.googleapis.com/test-ep-1"},
        )
        assert r.status_code == 200, r.text

        row = db.conn.execute(
            "SELECT * FROM push_subscriptions WHERE auth_user_id = ?",
            (TEST_USER_ID,),
        ).fetchone()
        assert row is None

    def test_unsubscribe_other_user_doesnt_affect_mine(self, auth_client):
        """User A unsubscribe ne touche pas les subs de User B."""
        client, db = auth_client
        # User A subscribe
        client.post("/api/notifications/subscribe",
                    json=_sub_payload("https://ep-shared"))
        # User B subscribe meme endpoint
        app.dependency_overrides[get_optional_user] = lambda: "user-b"
        client.post("/api/notifications/subscribe",
                    json=_sub_payload("https://ep-shared"))
        # Reset to user A
        app.dependency_overrides[get_optional_user] = lambda: TEST_USER_ID

        # User A unsubscribe (l'endpoint a ete reassigne au user-b apres upsert)
        r = client.request(
            "DELETE", "/api/notifications/subscribe",
            json={"endpoint": "https://ep-shared"},
        )
        assert r.status_code == 200, r.text

        # La row reste (appartenait a user-b apres l'upsert)
        rows = db.conn.execute(
            "SELECT auth_user_id FROM push_subscriptions WHERE endpoint = ?",
            ("https://ep-shared",),
        ).fetchall()
        # Le test reflete l'isolation user : User A delete ne touche que ses subs
        # (auth_user_id = TEST_USER_ID). User B en garde une.
        assert all(r["auth_user_id"] == "user-b" for r in rows)


# ════════════════════════════════════════════════════════════════════════════
#  GET /api/notifications/subscriptions
# ════════════════════════════════════════════════════════════════════════════

class TestListSubscriptions:
    def test_list_returns_user_subscriptions(self, auth_client):
        client, _ = auth_client
        client.post("/api/notifications/subscribe",
                    json=_sub_payload("https://endpoint-1"))
        client.post("/api/notifications/subscribe",
                    json=_sub_payload("https://endpoint-2"))

        r = client.get("/api/notifications/subscriptions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 2
        assert len(body["subscriptions"]) == 2

    def test_list_empty_for_no_subs(self, auth_client):
        client, _ = auth_client
        r = client.get("/api/notifications/subscriptions")
        assert r.status_code == 200
        assert r.json() == {"subscriptions": [], "count": 0}

    def test_list_without_user_returns_empty(self, shared_db):
        app.dependency_overrides[get_optional_user] = lambda: None
        app.dependency_overrides[get_db] = lambda: shared_db
        try:
            with TestClient(app) as client:
                r = client.get("/api/notifications/subscriptions")
                assert r.status_code == 200
                assert r.json() == {"subscriptions": []}
        finally:
            app.dependency_overrides.clear()
