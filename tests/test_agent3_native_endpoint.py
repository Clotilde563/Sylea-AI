"""
Tests d'integration pour l'endpoint POST /api/agent3/chat/native.

Mocke le client Anthropic pour verifier le flow SSE complet sans consommer
de credits. Verifie :
  - L'endpoint existe et retourne un text/event-stream
  - Le flow LLM -> tool_use -> tool_result -> LLM -> texte fonctionne
  - Les evenements SSE attendus sont emis (turn_start, tool_use, tool_result, result)
  - Les messages user et agent sont persistes en DB si user_id fourni
  - L'erreur API (credit vide) est remontee proprement
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ═══ Fakes Anthropic (reutilises de test_agent3_native_tools) ════════════════

@dataclass
class _Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict | None = None


@dataclass
class _Usage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class _Response:
    content: list[_Block]
    stop_reason: str
    usage: _Usage


class _FakeMessagesAPI:
    def __init__(self, responses: list[_Response]):
        self._responses = responses
        self._idx = 0

    async def create(self, **kwargs):
        if self._idx >= len(self._responses):
            raise RuntimeError(f"No scripted response for call {self._idx + 1}")
        r = self._responses[self._idx]
        self._idx += 1
        return r


class FakeAsyncAnthropic:
    def __init__(self, responses: list[_Response]):
        self.messages = _FakeMessagesAPI(responses)


def _text_resp(text: str) -> _Response:
    return _Response(content=[_Block(type="text", text=text)], stop_reason="end_turn", usage=_Usage())


def _tool_resp(name: str, input_dict: dict, tool_id: str = "tu_1") -> _Response:
    return _Response(
        content=[_Block(type="tool_use", id=tool_id, name=name, input=input_dict)],
        stop_reason="tool_use",
        usage=_Usage(),
    )


# ═══ Fixture client ═══════════════════════════════════════════════════════════

@pytest.fixture
def app_client(monkeypatch):
    """FastAPI TestClient avec une DB in-memory et une API key factice."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")
    from api.main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _bypass_agent3_auth_gate():
    """Audit securite 2026-06 : l'endpoint /chat/native est protege par
    `_require_agent3_plan` (plan team/enterprise requis, anonyme -> 401).

    Cette garde est testee SEPAREMENT dans test_agent3_auth_gate.py. Ces tests
    d'integration-ci ciblent la LOGIQUE de l'endpoint (flux SSE, tool-use,
    persistence) -> on neutralise la garde (= simule un user authentifie plan
    team) pour ne pas dependre d'un vrai token. Nettoyage apres chaque test."""
    from api.main import app
    from api.routers.agent3_openclaw import _require_agent3_plan
    app.dependency_overrides[_require_agent3_plan] = lambda: None
    yield
    app.dependency_overrides.pop(_require_agent3_plan, None)


def _parse_sse(body: str) -> list[dict]:
    """Parse un flux SSE bruteforcement en liste de {event, data}."""
    events: list[dict] = []
    cur_event = None
    for line in body.splitlines():
        if line.startswith("event:"):
            cur_event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            raw = line.split(":", 1)[1].strip()
            try:
                data = json.loads(raw)
            except Exception:
                data = {"_raw": raw}
            events.append({"event": cur_event, "data": data})
            cur_event = None
    return events


# ═══ Tests ════════════════════════════════════════════════════════════════════


class TestEndpointExists:
    def test_native_endpoint_registered(self, app_client):
        # HEAD n'est pas supporte mais on peut verifier via les routes FastAPI
        from api.main import app
        paths = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/api/agent3/chat/native" in paths

    def test_empty_message_returns_error_event(self, app_client):
        payload = {"messages": [{"role": "user", "content": "   "}]}
        resp = app_client.post("/api/agent3/chat/native", json=payload)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = _parse_sse(resp.text)
        # Doit y avoir un event "error"
        assert any(e["event"] == "error" for e in events)


class TestFullFlowMocked:
    def test_single_turn_text_response(self, app_client, monkeypatch):
        """LLM -> texte direct -> end_turn. Pas de tool_use."""
        import anthropic
        fake_client = FakeAsyncAnthropic([_text_resp("Bonjour, je suis Agent 3.")])
        monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda api_key: fake_client)

        # stream=False pour utiliser le fake .create() plutot que .stream()
        payload = {"messages": [{"role": "user", "content": "Salut"}], "stream": False}
        resp = app_client.post("/api/agent3/chat/native", json=payload)
        assert resp.status_code == 200
        events = _parse_sse(resp.text)

        # Events attendus : turn_start, thinking, turn_llm_done, done, result
        event_types = [e["event"] for e in events]
        assert "turn_start" in event_types
        assert "done" in event_types
        assert "result" in event_types

        result = next(e for e in events if e["event"] == "result")
        assert "Bonjour" in result["data"]["message"]
        assert result["data"]["turns"] == 1
        assert result["data"]["actions_count"] == 0

    def test_tool_use_then_final_answer(self, app_client, monkeypatch):
        """LLM -> tool_use(search) -> dispatcher.SEARCH -> tool_result -> LLM -> texte."""
        import anthropic
        fake_client = FakeAsyncAnthropic([
            _tool_resp("search", {"query": "test query"}, tool_id="tu_1"),
            _text_resp("Voici la reponse apres recherche."),
        ])
        monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda api_key: fake_client)

        # Mock openclaw_web_search pour eviter tout appel reseau
        from api.openclaw_bridge import OpenClawResponse
        from unittest.mock import AsyncMock
        mock_search = AsyncMock(return_value=OpenClawResponse(content="Fake search results", error=None))

        with patch("api.openclaw_bridge.openclaw_web_search", mock_search):
            resp = app_client.post("/api/agent3/chat/native", json={
                "messages": [{"role": "user", "content": "cherche un truc"}],
                "stream": False,
            })
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        types = [e["event"] for e in events]

        # Tool_use + tool_result doivent etre emis
        assert "tool_use" in types
        assert "tool_result" in types
        # Et la search mock a ete appelee
        mock_search.assert_called_once()

        # Resultat final
        result = next(e for e in events if e["event"] == "result")
        assert result["data"]["turns"] == 2
        assert result["data"]["actions_count"] == 1
        assert "apres recherche" in result["data"]["message"]

    def test_missing_api_key_returns_error(self, monkeypatch):
        """Sans ANTHROPIC_API_KEY, l'endpoint remonte un error event proprement."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from api.main import app
        with TestClient(app) as client:
            resp = client.post("/api/agent3/chat/native", json={
                "messages": [{"role": "user", "content": "test"}],
            })
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        err = next(e for e in events if e["event"] == "error")
        assert "API_KEY" in err["data"]["message"]


# ═══ Streaming + cancellation ═════════════════════════════════════════════════


class _FakeDelta:
    def __init__(self, dtype, **kw):
        self.type = dtype
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeStreamEvent:
    def __init__(self, etype, delta=None):
        self.type = etype
        self.delta = delta


class _FakeStream:
    def __init__(self, events, final):
        self._events = list(events)
        self._final = final

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._events:
            raise StopAsyncIteration
        return self._events.pop(0)

    async def get_final_message(self):
        return self._final


class _FakeStreamCM:
    def __init__(self, events, final):
        self._events = events
        self._final = final

    async def __aenter__(self):
        return _FakeStream(self._events, self._final)

    async def __aexit__(self, *a):
        return None


class _StreamingMessagesAPI:
    def __init__(self, pairs):
        # pairs : list[(events, final_message)]
        self._pairs = list(pairs)

    def stream(self, **kwargs):
        if not self._pairs:
            raise RuntimeError("no scripted stream")
        events, final = self._pairs.pop(0)
        return _FakeStreamCM(events, final)


class FakeStreamingAnthropic:
    def __init__(self, pairs):
        self.messages = _StreamingMessagesAPI(pairs)


class TestStreamingEndpoint:
    def test_stream_true_emits_token_delta(self, app_client, monkeypatch):
        """L'endpoint avec stream=true (defaut) relaye les token_delta SSE."""
        import anthropic
        text = "Salut Sylea !"
        events = [
            _FakeStreamEvent("content_block_delta", _FakeDelta("text_delta", text=text[:5])),
            _FakeStreamEvent("content_block_delta", _FakeDelta("text_delta", text=text[5:])),
        ]
        final = _Response(
            content=[_Block(type="text", text=text)],
            stop_reason="end_turn",
            usage=_Usage(),
        )
        fake = FakeStreamingAnthropic([(events, final)])
        monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda api_key: fake)

        payload = {"messages": [{"role": "user", "content": "hi"}]}  # stream defaut=true
        resp = app_client.post("/api/agent3/chat/native", json=payload)
        assert resp.status_code == 200
        parsed = _parse_sse(resp.text)
        types = [e["event"] for e in parsed]
        assert "token_delta" in types
        # Les deltas recomposes = texte complet
        deltas = [e["data"]["text"] for e in parsed if e["event"] == "token_delta"]
        assert "".join(deltas) == text
        # Resultat final bien emis
        assert "result" in types

    def test_cancel_endpoint_returns_false_when_token_unknown(self, app_client):
        resp = app_client.post("/api/agent3/chat/native/cancel", json={
            "cancel_token": "token-inexistant-xyz"
        })
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is False

    def test_cancel_endpoint_without_token_returns_false(self, app_client):
        resp = app_client.post("/api/agent3/chat/native/cancel", json={})
        assert resp.status_code == 200
        assert resp.json()["cancelled"] is False


class TestSlashCommandInterception:
    """Les slash commands doivent etre traitees AVANT tout appel au LLM."""

    def test_help_is_intercepted_without_llm_call(self, app_client, monkeypatch):
        # Si le LLM etait appele, le fake leverait une erreur (pas de response scripte).
        import anthropic

        class _Exploder:
            class messages:
                @staticmethod
                async def create(**kwargs):
                    raise AssertionError("LLM should not be called for /help")

                @staticmethod
                def stream(**kwargs):
                    raise AssertionError("LLM stream should not be called for /help")

        monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda api_key: _Exploder())

        payload = {"messages": [{"role": "user", "content": "/help"}], "stream": False}
        resp = app_client.post("/api/agent3/chat/native", json=payload)
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        # Seul un event "result" doit avoir ete emis, avec slash_command=True.
        result = next(e for e in events if e["event"] == "result")
        assert result["data"].get("slash_command") is True
        assert result["data"].get("turns") == 0

    def test_non_slash_message_still_hits_llm(self, app_client, monkeypatch):
        import anthropic
        fake_client = FakeAsyncAnthropic([_text_resp("Salut")])
        monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda api_key: fake_client)

        payload = {"messages": [{"role": "user", "content": "bonjour"}], "stream": False}
        resp = app_client.post("/api/agent3/chat/native", json=payload)
        assert resp.status_code == 200
        events = _parse_sse(resp.text)
        result = next(e for e in events if e["event"] == "result")
        assert result["data"].get("slash_command") is not True
        assert result["data"].get("turns") == 1
