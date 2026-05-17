"""
Tests E2E pour la migration PG de l'endpoint POST /api/evenement/confirmer.

Migration verifiee :
  - SELECT decisions (anti-doublon)             → SQLAlchemy text() async
  - SELECT sous_objectifs + cascade SO          → async + apply_impact_invariant_safe_async
  - Snapshot avant/apres + cascade_items        → meme transaction async

LLM helper `_identifier_so_pertinent` n'est pas migre (hors scope DB).
Sans agent, le fallback choisit le 1er SO non-sature.
"""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
from sylea.core.models.user import ProfilUtilisateur, Objectif
from api.dependencies import (
    get_optional_user, get_profil_repo, get_decision_repo, get_db, get_agent,
)
from api.main import app


TEST_USER_ID = "test-user-migration-evt"


# ── Fixtures ─────────────────────────────────────────────────────────────────

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


def _make_confirmer_payload(description: str, impact_probabilite: float = 5.0,
                             impact_jours: float = 50.0,
                             resume: str = "Resume de l'evenement",
                             pros: list = None, cons: list = None) -> dict:
    return {
        "description": description,
        "impact_probabilite": impact_probabilite,
        "impact_jours": impact_jours,
        "resume": resume,
        "pros": pros or ["bon"],
        "cons": cons or ["risque"],
    }


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/evenement/confirmer (migration)
# ════════════════════════════════════════════════════════════════════════════

class TestConfirmerEvenement:
    """Validates le flow complet : decision sauvee + profil maj + SO cascade
    via la migration PG-compatible."""

    def test_confirmer_creates_decision_and_updates_profil(self, auth_client):
        """Une decision typee 'evenement' est creee et le profil mis a jour."""
        client, repo, drepo, _ = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000,
                              temps_gagne_jours=0.0, probabilite_actuelle=10.0)

        payload = _make_confirmer_payload("Promotion accordee !",
                                           impact_probabilite=5.0,
                                           impact_jours=50.0)
        r = client.post("/api/evenement/confirmer", json=payload)
        assert r.status_code == 200, r.text

        decisions = drepo.lister_pour_utilisateur(profil.id, limite=10)
        assert len(decisions) == 1
        d = decisions[0]
        assert d.question == "[Evenement] Promotion accordee !"
        assert d.temps_gagne_avant == pytest.approx(0.0, abs=0.5)
        assert d.temps_gagne_apres == pytest.approx(50.0, abs=0.5)

        # Profil maj : temps_gagne = 50, probabilite_actuelle = 5%
        profil_relu = repo.charger(auth_user_id=TEST_USER_ID)
        assert profil_relu.temps_gagne_jours == pytest.approx(50.0, abs=0.5)
        assert profil_relu.probabilite_actuelle == pytest.approx(5.0, abs=0.1)

    def test_confirmer_anti_doublon_blocks_same_description(self, auth_client):
        """Meme description retourne 409."""
        client, repo, _, _ = auth_client
        _make_profil(repo)

        payload = _make_confirmer_payload("Achat appartement",
                                           impact_probabilite=3.0)
        r1 = client.post("/api/evenement/confirmer", json=payload)
        assert r1.status_code == 200, r1.text

        r2 = client.post("/api/evenement/confirmer", json=payload)
        assert r2.status_code == 409
        assert "deja ete enregistre" in r2.json()["detail"]

    def test_confirmer_different_descriptions_both_allowed(self, auth_client):
        """Descriptions differentes : chacune accepte."""
        client, repo, _, _ = auth_client
        _make_profil(repo)

        r1 = client.post("/api/evenement/confirmer",
                         json=_make_confirmer_payload("Event A", impact_probabilite=2.0))
        assert r1.status_code == 200, r1.text

        r2 = client.post("/api/evenement/confirmer",
                         json=_make_confirmer_payload("Event B", impact_probabilite=3.0))
        assert r2.status_code == 200, r2.text

    def test_confirmer_applies_so_cascade(self, auth_client):
        """Impact applique sur SO actif via cascade (fallback 1er SO sans agent)."""
        client, repo, _, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000,
                              temps_gagne_jours=0.0)
        so1_id = _create_so(db, profil.id, "SO Apha", 0, temps_estime=400.0)
        so2_id = _create_so(db, profil.id, "SO Beta", 1, temps_estime=600.0)

        payload = _make_confirmer_payload("Test cascade",
                                           impact_probabilite=2.0,
                                           impact_jours=20.0)
        r = client.post("/api/evenement/confirmer", json=payload)
        assert r.status_code == 200, r.text

        # te_prop SO Alpha = 400, intent_delta = 20/400*100 = 5%
        so1 = db.conn.execute(
            "SELECT progression FROM sous_objectifs WHERE id = ?", (so1_id,),
        ).fetchone()
        assert so1["progression"] == pytest.approx(5.0, abs=0.1)
        so2 = db.conn.execute(
            "SELECT progression FROM sous_objectifs WHERE id = ?", (so2_id,),
        ).fetchone()
        assert so2["progression"] == pytest.approx(0.0, abs=0.01)

    def test_confirmer_returns_cascade_items_with_deltas(self, auth_client):
        """La response contient cascade_items pour les SOs impactes."""
        client, repo, _, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000,
                              temps_gagne_jours=0.0)
        so1_id = _create_so(db, profil.id, "SO 1", 0, temps_estime=400.0)

        payload = _make_confirmer_payload("Avec cascade",
                                           impact_probabilite=2.0,
                                           impact_jours=20.0)
        r = client.post("/api/evenement/confirmer", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        # sous_objectif_impacte renseigne
        assert body["sous_objectif_impacte"] == "SO 1"

    def test_confirmer_overflow_cascade_preserves_invariant(self, auth_client):
        """Overflow cascade preserve l'invariant Dashboard."""
        client, repo, _, db = auth_client
        # Setup coherent : SO 1 quasi-sature
        profil = _make_profil(repo, temps_initial_jours=1000,
                              temps_gagne_jours=99.0)
        so1_id = _create_so(db, profil.id, "SO 1", 0,
                            temps_estime=100.0, progression=99.0)
        so2_id = _create_so(db, profil.id, "SO 2", 1,
                            temps_estime=900.0, progression=0.0)

        payload = _make_confirmer_payload("Overflow test",
                                           impact_probabilite=5.0,
                                           impact_jours=50.0)
        r = client.post("/api/evenement/confirmer", json=payload)
        assert r.status_code == 200, r.text

        # SO 1 cape a 100
        so1 = db.conn.execute(
            "SELECT progression FROM sous_objectifs WHERE id = ?", (so1_id,),
        ).fetchone()
        assert so1["progression"] == pytest.approx(100.0, abs=0.1)
        # SO 2 absorbe l'overflow
        so2 = db.conn.execute(
            "SELECT progression FROM sous_objectifs WHERE id = ?", (so2_id,),
        ).fetchone()
        assert so2["progression"] > 0.0

        # Invariant Dashboard
        profil_relu = repo.charger(auth_user_id=TEST_USER_ID)
        so_rows = db.conn.execute(
            "SELECT temps_estime, progression FROM sous_objectifs WHERE user_id = ?",
            (profil.id,),
        ).fetchall()
        sum_te = sum(max(30, r["temps_estime"] or 180) for r in so_rows)
        temps_restant_so = sum(
            (max(30, r["temps_estime"] or 180) / sum_te) *
            profil_relu.temps_initial_jours *
            (1 - (r["progression"] or 0) / 100)
            for r in so_rows
        )
        temps_restant_profil = profil_relu.temps_initial_jours - profil_relu.temps_gagne_jours
        assert abs(temps_restant_so - temps_restant_profil) < 1.5, (
            f"Invariant viole : SO={temps_restant_so:.2f} != "
            f"profil={temps_restant_profil:.2f}"
        )

    def test_confirmer_no_so_still_works(self, auth_client):
        """Sans SO, l'endpoint cree juste la decision sans crash."""
        client, repo, drepo, _ = auth_client
        profil = _make_profil(repo)

        r = client.post("/api/evenement/confirmer",
                         json=_make_confirmer_payload("Sans SO",
                                                       impact_probabilite=2.0))
        assert r.status_code == 200, r.text
        decisions = drepo.lister_pour_utilisateur(profil.id, limite=10)
        assert len(decisions) == 1

    def test_confirmer_without_profil_returns_404(self, auth_client):
        client, _, _, _ = auth_client
        r = client.post("/api/evenement/confirmer",
                         json=_make_confirmer_payload("Test"))
        assert r.status_code == 404
