"""Tests pour api.logging_setup."""

from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.logging_setup import (
    JsonFormatter,
    HumanReadableFormatter,
    RequestContextMiddleware,
    TimedOperation,
    configure_logging,
    get_logger,
    get_request_id,
    set_user_context,
    _request_id,
    _user_id,
    _user_tier,
)


@pytest.fixture(autouse=True)
def reset_context():
    """Reset des contextvars entre tests."""
    _request_id.set(None)
    _user_id.set(None)
    _user_tier.set(None)
    yield
    _request_id.set(None)
    _user_id.set(None)
    _user_tier.set(None)


def _capture_json_log(record_args: dict | None = None) -> dict:
    """Helper : formate un LogRecord et retourne le JSON parsé."""
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="t.py",
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    if record_args:
        for k, v in record_args.items():
            setattr(record, k, v)
    output = formatter.format(record)
    return json.loads(output)


def test_json_formatter_basic():
    payload = _capture_json_log()
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test"
    assert "ts" in payload


def test_json_formatter_includes_request_id():
    _request_id.set("req-abc-123")
    payload = _capture_json_log()
    assert payload["request_id"] == "req-abc-123"


def test_json_formatter_includes_user_context():
    _request_id.set("r1")
    _user_id.set("u-42")
    _user_tier.set("enterprise")
    payload = _capture_json_log()
    assert payload["user_id"] == "u-42"
    assert payload["user_tier"] == "enterprise"


def test_json_formatter_extra_fields():
    payload = _capture_json_log({"custom_field": "custom_value", "duration_ms": 42.5})
    assert payload["custom_field"] == "custom_value"
    assert payload["duration_ms"] == 42.5


def test_json_formatter_handles_non_serializable():
    """Les valeurs non sérialisables sont converties via repr() au lieu de crasher."""
    class Weird:
        def __repr__(self):
            return "<Weird>"
    payload = _capture_json_log({"weird": Weird()})
    assert payload["weird"] == "<Weird>"


def test_json_formatter_exception_info():
    formatter = JsonFormatter()
    try:
        raise ValueError("test error")
    except ValueError:
        import sys
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="t.py", lineno=1,
            msg="oops", args=(), exc_info=sys.exc_info(),
        )
    payload = json.loads(formatter.format(record))
    assert payload["exception"]["type"] == "ValueError"
    assert "test error" in payload["exception"]["message"]


def test_human_readable_formatter():
    formatter = HumanReadableFormatter(use_color=False)
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname="t.py", lineno=1,
        msg="hello", args=(), exc_info=None,
    )
    out = formatter.format(record)
    assert "INFO" in out
    assert "hello" in out


# ─── Middleware FastAPI ──────────────────────────────────────────────────────

@pytest.fixture
def app_with_middleware():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def ping():
        return {"request_id": get_request_id()}

    return app


def test_middleware_generates_request_id(app_with_middleware):
    client = TestClient(app_with_middleware)
    r = client.get("/ping")
    assert r.status_code == 200
    body_rid = r.json()["request_id"]
    header_rid = r.headers.get("X-Request-Id")
    assert body_rid == header_rid
    assert len(body_rid) >= 16  # UUID-ish


def test_middleware_propagates_incoming_request_id(app_with_middleware):
    client = TestClient(app_with_middleware)
    r = client.get("/ping", headers={"X-Request-Id": "client-supplied-id"})
    assert r.json()["request_id"] == "client-supplied-id"
    assert r.headers["X-Request-Id"] == "client-supplied-id"


def test_middleware_rejects_overlong_id(app_with_middleware):
    long_id = "x" * 500
    client = TestClient(app_with_middleware)
    r = client.get("/ping", headers={"X-Request-Id": long_id})
    # Doit générer un UUID au lieu d'accepter le very long
    assert r.json()["request_id"] != long_id


# ─── Timed operation ──────────────────────────────────────────────────────────

def test_timed_operation_logs_duration(caplog):
    caplog.set_level(logging.INFO)
    logger = get_logger("test_timed")
    with TimedOperation("my_op", logger, extra_field="value"):
        pass
    records = [r for r in caplog.records if "my_op" in r.message]
    assert len(records) >= 1
    completed = [r for r in records if "completed" in r.message]
    assert len(completed) == 1
    # extra fields posés sur le record
    assert hasattr(completed[0], "duration_ms")


def test_timed_operation_logs_exception(caplog):
    caplog.set_level(logging.DEBUG)
    logger = get_logger("test_timed")
    with pytest.raises(ValueError):
        with TimedOperation("failing_op", logger):
            raise ValueError("boom")
    failed = [r for r in caplog.records if "failing_op failed" in r.message]
    assert len(failed) == 1


# ─── Set user context ─────────────────────────────────────────────────────────

def test_set_user_context():
    set_user_context(user_id="u-1", tier="enterprise")
    payload = _capture_json_log()
    assert payload["user_id"] == "u-1"
    assert payload["user_tier"] == "enterprise"


# ─── configure_logging idempotency ────────────────────────────────────────────

def test_configure_logging_does_not_duplicate_handlers():
    configure_logging()
    handler_count_1 = len(logging.getLogger().handlers)
    configure_logging()
    handler_count_2 = len(logging.getLogger().handlers)
    assert handler_count_1 == handler_count_2
