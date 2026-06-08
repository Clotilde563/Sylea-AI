"""Tests pour api.actions_counter."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_unauth_returns_defaults():
    """Sans user_id, doit renvoyer les valeurs free par défaut."""
    from api.actions_counter import get_actions_status_async
    result = await get_actions_status_async(None)
    assert result["plan"] == "free"
    assert result["limit"] == 10
    assert result["remaining"] == 10
    assert result["used"] == 0
    assert result["is_unlimited"] is False
    assert "reset_at" in result


@pytest.mark.asyncio
async def test_status_free_user():
    """Free user avec 3 actions consommées doit voir 7 restantes."""
    from api.actions_counter import get_actions_status_async

    with patch("api.agent3_quotas.get_user_plan_async") as mock_plan, \
         patch("api.daily_action_limit.count_user_actions_today_async") as mock_count, \
         patch("api.actions_counter._get_profil_id_for_user") as mock_profil:
        mock_plan.return_value = {"name": "free"}
        mock_count.return_value = 3
        mock_profil.return_value = "profil-1"

        result = await get_actions_status_async("user-1")

    assert result["plan"] == "free"
    assert result["limit"] == 10
    assert result["used"] == 3
    assert result["remaining"] == 7
    assert result["is_unlimited"] is False


@pytest.mark.asyncio
async def test_status_pro_user():
    """Pro user a 30 actions/jour."""
    from api.actions_counter import get_actions_status_async

    with patch("api.agent3_quotas.get_user_plan_async") as mock_plan, \
         patch("api.daily_action_limit.count_user_actions_today_async") as mock_count, \
         patch("api.actions_counter._get_profil_id_for_user") as mock_profil:
        mock_plan.return_value = {"name": "pro"}
        mock_count.return_value = 12
        mock_profil.return_value = "profil-1"

        result = await get_actions_status_async("user-1")

    assert result["plan"] == "pro"
    assert result["limit"] == 30
    assert result["used"] == 12
    assert result["remaining"] == 18
    assert result["is_unlimited"] is False


@pytest.mark.asyncio
async def test_status_team_unlimited():
    """Team user : illimité."""
    from api.actions_counter import get_actions_status_async

    with patch("api.agent3_quotas.get_user_plan_async") as mock_plan, \
         patch("api.daily_action_limit.count_user_actions_today_async") as mock_count, \
         patch("api.actions_counter._get_profil_id_for_user") as mock_profil:
        mock_plan.return_value = {"name": "team"}
        mock_count.return_value = 200
        mock_profil.return_value = "profil-1"

        result = await get_actions_status_async("user-1")

    assert result["plan"] == "team"
    assert result["limit"] == -1
    assert result["remaining"] == -1
    assert result["is_unlimited"] is True


@pytest.mark.asyncio
async def test_quota_exceeded_clamps_remaining_to_zero():
    """Si used > limit (cas bord), remaining doit rester 0 (pas négatif)."""
    from api.actions_counter import get_actions_status_async

    with patch("api.agent3_quotas.get_user_plan_async") as mock_plan, \
         patch("api.daily_action_limit.count_user_actions_today_async") as mock_count, \
         patch("api.actions_counter._get_profil_id_for_user") as mock_profil:
        mock_plan.return_value = {"name": "free"}
        mock_count.return_value = 15  # dépassement (limite = 10)
        mock_profil.return_value = "profil-1"

        result = await get_actions_status_async("user-1")

    assert result["remaining"] == 0
    assert result["used"] == 15


@pytest.mark.asyncio
async def test_reset_at_format():
    """reset_at doit être un ISO timestamp UTC du prochain minuit."""
    from datetime import datetime
    from api.actions_counter import get_actions_status_async

    result = await get_actions_status_async(None)
    parsed = datetime.fromisoformat(result["reset_at"])
    assert parsed.tzinfo is not None
    assert parsed.hour == 0
    assert parsed.minute == 0


@pytest.mark.asyncio
async def test_endpoint_returns_correct_shape():
    """GET /api/actions/today doit renvoyer la bonne structure JSON."""
    from fastapi.testclient import TestClient
    from api.main import app

    client = TestClient(app)
    r = client.get("/api/actions/today")
    assert r.status_code == 200
    body = r.json()
    assert "used" in body
    assert "limit" in body
    assert "remaining" in body
    assert "plan" in body
    assert "is_unlimited" in body
    assert "reset_at" in body
