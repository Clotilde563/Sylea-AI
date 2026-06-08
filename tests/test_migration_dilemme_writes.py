"""
Tests E2E pour la migration PG de l'endpoint POST /api/dilemme/choisir.

Migration verifiee :
  - SELECT decisions (anti-doublon) → SQLAlchemy text() async
  - SELECT sous_objectifs + apply_impact_invariant_safe_async → cascade SO

Le LLM helper `_identifier_so_pertinent` n'est PAS migre (il fait un appel
HTTP a Claude, hors scope DB). Pour les tests, l'IA tombe en fallback :
le 1er SO non-sature est choisi.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
from sylea.core.models.user import ProfilUtilisateur, Objectif
from sylea.core.models.decision import Decision, OptionDilemme
from api.dependencies import (
    get_optional_user, get_profil_repo, get_decision_repo, get_db, get_agent,
)
from api.main import app


TEST_USER_ID = "test-user-migration-dilemme"


# ── Fixtures (reuse pattern from test_migration_historique) ─────────────────

@pytest.fixture()
def shared_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_sylea.db"
    db_path_str = str(db_path).replace("\\", "/")

    db = DatabaseManager(db_path)
    db._conn = sqlite3.connect(str(db_path), check_same_thread=False)
    db._conn.row_factory = sqlite3.Row
    db._conn.execute("PRAGMA journal_mode=WAL;")
    db._conn.execute("PRAGMA foreign_keys=ON;")
    db._initialiser_schema()

    import api.database.engine as engine_module
    new_url = f"sqlite+aiosqlite:///{db_path_str}"
    monkeypatch.setattr(engine_module, "DATABASE_URL", new_url)
    monkeypatch.setattr(engine_module, "is_sqlite", True)
    monkeypatch.setattr(engine_module, "is_postgres", False)
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(engine_module, "_engine_read", None)
    monkeypatch.setattr(engine_module, "_session_factory", None)

    yield db

    try:
        from api.database.engine import dispose_engines
        asyncio.run(dispose_engines())
    except Exception:
        pass
    try:
        db._conn.close()
    except Exception:
        pass


@pytest.fixture()
def auth_client(shared_db):
    repo = ProfilRepository(shared_db)
    drepo = DecisionRepository(shared_db)

    app.dependency_overrides[get_optional_user] = lambda: TEST_USER_ID
    app.dependency_overrides[get_profil_repo] = lambda: repo
    app.dependency_overrides[get_decision_repo] = lambda: drepo
    app.dependency_overrides[get_db] = lambda: shared_db
    # Pas d'agent IA : forcera le fallback dans _identifier_so_pertinent
    app.dependency_overrides[get_agent] = lambda: None
    yield TestClient(app), repo, drepo, shared_db
    app.dependency_overrides.clear()


def _make_profil(repo: ProfilRepository, temps_initial_jours: int = 1000,
                 temps_gagne_jours: float = 0.0,
                 probabilite_actuelle: float = 50.0) -> ProfilUtilisateur:
    profil = ProfilUtilisateur(
        nom="Test User", age=30, profession="dev", ville="Paris",
        situation_familiale="celibataire",
        revenu_annuel=30000.0, patrimoine_estime=10000.0, charges_mensuelles=1500.0,
        objectif=Objectif(description="Test", categorie="carrière"),
        temps_initial_jours=temps_initial_jours,
        temps_gagne_jours=temps_gagne_jours,
        probabilite_actuelle=probabilite_actuelle,
    )
    profil.id = str(uuid.uuid4())
    repo.sauvegarder(profil, auth_user_id=TEST_USER_ID)
    return profil


def _create_so(db: DatabaseManager, profil_id: str, titre: str, ordre: int,
               temps_estime: float = 200.0, progression: float = 0.0) -> str:
    so_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO sous_objectifs (id, user_id, titre, description, progression, "
        "ordre, cree_le, temps_estime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (so_id, profil_id, titre, "", progression, ordre,
         datetime.utcnow().isoformat(), temps_estime),
    )
    db.conn.commit()
    return so_id


def _make_choisir_payload(question: str, impact: float = 5.0,
                          impact_jours: float = 50.0,
                          impact_temporel_jours: int = 30) -> dict:
    """Payload typique pour POST /api/dilemme/choisir."""
    return {
        "question": question,
        "impact_temporel_jours": impact_temporel_jours,
        "options": [
            {
                "lettre": "A",
                "description": "Option A choisie",
                "pros": ["bon"],
                "cons": ["risque"],
                "impact_probabilite": impact,
                "impact_jours": impact_jours,
                "resume": "Option A resume",
            },
            {
                "lettre": "B",
                "description": "Option B",
                "pros": ["autre"],
                "cons": ["moins bien"],
                "impact_probabilite": -1.0,
                "impact_jours": -10.0,
                "resume": "Option B resume",
            },
        ],
        "choix": "A",
    }


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/dilemme/choisir (migration writes)
# ════════════════════════════════════════════════════════════════════════════

class TestChoisirOption:
    """Validates le flow complet : decision sauvee + profil maj + SO cascade."""

    def test_choisir_creates_decision_and_updates_profil(self, auth_client):
        """Une decision est creee, profil.probabilite_actuelle et
        temps_gagne sont mis a jour coherents avec la progression."""
        client, repo, drepo, _ = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000,
                              temps_gagne_jours=0.0, probabilite_actuelle=10.0)

        payload = _make_choisir_payload("Dois-je faire X ?",
                                         impact=5.0, impact_jours=50.0)
        r = client.post("/api/dilemme/choisir", json=payload)
        assert r.status_code == 200, r.text

        # Decision creee
        decisions = drepo.lister_pour_utilisateur(profil.id, limite=10)
        assert len(decisions) == 1
        d = decisions[0]
        assert d.question == payload["question"]
        assert d.temps_gagne_avant == pytest.approx(0.0, abs=0.5)
        assert d.temps_gagne_apres == pytest.approx(50.0, abs=0.5)

        # Profil maj : temps_gagne = 50, probabilite_actuelle = 5% (50/1000*100)
        profil_relu = repo.charger(auth_user_id=TEST_USER_ID)
        assert profil_relu.temps_gagne_jours == pytest.approx(50.0, abs=0.5)
        assert profil_relu.probabilite_actuelle == pytest.approx(5.0, abs=0.1)

    def test_choisir_applies_so_cascade(self, auth_client):
        """L'impact est applique sur le 1er SO non-sature via cascade.

        Note : sans agent IA, _identifier_so_pertinent retourne None et
        on fallback sur le 1er SO de la liste (par ordre).
        """
        client, repo, _, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000,
                              temps_gagne_jours=0.0)
        so1_id = _create_so(db, profil.id, "SO 1", 0, temps_estime=400.0)
        so2_id = _create_so(db, profil.id, "SO 2", 1, temps_estime=600.0)

        payload = _make_choisir_payload("Test SO cascade",
                                         impact=2.0, impact_jours=20.0)
        r = client.post("/api/dilemme/choisir", json=payload)
        assert r.status_code == 200, r.text

        # te_prop SO 1 = 400 (sur 1000 = sum_te)
        # intent_delta = 20 / 400 * 100 = 5%
        # SO 1 = 0 + 5 = 5%
        so1 = db.conn.execute(
            "SELECT progression FROM sous_objectifs WHERE id = ?", (so1_id,),
        ).fetchone()
        assert so1["progression"] == pytest.approx(5.0, abs=0.1)

        # SO 2 reste a 0
        so2 = db.conn.execute(
            "SELECT progression FROM sous_objectifs WHERE id = ?", (so2_id,),
        ).fetchone()
        assert so2["progression"] == pytest.approx(0.0, abs=0.01)

    def test_choisir_anti_doublon_blocks_duplicate(self, auth_client):
        """Le meme dilemme dans la fenetre temporelle est bloque (409)."""
        client, repo, drepo, _ = auth_client
        _make_profil(repo)

        payload = _make_choisir_payload("Dois-je acheter X ?",
                                         impact=3.0, impact_temporel_jours=30)

        # 1er appel : OK
        r1 = client.post("/api/dilemme/choisir", json=payload)
        assert r1.status_code == 200, r1.text

        # 2eme appel identique : doit retourner 409
        r2 = client.post("/api/dilemme/choisir", json=payload)
        assert r2.status_code == 409, r2.text
        assert "deja ete soumis" in r2.json()["detail"]

    def test_choisir_anti_doublon_allows_different_dilemme(self, auth_client):
        """Un dilemme avec options differentes ne bloque pas."""
        client, repo, _, _ = auth_client
        _make_profil(repo)

        payload1 = _make_choisir_payload("Q1", impact=3.0)
        payload2 = _make_choisir_payload("Q2", impact=3.0)
        # Differencier les options
        payload2["options"][0]["description"] = "Different option"

        r1 = client.post("/api/dilemme/choisir", json=payload1)
        assert r1.status_code == 200, r1.text

        r2 = client.post("/api/dilemme/choisir", json=payload2)
        assert r2.status_code == 200, r2.text

    def test_choisir_no_so_still_works(self, auth_client):
        """Sans SO, l'endpoint ne crash pas (cascade skip)."""
        client, repo, drepo, _ = auth_client
        profil = _make_profil(repo)

        payload = _make_choisir_payload("Pas de SO", impact=2.0)
        r = client.post("/api/dilemme/choisir", json=payload)
        assert r.status_code == 200, r.text
        # Decision creee normalement
        decisions = drepo.lister_pour_utilisateur(profil.id, limite=10)
        assert len(decisions) == 1

    def test_choisir_invalid_choix_returns_400(self, auth_client):
        client, repo, _, _ = auth_client
        _make_profil(repo)
        payload = _make_choisir_payload("Test", impact=2.0)
        payload["choix"] = "Z"  # Pas dans options A/B
        r = client.post("/api/dilemme/choisir", json=payload)
        assert r.status_code == 400

    def test_choisir_without_profil_returns_404(self, auth_client):
        client, _, _, _ = auth_client
        payload = _make_choisir_payload("Test", impact=2.0)
        r = client.post("/api/dilemme/choisir", json=payload)
        assert r.status_code == 404
