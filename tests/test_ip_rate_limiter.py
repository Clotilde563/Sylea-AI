"""Tests pour le middleware IPRateLimitMiddleware."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_ip_limit(monkeypatch):
    # Capacité petite pour pouvoir tester rapidement
    # Conftest désactive globalement IP rate limit ; on le ré-active ici.
    monkeypatch.delenv("SYLEA_DISABLE_IP_RATELIMIT", raising=False)
    monkeypatch.setenv("SYLEA_IP_RATELIMIT_CAPACITY", "5")
    monkeypatch.setenv("SYLEA_IP_RATELIMIT_REFILL", "0.1")
    monkeypatch.setenv("SYLEA_IP_RATELIMIT_BURST_LOGIN", "3")
    monkeypatch.setenv("SYLEA_IP_RATELIMIT_REFILL_LOGIN", "0.05")

    # Recharge le module pour appliquer les nouveaux env
    import importlib
    import api.ip_rate_limiter as iprl
    importlib.reload(iprl)

    app = FastAPI()
    app.add_middleware(iprl.IPRateLimitMiddleware)

    @app.get("/api/foo")
    def foo():
        return {"ok": True}

    @app.post("/api/auth/login")
    def login():
        return {"ok": True}

    @app.get("/api/health")
    def health():
        return {"ok": True}

    return app


def test_normal_request_passes(app_with_ip_limit):
    client = TestClient(app_with_ip_limit)
    r = client.get("/api/foo")
    assert r.status_code == 200


def test_burst_then_429(app_with_ip_limit):
    client = TestClient(app_with_ip_limit)
    # Capacity = 5 → on en consomme 5, la 6e doit échouer
    for _ in range(5):
        r = client.get("/api/foo")
        assert r.status_code == 200
    r6 = client.get("/api/foo")
    assert r6.status_code == 429
    assert "Retry-After" in r6.headers
    assert r6.json()["code"] == "rate_limit_exceeded"


def test_login_strict_burst(app_with_ip_limit):
    client = TestClient(app_with_ip_limit)
    # /api/auth/login a un bucket strict (capacity=3)
    for _ in range(3):
        r = client.post("/api/auth/login")
        assert r.status_code == 200
    r4 = client.post("/api/auth/login")
    assert r4.status_code == 429
    assert r4.headers.get("X-RateLimit-Bucket") == "auth"


def test_health_endpoint_excluded(app_with_ip_limit):
    client = TestClient(app_with_ip_limit)
    # /api/health doit pouvoir être appelé indéfiniment (probes Kubernetes)
    for _ in range(20):
        r = client.get("/api/health")
        assert r.status_code == 200


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("SYLEA_DISABLE_IP_RATELIMIT", "true")
    import importlib
    import api.ip_rate_limiter as iprl
    importlib.reload(iprl)

    app = FastAPI()
    app.add_middleware(iprl.IPRateLimitMiddleware)

    @app.get("/api/foo")
    def foo():
        return {"ok": True}

    client = TestClient(app)
    # Aucune limite : 100 reqs OK
    for _ in range(100):
        r = client.get("/api/foo")
        assert r.status_code == 200


def test_ip_hashing_does_not_leak(monkeypatch):
    """L'IP hashée doit avoir une longueur fixe et différente de l'IP brute."""
    from api.ip_rate_limiter import _hash_ip
    h1 = _hash_ip("127.0.0.1")
    h2 = _hash_ip("192.168.0.1")
    assert h1 != h2
    assert len(h1) == 16
    assert len(h2) == 16
    # Ne doit jamais contenir l'IP en clair
    assert "127" not in h1 or h1.count("127") < 4  # 16 chars hex, accidents OK


def test_proxy_headers_respected(monkeypatch):
    monkeypatch.delenv("SYLEA_DISABLE_IP_RATELIMIT", raising=False)
    monkeypatch.setenv("SYLEA_TRUSTED_PROXIES", "true")
    monkeypatch.setenv("SYLEA_IP_RATELIMIT_CAPACITY", "3")
    monkeypatch.setenv("SYLEA_IP_RATELIMIT_REFILL", "0.01")
    import importlib
    import api.ip_rate_limiter as iprl
    importlib.reload(iprl)

    app = FastAPI()
    app.add_middleware(iprl.IPRateLimitMiddleware)

    @app.get("/api/foo")
    def foo():
        return {"ok": True}

    client = TestClient(app)
    # Deux IPs différentes via CF-Connecting-IP : chacune doit avoir SON propre bucket
    for _ in range(3):
        assert client.get("/api/foo",
                          headers={"CF-Connecting-IP": "1.1.1.1"}).status_code == 200
    for _ in range(3):
        assert client.get("/api/foo",
                          headers={"CF-Connecting-IP": "2.2.2.2"}).status_code == 200
    # 4e req IP1 : doit échouer (bucket 1.1.1.1 vide)
    r = client.get("/api/foo", headers={"CF-Connecting-IP": "1.1.1.1"})
    assert r.status_code == 429
