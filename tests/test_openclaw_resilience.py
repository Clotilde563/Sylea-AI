"""Tests des 4 couches de resilience d'openclaw_invoke_tool :
  1. Full jitter backoff (anti thundering herd)
  2. Respect du header Retry-After (cap 30s)
  3. Metrics counters par (tool, event)
  4. Circuit breaker per-tool (isolation des pannes)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from api.openclaw_bridge import (
    CircuitBreaker,
    _compute_backoff_with_jitter,
    _parse_retry_after,
    _per_tool_breakers,
    get_all_breakers_stats,
    get_breaker_for_tool,
    get_retry_metrics,
    openclaw_invoke_tool,
    reset_retry_metrics,
)


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset metrics + breakers per-tool entre chaque test."""
    reset_retry_metrics()
    _per_tool_breakers.clear()
    yield
    reset_retry_metrics()
    _per_tool_breakers.clear()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Full jitter backoff
# ─────────────────────────────────────────────────────────────────────────────

class TestJitter:
    def test_jitter_is_bounded(self):
        # Pour attempt=0, max = min(30, 1) = 1s. Full jitter => [0, 1).
        for _ in range(100):
            b = _compute_backoff_with_jitter(0)
            assert 0.0 <= b <= 1.0

    def test_jitter_grows_exponentially_capped(self):
        # attempt=5 => max = min(30, 32) = 30. Full jitter => [0, 30].
        for _ in range(50):
            b = _compute_backoff_with_jitter(5)
            assert 0.0 <= b <= 30.0

    def test_jitter_cap_prevents_huge_delays(self):
        # attempt=20 => 2^20 = 1M secondes, mais cap a 30s.
        for _ in range(20):
            b = _compute_backoff_with_jitter(20, cap=30.0)
            assert b <= 30.0

    def test_jitter_spreads_retries(self):
        # 100 "clients" retry en meme temps. Verifier qu'ils ne se synchronisent pas.
        samples = [_compute_backoff_with_jitter(2) for _ in range(100)]
        # Au moins 20 valeurs distinctes (bien etale)
        distinct = len(set(round(s, 2) for s in samples))
        assert distinct >= 20, f"Seulement {distinct} valeurs distinctes — jitter faible ?"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Retry-After parsing
# ─────────────────────────────────────────────────────────────────────────────

class TestRetryAfter:
    def test_parse_seconds(self):
        assert _parse_retry_after("5") == 5.0
        assert _parse_retry_after("  10  ") == 10.0

    def test_parse_caps_at_30(self):
        assert _parse_retry_after("120") == 30.0  # cap par defaut
        assert _parse_retry_after("120", cap=60.0) == 60.0

    def test_parse_negative_rejected(self):
        assert _parse_retry_after("-5") is None

    def test_parse_empty_returns_none(self):
        assert _parse_retry_after("") is None
        assert _parse_retry_after("   ") is None
        assert _parse_retry_after(None or "") is None

    def test_parse_http_date_returns_none(self):
        # On ne supporte pas HTTP-date, on renvoie None pour fallback jitter
        assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Metrics counters
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestMetrics:
    async def test_success_records_attempt_and_success(self):
        fake_resp = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        with patch("httpx.AsyncClient") as m_client:
            m_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_resp)
            await openclaw_invoke_tool("browser", args={})
        m = get_retry_metrics()
        assert m.get("browser__attempt") == 1
        assert m.get("browser__success") == 1
        assert m.get("browser__failure", 0) == 0

    async def test_failure_records_failure(self):
        fake_resp = MagicMock(status_code=404, text="not found", headers={})
        with patch("httpx.AsyncClient") as m_client:
            m_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_resp)
            r = await openclaw_invoke_tool("browser", args={})
        assert r["success"] is False
        m = get_retry_metrics()
        assert m.get("browser__attempt") == 1
        assert m.get("browser__failure") == 1
        assert m.get("browser__http_404") == 1

    async def test_503_records_retry_with_retry_after(self, monkeypatch):
        # Premier call : 503 avec Retry-After: 1. Second call : 200.
        resp_503 = MagicMock(status_code=503, headers={"retry-after": "1"})
        resp_200 = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        call_count = {"n": 0}

        async def fake_post(*args, **kwargs):
            call_count["n"] += 1
            return resp_503 if call_count["n"] == 1 else resp_200

        # Evite le vrai sleep
        monkeypatch.setattr("asyncio.sleep", AsyncMock())

        with patch("httpx.AsyncClient") as m_client:
            m_client.return_value.__aenter__.return_value.post = fake_post
            r = await openclaw_invoke_tool("exec", args={})

        assert r["success"] is True
        m = get_retry_metrics()
        assert m.get("exec__http_503") == 1
        assert m.get("exec__retry") == 1
        assert m.get("exec__retry_after_honored") == 1
        assert m.get("exec__success") == 1

    async def test_504_records_retry_without_retry_after(self, monkeypatch):
        # 504 n'est pas dans RETRY_AFTER_STATUS (qui est 429, 503), donc
        # il prend le chemin jitter backoff sans honorer un header.
        resp_504 = MagicMock(status_code=504, headers={})
        resp_200 = MagicMock(status_code=200, json=MagicMock(return_value={"ok": True}))
        call_count = {"n": 0}

        async def fake_post(*args, **kwargs):
            call_count["n"] += 1
            return resp_504 if call_count["n"] == 1 else resp_200

        monkeypatch.setattr("asyncio.sleep", AsyncMock())
        with patch("httpx.AsyncClient") as m_client:
            m_client.return_value.__aenter__.return_value.post = fake_post
            r = await openclaw_invoke_tool("image_generate", args={})

        assert r["success"] is True
        m = get_retry_metrics()
        assert m.get("image_generate__http_504") == 1
        assert m.get("image_generate__retry") == 1
        assert m.get("image_generate__retry_after_honored", 0) == 0

    async def test_timeout_records_timeout(self, monkeypatch):
        call_count = {"n": 0}

        async def fake_post(*args, **kwargs):
            call_count["n"] += 1
            raise httpx.TimeoutException("read timeout")

        monkeypatch.setattr("asyncio.sleep", AsyncMock())
        with patch("httpx.AsyncClient") as m_client:
            m_client.return_value.__aenter__.return_value.post = fake_post
            r = await openclaw_invoke_tool("bash", args={})

        assert r["success"] is False
        m = get_retry_metrics()
        # 1 initial + 2 retries = 3 timeouts, 2 retries enregistres
        assert m.get("bash__timeout") == 3
        assert m.get("bash__retry") == 2
        assert m.get("bash__failure") == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. Circuit breaker per-tool
# ─────────────────────────────────────────────────────────────────────────────

class TestPerToolBreaker:
    def test_different_tools_get_different_breakers(self):
        b1 = get_breaker_for_tool("browser")
        b2 = get_breaker_for_tool("exec")
        assert b1 is not b2
        assert b1.name == "browser"
        assert b2.name == "exec"

    def test_same_tool_returns_same_breaker(self):
        b1 = get_breaker_for_tool("browser")
        b2 = get_breaker_for_tool("browser")
        assert b1 is b2

    def test_breaker_opens_per_tool_isolation(self):
        # Casse 'browser' : il ouvre son breaker. 'exec' reste closed.
        b_browser = get_breaker_for_tool("browser")
        b_exec = get_breaker_for_tool("exec")
        for _ in range(5):
            b_browser.record_failure()
        assert b_browser.state == "open"
        assert b_exec.state == "closed"

    def test_all_stats_contains_global_and_per_tool(self):
        get_breaker_for_tool("browser")
        get_breaker_for_tool("exec")
        stats = get_all_breakers_stats()
        assert "global" in stats
        assert "browser" in stats
        assert "exec" in stats

    def test_breaker_base_attributes(self):
        b = CircuitBreaker(failure_threshold=3, recovery_timeout=30, name="test_tool")
        assert b.state == "closed"
        assert b.can_execute() is True
        b.record_failure()
        b.record_failure()
        assert b.state == "closed"  # threshold = 3
        b.record_failure()
        assert b.state == "open"
        assert b.can_execute() is False
        b.record_success()
        assert b.state == "closed"


@pytest.mark.asyncio
class TestBreakerInIntegration:
    async def test_circuit_open_rejected_fast(self, monkeypatch):
        # Ouvre manuellement le breaker de 'browser', puis verifie qu'un appel
        # est rejete instantanement (pas de HTTP call).
        b = get_breaker_for_tool("browser")
        for _ in range(5):
            b.record_failure()
        assert b.state == "open"

        post_mock = AsyncMock()
        with patch("httpx.AsyncClient") as m_client:
            m_client.return_value.__aenter__.return_value.post = post_mock
            r = await openclaw_invoke_tool("browser", args={"url": "https://example.com"})

        assert r["success"] is False
        assert "indisponible" in r["error"].lower() or "circuit" in r["error"].lower() or "echecs" in r["error"].lower()
        post_mock.assert_not_called()  # pas d'appel reseau !
        m = get_retry_metrics()
        assert m.get("browser__circuit_open_rejected") == 1

    async def test_other_tools_unaffected_when_breaker_open(self, monkeypatch):
        # 'browser' breaker est ouvert. 'exec' doit marcher normalement.
        b = get_breaker_for_tool("browser")
        for _ in range(5):
            b.record_failure()
        assert b.state == "open"

        fake_resp = MagicMock(status_code=200, json=MagicMock(return_value={"result": "ok"}))
        with patch("httpx.AsyncClient") as m_client:
            m_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=fake_resp)
            r_exec = await openclaw_invoke_tool("exec", args={"command": "ls"})

        assert r_exec["success"] is True
