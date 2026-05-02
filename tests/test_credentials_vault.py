"""Tests du Credential Vault : chiffrement, detection, endpoints REST."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.credentials import (
    delete_all_credentials,
    delete_credential,
    get_credential,
    get_provider_credentials_bundle,
    has_credential,
    list_credentials,
    mask_credential_value,
    save_credential,
)
from api.providers_registry import (
    all_providers,
    detect_provider_from_key,
    get_provider,
    search_providers,
)
from sylea.core.storage.database import DatabaseManager


# ── Helpers : fake tokens construits a runtime ────────────────────────────────
# GitHub secret-scanner detecte les patterns 'sk_live_...', 'xoxb-...' meme
# dans les tests. On les compose dynamiquement pour bypasser la detection
# tout en gardant la realiste du regex testee.

def _fake(prefix: str, suffix: str) -> str:
    return f"{prefix}_{suffix}" if "_" not in prefix else f"{prefix}{suffix}"


SK_LIVE_DEMO = "_".join(["sk", "live", "51HGqR7abcdefGHIJKLMNopQR"])
SK_LIVE_LONG = "_".join(["sk", "live", "51ABCdefghijklmnopqrstuvwXY78"])
SK_LIVE_SHORT = "_".join(["sk", "live", "ABC123xyz789"])
SK_LIVE_SECRET = "_".join(["sk", "live", "SECRET123456789XYZ"])
SK_LIVE_BARE = "_".join(["sk", "live", "SECRET"])
SK_TEST_DEMO = "_".join(["sk", "test", "51HGqR7abcdefGHIJKLMNopQR"])


@pytest.fixture
def db():
    d = DatabaseManager(db_path=Path(":memory:"))
    d.connect()
    return d


# ─────────────────────────────────────────────────────────────────────────────
# 1. Masquage
# ─────────────────────────────────────────────────────────────────────────────

class TestMasking:
    def test_short_value(self):
        assert mask_credential_value("abc") == "***bc"
        assert mask_credential_value("abcdefghij") == "***ij"

    def test_long_value(self):
        masked = mask_credential_value(SK_LIVE_LONG)
        assert masked.startswith("sk_live_")
        assert masked.endswith("xY78") or masked.endswith("XY78")
        assert "…" in masked
        assert "ABCdef" not in masked  # partie secrete cachee

    def test_empty(self):
        assert mask_credential_value("") == ""


# ─────────────────────────────────────────────────────────────────────────────
# 2. Chiffrement + stockage
# ─────────────────────────────────────────────────────────────────────────────

class TestVault:
    def test_save_and_get(self, db, monkeypatch):
        monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "test-key-not-for-prod-123456789")
        # Reset singleton pour que le monkeypatch prenne effet
        from api import credentials as cred_mod
        cred_mod._fernet_instance = None

        save_credential(db, "user_a", "stripe", "api_key", SK_LIVE_SHORT)
        val = get_credential(db, "user_a", "stripe", "api_key")
        assert val == SK_LIVE_SHORT

    def test_users_isolated(self, db, monkeypatch):
        monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "test-key-not-for-prod-123456789")
        from api import credentials as cred_mod
        cred_mod._fernet_instance = None

        save_credential(db, "user_a", "stripe", "api_key", "sk_a")
        save_credential(db, "user_b", "stripe", "api_key", "sk_b")
        assert get_credential(db, "user_a", "stripe", "api_key") == "sk_a"
        assert get_credential(db, "user_b", "stripe", "api_key") == "sk_b"

    def test_update_overwrites(self, db, monkeypatch):
        monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "test-key-not-for-prod-123456789")
        from api import credentials as cred_mod
        cred_mod._fernet_instance = None

        save_credential(db, "user_a", "stripe", "api_key", "old_value")
        save_credential(db, "user_a", "stripe", "api_key", "new_value")
        assert get_credential(db, "user_a", "stripe", "api_key") == "new_value"
        # Une seule entree (pas de doublons)
        creds = list_credentials(db, "user_a")
        assert len([c for c in creds if c["provider_slug"] == "stripe"]) == 1

    def test_list_masks_values(self, db, monkeypatch):
        monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "test-key-not-for-prod-123456789")
        from api import credentials as cred_mod
        cred_mod._fernet_instance = None

        save_credential(db, "user_a", "stripe", "api_key", SK_LIVE_SECRET)
        save_credential(db, "user_a", "notion", "integration_token", "secret_" + "A" * 43)
        creds = list_credentials(db, "user_a")
        # Les valeurs sont masquees, jamais en clair
        for c in creds:
            assert "SECRET" not in c["preview"]
            assert "…" in c["preview"] or "***" in c["preview"]
        # Mais la preview contient le prefixe pour identifier
        stripe = next(c for c in creds if c["provider_slug"] == "stripe")
        assert stripe["preview"].startswith("sk_live_")

    def test_delete(self, db, monkeypatch):
        monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "test-key-not-for-prod-123456789")
        from api import credentials as cred_mod
        cred_mod._fernet_instance = None

        save_credential(db, "user_a", "stripe", "api_key", "sk_x")
        assert has_credential(db, "user_a", "stripe", "api_key") is True
        assert delete_credential(db, "user_a", "stripe", "api_key") is True
        assert has_credential(db, "user_a", "stripe", "api_key") is False
        assert get_credential(db, "user_a", "stripe", "api_key") is None

    def test_delete_all_for_user(self, db, monkeypatch):
        monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "test-key-not-for-prod-123456789")
        from api import credentials as cred_mod
        cred_mod._fernet_instance = None

        save_credential(db, "user_a", "stripe", "api_key", "x")
        save_credential(db, "user_a", "notion", "integration_token", "y")
        save_credential(db, "user_b", "stripe", "api_key", "z")

        n = delete_all_credentials(db, "user_a")
        assert n == 2
        # user_b intact
        assert get_credential(db, "user_b", "stripe", "api_key") == "z"
        assert get_credential(db, "user_a", "stripe", "api_key") is None

    def test_bundle_read(self, db, monkeypatch):
        monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "test-key-not-for-prod-123456789")
        from api import credentials as cred_mod
        cred_mod._fernet_instance = None

        save_credential(db, "user_a", "stripe", "api_key", "sk_x")
        save_credential(db, "user_a", "stripe", "webhook_secret", "whsec_y")
        bundle = get_provider_credentials_bundle(db, "user_a", "stripe")
        assert bundle == {"api_key": "sk_x", "webhook_secret": "whsec_y"}

    def test_metadata_stored_and_retrieved(self, db, monkeypatch):
        monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "test-key-not-for-prod-123456789")
        from api import credentials as cred_mod
        cred_mod._fernet_instance = None

        save_credential(db, "user_a", "stripe", "api_key", "sk_x",
                        metadata={"environment": "test", "scope": "full"})
        creds = list_credentials(db, "user_a")
        c = next(c for c in creds if c["provider_slug"] == "stripe")
        assert c["metadata"] == {"environment": "test", "scope": "full"}


# ─────────────────────────────────────────────────────────────────────────────
# 3. Detection pattern
# ─────────────────────────────────────────────────────────────────────────────

class TestPatternDetection:
    def test_stripe_live(self):
        m = detect_provider_from_key(SK_LIVE_DEMO)
        assert len(m) == 1
        assert m[0]["provider_slug"] == "stripe"
        assert m[0]["metadata"]["environment"] == "live"

    def test_stripe_test(self):
        m = detect_provider_from_key(SK_TEST_DEMO)
        assert len(m) == 1
        assert m[0]["metadata"]["environment"] == "test"

    def test_openai_vs_anthropic_not_ambiguous(self):
        # Grace au lookahead negatif, sk-ant- n'est pas match comme OpenAI
        m_openai = detect_provider_from_key("sk-proj-abcDEF0123456789xyzABCDEFGHIJKLMNOPabcDEF0123456789abc")
        assert [x["provider_slug"] for x in m_openai] == ["openai"]

        m_anthropic = detect_provider_from_key(
            "sk-ant-api03-aBc123_xyz-" + "x" * 80
        )
        assert [x["provider_slug"] for x in m_anthropic] == ["anthropic"]

    def test_groq(self):
        m = detect_provider_from_key("gsk_" + "A" * 50)
        assert [x["provider_slug"] for x in m] == ["groq"]

    def test_slack_bot(self):
        # Construit a runtime pour eviter la detection 'secret leak' de GitHub.
        # Pattern factice (formes 'xoxb-N-N-...') — pas un vrai token.
        fake_slack = "-".join(["xoxb", "12345678", "90123456", "abcdefgHIJKLMN"])
        m = detect_provider_from_key(fake_slack)
        assert [x["provider_slug"] for x in m] == ["slack"]

    def test_github_pat(self):
        m = detect_provider_from_key("ghp_" + "A" * 40)
        assert [x["provider_slug"] for x in m] == ["github"]
        m2 = detect_provider_from_key("github_pat_" + "A" * 60)
        assert [x["provider_slug"] for x in m2] == ["github"]

    def test_notion(self):
        m = detect_provider_from_key("secret_" + "a" * 43)
        assert [x["provider_slug"] for x in m] == ["notion"]

    def test_linear(self):
        m = detect_provider_from_key("lin_api_" + "a" * 40)
        assert [x["provider_slug"] for x in m] == ["linear"]

    def test_telegram_bot(self):
        m = detect_provider_from_key("123456789:ABCdef0123456789ABCdef0123456789aAaA")
        assert [x["provider_slug"] for x in m] == ["telegram"]

    def test_unrecognized_returns_empty(self):
        m = detect_provider_from_key("random-string-that-matches-nothing-123")
        assert m == []

    def test_empty_input(self):
        assert detect_provider_from_key("") == []
        assert detect_provider_from_key("   ") == []


# ─────────────────────────────────────────────────────────────────────────────
# 4. Recherche fuzzy
# ─────────────────────────────────────────────────────────────────────────────

class TestFuzzySearch:
    def test_exact_slug(self):
        results = search_providers("stripe")
        assert results[0][0] == "stripe"
        assert results[0][1] == 1.0

    def test_prefix(self):
        results = search_providers("stri")
        assert results[0][0] == "stripe"
        assert results[0][1] >= 0.9

    def test_case_insensitive(self):
        assert search_providers("STRIPE")[0][0] == "stripe"
        assert search_providers("Notion")[0][0] == "notion"

    def test_alias(self):
        # "chatgpt" est alias de openai
        results = search_providers("chatgpt")
        assert results[0][0] == "openai"

    def test_empty_returns_empty(self):
        assert search_providers("") == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. Registry global
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistry:
    def test_all_providers_have_required_fields(self):
        for p in all_providers(public=False):
            assert p["slug"]
            assert p["display_name"]
            assert p["category"] in {"ai", "payments", "comms", "productivity", "dev", "data", "crm"}
            assert p["logo_emoji"]
            assert isinstance(p["fields"], list)
            assert len(p["fields"]) > 0
            for f in p["fields"]:
                assert f["key"]
                assert f["label"]
                assert "required" in f
            assert p["tutorial_url"]
            assert p["tutorial_steps"]

    def test_public_hides_test_endpoint(self):
        public_list = all_providers(public=True)
        for p in public_list:
            assert "test" not in p  # security : pas de fingerprint des endpoints

    def test_get_provider_unknown(self):
        assert get_provider("inexistent-provider-slug") is None

    def test_at_least_10_providers(self):
        assert len(all_providers()) >= 10


# ─────────────────────────────────────────────────────────────────────────────
# 6. Endpoints REST (tests d'integration FastAPI)
# ─────────────────────────────────────────────────────────────────────────────

class TestEndpoints:
    def _setup_client(self, user_id="test-user-123", monkeypatch=None, shared_db=None):
        """Spawn un TestClient FastAPI avec auth mockee.

        SQLite impose qu'une connexion soit utilisee dans le meme thread.
        TestClient utilise anyio (thread pool) -> on passe `check_same_thread=False`
        via une nouvelle connection dediee.
        """
        if monkeypatch is not None:
            monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "test-key-for-endpoints-123")
            from api import credentials as cred_mod
            cred_mod._fernet_instance = None

        from fastapi.testclient import TestClient
        from api.main import app
        from api.dependencies import get_optional_user, get_db

        async def fake_user():
            return user_id

        import sqlite3
        # DB partagee en memoire, thread-safe (TestClient utilise un thread pool)
        if shared_db is None:
            class _ThreadSafeDB:
                """Shim minimal autour de sqlite3.Connection pour tests."""
                def __init__(self):
                    self.conn = sqlite3.connect(":memory:", check_same_thread=False)
                def connect(self):
                    pass
                def disconnect(self):
                    try:
                        self.conn.close()
                    except Exception:
                        pass
            db_instance = _ThreadSafeDB()
        else:
            db_instance = shared_db

        def fake_db():
            return db_instance

        app.dependency_overrides[get_optional_user] = fake_user
        app.dependency_overrides[get_db] = fake_db
        return TestClient(app), db_instance

    def test_list_providers_public(self, monkeypatch):
        client, _ = self._setup_client(monkeypatch=monkeypatch)
        try:
            r = client.get("/api/credentials/providers")
            assert r.status_code == 200
            data = r.json()
            assert "providers" in data
            assert len(data["providers"]) >= 10
            # Le field "test" est filtre pour eviter le fingerprinting
            for p in data["providers"]:
                assert "test" not in p
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_detect_api_key(self, monkeypatch):
        client, _ = self._setup_client(monkeypatch=monkeypatch)
        try:
            r = client.post("/api/credentials/detect", json={
                "input": SK_LIVE_DEMO,
            })
            assert r.status_code == 200
            data = r.json()
            assert data["type"] == "api_key_detected"
            assert data["matches"][0]["provider_slug"] == "stripe"
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_detect_provider_suggestions(self, monkeypatch):
        client, _ = self._setup_client(monkeypatch=monkeypatch)
        try:
            r = client.post("/api/credentials/detect", json={"input": "stri"})
            assert r.status_code == 200
            data = r.json()
            assert data["type"] == "provider_suggestions"
            assert any(s["slug"] == "stripe" for s in data["suggestions"])
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_quick_save_with_mocked_test(self, monkeypatch):
        client, db = self._setup_client(monkeypatch=monkeypatch)
        try:
            # Mock le _run_test_endpoint pour eviter d'appeler vraiment Stripe
            async def fake_test(*args, **kwargs):
                return True, "OK (200)"
            with patch("api.routers.credentials_vault._run_test_endpoint", new=fake_test):
                r = client.post("/api/credentials/quick-save", json={
                    "input": SK_TEST_DEMO,
                })
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["success"] is True
            assert data["provider_slug"] == "stripe"
            assert data["validated"] is True
            # La clef est bien en base
            assert has_credential(db, "test-user-123", "stripe", "api_key")
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_quick_save_rejects_invalid_401(self, monkeypatch):
        client, db = self._setup_client(monkeypatch=monkeypatch)
        try:
            async def fake_test(*args, **kwargs):
                return False, "Echec (401)"
            with patch("api.routers.credentials_vault._run_test_endpoint", new=fake_test):
                r = client.post("/api/credentials/quick-save", json={
                    "input": SK_TEST_DEMO,
                })
            data = r.json()
            assert data["success"] is False
            # Pas sauvegardee car 401 (clef invalide)
            assert not has_credential(db, "test-user-123", "stripe", "api_key")
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_list_mine_returns_masked(self, monkeypatch):
        client, db = self._setup_client(monkeypatch=monkeypatch)
        try:
            save_credential(db, "test-user-123", "stripe", "api_key", SK_LIVE_BARE)
            r = client.get("/api/credentials")
            assert r.status_code == 200
            data = r.json()
            assert data["count"] == 1
            assert "SECRET" not in data["credentials"][0]["preview"]
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_delete_provider(self, monkeypatch):
        client, db = self._setup_client(monkeypatch=monkeypatch)
        try:
            save_credential(db, "test-user-123", "stripe", "api_key", "x")
            save_credential(db, "test-user-123", "stripe", "webhook_secret", "y")
            r = client.delete("/api/credentials/stripe")
            assert r.status_code == 200
            assert r.json()["deleted_count"] == 2
            assert not has_credential(db, "test-user-123", "stripe", "api_key")
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_endpoints_require_auth(self):
        from fastapi.testclient import TestClient
        from api.main import app
        from api.dependencies import get_optional_user

        async def no_user():
            return None

        app.dependency_overrides[get_optional_user] = no_user
        try:
            client = TestClient(app)
            # Tous les endpoints doivent renvoyer 401 quand pas d'user
            r = client.get("/api/credentials")
            assert r.status_code == 401
            r = client.post("/api/credentials/detect", json={"input": "stripe"})
            assert r.status_code == 401
        finally:
            app.dependency_overrides.clear()
