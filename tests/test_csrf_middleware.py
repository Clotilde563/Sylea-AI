"""Tests pour le middleware CSRFMiddleware."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.csrf_middleware import (
    CSRFMiddleware,
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    generate_csrf_token,
    is_path_exempt,
    verify_csrf_token,
)


@pytest.fixture
def app_with_csrf(monkeypatch):
    # Conftest désactive globalement CSRF ; on le ré-active ici.
    monkeypatch.delenv("SYLEA_DISABLE_CSRF", raising=False)
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.get("/api/foo")
    def get_foo():
        return {"ok": True}

    @app.post("/api/foo")
    def post_foo(body: dict | None = None):
        return {"received": body or {}}

    @app.post("/api/auth/login")
    def login(body: dict | None = None):
        return {"logged": True}

    return app


@pytest.fixture
def client(app_with_csrf):
    return TestClient(app_with_csrf)


def test_get_sets_csrf_cookie(client):
    r = client.get("/api/foo")
    assert r.status_code == 200
    assert CSRF_COOKIE_NAME in r.cookies
    token = r.cookies[CSRF_COOKIE_NAME]
    assert verify_csrf_token(token)


def test_post_without_token_rejected(client):
    r = client.post("/api/foo", json={"x": 1})
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_missing"


def test_post_with_valid_token_accepted(client):
    # 1) GET pour récupérer le cookie
    r1 = client.get("/api/foo")
    token = r1.cookies[CSRF_COOKIE_NAME]
    # 2) POST avec cookie + header
    r2 = client.post(
        "/api/foo",
        json={"x": 1},
        headers={CSRF_HEADER_NAME: token},
        cookies={CSRF_COOKIE_NAME: token},
    )
    assert r2.status_code == 200


def test_post_with_mismatched_header_rejected(client):
    r1 = client.get("/api/foo")
    token = r1.cookies[CSRF_COOKIE_NAME]
    r2 = client.post(
        "/api/foo",
        json={"x": 1},
        headers={CSRF_HEADER_NAME: "different-token"},
        cookies={CSRF_COOKIE_NAME: token},
    )
    assert r2.status_code == 403
    assert r2.json()["code"] == "csrf_mismatch"


def test_post_with_forged_token_rejected(client):
    # Token "forgé" avec mauvaise signature
    forged = "ZmFrZS1yYW5kb20tZGF0YS1mb3ItdGVzdA.ZmFrZS1zaWduYXR1cmU"
    r2 = client.post(
        "/api/foo",
        json={"x": 1},
        headers={CSRF_HEADER_NAME: forged},
        cookies={CSRF_COOKIE_NAME: forged},
    )
    assert r2.status_code == 403
    assert r2.json()["code"] == "csrf_invalid_signature"


def test_login_endpoint_exempt(client):
    # /api/auth/login doit passer sans CSRF
    r = client.post("/api/auth/login", json={"email": "x@y.z"})
    assert r.status_code == 200


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("SYLEA_DISABLE_CSRF", "true")
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.post("/api/foo")
    def post_foo():
        return {"ok": True}

    client = TestClient(app)
    r = client.post("/api/foo", json={"x": 1})
    assert r.status_code == 200


def test_generate_then_verify():
    t = generate_csrf_token()
    assert verify_csrf_token(t)


def test_verify_garbage():
    assert not verify_csrf_token("")
    assert not verify_csrf_token("notoken")
    assert not verify_csrf_token("a.b")
    assert not verify_csrf_token("...")


def test_is_path_exempt():
    assert is_path_exempt("/api/auth/login")
    assert is_path_exempt("/api/auth/register")
    assert is_path_exempt("/api/auth/verify")
    assert is_path_exempt("/api/auth/forgot-password")
    assert is_path_exempt("/api/health")
    assert is_path_exempt("/ws/agent")
    assert is_path_exempt("/api/stripe/webhook")
    assert not is_path_exempt("/api/profil")
    assert not is_path_exempt("/api/dilemme/analyser")
    assert not is_path_exempt("/api/agent/chat")


def test_cookie_is_not_httponly(client):
    """Le cookie CSRF DOIT être lisible en JS (double-submit pattern)."""
    r = client.get("/api/foo")
    # FastAPI TestClient ne renvoie pas le flag HttpOnly directement
    # via .cookies. On vérifie via le header Set-Cookie brut.
    set_cookie = r.headers.get("set-cookie", "")
    if CSRF_COOKIE_NAME in set_cookie:
        # Doit NE PAS contenir HttpOnly
        assert "HttpOnly" not in set_cookie or "HttpOnly=false" in set_cookie.lower()


def test_get_does_not_rotate_existing_valid_cookie(client):
    # 1er GET : pose le cookie
    r1 = client.get("/api/foo")
    token1 = r1.cookies[CSRF_COOKIE_NAME]
    # 2e GET avec le même cookie : on garde le token
    r2 = client.get("/api/foo", cookies={CSRF_COOKIE_NAME: token1})
    # Soit pas de nouveau cookie posé, soit le même token
    new_token = r2.cookies.get(CSRF_COOKIE_NAME)
    assert new_token is None or new_token == token1


def test_put_and_patch_and_delete_require_csrf(client, monkeypatch):
    # Ajoutons des endpoints pour PUT/PATCH/DELETE
    monkeypatch.delenv("SYLEA_DISABLE_CSRF", raising=False)
    app = FastAPI()
    app.add_middleware(CSRFMiddleware)

    @app.put("/api/x")
    def put_x():
        return {"m": "put"}

    @app.patch("/api/x")
    def patch_x():
        return {"m": "patch"}

    @app.delete("/api/x")
    def delete_x():
        return {"m": "delete"}

    c = TestClient(app)
    assert c.put("/api/x").status_code == 403
    assert c.patch("/api/x").status_code == 403
    assert c.delete("/api/x").status_code == 403
