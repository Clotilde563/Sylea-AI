"""
Tests for the FastAPI dilemme endpoints (/api/dilemme/analyser, /api/dilemme/choisir).

Uses an in-memory SQLite database and no Claude agent (agent=None).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sylea.core.storage.database import DatabaseManager
from api.main import app
from api.dependencies import get_db, get_agent


# ── Helpers ──────────────────────────────────────────────────────────────────

_PROFIL_PAYLOAD = {
    "nom": "Test User",
    "age": 30,
    "profession": "Ingenieur",
    "ville": "Paris",
    "situation_familiale": "Celibataire",
    "revenu_annuel": 50000,
    "patrimoine_estime": 10000,
    "charges_mensuelles": 1500,
    "objectif": {
        "description": "Devenir CTO",
        "categorie": "carri\u00e8re",
        "deadline": "2030-01-01",
        "probabilite_base": 25.0,
    },
}


def _make_test_db() -> DatabaseManager:
    """Create a DatabaseManager with an in-memory SQLite DB allowing cross-thread access."""
    db = DatabaseManager(db_path=Path(":memory:"))
    # Override connect to use check_same_thread=False (needed for TestClient async threading)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    db._conn = conn
    db._initialiser_schema()
    # Migration not in _initialiser_schema but expected by ProfilUtilisateur.to_dict
    try:
        conn.execute(
            "ALTER TABLE profil_utilisateur ADD COLUMN objectif_probabilite_calculee REAL DEFAULT 0.0"
        )
    except Exception:
        pass
    return db


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def client():
    """Create a TestClient backed by an in-memory SQLite DB and no agent."""
    db = _make_test_db()

    async def _override_get_db():
        yield db

    def _override_get_agent():
        return None

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_agent] = _override_get_agent

    with TestClient(app) as c:
        yield c

    db.disconnect()
    app.dependency_overrides.clear()


@pytest.fixture()
def client_with_profil(client: TestClient):
    """Return a client that already has a profil created."""
    resp = client.post("/api/profil", json=_PROFIL_PAYLOAD)
    assert resp.status_code == 200, f"Profil creation failed: {resp.text}"
    return client


# ── Tests: POST /api/dilemme/analyser ────────────────────────────────────────

def test_analyser_with_two_options(client_with_profil: TestClient):
    """Analyser with 2 options returns 200 and fallback AnalyseDilemmeOut."""
    payload = {
        "question": "Dois-je changer de travail ?",
        "options": ["Rester dans mon poste actuel", "Accepter la nouvelle offre"],
    }
    resp = client_with_profil.post("/api/dilemme/analyser", json=payload)
    assert resp.status_code == 200

    data = resp.json()
    assert data["question"] == payload["question"]
    assert len(data["options"]) == 2
    assert data["options"][0]["lettre"] == "A"
    assert data["options"][1]["lettre"] == "B"
    # Fallback mode (no agent) → impact_probabilite should be 0.0
    for opt in data["options"]:
        assert opt["impact_probabilite"] == 0.0
        assert len(opt["pros"]) > 0
        assert len(opt["cons"]) > 0
    assert data["option_recommandee"] == "A"
    assert "verdict" in data


def test_analyser_with_less_than_two_options(client_with_profil: TestClient):
    """Analyser with fewer than 2 options returns 400."""
    payload = {
        "question": "Dois-je changer de travail ?",
        "options": ["Seule option"],
    }
    resp = client_with_profil.post("/api/dilemme/analyser", json=payload)
    assert resp.status_code == 400
    assert "2 options" in resp.json()["detail"]


def test_analyser_without_profil(client: TestClient):
    """Analyser without an existing profil returns 404."""
    payload = {
        "question": "Dois-je changer de travail ?",
        "options": ["Option A", "Option B"],
    }
    resp = client.post("/api/dilemme/analyser", json=payload)
    assert resp.status_code == 404


# ── Tests: POST /api/dilemme/choisir ─────────────────────────────────────────

def test_choisir_updates_probability(client_with_profil: TestClient):
    """Choisir an option records a decision and updates the probability."""
    # First get current profil to know prob before
    profil_resp = client_with_profil.get("/api/profil")
    assert profil_resp.status_code == 200
    prob_avant = profil_resp.json()["probabilite_actuelle"]

    impact = 2.5
    payload = {
        "question": "Dois-je changer de travail ?",
        "options": [
            {
                "lettre": "A",
                "description": "Rester dans mon poste actuel",
                "pros": ["Stabilite"],
                "cons": ["Ennui"],
                "impact_probabilite": impact,
                "resume": "Rester est stable.",
            },
            {
                "lettre": "B",
                "description": "Accepter la nouvelle offre",
                "pros": ["Progression"],
                "cons": ["Risque"],
                "impact_probabilite": -1.0,
                "resume": "Changer comporte des risques.",
            },
        ],
        "choix": "A",
    }
    resp = client_with_profil.post("/api/dilemme/choisir", json=payload)
    assert resp.status_code == 200

    data = resp.json()
    assert data["probabilite_avant"] == prob_avant
    expected_apres = max(0.01, min(99.9, prob_avant + impact))
    assert data["probabilite_apres"] == pytest.approx(expected_apres, abs=0.01)
    assert data["question"] == payload["question"]
    assert data["option_choisie_id"] is not None

    # Verify profil probability was updated
    profil_resp2 = client_with_profil.get("/api/profil")
    assert profil_resp2.json()["probabilite_actuelle"] == pytest.approx(expected_apres, abs=0.01)
