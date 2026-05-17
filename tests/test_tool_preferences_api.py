"""
Tests des endpoints de gestion des preferences tool utilisateur (Phase 3).

Couvre :
  GET    /api/agent3/tools                      -> liste + groupes + statuts
  POST   /api/agent3/tools/{tool_name}/toggle   -> toggle on/off
  DELETE /api/agent3/tools/{tool_name}/override -> supprime override
  POST   /api/agent3/tools/bulk-toggle          -> toggle en masse

Verifie :
  - l'auth est requise pour modifier (401 sans user)
  - GET fonctionne aussi sans auth (lecture anonyme de la liste)
  - la regle d'effectivite (user=False -> disabled, sinon profile gagne)
  - la persistence en DB (user_tool_preferences)
  - la validation des noms de tools (404 si inconnu)
  - bulk-toggle : skip les tools invalides, ne casse pas sur dict vide
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.dependencies import get_db, get_agent, get_optional_user
from sylea.core.storage.database import DatabaseManager
from tests.conftest import make_shared_db, dispose_shared_db


TEST_USER_ID = "test-user-tools"


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """DB SQLite partagee (sync + async) via fichier temp.
    Migration shared-DB : remplace `:memory:` pour que les writes async via
    SQLAlchemy session_factory pointent sur la meme DB que la conn sync."""
    manager = make_shared_db(tmp_path, monkeypatch)
    manager._conn.execute(
        "INSERT INTO users (id, email, hashed_password, provider, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (TEST_USER_ID, "tools@test.com", "fake_hash", "local"),
    )
    manager._conn.commit()
    yield manager
    dispose_shared_db(manager)


@pytest.fixture()
def client_authed(db):
    """TestClient avec user authentifie."""
    async def _get_db():
        yield db

    def _get_agent():
        return None

    async def _get_user():
        return TEST_USER_ID

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_agent] = _get_agent
    app.dependency_overrides[get_optional_user] = _get_user

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture()
def client_anon(db):
    """TestClient sans user (None)."""
    async def _get_db():
        yield db

    def _get_agent():
        return None

    async def _get_user():
        return None

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_agent] = _get_agent
    app.dependency_overrides[get_optional_user] = _get_user

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/agent3/tools
# ══════════════════════════════════════════════════════════════════════════════


class TestListTools:
    def test_returns_38_tools(self, client_authed):
        resp = client_authed.get("/api/agent3/tools")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_tools"] == 38
        assert len(body["tools"]) == 38

    def test_groups_structure(self, client_authed):
        resp = client_authed.get("/api/agent3/tools")
        body = resp.json()
        # Les 11 groupes doivent etre presents
        expected_groups = {
            "web", "ui", "runtime", "fs", "sessions", "memory",
            "automation", "messaging", "media", "safety", "special",
        }
        assert set(body["groups"].keys()) == expected_groups

    def test_each_tool_has_status_fields(self, client_authed):
        resp = client_authed.get("/api/agent3/tools")
        body = resp.json()
        for tool in body["tools"]:
            assert "name" in tool
            assert "group" in tool
            assert "description" in tool
            assert "enabled_profile" in tool
            assert "enabled_user" in tool
            assert "effectively_enabled" in tool

    def test_no_overrides_initially(self, client_authed):
        resp = client_authed.get("/api/agent3/tools")
        body = resp.json()
        assert body["has_user_overrides"] is False
        # Tous les enabled_user doivent etre None
        for tool in body["tools"]:
            assert tool["enabled_user"] is None

    def test_anonymous_can_read_tools(self, client_anon):
        """GET fonctionne meme sans auth, juste sans overrides user."""
        resp = client_anon.get("/api/agent3/tools")
        assert resp.status_code == 200
        body = resp.json()
        assert body["has_user_overrides"] is False


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/agent3/tools/{tool_name}/toggle
# ══════════════════════════════════════════════════════════════════════════════


class TestToggleTool:
    def test_toggle_enable(self, client_authed):
        resp = client_authed.post(
            "/api/agent3/tools/web_search/toggle",
            json={"enabled": True},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["tool"] == "web_search"
        assert body["enabled_user"] is True

    def test_toggle_disable(self, client_authed):
        resp = client_authed.post(
            "/api/agent3/tools/web_search/toggle",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["enabled_user"] is False
        # effectively_enabled devient False car user a explicitement coupe
        assert body["effectively_enabled"] is False

    def test_toggle_unknown_tool_returns_404(self, client_authed):
        resp = client_authed.post(
            "/api/agent3/tools/does_not_exist/toggle",
            json={"enabled": True},
        )
        assert resp.status_code == 404

    def test_toggle_requires_auth(self, client_anon):
        resp = client_anon.post(
            "/api/agent3/tools/web_search/toggle",
            json={"enabled": True},
        )
        assert resp.status_code == 401

    def test_toggle_persisted_in_db(self, client_authed, db):
        """Apres toggle, l'override est bien enregistree en DB."""
        client_authed.post(
            "/api/agent3/tools/firecrawl/toggle",
            json={"enabled": False},
        )
        row = db.conn.execute(
            "SELECT enabled FROM user_tool_preferences WHERE user_id = ? AND tool_name = ?",
            (TEST_USER_ID, "firecrawl"),
        ).fetchone()
        assert row is not None
        assert row["enabled"] == 0

    def test_toggle_visible_in_subsequent_get(self, client_authed):
        """Apres toggle, le GET renvoie le nouvel etat."""
        client_authed.post(
            "/api/agent3/tools/pii_scrub/toggle",
            json={"enabled": False},
        )
        resp = client_authed.get("/api/agent3/tools")
        body = resp.json()
        tool = next(t for t in body["tools"] if t["name"] == "pii_scrub")
        assert tool["enabled_user"] is False
        assert tool["effectively_enabled"] is False
        assert body["has_user_overrides"] is True

    def test_toggle_upsert_overrides_previous(self, client_authed, db):
        """Deux toggles successifs : le second ecrase le premier."""
        client_authed.post("/api/agent3/tools/brave_search/toggle", json={"enabled": True})
        client_authed.post("/api/agent3/tools/brave_search/toggle", json={"enabled": False})

        rows = db.conn.execute(
            "SELECT COUNT(*) AS n FROM user_tool_preferences WHERE user_id = ? AND tool_name = ?",
            (TEST_USER_ID, "brave_search"),
        ).fetchone()
        # Un seul row grace au UPSERT (PRIMARY KEY user_id+tool_name)
        assert rows["n"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# DELETE /api/agent3/tools/{tool_name}/override
# ══════════════════════════════════════════════════════════════════════════════


class TestClearOverride:
    def test_clear_existing_override(self, client_authed, db):
        # Poser un override
        client_authed.post(
            "/api/agent3/tools/exa_search/toggle",
            json={"enabled": False},
        )
        # Le supprimer
        resp = client_authed.delete("/api/agent3/tools/exa_search/override")
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["override_cleared"] is True

        # Verifier en DB : la ligne n'existe plus
        row = db.conn.execute(
            "SELECT * FROM user_tool_preferences WHERE user_id = ? AND tool_name = ?",
            (TEST_USER_ID, "exa_search"),
        ).fetchone()
        assert row is None

    def test_clear_non_existing_override_is_idempotent(self, client_authed):
        # Pas d'erreur si pas d'override : on doit retourner 200 quand meme
        resp = client_authed.delete("/api/agent3/tools/tavily_search/override")
        assert resp.status_code == 200

    def test_clear_requires_auth(self, client_anon):
        resp = client_anon.delete("/api/agent3/tools/web_search/override")
        assert resp.status_code == 401

    def test_clear_restores_profile_default(self, client_authed):
        """Apres clear, le tool revient au reglage profile (enabled_user=None)."""
        client_authed.post(
            "/api/agent3/tools/google_search/toggle",
            json={"enabled": False},
        )
        client_authed.delete("/api/agent3/tools/google_search/override")

        resp = client_authed.get("/api/agent3/tools")
        body = resp.json()
        tool = next(t for t in body["tools"] if t["name"] == "google_search")
        assert tool["enabled_user"] is None


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/agent3/tools/bulk-toggle
# ══════════════════════════════════════════════════════════════════════════════


class TestBulkToggle:
    def test_bulk_multiple_tools(self, client_authed):
        resp = client_authed.post(
            "/api/agent3/tools/bulk-toggle",
            json={"preferences": {
                "web_search": False,
                "firecrawl": True,
                "perplexity_search": False,
            }},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["updated_count"] == 3
        assert set(body["updated"]) == {"web_search", "firecrawl", "perplexity_search"}

    def test_bulk_skips_invalid_tools(self, client_authed):
        resp = client_authed.post(
            "/api/agent3/tools/bulk-toggle",
            json={"preferences": {
                "web_search": True,
                "fake_tool_xxx": True,
                "exa_search": False,
            }},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["updated_count"] == 2
        assert "fake_tool_xxx" in body["skipped"]
        assert set(body["updated"]) == {"web_search", "exa_search"}

    def test_bulk_empty_preferences(self, client_authed):
        resp = client_authed.post(
            "/api/agent3/tools/bulk-toggle",
            json={"preferences": {}},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["updated_count"] == 0

    def test_bulk_invalid_preferences_type(self, client_authed):
        resp = client_authed.post(
            "/api/agent3/tools/bulk-toggle",
            json={"preferences": "not-a-dict"},
        )
        assert resp.status_code == 400

    def test_bulk_requires_auth(self, client_anon):
        resp = client_anon.post(
            "/api/agent3/tools/bulk-toggle",
            json={"preferences": {"web_search": True}},
        )
        assert resp.status_code == 401

    def test_bulk_persisted_in_db(self, client_authed, db):
        client_authed.post(
            "/api/agent3/tools/bulk-toggle",
            json={"preferences": {
                "content_moderation": False,
                "url_safety_check": True,
                "pii_scrub": False,
            }},
        )
        rows = db.conn.execute(
            "SELECT tool_name, enabled FROM user_tool_preferences WHERE user_id = ?",
            (TEST_USER_ID,),
        ).fetchall()
        prefs = {r["tool_name"]: bool(r["enabled"]) for r in rows}
        assert prefs == {
            "content_moderation": False,
            "url_safety_check": True,
            "pii_scrub": False,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Integration : scenario complet utilisateur
# ══════════════════════════════════════════════════════════════════════════════


class TestIntegrationScenario:
    def test_user_disables_sensitive_tools_then_resets(self, client_authed):
        """
        Scenario : l'utilisateur desactive les tools sensibles, verifie
        que l'etat est persiste, puis reset pour revenir au profil.
        """
        # 1. Desactiver en masse
        resp = client_authed.post(
            "/api/agent3/tools/bulk-toggle",
            json={"preferences": {
                "exec": False,
                "bash": False,
                "process": False,
                "write": False,
            }},
        )
        assert resp.status_code == 200
        assert resp.json()["updated_count"] == 4

        # 2. Verifier via GET
        body = client_authed.get("/api/agent3/tools").json()
        for tool in body["tools"]:
            if tool["name"] in ("exec", "bash", "process", "write"):
                assert tool["enabled_user"] is False
                assert tool["effectively_enabled"] is False
        assert body["has_user_overrides"] is True

        # 3. Reset un a un
        for name in ("exec", "bash", "process", "write"):
            resp = client_authed.delete(f"/api/agent3/tools/{name}/override")
            assert resp.status_code == 200

        # 4. Plus aucun override
        body = client_authed.get("/api/agent3/tools").json()
        assert body["has_user_overrides"] is False

    def test_user_preferences_isolated(self, client_authed, db):
        """Les preferences d'un user ne debordent pas sur un autre user."""
        # Creer un second user
        db.conn.execute(
            "INSERT INTO users (id, email, hashed_password, provider, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            ("other-user", "other@test.com", "fake_hash", "local"),
        )
        db.conn.commit()

        # User courant toggle
        client_authed.post(
            "/api/agent3/tools/web_search/toggle", json={"enabled": False},
        )

        # Verifier que TEST_USER_ID a 1 pref
        count_me = db.conn.execute(
            "SELECT COUNT(*) AS n FROM user_tool_preferences WHERE user_id = ?",
            (TEST_USER_ID,),
        ).fetchone()["n"]
        assert count_me == 1

        # L'autre user n'a rien
        count_other = db.conn.execute(
            "SELECT COUNT(*) AS n FROM user_tool_preferences WHERE user_id = ?",
            ("other-user",),
        ).fetchone()["n"]
        assert count_other == 0
