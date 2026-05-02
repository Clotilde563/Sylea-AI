"""Tests pour api/web_providers.py — providers web search natifs multi-user."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sylea.core.storage.database import DatabaseManager


@pytest.fixture
def db():
    d = DatabaseManager(db_path=Path(":memory:"))
    d.connect()
    return d


@pytest.fixture(autouse=True)
def _master_key(monkeypatch):
    monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "test-key-not-for-prod-123456789")
    from api import credentials as cred_mod
    cred_mod._fernet_instance = None


def _save_key(db, user_id: str, provider: str, value: str):
    from api.credentials import save_credential
    save_credential(db, user_id, provider, "api_key", value)


class TestKeyResolution:
    def test_has_user_key_for_when_present(self, db):
        from api.web_providers import has_user_key_for
        _save_key(db, "u1", "perplexity", "pplx-test-abc")
        assert has_user_key_for(db, "u1", "perplexity_search") is True

    def test_has_user_key_for_when_absent(self, db):
        from api.web_providers import has_user_key_for
        assert has_user_key_for(db, "u1", "perplexity_search") is False

    def test_unknown_tool(self, db):
        from api.web_providers import has_user_key_for
        assert has_user_key_for(db, "u1", "weather_search") is False


class TestIsolation:
    """Les clefs ne DOIVENT PAS fuiter entre users."""

    def test_user_a_b_isolated(self, db):
        from api.web_providers import has_user_key_for
        _save_key(db, "alice", "perplexity", "pplx-alice")
        _save_key(db, "bob", "brave", "BSA-bob")

        assert has_user_key_for(db, "alice", "perplexity_search") is True
        assert has_user_key_for(db, "alice", "brave_search") is False
        assert has_user_key_for(db, "bob", "brave_search") is True
        assert has_user_key_for(db, "bob", "perplexity_search") is False


class TestPerplexity:
    @pytest.mark.asyncio
    async def test_missing_key(self, db):
        from api.web_providers import search_perplexity
        r = await search_perplexity(db, "u_no_key", "test query")
        assert r["ok"] is False
        assert r["error"] == "missing_api_key"

    @pytest.mark.asyncio
    async def test_empty_query(self, db):
        from api.web_providers import search_perplexity
        _save_key(db, "u1", "perplexity", "pplx-test")
        r = await search_perplexity(db, "u1", "")
        assert r["ok"] is False
        assert r["error"] == "empty_query"

    @pytest.mark.asyncio
    async def test_happy_path_mocked(self, db):
        from api.web_providers import search_perplexity
        _save_key(db, "u1", "perplexity", "pplx-test-abc")

        mock_response = (200, {
            "choices": [{"message": {"content": "Python est un langage..."}}],
            "citations": ["https://python.org", "https://docs.python.org"],
        })
        with patch("api.web_providers._post_json", AsyncMock(return_value=mock_response)):
            r = await search_perplexity(db, "u1", "qu est ce que python")
        assert r["ok"] is True
        assert r["provider"] == "perplexity"
        assert "Python" in r["answer"]
        assert len(r["results"]) == 2
        assert r["cost_usd"] == 0.005

    @pytest.mark.asyncio
    async def test_api_401(self, db):
        from api.web_providers import search_perplexity
        _save_key(db, "u1", "perplexity", "pplx-bad")

        with patch("api.web_providers._post_json", AsyncMock(return_value=(401, {"error": {"message": "invalid key"}}))):
            r = await search_perplexity(db, "u1", "test")
        assert r["ok"] is False
        assert r["error"] == "http_401"


class TestBrave:
    @pytest.mark.asyncio
    async def test_happy_path(self, db):
        from api.web_providers import search_brave
        _save_key(db, "u1", "brave", "BSA-test")

        mock_response = (200, {
            "web": {
                "results": [
                    {"title": "Result 1", "url": "https://a.com", "description": "desc 1"},
                    {"title": "Result 2", "url": "https://b.com", "description": "desc 2"},
                ]
            }
        })
        with patch("api.web_providers._get_json", AsyncMock(return_value=mock_response)):
            r = await search_brave(db, "u1", "privacy browser")
        assert r["ok"] is True
        assert len(r["results"]) == 2
        assert r["results"][0]["url"] == "https://a.com"


class TestTavily:
    @pytest.mark.asyncio
    async def test_happy_path(self, db):
        from api.web_providers import search_tavily
        _save_key(db, "u1", "tavily", "tvly-test")

        mock_response = (200, {
            "answer": "L'IA est...",
            "results": [
                {"title": "T1", "url": "https://t.com", "content": "ctx", "score": 0.9},
            ],
        })
        with patch("api.web_providers._post_json", AsyncMock(return_value=mock_response)):
            r = await search_tavily(db, "u1", "test")
        assert r["ok"] is True
        assert r["answer"] == "L'IA est..."
        assert r["results"][0]["score"] == 0.9


class TestExa:
    @pytest.mark.asyncio
    async def test_happy_path(self, db):
        from api.web_providers import search_exa
        _save_key(db, "u1", "exa", "exa-test")

        mock_response = (200, {
            "results": [
                {"title": "Exa result", "url": "https://e.com", "text": "long text", "publishedDate": "2025-01-01"},
            ]
        })
        with patch("api.web_providers._post_json", AsyncMock(return_value=mock_response)):
            r = await search_exa(db, "u1", "semantic query")
        assert r["ok"] is True
        assert r["results"][0]["published"] == "2025-01-01"


class TestFirecrawl:
    @pytest.mark.asyncio
    async def test_scrape_ok(self, db):
        from api.web_providers import firecrawl_scrape
        _save_key(db, "u1", "firecrawl", "fc-test")

        mock_response = (200, {
            "data": {"markdown": "# Page\nContent", "metadata": {"title": "Page"}}
        })
        with patch("api.web_providers._post_json", AsyncMock(return_value=mock_response)):
            r = await firecrawl_scrape(db, "u1", "https://example.com")
        assert r["ok"] is True
        assert r["markdown"].startswith("# Page")

    @pytest.mark.asyncio
    async def test_search_ok(self, db):
        from api.web_providers import firecrawl_search
        _save_key(db, "u1", "firecrawl", "fc-test")

        mock_response = (200, {
            "data": [
                {"title": "Doc", "url": "https://d.com", "description": "desc"}
            ]
        })
        with patch("api.web_providers._post_json", AsyncMock(return_value=mock_response)):
            r = await firecrawl_search(db, "u1", "fastapi docs")
        assert r["ok"] is True
        assert len(r["results"]) == 1


class TestXAI:
    @pytest.mark.asyncio
    async def test_happy_path(self, db):
        from api.web_providers import search_xai
        _save_key(db, "u1", "xai", "xai-test")

        mock_response = (200, {
            "choices": [{"message": {"content": "Derniers posts X:\n1. @user1 ..."}}]
        })
        with patch("api.web_providers._post_json", AsyncMock(return_value=mock_response)):
            r = await search_xai(db, "u1", "AI news today")
        assert r["ok"] is True
        assert "@user1" in r["answer"]


class TestInvokeProvider:
    @pytest.mark.asyncio
    async def test_unknown_provider(self, db):
        from api.web_providers import invoke_provider
        r = await invoke_provider(db, "u1", "mystery_tool", {})
        assert r["ok"] is False

    @pytest.mark.asyncio
    async def test_firecrawl_scrape_when_url(self, db):
        from api.web_providers import invoke_provider
        _save_key(db, "u1", "firecrawl", "fc-test")
        with patch("api.web_providers._post_json", AsyncMock(return_value=(200, {"data": {"markdown": "ok"}}))):
            r = await invoke_provider(db, "u1", "firecrawl", {"url": "https://x.com"})
        assert r["ok"] is True

    @pytest.mark.asyncio
    async def test_firecrawl_search_when_query(self, db):
        from api.web_providers import invoke_provider
        _save_key(db, "u1", "firecrawl", "fc-test")
        with patch("api.web_providers._post_json", AsyncMock(return_value=(200, {"data": []}))):
            r = await invoke_provider(db, "u1", "firecrawl", {"query": "test"})
        assert r["ok"] is True

    @pytest.mark.asyncio
    async def test_perplexity_routed(self, db):
        from api.web_providers import invoke_provider
        _save_key(db, "u1", "perplexity", "pplx-test")
        with patch("api.web_providers._post_json", AsyncMock(return_value=(200, {
            "choices": [{"message": {"content": "x"}}],
            "citations": [],
        }))):
            r = await invoke_provider(db, "u1", "perplexity_search", {"query": "test"})
        assert r["ok"] is True
        assert r["provider"] == "perplexity"


class TestMultiUserIsolation:
    """Regression test critique : deux users appellent le MEME tool. Leurs
    cles doivent etre utilisees independamment, aucune fuite."""

    @pytest.mark.asyncio
    async def test_two_users_same_tool_separate_keys(self, db):
        """Alice et Bob ont chacun leur propre cle Perplexity.
        L'appel Alice utilise la cle Alice. Bob utilise la sienne."""
        from api.web_providers import search_perplexity

        _save_key(db, "alice", "perplexity", "pplx-KEY-ALICE")
        _save_key(db, "bob", "perplexity", "pplx-KEY-BOB")

        captured_auth_headers = []

        async def mock_post(url, headers, body, **kw):
            captured_auth_headers.append(headers.get("Authorization"))
            return 200, {"choices": [{"message": {"content": "x"}}], "citations": []}

        with patch("api.web_providers._post_json", side_effect=mock_post):
            await search_perplexity(db, "alice", "q1")
            await search_perplexity(db, "bob", "q2")

        assert captured_auth_headers[0] == "Bearer pplx-KEY-ALICE"
        assert captured_auth_headers[1] == "Bearer pplx-KEY-BOB"
        # Aucune cle n'est leak entre users
        assert "pplx-KEY-BOB" not in captured_auth_headers[0]
        assert "pplx-KEY-ALICE" not in captured_auth_headers[1]
