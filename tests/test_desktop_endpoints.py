"""
Tests des endpoints /api/desktop/* — sync agents-activation et bridge
ecoute active web -> desktop (Sprint 1 Ecoute active, cours univ/prepa).

Ces endpoints servent uniquement de canal entre le frontend web et l'app
desktop : ils ne touchent pas la DB. On mock ws_manager pour valider le
broadcast des events sans avoir a brancher un vrai WebSocket.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_optional_user
from api.main import app, _agents_activation_state


TEST_USER_ID = "test-user-desktop"


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def auth_client():
    """Client FastAPI avec auth mockee a TEST_USER_ID."""
    app.dependency_overrides[get_optional_user] = lambda: TEST_USER_ID
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def anon_client():
    """Client FastAPI SANS auth (get_optional_user retourne None)."""
    app.dependency_overrides[get_optional_user] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_state():
    """Vide le state in-memory entre chaque test pour eviter les fuites."""
    _agents_activation_state.clear()
    yield
    _agents_activation_state.clear()


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/desktop/agents-activation
# ════════════════════════════════════════════════════════════════════════════

def test_agents_activation_post_requires_auth(anon_client):
    r = anon_client.post(
        "/api/desktop/agents-activation",
        json={"agent2": True, "agent3": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"ok": False, "error": "auth_required"}


def test_agents_activation_post_stores_state_and_broadcasts(auth_client):
    with patch("api.websocket.ws_manager.send_to_user", new=AsyncMock()) as mock_send:
        r = auth_client.post(
            "/api/desktop/agents-activation",
            json={"agent1": True, "agent2": True, "agent3": False},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["active"] == {"agent1": True, "agent2": True, "agent3": False}

    # State persiste pour ce user
    assert _agents_activation_state[TEST_USER_ID] == {
        "agent1": True, "agent2": True, "agent3": False,
    }
    # Broadcast WS appele exactement une fois avec le bon payload
    mock_send.assert_called_once()
    call_args = mock_send.call_args
    assert call_args.args[0] == TEST_USER_ID
    assert call_args.args[1]["type"] == "agents_activation"
    assert call_args.args[1]["active"] == {"agent1": True, "agent2": True, "agent3": False}


def test_agents_activation_post_sanitises_payload(auth_client):
    """Les cles inattendues sont ignorees, les valeurs sont coercees en bool."""
    with patch("api.websocket.ws_manager.send_to_user", new=AsyncMock()):
        r = auth_client.post(
            "/api/desktop/agents-activation",
            json={
                "agent1": "yes",      # string truthy
                "agent2": 0,          # int falsy
                "agent3": True,
                "agent99": True,      # cle inattendue ignoree
                "evil_field": "rm -rf /",
            },
        )
    body = r.json()
    assert body["active"] == {"agent1": True, "agent2": False, "agent3": True}
    assert "agent99" not in body["active"]
    assert "evil_field" not in body["active"]


def test_agents_activation_post_missing_keys_default_false(auth_client):
    """Si une cle manque dans le payload, on default a False (pas crash)."""
    with patch("api.websocket.ws_manager.send_to_user", new=AsyncMock()):
        r = auth_client.post(
            "/api/desktop/agents-activation",
            json={"agent2": True},  # agent1 et agent3 absents
        )
    assert r.status_code == 200
    body = r.json()
    assert body["active"] == {"agent1": False, "agent2": True, "agent3": False}


# ════════════════════════════════════════════════════════════════════════════
#  GET /api/desktop/agents-activation
# ════════════════════════════════════════════════════════════════════════════

def test_agents_activation_get_anon_returns_all_false(anon_client):
    r = anon_client.get("/api/desktop/agents-activation")
    assert r.status_code == 200
    assert r.json() == {"active": {"agent1": False, "agent2": False, "agent3": False}}


def test_agents_activation_get_returns_default_when_user_unknown(auth_client):
    """User auth mais qui n'a jamais POST -> retourne defaults False."""
    r = auth_client.get("/api/desktop/agents-activation")
    assert r.status_code == 200
    assert r.json() == {"active": {"agent1": False, "agent2": False, "agent3": False}}


def test_agents_activation_get_returns_persisted_state(auth_client):
    """Apres un POST, le GET doit retourner le snapshot."""
    with patch("api.websocket.ws_manager.send_to_user", new=AsyncMock()):
        auth_client.post(
            "/api/desktop/agents-activation",
            json={"agent1": False, "agent2": True, "agent3": True},
        )
    r = auth_client.get("/api/desktop/agents-activation")
    body = r.json()
    assert body["active"] == {"agent1": False, "agent2": True, "agent3": True}


def test_agents_activation_post_then_overwrite(auth_client):
    """POST 2 fois : seul le dernier etat est conserve."""
    with patch("api.websocket.ws_manager.send_to_user", new=AsyncMock()):
        auth_client.post(
            "/api/desktop/agents-activation",
            json={"agent1": True, "agent2": True, "agent3": True},
        )
        auth_client.post(
            "/api/desktop/agents-activation",
            json={"agent1": False, "agent2": False, "agent3": False},
        )
    r = auth_client.get("/api/desktop/agents-activation")
    assert r.json()["active"] == {"agent1": False, "agent2": False, "agent3": False}


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/desktop/start-lecture (Ecoute active web -> desktop)
# ════════════════════════════════════════════════════════════════════════════

def test_start_lecture_requires_auth(anon_client):
    r = anon_client.post("/api/desktop/start-lecture")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "auth_required"}


def test_start_lecture_when_desktop_disconnected_returns_error(auth_client):
    with patch("api.websocket.ws_manager.is_connected", return_value=False):
        r = auth_client.post("/api/desktop/start-lecture")
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "desktop_not_connected"}


def test_start_lecture_when_desktop_connected_broadcasts_event(auth_client):
    """Avec desktop connecte, broadcast {type:'start_lecture'} via WS."""
    mock_send = AsyncMock()
    with patch("api.websocket.ws_manager.is_connected", return_value=True), \
         patch("api.websocket.ws_manager.send_to_user", new=mock_send):
        r = auth_client.post("/api/desktop/start-lecture")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    mock_send.assert_called_once_with(TEST_USER_ID, {"type": "start_lecture"})


def test_start_lecture_doesnt_broadcast_when_offline(auth_client):
    """Si desktop offline, on NE FAIT PAS l'appel send_to_user (eviter de
    spam les futures sessions du meme user qui se reconnecteraient)."""
    mock_send = AsyncMock()
    with patch("api.websocket.ws_manager.is_connected", return_value=False), \
         patch("api.websocket.ws_manager.send_to_user", new=mock_send):
        r = auth_client.post("/api/desktop/start-lecture")
    assert r.json()["ok"] is False
    mock_send.assert_not_called()


# ════════════════════════════════════════════════════════════════════════════
#  Isolation par user_id (security)
# ════════════════════════════════════════════════════════════════════════════

def test_agents_activation_state_is_per_user():
    """Le state d'un user A ne doit JAMAIS fuiter vers un user B."""
    user_a = "user-alpha"
    user_b = "user-beta"

    # User A POST son etat
    app.dependency_overrides[get_optional_user] = lambda: user_a
    client = TestClient(app)
    with patch("api.websocket.ws_manager.send_to_user", new=AsyncMock()):
        client.post(
            "/api/desktop/agents-activation",
            json={"agent2": True, "agent3": True},
        )

    # User B fait un GET -> doit voir des defaults, pas l'etat de A
    app.dependency_overrides[get_optional_user] = lambda: user_b
    client = TestClient(app)
    r = client.get("/api/desktop/agents-activation")
    assert r.json()["active"] == {"agent1": False, "agent2": False, "agent3": False}

    app.dependency_overrides.clear()
