"""Fixtures pytest pour les tests e2e OpenClaw.

Les markers et options pytest sont dans `tests/conftest.py` (racine).
Ce fichier contient uniquement les fixtures spécifiques aux e2e.
"""

from __future__ import annotations

import pytest_asyncio

from tests.e2e.mock_openclaw_gateway import MockGateway


@pytest_asyncio.fixture
async def mock_gateway(monkeypatch):
    """Spawn un Mock Gateway local sur port libre, override OPENCLAW_GATEWAY_URL.

    Reset aussi les caches globaux (breakers, health, retry metrics) entre tests
    pour eviter les fuites d'etat.
    """
    # Reset caches globaux AVANT le test
    from api.openclaw_bridge import (
        _gateway_health_cache, _per_tool_breakers,
        reset_retry_metrics, reset_external_cost, reset_tool_latencies,
        reset_daily_cost,
    )
    _gateway_health_cache["is_up"] = None
    _gateway_health_cache["checked_at"] = 0.0
    _gateway_health_cache["last_error"] = ""
    _per_tool_breakers.clear()
    reset_retry_metrics()
    reset_external_cost()
    reset_tool_latencies()
    reset_daily_cost()

    mock = MockGateway()
    await mock.start()
    # Override l'URL Gateway utilisee par api.openclaw_bridge.
    monkeypatch.setattr("api.openclaw_bridge.OPENCLAW_GATEWAY_URL", mock.url)
    try:
        yield mock
    finally:
        await mock.stop()
