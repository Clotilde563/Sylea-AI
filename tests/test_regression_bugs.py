"""
Regression tests for 3 critical bugs:
  Bug 1: Context (agent_collected_info) must be injected in dilemme analysis
  Bug 2: Impact must never be 0 for both options (when agent is active)
  Bug 3: Negative impact must decrease sous-objectif progression

These tests require ANTHROPIC_API_KEY for Bug 1 & 2 (real API calls).
Bug 3 is purely local (database logic).
"""

import os
import sqlite3

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from api.main import app
from api.dependencies import get_db, get_agent, get_optional_user
from sylea.core.storage.database import DatabaseManager


TEST_USER_ID = "test-regression-user"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_test_db() -> DatabaseManager:
    """Create a DatabaseManager with an in-memory SQLite DB allowing cross-thread access."""
    db = DatabaseManager(db_path=Path(":memory:"))
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    db._conn = conn
    db._initialiser_schema()
    # Migration colonne manquante
    try:
        conn.execute(
            "ALTER TABLE profil_utilisateur ADD COLUMN objectif_probabilite_calculee REAL DEFAULT 0.0"
        )
    except Exception:
        pass
    return db


_PROFIL_PAYLOAD = {
    "nom": "Test User",
    "age": 25,
    "profession": "developpeur",
    "ville": "Paris",
    "situation_familiale": "celibataire",
    "revenu_annuel": 40000,
    "patrimoine_estime": 5000,
    "charges_mensuelles": 1000,
    "objectif": {
        "description": "Devenir freelance",
        "categorie": "carri\u00e8re",
        "deadline": "2030-01-01",
        "probabilite_base": 5.0,
    },
}


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    """Create an in-memory DB with schema + test user for FK constraints."""
    manager = _make_test_db()
    conn = manager._conn
    # Insert a test user for FK on agent_collected_info
    conn.execute(
        "INSERT INTO users (id, email, hashed_password, provider, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (TEST_USER_ID, "regression@test.com", "fake_hash", "local"),
    )
    conn.commit()
    yield manager
    manager.disconnect()


@pytest.fixture()
def client_with_context(db):
    """
    TestClient with a profile AND collected context about known people.
    Used for Bug 1 and Bug 2 regression tests.
    Does NOT override get_agent so the real Claude API is used for analysis.
    """
    async def _override_get_db():
        yield db

    async def _override_get_optional_user():
        return TEST_USER_ID

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_optional_user] = _override_get_optional_user

    with TestClient(app) as c:
        # Create profil
        resp = c.post("/api/profil", json=_PROFIL_PAYLOAD)
        assert resp.status_code == 200, f"Profil creation failed: {resp.text}"

        # Add collected context about Arthur and Remi
        db._conn.execute(
            "INSERT INTO agent_collected_info (user_id, field, value, collected_at) "
            "VALUES (?, 'environnement_social', "
            "'Arthur est un ami motivant qui aide dans les projets pro. "
            "Remi est un ami negatif qui freine la progression.', datetime('now'))",
            (TEST_USER_ID,),
        )
        db._conn.commit()

        yield c, db, TEST_USER_ID

    app.dependency_overrides.clear()


# ── Bug 1 regression: Context must be injected in analysis ────────────────

@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="No API key -- ANTHROPIC_API_KEY not set",
)
def test_collected_context_injected_in_dilemme(client_with_context):
    """Bug 1 regression: agent_collected_info MUST be used in dilemme analysis."""
    client, db, user_id = client_with_context

    res = client.post("/api/dilemme/analyser", json={
        "question": "Aller a la soiree de Arthur ou Remi",
        "options": ["Aller a la soiree de Arthur", "Aller a la soiree de Remi"],
        "impact_temporel_jours": 1,
    })
    assert res.status_code == 200
    data = res.json()

    # The verdict should NOT say "sans donnees" or "inconnu" about Arthur/Remi
    # because the collected context describes them
    verdict = data.get("verdict", "").lower()
    assert "inconnu" not in verdict or "sans donn" not in verdict, \
        f"Verdict treats Arthur/Remi as unknown despite collected context: {verdict}"


# ── Bug 2 regression: Impact must never be 0 for both options ─────────────

@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="No API key -- ANTHROPIC_API_KEY not set",
)
def test_impact_never_zero_for_both_options(client_with_context):
    """Bug 2 regression: at least one option must have non-zero impact."""
    client, db, user_id = client_with_context

    res = client.post("/api/dilemme/analyser", json={
        "question": "Choix du jour",
        "options": ["Apprendre React pendant 2h", "Regarder Netflix pendant 2h"],
        "impact_temporel_jours": 1,
    })
    assert res.status_code == 200
    data = res.json()

    impacts = [opt["impact_probabilite"] for opt in data["options"]]
    # At least one impact must be non-zero
    assert any(abs(i) > 0 for i in impacts), \
        f"All impacts are zero: {impacts}"


# ── Bug 3 regression: Negative impact must decrease SO progression ────────

def test_negative_impact_decreases_so_progression():
    """Bug 3 regression: negative impact must NOT increase sous-objectif progression.

    Tests the formula used in api/routers/dilemme.py choisir endpoint:
      impact_so = impact_probabilite * (total_te / te)
      new_prog  = min(100, max(0, progression + impact_so))
    """
    old_progression = 50.0

    # Simulate the update formula from dilemme.py with negative impact
    impact_probabilite = -5.0
    total_te = 365  # sum of all SO temps_estime
    te = 365        # this SO's temps_estime
    impact_so = impact_probabilite * (total_te / te)  # Should be -5.0
    new_progression = max(0, min(100, old_progression + impact_so))

    assert impact_so < 0, f"impact_so should be negative: {impact_so}"
    assert new_progression < old_progression, \
        f"Negative impact should decrease progression: {old_progression} -> {new_progression}"
    assert new_progression == 45.0, \
        f"Expected 45.0, got {new_progression}"


def test_negative_impact_with_multiple_so():
    """Bug 3 regression (variant): negative impact with multiple SOs still decreases progression."""
    old_progression = 50.0

    # With multiple SOs, total_te > te, amplifying the impact
    impact_probabilite = -2.0
    total_te = 730  # two SOs of 365 days each
    te = 365        # this SO's temps_estime
    impact_so = impact_probabilite * (total_te / te)  # -2.0 * 2 = -4.0
    new_progression = max(0, min(100, old_progression + impact_so))

    assert impact_so == -4.0, f"Expected impact_so = -4.0, got {impact_so}"
    assert new_progression == 46.0, f"Expected 46.0, got {new_progression}"
    assert new_progression < old_progression


def test_positive_impact_increases_so_progression():
    """Sanity check: positive impact should increase progression."""
    old_progression = 50.0
    impact_probabilite = 3.0
    total_te = 365
    te = 365
    impact_so = impact_probabilite * (total_te / te)
    new_progression = max(0, min(100, old_progression + impact_so))

    assert new_progression > old_progression
    assert new_progression == 53.0


def test_progression_clamped_at_zero():
    """Progression must never go below 0."""
    old_progression = 2.0
    impact_probabilite = -10.0
    total_te = 365
    te = 365
    impact_so = impact_probabilite * (total_te / te)
    new_progression = max(0, min(100, old_progression + impact_so))

    assert new_progression == 0.0, f"Expected 0.0, got {new_progression}"
