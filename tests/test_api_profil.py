"""
Tests des endpoints FastAPI pour le profil utilisateur.

Utilise un TestClient avec une base SQLite en memoire
pour isoler chaque test.
"""

import sqlite3
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from api.main import app
from api.dependencies import get_db, get_agent
from sylea.core.storage.database import DatabaseManager


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    """
    Cree une base SQLite en memoire avec le schema initialise.

    Utilise check_same_thread=False car le TestClient de Starlette
    execute les requetes dans un thread different.
    """
    manager = DatabaseManager(db_path=Path(":memory:"))
    # Override connect to allow cross-thread usage in tests
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    manager._conn = conn
    manager._initialiser_schema()
    # Migration manquante dans _initialiser_schema — colonne ajoutee par le prod DB
    try:
        conn.execute(
            "ALTER TABLE profil_utilisateur ADD COLUMN objectif_probabilite_calculee REAL DEFAULT 0.0"
        )
    except Exception:
        pass
    yield manager
    manager.disconnect()


@pytest.fixture()
def client(db):
    """
    TestClient FastAPI avec la DB en memoire injectee.

    Override get_db pour fournir le DatabaseManager en memoire
    et get_agent pour retourner None (mode local, pas d'IA).
    """

    async def _override_get_db():
        yield db

    def _override_get_agent():
        return None

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_agent] = _override_get_agent

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

class TestGetProfilEmpty:
    """GET /api/profil quand aucun profil n'existe."""

    def test_returns_404_when_no_profil(self, client):
        resp = client.get("/api/profil")
        assert resp.status_code == 404
        assert "profil" in resp.json()["detail"].lower()


class TestCreateProfil:
    """POST /api/profil cree un nouveau profil."""

    def test_create_profil_returns_200(self, client):
        payload = _profil_payload()
        resp = client.post("/api/profil", json=payload)
        assert resp.status_code == 200

        body = resp.json()
        assert body["nom"] == "Jean Dupont"
        assert body["age"] == 35
        assert body["profession"] == "Ingenieur"
        assert body["ville"] == "Paris"
        assert body["id"]  # ID non vide
        assert body["objectif"] is not None
        assert body["objectif"]["description"] == "Lancer ma startup dans le secteur tech"
        assert body["objectif"]["categorie"] == "carri\u00e8re"
        assert body["objectif"]["deadline"] == "2028-06-01"
        assert body["cree_le"]
        assert body["mis_a_jour_le"]

    def test_create_profil_stores_competences(self, client):
        payload = _profil_payload()
        resp = client.post("/api/profil", json=payload)
        body = resp.json()
        assert "Python" in body["competences"]
        assert "SQL" in body["competences"]

    def test_create_profil_without_objectif(self, client):
        payload = _profil_payload(objectif=None)
        resp = client.post("/api/profil", json=payload)
        assert resp.status_code == 200
        assert resp.json()["objectif"] is None


class TestGetProfilAfterCreate:
    """GET /api/profil apres creation."""

    def test_get_returns_created_profil(self, client):
        payload = _profil_payload()
        client.post("/api/profil", json=payload)

        resp = client.get("/api/profil")
        assert resp.status_code == 200

        body = resp.json()
        assert body["nom"] == "Jean Dupont"
        assert body["objectif"]["description"] == "Lancer ma startup dans le secteur tech"


class TestRecalculerProbabilite:
    """POST /api/profil/probabilite recalcule en mode local."""

    def test_probabilite_without_profil_returns_404(self, client):
        resp = client.post("/api/profil/probabilite", json={})
        assert resp.status_code == 404

    def test_probabilite_local_returns_result(self, client):
        # Creer le profil d'abord
        client.post("/api/profil", json=_profil_payload())

        resp = client.post("/api/profil/probabilite", json={})
        assert resp.status_code == 200

        body = resp.json()
        assert "probabilite" in body
        assert isinstance(body["probabilite"], float)
        assert body["probabilite"] > 0
        assert "resume" in body
        assert "points_forts" in body
        assert "points_faibles" in body
        assert "conseil_prioritaire" in body

    def test_probabilite_without_objectif_returns_400(self, client):
        # Profil sans objectif
        client.post("/api/profil", json=_profil_payload(objectif=None))

        resp = client.post("/api/profil/probabilite", json={})
        assert resp.status_code == 400


class TestDeleteProfil:
    """DELETE /api/profil supprime le profil."""

    def test_delete_without_profil_returns_404(self, client):
        resp = client.delete("/api/profil")
        assert resp.status_code == 404

    def test_delete_profil_success(self, client):
        client.post("/api/profil", json=_profil_payload())

        resp = client.delete("/api/profil")
        assert resp.status_code == 200
        assert "supprim" in resp.json()["detail"].lower()

        # Verifier que le profil n'existe plus
        resp2 = client.get("/api/profil")
        assert resp2.status_code == 404
