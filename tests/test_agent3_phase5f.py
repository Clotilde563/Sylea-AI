"""Tests Phase 5f — Latence p50/p95/p99 + Cost cap journalier.

Couvre :
  1. `record_tool_latency` + `get_tool_latency_stats` : bounded deque + percentiles.
  2. `check_daily_cost_cap` : verification pre-call (allowed/refused).
  3. `record_daily_cost` + `get_daily_cost_for_user` : cumul jour.
  4. Integration dispatcher : appel bloque si cap atteint avant invocation.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.agent3_native_dispatcher import Agent3ActionDispatcher
from api.openclaw_bridge import (
    DEFAULT_DAILY_COST_CAP_USD,
    check_daily_cost_cap,
    get_daily_cost_for_user,
    get_tool_latency_stats,
    record_daily_cost,
    record_tool_latency,
    reset_daily_cost,
    reset_tool_latencies,
)
from sylea.core.storage.database import DatabaseManager


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Shared-DB (sync + async) — migration PG."""
    from tests.conftest import make_shared_db, dispose_shared_db
    d = make_shared_db(tmp_path, monkeypatch)
    yield d
    dispose_shared_db(d)


@pytest.fixture
def dispatcher(db):
    return Agent3ActionDispatcher(db=db, user_id="phase5f_user", session_key="sess")


@pytest.fixture(autouse=True)
def _reset_state():
    reset_tool_latencies()
    reset_daily_cost()
    yield
    reset_tool_latencies()
    reset_daily_cost()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Latences
# ─────────────────────────────────────────────────────────────────────────────

class TestLatencyTracking:
    def test_record_and_stats(self):
        # 10 appels pour image_generate, durees 0.5s a 5.0s
        for i in range(10):
            record_tool_latency("image_generate", 0.5 + i * 0.5)
        stats = get_tool_latency_stats()
        assert "image_generate" in stats
        s = stats["image_generate"]
        assert s["count"] == 10
        assert s["min_ms"] == 500.0
        assert s["max_ms"] == 5000.0
        assert 500.0 <= s["p50_ms"] <= 5000.0
        assert s["p95_ms"] >= s["p50_ms"]
        assert s["p99_ms"] >= s["p95_ms"]
        assert s["avg_ms"] == pytest.approx(2750.0, abs=1.0)

    def test_bounded_window(self):
        # Envoie 150 durees, garde 100
        for i in range(150):
            record_tool_latency("browser", float(i) / 100.0)
        stats = get_tool_latency_stats()
        assert stats["browser"]["count"] == 100

    def test_outliers_rejected(self):
        record_tool_latency("exec", -1.0)  # negatif rejete
        record_tool_latency("exec", 5000.0)  # > 3600s rejete
        record_tool_latency("exec", 0.1)  # ok
        stats = get_tool_latency_stats()
        assert stats.get("exec", {}).get("count", 0) == 1

    def test_multiple_tools_isolated(self):
        record_tool_latency("browser", 1.0)
        record_tool_latency("image_generate", 5.0)
        stats = get_tool_latency_stats()
        assert stats["browser"]["count"] == 1
        assert stats["image_generate"]["count"] == 1
        assert stats["browser"]["p50_ms"] == 1000.0
        assert stats["image_generate"]["p50_ms"] == 5000.0

    def test_percentile_calculation(self):
        # 100 durees uniformement distribuees de 0.01 a 1.00s
        for i in range(1, 101):
            record_tool_latency("test_tool", i / 100.0)
        stats = get_tool_latency_stats()
        s = stats["test_tool"]
        # p50 devrait etre autour de 500ms
        assert 490 <= s["p50_ms"] <= 510
        # p95 autour de 950ms
        assert 940 <= s["p95_ms"] <= 960
        # p99 autour de 990ms
        assert 980 <= s["p99_ms"] <= 1000


# ─────────────────────────────────────────────────────────────────────────────
# 2. Daily cost cap
# ─────────────────────────────────────────────────────────────────────────────

class TestDailyCostCap:
    def test_allowed_below_cap(self):
        allowed, current, pct = check_daily_cost_cap("user_x", 0.5, cap_usd=5.0)
        assert allowed is True
        assert current == 0.0
        assert pct == pytest.approx(10.0, abs=0.5)

    def test_allowed_at_exact_cap(self):
        record_daily_cost("user_y", 4.5)
        allowed, current, pct = check_daily_cost_cap("user_y", 0.5, cap_usd=5.0)
        assert allowed is True
        assert current == pytest.approx(4.5)
        assert pct == pytest.approx(100.0, abs=0.5)

    def test_refused_above_cap(self):
        record_daily_cost("user_z", 4.8)
        allowed, current, pct = check_daily_cost_cap("user_z", 0.5, cap_usd=5.0)
        assert allowed is False
        assert pct > 100.0

    def test_cap_zero_disables_check(self):
        # cap=0 est interprete comme "pas de limite"
        allowed, _, _ = check_daily_cost_cap("user_q", 1000.0, cap_usd=0.0)
        assert allowed is True

    def test_users_isolated(self):
        record_daily_cost("user_a", 4.9)
        allowed_a, _, _ = check_daily_cost_cap("user_a", 0.5, cap_usd=5.0)
        allowed_b, _, _ = check_daily_cost_cap("user_b", 0.5, cap_usd=5.0)
        assert allowed_a is False
        assert allowed_b is True


# ─────────────────────────────────────────────────────────────────────────────
# 3. Integration dispatcher : bloque au-dessus du cap
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestDispatcherCostCap:
    async def test_below_cap_call_proceeds(self, dispatcher):
        fake_resp = {"success": True, "result": {"image_url": "/tmp/x.png"}}
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(return_value=fake_resp),
        ) as m:
            r = await dispatcher.execute("IMAGE_GENERATE", {"args": {"prompt": "cat"}})
        assert r["is_error"] is False
        m.assert_awaited_once()

    async def test_cap_exceeded_blocks_call(self, dispatcher):
        # Pre-charge le cumul journalier proche du cap default ($5)
        record_daily_cost("phase5f_user", 4.99)
        fake_invoke = AsyncMock()
        with patch("api.openclaw_bridge.openclaw_invoke_tool", new=fake_invoke):
            # image_generate coute ~$0.04, total projete = $5.03 > $5 cap defaut
            r = await dispatcher.execute("IMAGE_GENERATE", {"args": {"prompt": "x"}})
        assert r["is_error"] is True
        assert "budget" in r["content"].lower() or "limite" in r["content"].lower()
        assert r["raw"].get("cost_cap_exceeded") is True
        # L'appel n'a pas ete fait au Gateway
        fake_invoke.assert_not_called()

    async def test_zero_cost_tool_not_blocked(self, dispatcher):
        # web_search est gratuit ($0.00), meme si cumul jour eleve ca passe
        record_daily_cost("phase5f_user", 4.99)
        fake_resp = {"success": True, "result": {"results": []}}
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(return_value=fake_resp),
        ) as m:
            r = await dispatcher.execute("WEB_SEARCH", {"args": {"query": "ai"}})
        assert r["is_error"] is False
        m.assert_awaited_once()

    async def test_default_cap_respected(self):
        assert DEFAULT_DAILY_COST_CAP_USD > 0
        assert DEFAULT_DAILY_COST_CAP_USD <= 100  # sanity : pas 1000$

    async def test_user_pref_overrides_default(self, db):
        # Configure un cap custom de 0.01$ pour ce user via preferences
        from api.routers.agent3_openclaw import _ensure_agent3_tables_async, _save_user_preferences_async
        await _ensure_agent3_tables_async()
        await _save_user_preferences_async("tight_user", {
            "external_cost_cap_usd_per_day": 0.01,
        })
        dispatcher_tight = Agent3ActionDispatcher(
            db=db, user_id="tight_user", session_key="sess",
        )
        fake_invoke = AsyncMock()
        with patch("api.openclaw_bridge.openclaw_invoke_tool", new=fake_invoke):
            # image_generate coute $0.04 > $0.01 cap user
            r = await dispatcher_tight.execute("IMAGE_GENERATE", {"args": {"prompt": "x"}})
        assert r["is_error"] is True
        assert r["raw"]["cost_cap_exceeded"] is True
        assert r["raw"]["cap_usd"] == 0.01
        fake_invoke.assert_not_called()
