"""Tests Phase 5d — Health check Gateway + Cost tracker + Contextual filter.

Couvre :
  1. `is_gateway_up` cache TTL + fallback si HTTP fail
  2. `record_external_cost` + `get_external_cost_for_user`
  3. `estimate_tool_cost_usd` (pricing dict + fallback cost_usd du Gateway)
  4. `_openclaw_direct` incremente le cost tracker apres un succes
  5. `tool_subset_for_category` retourne le bon subset
  6. `classify_intent_haiku` fallback 'any' sur erreur + parsing reponse Haiku
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from api.agent3_native_dispatcher import Agent3ActionDispatcher
from api.agent3_tool_classifier import (
    CATEGORIES,
    classify_intent_haiku,
    tool_subset_for_category,
)
from api.openclaw_bridge import (
    _gateway_health_cache,
    get_external_cost_for_user,
    get_gateway_health_status,
    is_gateway_up,
    record_external_cost,
    reset_external_cost,
)
from api.openclaw_tool_schemas import (
    OPENCLAW_TOOL_ESTIMATED_COST_USD,
    estimate_tool_cost_usd,
)
from sylea.core.storage.database import DatabaseManager


@pytest.fixture
def db():
    d = DatabaseManager(db_path=Path(":memory:"))
    d.connect()
    return d


@pytest.fixture
def dispatcher(db):
    return Agent3ActionDispatcher(db=db, user_id="cost_user", session_key="sess")


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset caches entre tests."""
    _gateway_health_cache["is_up"] = None
    _gateway_health_cache["checked_at"] = 0.0
    _gateway_health_cache["last_error"] = ""
    reset_external_cost()
    yield
    _gateway_health_cache["is_up"] = None
    reset_external_cost()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Health check Gateway
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestGatewayHealth:
    async def test_up_when_200(self):
        resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=resp)
            up = await is_gateway_up(force_refresh=True)
        assert up is True
        status = get_gateway_health_status()
        assert status["is_up"] is True
        assert status["last_error"] == ""

    async def test_down_when_500(self):
        resp = MagicMock(status_code=500)
        with patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(return_value=resp)
            up = await is_gateway_up(force_refresh=True)
        assert up is False
        status = get_gateway_health_status()
        assert status["is_up"] is False
        assert "HTTP 500" in status["last_error"]

    async def test_down_on_connection_error(self):
        with patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = AsyncMock(
                side_effect=httpx.ConnectError("refused")
            )
            up = await is_gateway_up(force_refresh=True)
        assert up is False
        status = get_gateway_health_status()
        assert "ConnectError" in status["last_error"]

    async def test_cache_hits_skip_http_call(self):
        resp = MagicMock(status_code=200)
        post_mock = AsyncMock(return_value=resp)
        with patch("httpx.AsyncClient") as m:
            m.return_value.__aenter__.return_value.get = post_mock
            await is_gateway_up(force_refresh=True)  # 1 appel
            await is_gateway_up()                    # cache hit, 0 appel
            await is_gateway_up()                    # cache hit, 0 appel
        # Un seul appel HTTP reel
        assert post_mock.call_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cost tracker per-tool
# ─────────────────────────────────────────────────────────────────────────────

class TestCostTracker:
    def test_record_increments(self):
        record_external_cost("user_a", "image_generate", 0.04)
        record_external_cost("user_a", "image_generate", 0.04)
        record_external_cost("user_a", "perplexity_search", 0.005)
        r = get_external_cost_for_user("user_a")
        assert r["total_usd"] == pytest.approx(0.085, abs=0.0001)
        assert r["by_tool"]["image_generate"]["usd"] == pytest.approx(0.08, abs=0.0001)
        assert r["by_tool"]["image_generate"]["calls"] == 2
        assert r["by_tool"]["perplexity_search"]["calls"] == 1

    def test_different_users_isolated(self):
        record_external_cost("user_a", "video_generate", 0.5)
        record_external_cost("user_b", "image_generate", 0.04)
        a = get_external_cost_for_user("user_a")
        b = get_external_cost_for_user("user_b")
        assert a["total_usd"] == pytest.approx(0.5)
        assert b["total_usd"] == pytest.approx(0.04)
        assert "video_generate" not in b["by_tool"]
        assert "image_generate" not in a["by_tool"]

    def test_zero_cost_still_counts_calls(self):
        record_external_cost("user_z", "web_search", 0.0)  # ddg = gratuit
        record_external_cost("user_z", "web_search", 0.0)
        r = get_external_cost_for_user("user_z")
        assert r["total_usd"] == 0.0
        assert r["by_tool"]["web_search"]["calls"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# 3. Estimate tool cost
# ─────────────────────────────────────────────────────────────────────────────

class TestEstimateToolCost:
    def test_known_paid_tool(self):
        assert estimate_tool_cost_usd("image_generate") == 0.04
        assert estimate_tool_cost_usd("video_generate") == 0.5
        assert estimate_tool_cost_usd("perplexity_search") == 0.005

    def test_known_free_tool(self):
        assert estimate_tool_cost_usd("web_search") == 0.0
        assert estimate_tool_cost_usd("web_fetch") == 0.0
        assert estimate_tool_cost_usd("exec") == 0.0

    def test_unknown_tool_returns_zero(self):
        assert estimate_tool_cost_usd("nonexistent_tool") == 0.0

    def test_real_cost_from_gateway_takes_priority(self):
        # Si le Gateway remonte un cost_usd dans result, on prend cette valeur.
        assert estimate_tool_cost_usd("image_generate", result={"cost_usd": 0.12}) == 0.12
        # Si le Gateway ne remonte rien, on fallback sur pricing dict.
        assert estimate_tool_cost_usd("image_generate", result={"image_url": "x"}) == 0.04
        # Si cost_usd negatif ou invalide, fallback.
        assert estimate_tool_cost_usd("image_generate", result={"cost_usd": -1}) == 0.04

    def test_pricing_dict_has_all_38_tools(self):
        from api.openclaw_tool_schemas import all_anthropic_tool_names
        names = all_anthropic_tool_names()
        for n in names:
            assert n in OPENCLAW_TOOL_ESTIMATED_COST_USD, f"Manque pricing pour {n}"


@pytest.mark.asyncio
class TestDispatcherTracksCost:
    async def test_successful_invocation_records_cost(self, dispatcher):
        fake_resp = {"success": True, "result": {"image_url": "/tmp/img.png"}}
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(return_value=fake_resp),
        ):
            r = await dispatcher.execute("IMAGE_GENERATE", {"args": {"prompt": "cat"}})
        assert r["is_error"] is False
        assert r["raw"]["cost_usd"] == pytest.approx(0.04, abs=0.001)
        tracked = get_external_cost_for_user("cost_user")
        assert tracked["total_usd"] == pytest.approx(0.04)
        assert tracked["by_tool"]["image_generate"]["calls"] == 1

    async def test_real_cost_from_result_used(self, dispatcher):
        fake_resp = {"success": True, "result": {"image_url": "/tmp/x.png", "cost_usd": 0.08}}
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(return_value=fake_resp),
        ):
            r = await dispatcher.execute("IMAGE_GENERATE", {"args": {"prompt": "hd"}})
        assert r["raw"]["cost_usd"] == pytest.approx(0.08, abs=0.001)
        tracked = get_external_cost_for_user("cost_user")
        assert tracked["total_usd"] == pytest.approx(0.08)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Tool subset per category
# ─────────────────────────────────────────────────────────────────────────────

class TestToolSubsetMapping:
    def test_any_returns_none_no_filter(self):
        assert tool_subset_for_category("any") is None

    def test_conversation_is_minimal(self):
        s = tool_subset_for_category("conversation")
        assert s is not None
        # Contient au moins memory + meta-tools clawhub (always-on)
        assert "memory" in s
        assert "memory_search" in s
        assert "clawhub_search" in s
        # Ne contient pas les tools lourds
        assert "image_generate" not in s
        assert "exec" not in s

    def test_media_gen_includes_generators(self):
        s = tool_subset_for_category("media_gen")
        assert s is not None
        assert "image_generate" in s
        assert "music_generate" in s
        assert "video_generate" in s
        assert "voice_generate" in s

    def test_web_research_includes_all_search_engines(self):
        s = tool_subset_for_category("web_research")
        assert s is not None
        for engine in ["search", "perplexity_search", "brave_search", "google_search",
                        "tavily_search", "exa_search", "firecrawl", "web_fetch"]:
            assert engine in s, f"Manque {engine}"

    def test_skill_tool_names_preserved(self):
        s = tool_subset_for_category("conversation", skill_tool_names={"skill_foo", "skill_bar"})
        assert s is not None
        assert "skill_foo" in s
        assert "skill_bar" in s

    def test_unknown_category_returns_none(self):
        assert tool_subset_for_category("not_a_real_category") is None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Classifier Haiku (mocks)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestClassifier:
    async def test_short_conversational_message(self):
        # Tres court, pas d'http/question -> skip classifier, retourne 'conversation'.
        assert await classify_intent_haiku("Merci") == "conversation"
        assert await classify_intent_haiku("ok") == "any"  # < 3 chars -> 'any'

    async def test_missing_api_key_returns_any(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        assert await classify_intent_haiku("Cherche les meilleurs restaurants a Paris") == "any"

    async def test_valid_category_parsed(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

        fake_block = MagicMock()
        fake_block.type = "text"
        fake_block.text = "web_research"
        fake_resp = MagicMock(content=[fake_block])

        fake_client = MagicMock()
        fake_client.messages.create = AsyncMock(return_value=fake_resp)

        result = await classify_intent_haiku("Quel temps fait-il a Paris ?", client=fake_client)
        assert result == "web_research"

    async def test_unexpected_response_fallback(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

        fake_block = MagicMock()
        fake_block.type = "text"
        fake_block.text = "I think this is a web search"  # format invalide

        fake_client = MagicMock()
        fake_client.messages.create = AsyncMock(return_value=MagicMock(content=[fake_block]))

        result = await classify_intent_haiku("Question generique ?", client=fake_client)
        assert result == "any"

    async def test_exception_fallback_to_any(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")

        fake_client = MagicMock()
        fake_client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))

        result = await classify_intent_haiku("Envoie un email a Jean", client=fake_client)
        assert result == "any"  # fallback silencieux

    async def test_all_categories_recognizable(self, monkeypatch):
        # Verifie qu'on peut matcher chacune des categories sans ambiguite.
        for cat in CATEGORIES:
            if cat == "any":
                continue
            monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
            fake_block = MagicMock()
            fake_block.type = "text"
            fake_block.text = cat
            fake_client = MagicMock()
            fake_client.messages.create = AsyncMock(
                return_value=MagicMock(content=[fake_block])
            )
            r = await classify_intent_haiku("test message long enough", client=fake_client)
            assert r == cat, f"Classifier a mal parse la categorie '{cat}' -> '{r}'"
