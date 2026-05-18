"""Tests pour api.error_tracking (Sentry)."""

from __future__ import annotations

import importlib

import pytest

import api.error_tracking as et


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    et._initialized = False
    monkeypatch.delenv("SENTRY_DSN", raising=False)


def test_init_noop_without_dsn():
    assert et.init_sentry() is False
    assert et.is_initialized() is False


def test_capture_exception_safe_without_init():
    """Doit jamais crasher même si Sentry n'est pas init."""
    try:
        raise ValueError("test")
    except ValueError as e:
        et.capture_exception(e)  # ne doit pas raise


def test_capture_message_safe_without_init():
    et.capture_message("test", level="info")  # ne doit pas raise


def test_set_user_safe_without_init():
    et.set_user("u-1", tier="free")  # ne doit pas raise


def test_get_config_without_init():
    cfg = et.get_config()
    assert cfg["initialized"] is False
    assert cfg["dsn_present"] is False


def test_get_config_with_dsn(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://abc@sentry.io/123")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "test")
    monkeypatch.setenv("SENTRY_RELEASE", "1.0.0")
    cfg = et.get_config()
    assert cfg["dsn_present"] is True
    assert cfg["environment"] == "test"
    assert cfg["release"] == "1.0.0"


def test_before_send_drops_401():
    """Les 401 ne doivent pas être envoyées à Sentry."""
    class FakeHttpError(Exception):
        status_code = 401

    event = {"request": {}}
    try:
        raise FakeHttpError()
    except FakeHttpError:
        import sys
        result = et._before_send(event, {"exc_info": sys.exc_info()})
    assert result is None


def test_before_send_drops_429():
    class FakeRateLimitError(Exception):
        status_code = 429

    event = {"request": {}}
    try:
        raise FakeRateLimitError()
    except FakeRateLimitError:
        import sys
        result = et._before_send(event, {"exc_info": sys.exc_info()})
    assert result is None


def test_before_send_keeps_500():
    """Les vraies erreurs (500) doivent passer."""
    class InternalError(Exception):
        pass

    event = {"request": {}}
    try:
        raise InternalError("boom")
    except InternalError:
        import sys
        result = et._before_send(event, {"exc_info": sys.exc_info()})
    assert result is not None


def test_before_send_scrubs_auth_header():
    event = {
        "request": {
            "headers": {
                "Authorization": "Bearer secret-token-123",
                "Cookie": "session=abc",
                "X-API-Key": "key-456",
                "User-Agent": "Mozilla/5.0",
            },
            "query_string": "password=secret",
            "data": {"password": "secret"},
        },
    }
    result = et._before_send(event, {})
    assert result is not None
    headers = result["request"]["headers"]
    assert headers["Authorization"] == "[REDACTED]"
    assert headers["Cookie"] == "[REDACTED]"
    assert headers["X-API-Key"] == "[REDACTED]"
    assert headers["User-Agent"] == "Mozilla/5.0"  # non sensible
    assert "query_string" not in result["request"]
    assert "data" not in result["request"]


def test_before_send_adds_request_id_tag():
    from api.logging_setup import _request_id
    _request_id.set("test-rid-789")
    try:
        event = {"request": {}}
        result = et._before_send(event, {})
        assert result is not None
        assert result["tags"]["request_id"] == "test-rid-789"
    finally:
        _request_id.set(None)
