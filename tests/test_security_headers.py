"""Tests pour le middleware SecurityHeadersMiddleware."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.security_headers import (
    SecurityHeadersMiddleware,
    _build_csp,
    _build_permissions_policy,
    _get_mode,
    get_security_headers_config,
)


@pytest.fixture
def app_with_headers(monkeypatch):
    # Conftest désactive globalement les headers ; on les ré-active ici.
    monkeypatch.delenv("SYLEA_DISABLE_SECURITY_HEADERS", raising=False)
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


@pytest.fixture
def client(app_with_headers):
    return TestClient(app_with_headers)


def test_csp_header_is_set(client):
    r = client.get("/ping")
    assert r.status_code == 200
    csp = r.headers.get("Content-Security-Policy")
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp


def test_x_content_type_nosniff(client):
    r = client.get("/ping")
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_x_frame_options_deny(client):
    r = client.get("/ping")
    assert r.headers.get("X-Frame-Options") == "DENY"


def test_referrer_policy(client):
    r = client.get("/ping")
    assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_permissions_policy_includes_microphone_self(client):
    r = client.get("/ping")
    pp = r.headers.get("Permissions-Policy", "")
    assert "microphone=(self)" in pp
    assert "geolocation=(self)" in pp
    assert "camera=()" in pp


def test_coop_and_corp(client):
    r = client.get("/ping")
    assert r.headers.get("Cross-Origin-Opener-Policy") == "same-origin"
    assert r.headers.get("Cross-Origin-Resource-Policy") == "same-site"


def test_hsts_only_in_strict_mode(monkeypatch):
    # Force le mode strict via env + ré-active les headers
    monkeypatch.delenv("SYLEA_DISABLE_SECURITY_HEADERS", raising=False)
    monkeypatch.setenv("SYLEA_SECURITY_HEADERS_MODE", "strict")
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/ping")
    hsts = r.headers.get("Strict-Transport-Security", "")
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts
    assert "preload" in hsts


def test_hsts_absent_in_dev_mode(monkeypatch):
    monkeypatch.delenv("SYLEA_DISABLE_SECURITY_HEADERS", raising=False)
    monkeypatch.setenv("SYLEA_SECURITY_HEADERS_MODE", "dev")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/ping")
    assert r.headers.get("Strict-Transport-Security") is None


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("SYLEA_DISABLE_SECURITY_HEADERS", "true")
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    client = TestClient(app)
    r = client.get("/ping")
    assert r.headers.get("Content-Security-Policy") is None
    assert r.headers.get("X-Frame-Options") is None


def test_csp_dev_mode_allows_unsafe_eval():
    csp = _build_csp("dev")
    assert "'unsafe-eval'" in csp


def test_csp_strict_mode_no_unsafe_eval():
    csp = _build_csp("strict")
    assert "'unsafe-eval'" not in csp


def test_csp_includes_anthropic_api():
    csp = _build_csp("strict")
    assert "https://api.anthropic.com" in csp


def test_csp_strict_includes_upgrade_insecure():
    csp = _build_csp("strict")
    assert "upgrade-insecure-requests" in csp


def test_csp_extra_script_src(monkeypatch):
    monkeypatch.setenv("SYLEA_CSP_EXTRA_SCRIPT_SRC", "https://cdn.example.com,https://gtm.example.com")
    csp = _build_csp("strict")
    assert "https://cdn.example.com" in csp
    assert "https://gtm.example.com" in csp


def test_get_mode_strict_when_postgres(monkeypatch):
    monkeypatch.delenv("SYLEA_SECURITY_HEADERS_MODE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host/db")
    assert _get_mode() == "strict"


def test_get_mode_dev_when_no_pg(monkeypatch):
    monkeypatch.delenv("SYLEA_SECURITY_HEADERS_MODE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _get_mode() == "dev"


def test_get_security_headers_config_returns_dict(monkeypatch):
    monkeypatch.delenv("SYLEA_DISABLE_SECURITY_HEADERS", raising=False)
    cfg = get_security_headers_config()
    assert "mode" in cfg
    assert "csp_length" in cfg
    assert cfg["csp_length"] > 100  # CSP non-vide


def test_permissions_policy_well_formed():
    pp = _build_permissions_policy()
    # Toutes les directives sont séparées par ", "
    parts = [p.strip() for p in pp.split(",")]
    # Chaque directive est `nom=(...)`
    for p in parts:
        assert "=" in p
        assert p.count("(") == 1
        assert p.endswith(")")
