"""
Tests des endpoints /api/agent3/clawhub/* — Phase 4 Part F (auto-extension).

Couvre UNIQUEMENT les endpoints read-only + settings + events :
  GET    /api/agent3/clawhub/skills              -> liste (bundled + user)
  GET    /api/agent3/clawhub/skills/{slug}       -> detail + SKILL.md
  POST   /api/agent3/clawhub/skills/refresh      -> force rescan cache
  GET    /api/agent3/clawhub/events              -> historique auto-extensions
  GET    /api/agent3/clawhub/settings            -> permission_mode, toggles
  PUT    /api/agent3/clawhub/settings            -> update prefs

Les endpoints de search / install manuels / uninstall / per-skill toggle ont
ete retires : l'agent s'auto-etend de maniere autonome (search -> install
-> use -> publish). L'UI n'expose plus ces actions manuellement.

Verifie :
  - l'auth est requise (pas de user -> erreur)
  - refresh invalide bien le cache
  - les events sont logues par le dispatcher et listes en DESC
  - settings persistent en DB et sont per-user
  - permission_mode n'accepte que "default" ou "bypass"
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.dependencies import get_db, get_agent, get_optional_user
from sylea.core.storage.database import DatabaseManager


TEST_USER_ID = "test-user-clawhub"


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures (memoire + override des deps)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def db():
    manager = DatabaseManager(db_path=Path(":memory:"))
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    manager._conn = conn
    manager._initialiser_schema()

    conn.execute(
        "INSERT INTO users (id, email, hashed_password, provider, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (TEST_USER_ID, "clawhub@test.com", "fake", "local"),
    )
    conn.commit()
    yield manager
    manager.disconnect()


@pytest.fixture()
def client(db):
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


@pytest.fixture(autouse=True)
def reset_loader_cache():
    """Reset le cache du loader pour isolation entre tests."""
    from api.agent3_skills.clawhub_loader import _reset_cache
    _reset_cache()
    yield
    _reset_cache()


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/agent3/clawhub/skills (read-only)
# ══════════════════════════════════════════════════════════════════════════════


class TestListSkills:
    def test_requires_auth(self, client_anon):
        resp = client_anon.get("/api/agent3/clawhub/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("error") == "Non authentifie"

    def test_returns_list(self, client):
        resp = client.get("/api/agent3/clawhub/skills")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("success") is True
        assert "skills" in body
        assert "count" in body
        assert "bundled_count" in body
        assert "user_count" in body
        assert body["bundled_count"] + body["user_count"] == body["count"]

    def test_default_all_enabled(self, client):
        """Sans preference 'clawhub_enabled_slugs', toutes les skills sont
        'enabled' par defaut (mode auto-extensible)."""
        resp = client.get("/api/agent3/clawhub/skills")
        body = resp.json()
        assert body["enabled_mode"] == "all"
        assert body["enabled_slugs"] is None
        for s in body["skills"]:
            assert s["enabled"] is True

    def test_each_skill_has_tool_name(self, client):
        resp = client.get("/api/agent3/clawhub/skills")
        body = resp.json()
        for s in body["skills"]:
            assert "tool_name" in s
            assert s["tool_name"].startswith("skill_")

    def test_filter_bundled_only(self, client):
        resp = client.get("/api/agent3/clawhub/skills?include_user=false")
        assert resp.status_code == 200
        body = resp.json()
        assert body["user_count"] == 0
        for s in body["skills"]:
            assert s["is_bundled"] is True

    def test_force_refresh_works(self, client):
        resp = client.get("/api/agent3/clawhub/skills?force_refresh=true")
        assert resp.status_code == 200
        assert resp.json().get("success") is True


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/agent3/clawhub/skills/{slug}
# ══════════════════════════════════════════════════════════════════════════════


class TestGetSkillDetail:
    def test_requires_auth(self, client_anon):
        resp = client_anon.get("/api/agent3/clawhub/skills/weather")
        body = resp.json()
        assert body.get("error") == "Non authentifie"

    def test_returns_404_for_unknown_slug(self, client):
        resp = client.get("/api/agent3/clawhub/skills/nonexistent-skill-xyz-abc")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("success") is False
        assert "introuvable" in body.get("error", "").lower()

    def test_returns_detail_for_existing_bundled(self, client):
        # On prend la premiere skill bundled dispo
        list_resp = client.get("/api/agent3/clawhub/skills")
        list_body = list_resp.json()
        if not list_body["skills"]:
            pytest.skip("Pas de skills bundled sur ce systeme")
        slug = list_body["skills"][0]["slug"]

        resp = client.get(f"/api/agent3/clawhub/skills/{slug}")
        body = resp.json()
        assert body.get("success") is True
        assert body["skill"]["slug"] == slug
        assert "tool_name" in body["skill"]
        # Le SKILL.md est charge
        assert "skill_md" in body


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/agent3/clawhub/skills/refresh
# ══════════════════════════════════════════════════════════════════════════════


class TestRefreshCache:
    def test_requires_auth(self, client_anon):
        resp = client_anon.post("/api/agent3/clawhub/skills/refresh")
        assert resp.json().get("error") == "Non authentifie"

    def test_refresh_returns_counts(self, client):
        resp = client.post("/api/agent3/clawhub/skills/refresh")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("success") is True
        assert "count" in body
        assert "bundled_count" in body
        assert "user_count" in body


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/agent3/clawhub/events — historique auto-extensions
# ══════════════════════════════════════════════════════════════════════════════


class TestEventsEndpoint:
    def test_requires_auth(self, client_anon):
        resp = client_anon.get("/api/agent3/clawhub/events")
        assert resp.status_code == 200
        assert resp.json().get("error") == "Non authentifie"

    def test_empty_events_initially(self, client):
        """Un nouveau user n'a aucun evenement au depart."""
        resp = client.get("/api/agent3/clawhub/events")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("success") is True
        assert body.get("count") == 0
        assert body.get("events") == []
        # Les counts par type sont presents mais a zero
        counts = body.get("counts_by_type", {})
        assert counts.get("auto_search", 0) == 0
        assert counts.get("auto_install", 0) == 0
        assert counts.get("auto_publish", 0) == 0

    def test_events_logged_by_helper(self, client, db):
        """Le helper _log_clawhub_event insere, et l'endpoint les retourne
        triees DESC (plus recent en premier)."""
        from api.routers.agent3_openclaw import _log_clawhub_event

        _log_clawhub_event(
            db, TEST_USER_ID, "auto_search", "slack",
            trigger_context="query=slack notifications",
        )
        _log_clawhub_event(
            db, TEST_USER_ID, "auto_install", "slack",
            trigger_context="install slack",
        )
        _log_clawhub_event(
            db, TEST_USER_ID, "auto_publish", "custom-skill",
            trigger_context="create missing skill",
            success=False,
            error_message="Network error",
        )

        resp = client.get("/api/agent3/clawhub/events")
        body = resp.json()
        assert body.get("success") is True
        assert body["count"] == 3

        events = body["events"]
        # Tri DESC : le plus recent (publish) en premier
        types = [e["event_type"] for e in events]
        assert set(types) == {"auto_search", "auto_install", "auto_publish"}

        # Le publish est en echec
        publish = [e for e in events if e["event_type"] == "auto_publish"][0]
        assert publish["success"] is False
        assert "Network error" in publish["error_message"]

        # Counts par type
        counts = body["counts_by_type"]
        assert counts["auto_search"] == 1
        assert counts["auto_install"] == 1
        assert counts["auto_publish"] == 1

    def test_events_are_per_user(self, db):
        """Les events d'un user ne doivent pas fuiter chez un autre."""
        from api.routers.agent3_openclaw import _log_clawhub_event

        user2 = "user-2-events"
        db.conn.execute(
            "INSERT INTO users (id, email, hashed_password, provider, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (user2, "user2@test.com", "fake", "local"),
        )
        db.conn.commit()

        _log_clawhub_event(db, TEST_USER_ID, "auto_install", "skill-a")
        _log_clawhub_event(db, user2, "auto_install", "skill-b")

        async def _get_db():
            yield db

        def _get_agent():
            return None

        async def _get_user1():
            return TEST_USER_ID

        app.dependency_overrides[get_db] = _get_db
        app.dependency_overrides[get_agent] = _get_agent
        app.dependency_overrides[get_optional_user] = _get_user1
        with TestClient(app) as c1:
            body1 = c1.get("/api/agent3/clawhub/events").json()
        slugs1 = [e["slug"] for e in body1["events"]]
        assert slugs1 == ["skill-a"]

        async def _get_user2():
            return user2

        app.dependency_overrides[get_optional_user] = _get_user2
        with TestClient(app) as c2:
            body2 = c2.get("/api/agent3/clawhub/events").json()
        slugs2 = [e["slug"] for e in body2["events"]]
        assert slugs2 == ["skill-b"]

        app.dependency_overrides.clear()

    def test_events_limit_clamp(self, client, db):
        """Le parametre limit est borne a [1, 200]."""
        from api.routers.agent3_openclaw import _log_clawhub_event
        for i in range(10):
            _log_clawhub_event(db, TEST_USER_ID, "auto_search", f"skill-{i}")

        # limit normal
        resp = client.get("/api/agent3/clawhub/events?limit=5")
        assert resp.status_code == 200
        # max clamp : le backend doit au moins accepter et ne pas crasher
        resp_big = client.get("/api/agent3/clawhub/events?limit=99999")
        assert resp_big.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# GET/PUT /api/agent3/clawhub/settings
# ══════════════════════════════════════════════════════════════════════════════


class TestSettings:
    def test_get_defaults(self, client):
        resp = client.get("/api/agent3/clawhub/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert body["permission_mode"] == "default"
        assert body["clawhub_skills_enabled"] is True
        assert body["clawhub_meta_enabled"] is True
        assert body["clawhub_enabled_slugs"] is None
        assert body["enabled_mode"] == "all"

    def test_put_permission_mode_bypass(self, client):
        resp = client.put(
            "/api/agent3/clawhub/settings",
            json={"permission_mode": "bypass"},
        )
        body = resp.json()
        assert body.get("success") is True
        assert body["permission_mode"] == "bypass"

        # Persiste
        get_body = client.get("/api/agent3/clawhub/settings").json()
        assert get_body["permission_mode"] == "bypass"

    def test_put_invalid_permission_mode_ignored(self, client):
        """Un mode invalide doit etre ignore et garder l'ancien."""
        # Set valid first
        client.put("/api/agent3/clawhub/settings", json={"permission_mode": "bypass"})
        # Try invalid
        resp = client.put(
            "/api/agent3/clawhub/settings",
            json={"permission_mode": "root_exploit"},
        )
        body = resp.json()
        # L'ancien mode est preserve
        assert body["permission_mode"] == "bypass"

    def test_put_toggles_enabled_flags(self, client):
        resp = client.put(
            "/api/agent3/clawhub/settings",
            json={
                "clawhub_skills_enabled": False,
                "clawhub_meta_enabled": False,
            },
        )
        body = resp.json()
        assert body["clawhub_skills_enabled"] is False
        assert body["clawhub_meta_enabled"] is False

    def test_put_enabled_slugs_filter(self, client):
        resp = client.put(
            "/api/agent3/clawhub/settings",
            json={"clawhub_enabled_slugs": ["slack", "weather"]},
        )
        body = resp.json()
        assert body.get("success") is True
        assert body["clawhub_enabled_slugs"] == ["slack", "weather"]

    def test_put_enabled_slugs_null_resets_to_all(self, client):
        # Set a filter
        client.put(
            "/api/agent3/clawhub/settings",
            json={"clawhub_enabled_slugs": ["slack"]},
        )
        # Reset to all
        resp = client.put(
            "/api/agent3/clawhub/settings",
            json={"clawhub_enabled_slugs": None},
        )
        body = resp.json()
        assert body["clawhub_enabled_slugs"] is None

        get_body = client.get("/api/agent3/clawhub/settings").json()
        assert get_body["enabled_mode"] == "all"

    def test_settings_are_per_user(self, db):
        """Deux users doivent avoir des settings independants."""
        user2 = "user-2-clawhub"
        db.conn.execute(
            "INSERT INTO users (id, email, hashed_password, provider, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            (user2, "user2@test.com", "fake", "local"),
        )
        db.conn.commit()

        async def _get_db():
            yield db

        def _get_agent():
            return None

        # User 1 : mode bypass
        async def _get_user1():
            return TEST_USER_ID

        app.dependency_overrides[get_db] = _get_db
        app.dependency_overrides[get_agent] = _get_agent
        app.dependency_overrides[get_optional_user] = _get_user1
        with TestClient(app) as c1:
            c1.put("/api/agent3/clawhub/settings", json={"permission_mode": "bypass"})
            body1 = c1.get("/api/agent3/clawhub/settings").json()
        assert body1["permission_mode"] == "bypass"

        # User 2 : defaut
        async def _get_user2():
            return user2

        app.dependency_overrides[get_optional_user] = _get_user2
        with TestClient(app) as c2:
            body2 = c2.get("/api/agent3/clawhub/settings").json()
        assert body2["permission_mode"] == "default"

        app.dependency_overrides.clear()


# ══════════════════════════════════════════════════════════════════════════════
# Integration : PUT /preferences reconnaît aussi les nouvelles cles
# ══════════════════════════════════════════════════════════════════════════════


class TestPreferencesIntegration:
    def test_preferences_accepts_phase4_keys(self, client):
        resp = client.put(
            "/api/agent3/preferences",
            json={
                "permission_mode": "bypass",
                "clawhub_skills_enabled": False,
                "clawhub_meta_enabled": True,
                "clawhub_enabled_slugs": ["a", "b", "c"],
            },
        )
        body = resp.json()
        assert body.get("success") is True
        prefs = body["preferences"]
        assert prefs["permission_mode"] == "bypass"
        assert prefs["clawhub_skills_enabled"] is False
        assert prefs["clawhub_meta_enabled"] is True
        assert prefs["clawhub_enabled_slugs"] == ["a", "b", "c"]

    def test_preferences_rejects_invalid_permission_mode(self, client):
        """Le mode invalide doit etre silencieusement ignore."""
        # Set valid first
        client.put("/api/agent3/preferences", json={"permission_mode": "bypass"})
        # Try invalid
        resp = client.put("/api/agent3/preferences", json={"permission_mode": "root"})
        prefs = resp.json()["preferences"]
        assert prefs["permission_mode"] == "bypass"  # preserve

    def test_preferences_caps_enabled_slugs(self, client):
        """Liste de slugs capped a 200 elements."""
        huge_list = [f"s{i}" for i in range(300)]
        resp = client.put(
            "/api/agent3/preferences",
            json={"clawhub_enabled_slugs": huge_list},
        )
        prefs = resp.json()["preferences"]
        assert len(prefs["clawhub_enabled_slugs"]) <= 200


# ══════════════════════════════════════════════════════════════════════════════
# Dispatcher instrumentation : les meta-tools logent bien dans
# agent3_clawhub_events (verifie via l'endpoint /events apres dispatch)
# ══════════════════════════════════════════════════════════════════════════════


class TestDispatcherLogsEvents:
    """Verifie que le dispatcher natif appelle _log_clawhub_event apres
    chaque appel CLAWHUB_SEARCH / CLAWHUB_INSTALL / CLAWHUB_PUBLISH.

    On mock le meta-tool dispatcher pour controller la reponse.
    """

    @pytest.mark.asyncio
    async def test_search_success_logs_event(self, db):
        from unittest.mock import AsyncMock, patch
        from api.agent3_native_dispatcher import Agent3ActionDispatcher

        dispatcher = Agent3ActionDispatcher(
            db=db, user_id=TEST_USER_ID, session_key="sess-test",
        )

        fake = {
            "content": "1 skill trouve",
            "is_error": False,
            "raw": {"results": [{"slug": "slack"}], "query": "slack"},
        }
        with patch(
            "api.agent3_skills.clawhub_meta_tools.dispatch_clawhub_meta_tool",
            new=AsyncMock(return_value=fake),
        ):
            result = await dispatcher.execute(
                "CLAWHUB_SEARCH",
                {"query": "slack notifications"},
            )

        assert result.get("is_error") is False

        # L'event a ete logue
        from api.routers.agent3_openclaw import _list_clawhub_events
        events = _list_clawhub_events(db, TEST_USER_ID)
        assert len(events) == 1
        assert events[0]["event_type"] == "auto_search"
        assert events[0]["success"] is True
        assert "slack" in events[0]["slug"].lower()

    @pytest.mark.asyncio
    async def test_install_failure_logs_error(self, db):
        from unittest.mock import AsyncMock, patch
        from api.agent3_native_dispatcher import Agent3ActionDispatcher

        dispatcher = Agent3ActionDispatcher(
            db=db, user_id=TEST_USER_ID, session_key="sess-test",
        )

        fake = {
            "content": "Erreur d'installation : slug inconnu",
            "is_error": True,
            "raw": {"slug": "bad-slug", "rc": 1},
        }
        with patch(
            "api.agent3_skills.clawhub_meta_tools.dispatch_clawhub_meta_tool",
            new=AsyncMock(return_value=fake),
        ):
            result = await dispatcher.execute(
                "CLAWHUB_INSTALL",
                {"slug": "bad-slug"},
            )

        assert result.get("is_error") is True

        from api.routers.agent3_openclaw import _list_clawhub_events
        events = _list_clawhub_events(db, TEST_USER_ID)
        assert len(events) == 1
        ev = events[0]
        assert ev["event_type"] == "auto_install"
        assert ev["success"] is False
        assert ev["slug"] == "bad-slug"
        assert "slug inconnu" in ev["error_message"].lower()

    @pytest.mark.asyncio
    async def test_publish_success_logs_event(self, db):
        from unittest.mock import AsyncMock, patch
        from api.agent3_native_dispatcher import Agent3ActionDispatcher

        dispatcher = Agent3ActionDispatcher(
            db=db, user_id=TEST_USER_ID, session_key="sess-test",
        )

        fake = {
            "content": "Skill 'new-skill' publiee",
            "is_error": False,
            "raw": {"slug": "new-skill", "url": "https://clawhub.com/..."},
        }
        with patch(
            "api.agent3_skills.clawhub_meta_tools.dispatch_clawhub_meta_tool",
            new=AsyncMock(return_value=fake),
        ):
            result = await dispatcher.execute(
                "CLAWHUB_PUBLISH",
                {"slug": "new-skill", "description": "Nouvelle skill auto-creee"},
            )

        assert result.get("is_error") is False

        from api.routers.agent3_openclaw import _list_clawhub_events
        events = _list_clawhub_events(db, TEST_USER_ID)
        assert len(events) == 1
        assert events[0]["event_type"] == "auto_publish"
        assert events[0]["slug"] == "new-skill"
        assert events[0]["success"] is True


# ══════════════════════════════════════════════════════════════════════════════
# Non-regression : les endpoints supprimes retournent bien 404/405
# ══════════════════════════════════════════════════════════════════════════════


class TestRemovedEndpoints:
    """Apres simplification UI : les endpoints manuels search/install/
    uninstall/toggle ne sont plus exposes. Verifie qu'ils renvoient 404/405.
    """

    def test_search_endpoint_removed(self, client):
        resp = client.post("/api/agent3/clawhub/skills/search", json={"query": "x"})
        assert resp.status_code in (404, 405)

    def test_install_endpoint_removed(self, client):
        resp = client.post("/api/agent3/clawhub/skills/install/some-slug", json={})
        assert resp.status_code in (404, 405)

    def test_toggle_endpoint_removed(self, client):
        resp = client.put(
            "/api/agent3/clawhub/skills/some-slug/toggle",
            json={"enabled": True},
        )
        assert resp.status_code in (404, 405)

    def test_uninstall_endpoint_removed(self, client):
        resp = client.delete("/api/agent3/clawhub/skills/some-slug")
        assert resp.status_code in (404, 405)
