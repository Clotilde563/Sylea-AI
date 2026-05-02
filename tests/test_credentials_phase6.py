"""Phase 6 : extension catalogue + support 'infini' skills ClawHub.

Couvre :
  1. Le catalogue contient >= 35 providers (tier 2 étendu)
  2. Les patterns de détection fonctionnent pour les 20+ nouveaux providers
  3. Endpoint `/credentials/missing-for-skills` scanne les required_env
  4. Endpoint `/credentials/custom-skill-env` stocke en namespace isolé
  5. `skill_executor` renvoie credentials_status dans le raw
  6. Les env vars custom matchent provider si nom heuristique match
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from api.credentials import has_credential, save_credential
from api.providers_registry import (
    PROVIDERS,
    all_providers,
    detect_provider_from_key,
    get_provider,
)


@pytest.fixture(autouse=True)
def _reset_fernet(monkeypatch):
    monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "phase6-master-key-testtest")
    from api import credentials as cred_mod
    cred_mod._fernet_instance = None


class _ThreadSafeDB:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
    def connect(self): pass
    def disconnect(self):
        try: self.conn.close()
        except Exception: pass


@pytest.fixture
def db():
    return _ThreadSafeDB()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Catalogue étendu
# ─────────────────────────────────────────────────────────────────────────────

class TestCatalogExtension:
    def test_at_least_35_providers(self):
        assert len(PROVIDERS) >= 35, f"Expected >= 35 providers, got {len(PROVIDERS)}"

    def test_ai_providers_presence(self):
        # Les providers AI principaux doivent etre presents
        ai_slugs = {p["slug"] for p in PROVIDERS if p["category"] == "ai"}
        expected = {"openai", "anthropic", "mistral", "cohere", "groq",
                    "perplexity", "openrouter", "xai", "huggingface", "replicate"}
        missing = expected - ai_slugs
        assert not missing, f"AI providers manquants : {missing}"

    def test_comms_providers(self):
        comms = {p["slug"] for p in PROVIDERS if p["category"] == "comms"}
        assert {"slack", "discord", "telegram", "sendgrid", "resend"}.issubset(comms)

    def test_dev_providers(self):
        dev = {p["slug"] for p in PROVIDERS if p["category"] == "dev"}
        assert {"github", "vercel", "sentry", "posthog", "cloudflare"}.issubset(dev)

    def test_productivity_providers(self):
        prod = {p["slug"] for p in PROVIDERS if p["category"] == "productivity"}
        assert {"notion", "linear", "clickup", "asana", "trello"}.issubset(prod)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Patterns des nouveaux providers
# ─────────────────────────────────────────────────────────────────────────────

class TestNewPatterns:
    def test_openrouter_not_confused_with_openai(self):
        # sk-or-v1- est OpenRouter, PAS OpenAI grace au lookahead negatif
        m = detect_provider_from_key("sk-or-v1-" + "a" * 64)
        slugs = {x["provider_slug"] for x in m}
        assert "openrouter" in slugs
        assert "openai" not in slugs

    def test_xai_grok(self):
        m = detect_provider_from_key("xai-" + "A" * 85)
        assert [x["provider_slug"] for x in m] == ["xai"]

    def test_huggingface(self):
        m = detect_provider_from_key("hf_" + "a" * 37)
        slugs = {x["provider_slug"] for x in m}
        assert "huggingface" in slugs

    def test_replicate(self):
        m = detect_provider_from_key("r8_" + "a" * 40)
        assert [x["provider_slug"] for x in m] == ["replicate"]

    def test_sendgrid(self):
        key = "SG." + "a" * 22 + "." + "b" * 43
        m = detect_provider_from_key(key)
        assert [x["provider_slug"] for x in m] == ["sendgrid"]

    def test_resend(self):
        m = detect_provider_from_key("re_" + "a" * 24 + "_" + "b" * 24)
        assert [x["provider_slug"] for x in m] == ["resend"]

    def test_twilio_account_sid(self):
        m = detect_provider_from_key("AC" + "a" * 32)
        slugs = {x["provider_slug"] for x in m}
        assert "twilio" in slugs
        # Vercel ne matche plus (lookahead negatif AC)
        assert "vercel" not in slugs

    def test_hubspot(self):
        m = detect_provider_from_key("pat-na1-abc-def-0123456789")
        assert [x["provider_slug"] for x in m] == ["hubspot"]

    def test_posthog(self):
        m = detect_provider_from_key("phc_" + "a" * 44)
        assert [x["provider_slug"] for x in m] == ["posthog"]

    def test_clickup(self):
        m = detect_provider_from_key("pk_12345678_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123")
        assert [x["provider_slug"] for x in m] == ["clickup"]

    def test_sentry(self):
        m = detect_provider_from_key("sntrys_" + "ABCdef0123+/=_-" * 4)
        slugs = {x["provider_slug"] for x in m}
        assert "sentry" in slugs

    def test_mistral(self):
        m = detect_provider_from_key("A" * 32)
        slugs = {x["provider_slug"] for x in m}
        # Mistral = 32 alnum. D'autres patterns peuvent matcher (elevenlabs=32hex,
        # datadog=32hex, mixpanel=32hex) mais seulement pour hex.
        # Avec "A" * 32 (pas hex), seul Mistral matche.
        assert "mistral" in slugs


# ─────────────────────────────────────────────────────────────────────────────
# 3. Endpoint missing-for-skills
# ─────────────────────────────────────────────────────────────────────────────

class TestMissingForSkills:
    def _setup_client(self, db, user_id="phase6-user"):
        from fastapi.testclient import TestClient
        from api.main import app
        from api.dependencies import get_optional_user, get_db

        async def fake_user(): return user_id
        def fake_db(): return db

        app.dependency_overrides[get_optional_user] = fake_user
        app.dependency_overrides[get_db] = fake_db
        return TestClient(app)

    def test_missing_for_skills_empty(self, db):
        client = self._setup_client(db)
        try:
            with patch("api.agent3_skills.clawhub_loader.load_all_skills", return_value=[]):
                r = client.get("/api/credentials/missing-for-skills")
            assert r.status_code == 200
            data = r.json()
            assert data["skills"] == []
            assert data["total_missing_count"] == 0
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_missing_with_matched_provider(self, db):
        # Skill qui requiert STRIPE_API_KEY -> matche le provider "stripe"
        from api.agent3_skills.clawhub_loader import ClawHubSkillMeta
        fake_meta = ClawHubSkillMeta(
            slug="stripe-refunds",
            name="Stripe Refunds",
            description="Rembourse des paiements",
            path=Path("/tmp/fake"),
            required_env=["STRIPE_API_KEY"],
        )
        client = self._setup_client(db)
        try:
            with patch("api.agent3_skills.clawhub_loader.load_all_skills", return_value=[fake_meta]):
                r = client.get("/api/credentials/missing-for-skills")
            data = r.json()
            assert len(data["skills"]) == 1
            s = data["skills"][0]
            assert s["slug"] == "stripe-refunds"
            m = s["missing"][0]
            assert m["env_name"] == "STRIPE_API_KEY"
            assert m["matched_provider"] == "stripe"
            assert m["has_credential"] is False
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_missing_with_custom_provider(self, db):
        # Env name qui ne matche aucun provider connu
        from api.agent3_skills.clawhub_loader import ClawHubSkillMeta
        fake_meta = ClawHubSkillMeta(
            slug="my-internal-skill",
            name="My Internal Tool",
            description="Outil perso",
            path=Path("/tmp/fake"),
            required_env=["MYCOMPANY_INTERNAL_TOKEN"],
        )
        client = self._setup_client(db)
        try:
            with patch("api.agent3_skills.clawhub_loader.load_all_skills", return_value=[fake_meta]):
                r = client.get("/api/credentials/missing-for-skills")
            data = r.json()
            m = data["skills"][0]["missing"][0]
            assert m["matched_provider"] is None  # custom
            assert m["field_key"] == "MYCOMPANY_INTERNAL_TOKEN"
            assert "custom_provider_slug" in m
            assert m["custom_provider_slug"] == "clawhub_skill_my-internal-skill"
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_existing_credential_marks_has(self, db):
        # Cas mixte : une cred existe (stripe), l'autre non (custom)
        save_credential(db, "phase6-user", "stripe", "api_key", "sk_live_test")
        from api.agent3_skills.clawhub_loader import ClawHubSkillMeta
        fake_meta = ClawHubSkillMeta(
            slug="multi-skill",
            name="Multi",
            description="",
            path=Path("/tmp/fake"),
            required_env=["STRIPE_API_KEY", "CUSTOM_TOKEN"],
        )
        client = self._setup_client(db)
        try:
            with patch("api.agent3_skills.clawhub_loader.load_all_skills", return_value=[fake_meta]):
                r = client.get("/api/credentials/missing-for-skills")
            data = r.json()
            missing = data["skills"][0]["missing"]
            stripe_m = next(m for m in missing if m["env_name"] == "STRIPE_API_KEY")
            custom_m = next(m for m in missing if m["env_name"] == "CUSTOM_TOKEN")
            assert stripe_m["has_credential"] is True
            assert custom_m["has_credential"] is False
            assert data["total_missing_count"] == 1
        finally:
            from api.main import app
            app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Endpoint custom-skill-env
# ─────────────────────────────────────────────────────────────────────────────

class TestCustomSkillEnv:
    def _setup_client(self, db, user_id="phase6-user"):
        from fastapi.testclient import TestClient
        from api.main import app
        from api.dependencies import get_optional_user, get_db

        async def fake_user(): return user_id
        def fake_db(): return db

        app.dependency_overrides[get_optional_user] = fake_user
        app.dependency_overrides[get_db] = fake_db
        return TestClient(app)

    def test_save_custom_env(self, db):
        client = self._setup_client(db)
        try:
            r = client.post("/api/credentials/custom-skill-env", json={
                "skill_slug": "my-skill",
                "env_name": "MY_CUSTOM_TOKEN",
                "value": "secret-value-123",
            })
            assert r.status_code == 200
            data = r.json()
            assert data["success"] is True
            assert data["provider_slug"] == "clawhub_skill_my-skill"
            assert data["field_key"] == "MY_CUSTOM_TOKEN"
            # Verifie que la valeur est bien stockee chiffrée
            assert has_credential(db, "phase6-user", "clawhub_skill_my-skill", "MY_CUSTOM_TOKEN")
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_rejects_invalid_slug(self, db):
        client = self._setup_client(db)
        try:
            r = client.post("/api/credentials/custom-skill-env", json={
                "skill_slug": "../etc/passwd",
                "env_name": "X",
                "value": "y",
            })
            assert r.status_code == 400
        finally:
            from api.main import app
            app.dependency_overrides.clear()

    def test_rejects_invalid_env_name(self, db):
        client = self._setup_client(db)
        try:
            # Les env vars doivent etre UPPERCASE + underscore seulement
            for bad in ["lowercase", "has spaces", "1_starts_digit", "my-var"]:
                r = client.post("/api/credentials/custom-skill-env", json={
                    "skill_slug": "my-skill", "env_name": bad, "value": "y",
                })
                assert r.status_code == 400, f"Should reject: {bad}"
        finally:
            from api.main import app
            app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 5. skill_executor : credentials_status dans raw
# ─────────────────────────────────────────────────────────────────────────────

class TestSkillExecutorCredentials:
    @pytest.mark.asyncio
    async def test_status_included_in_raw(self, db, monkeypatch, tmp_path):
        # Cree un skill fake avec required_env
        import api.agent3_skills.clawhub_loader as loader
        from api.agent3_skills.clawhub_loader import _reset_cache

        # Pour que auth_user_id="usr-skill-e2e" pointe vers tmp_path au lieu
        # du vrai home utilisateur, on override SYLEA_USER_SKILLS_ROOT.
        users_root = tmp_path / "users_root"
        monkeypatch.setenv("SYLEA_USER_SKILLS_ROOT", str(users_root))

        skill_dir = users_root / "usr-skill-e2e" / ".openclaw" / "skills"
        (skill_dir / "test-skill").mkdir(parents=True)
        md_content = """---
name: test-skill
description: Skill de test
metadata:
  openclaw:
    requires:
      env:
        - STRIPE_API_KEY
        - MY_UNKNOWN_VAR
---

# Test Skill
Corps du SKILL.md.
"""
        (skill_dir / "test-skill" / "SKILL.md").write_text(md_content, encoding="utf-8")

        _reset_cache()
        monkeypatch.setattr(loader, "BUNDLED_SKILLS_DIRS", [])

        # L'user a deja la stripe cred
        save_credential(db, "usr-skill-e2e", "stripe", "api_key", "sk_live_x")

        from api.agent3_skills.skill_executor import dispatch_skill_invocation
        r = await dispatch_skill_invocation(
            tool_name="skill_test_skill",
            tool_input={"instruction": "ping"},
            auth_user_id="usr-skill-e2e",
            db=db,
        )
        assert r["is_error"] is False, f"Dispatch failed: {r.get('content', '?')[:200]}"
        statuses = r["raw"].get("credentials_status", [])
        assert len(statuses) == 2, f"Expected 2 creds, got {statuses}"
        stripe_s = next(s for s in statuses if s["env_name"] == "STRIPE_API_KEY")
        unknown_s = next(s for s in statuses if s["env_name"] == "MY_UNKNOWN_VAR")
        assert stripe_s["has"] is True
        assert stripe_s["provider"] == "stripe"
        assert unknown_s["has"] is False
        assert unknown_s["provider"] is None  # custom
        assert r["raw"]["credentials_missing_count"] == 1
        # Le content pour le LLM mentionne les missing
        assert "MY_UNKNOWN_VAR" in r["content"] or "MANQUANTE" in r["content"]
        _reset_cache()
