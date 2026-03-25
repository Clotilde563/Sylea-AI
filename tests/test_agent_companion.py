"""
Tests des endpoints Agent Companion (Agent Sylea 1).

Ces tests appellent la vraie API Claude (claude-haiku) et necessitent
la variable d'environnement ANTHROPIC_API_KEY.
Utilise un TestClient avec une base SQLite en memoire.
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

TEST_USER_ID = "test-user-agent-companion"


# Skip all tests if no API key
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="No API key — ANTHROPIC_API_KEY not set",
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    """
    Cree une base SQLite en memoire avec le schema initialise.
    Utilise check_same_thread=False car le TestClient execute
    les requetes dans un thread different.
    """
    manager = DatabaseManager(db_path=Path(":memory:"))
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    manager._conn = conn
    manager._initialiser_schema()
    # Migration colonne manquante
    try:
        conn.execute(
            "ALTER TABLE profil_utilisateur ADD COLUMN objectif_probabilite_calculee REAL DEFAULT 0.0"
        )
    except Exception:
        pass
    # Inserer un utilisateur test pour satisfaire la FK de agent_messages
    conn.execute(
        "INSERT INTO users (id, email, hashed_password, provider, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (TEST_USER_ID, "test@test.com", "fake_hash", "local"),
    )
    conn.commit()
    yield manager
    manager.disconnect()


@pytest.fixture()
def client(db):
    """
    TestClient FastAPI avec la DB en memoire injectee.
    On ne remplace PAS get_agent car l'agent companion utilise
    directement l'API Anthropic, pas la dependance get_agent.
    """

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
    """Retourne un payload ProfilIn valide pour les tests."""
    data = {
        "nom": "Jean Dupont",
        "age": 35,
        "profession": "Ingenieur",
        "ville": "Paris",
        "situation_familiale": "celibataire",
        "revenu_annuel": 60000,
        "patrimoine_estime": 30000,
        "charges_mensuelles": 1500,
        "heures_travail": 8.0,
        "heures_sommeil": 7.0,
        "heures_loisirs": 2.0,
        "heures_transport": 1.0,
        "heures_objectif": 1.0,
        "niveau_sante": 7,
        "niveau_stress": 5,
        "niveau_energie": 7,
        "niveau_bonheur": 7,
        "competences": ["Python", "SQL"],
        "diplomes": ["Master"],
        "langues": ["Francais", "Anglais"],
        "objectif": {
            "description": "Lancer ma startup dans le secteur tech",
            "categorie": "carri\u00e8re",
            "deadline": "2028-06-01",
            "probabilite_base": 0.0,
        },
    }
    data.update(overrides)
    return data


# ── Tests ────────────────────────────────────────────────────────────────────

class TestAgentChat:
    """POST /api/agent/chat"""

    def test_agent_chat_without_profil(self, client):
        """L'agent repond meme sans profil cree."""
        resp = client.post("/api/agent/chat", json={
            "messages": [{"role": "user", "content": "Bonjour, comment ca va ?"}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "message" in body
        assert len(body["message"]) > 0

    def test_agent_chat_with_profil(self, client):
        """L'agent repond avec un profil existant."""
        # Creer le profil d'abord
        client.post("/api/profil", json=_profil_payload())

        resp = client.post("/api/agent/chat", json={
            "messages": [{"role": "user", "content": "Salut ! Comment avance mon objectif ?"}],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "message" in body
        assert len(body["message"]) > 0


class TestAgentMessages:
    """GET /api/agent/messages et persistence."""

    def test_agent_messages_persistence(self, client):
        """Apres un chat, GET /api/agent/messages retourne au moins 2 messages."""
        # Envoyer un message
        client.post("/api/agent/chat", json={
            "messages": [{"role": "user", "content": "Je suis motive aujourd'hui !"}],
        })

        # Recuperer les messages persistes
        resp = client.get("/api/agent/messages")
        assert resp.status_code == 200
        messages = resp.json()
        # Au minimum le message user + la reponse agent
        assert len(messages) >= 2
        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "agent" in roles


class TestAgentCollectedInfo:
    """Extraction automatique d'infos personnelles."""

    def test_agent_collected_info_extraction(self, client, db):
        """L'agent extrait les infos personnelles de la conversation."""
        # Creer un profil
        client.post("/api/profil", json=_profil_payload())

        # Envoyer un message avec des infos personnelles
        client.post("/api/agent/chat", json={
            "messages": [
                {"role": "user", "content": "Je fais du tennis tous les samedis et je parle anglais couramment."},
            ],
        })

        # Attendre que la tache async d'extraction termine
        time.sleep(3)

        # Verifier que des infos ont ete collectees
        cursor = db.conn.execute(
            "SELECT field, value FROM agent_collected_info"
        )
        rows = cursor.fetchall()
        assert len(rows) > 0, "Aucune info collectee — l'extraction n'a rien trouve"


class TestCheckContext:
    """POST /api/agent/check-context"""

    def test_check_context_no_context_needed(self, client):
        """Question simple — pas besoin de contexte supplementaire."""
        resp = client.post("/api/agent/check-context", json={
            "type": "dilemme",
            "question": "Manger ou courir",
            "options": ["Manger", "Courir"],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["needs_context"] is False

    def test_check_context_needs_context(self, client):
        """Question impliquant des personnes inconnues — contexte necessaire."""
        resp = client.post("/api/agent/check-context", json={
            "type": "dilemme",
            "question": "Me mettre en couple avec Claire ou Laura",
            "options": ["Claire", "Laura"],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["needs_context"] is True
        # L'agent doit poser une question pour clarifier
        assert body["agent_question"] is not None
        assert len(body["agent_question"]) > 0


class TestSaveContext:
    """POST /api/agent/save-context"""

    def test_save_context_sufficient(self, client):
        """Reponse claire — le contexte est suffisant."""
        resp = client.post("/api/agent/save-context", json={
            "context_text": "Claire est ma meilleure amie depuis le lycee, Laura est une collegue de travail.",
            "related_to": "dilemme: Me mettre en couple avec Claire ou Laura",
            "type": "dilemme",
            "question": "Me mettre en couple avec Claire ou Laura",
            "options": ["Claire", "Laura"],
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["sufficient"] is True


class TestProactive:
    """POST /api/agent/proactive"""

    def test_proactive_no_message_too_early(self, client):
        """Juste apres un chat, le proactif ne doit rien renvoyer (regle 72h)."""
        # Envoyer un message (etablit la derniere interaction)
        client.post("/api/agent/chat", json={
            "messages": [{"role": "user", "content": "Tout va bien merci !"}],
        })

        # Demander un message proactif — trop tot (< 72h)
        resp = client.post("/api/agent/proactive")
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] is None


class TestDeleteMessages:
    """DELETE /api/agent/messages"""

    def test_delete_messages(self, client):
        """Supprimer tous les messages de conversation."""
        # Envoyer un message
        client.post("/api/agent/chat", json={
            "messages": [{"role": "user", "content": "Un message a supprimer."}],
        })

        # Verifier qu'il y a des messages
        resp = client.get("/api/agent/messages")
        assert len(resp.json()) >= 2

        # Supprimer
        resp = client.delete("/api/agent/messages")
        assert resp.status_code == 200
        assert "supprim" in resp.json()["detail"].lower()

        # Verifier que c'est vide
        resp = client.get("/api/agent/messages")
        assert resp.status_code == 200
        assert len(resp.json()) == 0
