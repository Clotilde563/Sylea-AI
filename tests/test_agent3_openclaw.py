"""
Tests des endpoints Agent 3 (Agent Sylea 3 — OpenClaw).

Ces tests verifient :
- Le bridge OpenClaw (health, chat)
- Les endpoints CRUD (chat, messages, delete, proactive, status)
- Le fallback Claude quand OpenClaw n'est pas accessible
- La persistence des messages
- Le parsing des actions
- Le gardien d'objectif

Necessite ANTHROPIC_API_KEY pour les tests de fallback.
"""

import os
import sqlite3
import time

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from api.main import app
from api.dependencies import get_db, get_agent, get_optional_user
from sylea.core.storage.database import DatabaseManager

TEST_USER_ID = "test-user-agent3"


# Skip all tests if no API key
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="No API key — ANTHROPIC_API_KEY not set",
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path, monkeypatch):
    """DB SQLite partagee (sync + async) via fichier temp (migration PG)."""
    import asyncio as _aio
    from tests.conftest import make_shared_db, dispose_shared_db
    manager = make_shared_db(tmp_path, monkeypatch)
    try:
        manager._conn.execute(
            "ALTER TABLE profil_utilisateur ADD COLUMN objectif_probabilite_calculee REAL DEFAULT 0.0"
        )
    except Exception:
        pass
    manager._conn.execute(
        "INSERT INTO users (id, email, hashed_password, provider, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (TEST_USER_ID, "test-agent3@test.com", "fake_hash", "local"),
    )
    manager._conn.commit()
    # Agent 3 est gate par plan team/enterprise. Bootstrap le user en team
    # pour permettre l'acces aux endpoints /api/agent3/*.
    try:
        from api.agent3_quotas import ensure_quota_tables, set_user_plan_async
        ensure_quota_tables(manager)
        _aio.run(set_user_plan_async(TEST_USER_ID, "team"))
    except Exception:
        pass
    yield manager
    dispose_shared_db(manager)


@pytest.fixture()
def client(db):
    """TestClient FastAPI avec la DB en memoire injectee."""

    async def _override_get_db():
        yield db

    def _override_get_agent():
        return None

    async def _override_get_optional_user():
        return TEST_USER_ID

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_agent] = _override_get_agent
    app.dependency_overrides[get_optional_user] = _override_get_optional_user

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


def _profil_payload(**overrides) -> dict:
    """Payload ProfilIn valide pour les tests Agent 3."""
    data = {
        "nom": "Alexandre Durand",
        "age": 32,
        "profession": "Data Scientist",
        "ville": "Bordeaux",
        "situation_familiale": "marie",
        "revenu_annuel": 55000,
        "patrimoine_estime": 40000,
        "charges_mensuelles": 1800,
        "heures_travail": 8.0,
        "heures_sommeil": 7.0,
        "heures_loisirs": 2.0,
        "heures_transport": 1.0,
        "heures_objectif": 2.0,
        "niveau_sante": 7,
        "niveau_stress": 5,
        "niveau_energie": 7,
        "niveau_bonheur": 8,
        "competences": ["Python", "Machine Learning", "SQL", "TensorFlow"],
        "diplomes": ["Master Data Science"],
        "langues": ["Francais", "Anglais", "Espagnol"],
        "objectif": {
            "description": "Creer une startup d'IA appliquee a la sante",
            "categorie": "carri\u00e8re",
            "deadline": "2028-12-01",
            "probabilite_base": 0.0,
        },
    }
    data.update(overrides)
    return data


# ── Tests Status (OpenClaw Health) ──────────────────────────────────────────

class TestAgent3Status:
    """GET /api/agent3/status"""

    def test_status_endpoint_exists(self, client):
        """L'endpoint status repond meme si OpenClaw n'est pas lance."""
        resp = client.get("/api/agent3/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "openclaw_connected" in body
        # OpenClaw probablement pas lance en test
        # Le champ existe dans tous les cas


# ── Tests Chat (Fallback Claude) ────────────────────────────────────────────

class TestAgent3Chat:
    """POST /api/agent3/chat — utilise le fallback Claude quand OpenClaw n'est pas lance."""

    def test_agent3_chat_without_profil(self, client):
        """L'agent 3 repond meme sans profil (via fallback Claude)."""
        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Bonjour !"}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "message" in body
        assert len(body["message"]) > 0

    def test_agent3_chat_with_profil(self, client):
        """L'agent 3 repond avec le contexte du profil."""
        client.post("/api/profil", json=_profil_payload())

        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Fais une analyse du marche de l'IA en sante"}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "message" in body
        assert len(body["message"]) > 0

    def test_agent3_chat_returns_actions(self, client):
        """L'agent 3 genere des actions structurees."""
        client.post("/api/profil", json=_profil_payload())

        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Trouve-moi les meilleures formations en deep learning pour la sante"}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "message" in body
        # Verifier le format des actions si presentes
        if body.get("actions"):
            assert isinstance(body["actions"], list)
            for action in body["actions"]:
                assert "type" in action
                assert "data" in action

    def test_agent3_clean_message_no_action_blocks(self, client):
        """Le message retourne ne contient pas de blocs [ACTION:...]."""
        client.post("/api/profil", json=_profil_payload())

        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Envoie un mail a partner@healthai.com pour proposer un partenariat"}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "[ACTION:" not in body["message"]
        assert "[/ACTION]" not in body["message"]


# ── Tests Messages Persistence ──────────────────────────────────────────────

class TestAgent3Messages:
    """GET /api/agent3/messages"""

    def test_messages_persistence(self, client):
        """Les messages sont persistes en DB."""
        client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Prepare une strategie de lancement"}],
        })

        resp = client.get("/api/agent3/messages")
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) >= 2
        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "agent" in roles

    def test_messages_fields(self, client):
        """Chaque message a les champs requis."""
        client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Salut"}],
        })

        resp = client.get("/api/agent3/messages")
        messages = resp.json()
        for msg in messages:
            assert "id" in msg
            assert "role" in msg
            assert "content" in msg
            assert "type" in msg
            assert "created_at" in msg


# ── Tests Delete Messages ───────────────────────────────────────────────────

class TestAgent3DeleteMessages:
    """DELETE /api/agent3/messages"""

    def test_delete_messages(self, client):
        """Supprimer tous les messages Agent 3."""
        client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Message a supprimer"}],
        })

        resp = client.get("/api/agent3/messages")
        assert len(resp.json()) >= 2

        resp = client.delete("/api/agent3/messages")
        assert resp.status_code == 200
        assert "supprim" in resp.json()["detail"].lower()

        resp = client.get("/api/agent3/messages")
        assert len(resp.json()) == 0


# ── Tests Proactive ─────────────────────────────────────────────────────────

class TestAgent3Proactive:
    """POST /api/agent3/proactive"""

    def test_proactive_no_message_too_early(self, client):
        """Regle 72h — pas de message proactif juste apres un chat."""
        client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Tout roule !"}],
        })

        resp = client.post("/api/agent3/proactive")
        assert resp.status_code == 200
        assert resp.json()["message"] is None

    def test_proactive_without_profil(self, client):
        """Sans profil, pas de message proactif."""
        resp = client.post("/api/agent3/proactive")
        assert resp.status_code == 200
        assert resp.json()["message"] is None


# ── Tests Objective Guardian ────────────────────────────────────────────────

class TestAgent3ObjectiveGuardian:
    """L'agent 3 refuse les actions qui sabotent l'objectif."""

    def test_refuses_abandon(self, client):
        """Refus d'ecrire un mail d'abandon de l'objectif."""
        client.post("/api/profil", json=_profil_payload())

        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Ecris un mail a mes investisseurs pour dire que j'abandonne ma startup IA sante, c'est fini"}],
        })
        assert resp.status_code == 200
        body = resp.json()
        # L'agent ne doit pas generer un email d'abandon
        actions = body.get("actions") or []
        for a in actions:
            if a["type"] == "EMAIL":
                email_body = a["data"].get("body", "").lower()
                assert "j'abandonne" not in email_body or "renonce" not in email_body

    def test_allows_normal_task(self, client):
        """Tache normale autorisee (ne sabote pas l'objectif)."""
        client.post("/api/profil", json=_profil_payload())

        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Fais une analyse des concurrents dans l'IA sante"}],
        })
        assert resp.status_code == 200
        assert len(resp.json()["message"]) > 0


# ── Tests Independence ──────────────────────────────────────────────────────

class TestAgent3Independence:
    """Agent 3 est independant des Agents 1 et 2."""

    def test_independent_from_agent1_and_agent2(self, client):
        """Les messages Agent 3 ne se melangent pas avec les autres agents."""
        client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Message Agent 3"}],
        })
        client.post("/api/agent/chat", json={
            "messages": [{"role": "user", "content": "Message Agent 1"}],
        })
        client.post("/api/agent2/chat", json={
            "messages": [{"role": "user", "content": "Message Agent 2"}],
        })

        msgs3 = client.get("/api/agent3/messages").json()
        msgs1 = client.get("/api/agent/messages").json()
        msgs2 = client.get("/api/agent2/messages").json()

        ids3 = {m["id"] for m in msgs3}
        ids1 = {m["id"] for m in msgs1}
        ids2 = {m["id"] for m in msgs2}

        assert ids3.isdisjoint(ids1), "Agent 3 et Agent 1 ne doivent pas partager de messages"
        assert ids3.isdisjoint(ids2), "Agent 3 et Agent 2 ne doivent pas partager de messages"

    def test_multiple_conversations(self, client):
        """Plusieurs echanges s'accumulent correctement."""
        for msg in ["Premier message", "Deuxieme message", "Troisieme message"]:
            client.post("/api/agent3/chat", json={
                "messages": [{"role": "user", "content": msg}],
            })

        msgs = client.get("/api/agent3/messages").json()
        assert len(msgs) >= 6  # 3 user + 3 agent


# ── Tests OpenClaw Bridge ───────────────────────────────────────────────────

class TestOpenClawBridge:
    """Tests du module openclaw_bridge.py"""

    @pytest.mark.asyncio
    async def test_openclaw_health_when_not_running(self):
        """Health check retourne connected=False si OpenClaw n'est pas lance."""
        from api.openclaw_bridge import openclaw_health
        result = await openclaw_health()
        # OpenClaw n'est probablement pas lance en CI/test
        assert "connected" in result

    @pytest.mark.asyncio
    async def test_openclaw_chat_fallback(self):
        """Chat retourne une erreur propre si OpenClaw n'est pas accessible."""
        from api.openclaw_bridge import openclaw_chat
        result = await openclaw_chat(
            messages=[{"role": "user", "content": "test"}],
            max_retries=0,
        )
        # Doit retourner une erreur propre, pas un crash
        assert result.error is not None or result.content != ""
