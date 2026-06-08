"""
Tests E2E pour la migration PG des endpoints d'ecriture de objectifs.py.

Endpoints couverts :
  - POST /api/taches/abandonner         (UPDATE simple)
  - POST /api/taches/completer          (cascade SO + Decision + UPDATE)

Helper migre :
  - apply_impact_invariant_safe_async   (so_invariant.py)
  - _cascade_overflow_async             (so_invariant.py)

Strategie test : DB SQLite partagee (temp file) entre :
  - DatabaseManager (sync, utilise par les repositories)
  - get_session_factory() (async, utilise par les helpers migres)
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
from sylea.core.models.user import ProfilUtilisateur, Objectif
from api.dependencies import (
    get_optional_user, get_profil_repo, get_decision_repo, get_db,
)
from api.main import app


TEST_USER_ID = "test-user-migration-obj"


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def shared_db(tmp_path, monkeypatch):
    """DB SQLite fichier partagee entre sync DatabaseManager et async session."""
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
    """Client FastAPI avec DB partagee + auth mockee."""
    repo = ProfilRepository(shared_db)
    drepo = DecisionRepository(shared_db)

    app.dependency_overrides[get_optional_user] = lambda: TEST_USER_ID
    app.dependency_overrides[get_profil_repo] = lambda: repo
    app.dependency_overrides[get_decision_repo] = lambda: drepo
    app.dependency_overrides[get_db] = lambda: shared_db
    yield TestClient(app), repo, drepo, shared_db
    app.dependency_overrides.clear()


def _make_profil(repo: ProfilRepository, temps_initial_jours: int = 1000,
                 temps_gagne_jours: float = 0.0,
                 probabilite_actuelle: float = 0.0) -> ProfilUtilisateur:
    """Cree un profil de test."""
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
    """Cree un sous-objectif et retourne son ID."""
    so_id = str(uuid.uuid4())
    db.conn.execute(
        "INSERT INTO sous_objectifs (id, user_id, titre, description, progression, "
        "ordre, cree_le, temps_estime) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (so_id, profil_id, titre, "", progression, ordre,
         datetime.utcnow().isoformat(), temps_estime),
    )
    db.conn.commit()
    return so_id


def _create_taches_today(db: DatabaseManager, profil_id: str,
                         taches_data: list[dict],
                         statut: str = "en_cours") -> str:
    """Cree des taches quotidiennes pour aujourd'hui."""
    tache_id = str(uuid.uuid4())
    today = date.today().isoformat()
    db.conn.execute(
        "INSERT INTO taches_quotidiennes (id, user_id, date, taches_json, "
        "deadline, statut, cree_le) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (tache_id, profil_id, today,
         json.dumps(taches_data, ensure_ascii=False),
         "23:59", statut, datetime.utcnow().isoformat()),
    )
    db.conn.commit()
    return tache_id


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/taches/abandonner
# ════════════════════════════════════════════════════════════════════════════

class TestAbandonnerTaches:
    """Validates que l'endpoint POST /api/taches/abandonner (migre async)
    marque correctement les taches du jour comme 'abandonnee'."""

    def test_abandonner_marks_today_taches_as_abandoned(self, auth_client):
        """Les taches en_cours du jour passent en abandonnee."""
        client, repo, _, db = auth_client
        profil = _make_profil(repo)
        _create_taches_today(
            db, profil.id,
            [{"id": "t1", "description": "Faire X", "completee": False}],
            statut="en_cours",
        )

        r = client.post("/api/taches/abandonner")
        assert r.status_code == 200, r.text
        assert r.json() == {"detail": "Taches abandonnees."}

        # Verifier le statut en DB
        row = db.conn.execute(
            "SELECT statut FROM taches_quotidiennes WHERE user_id = ?",
            (profil.id,),
        ).fetchone()
        assert row["statut"] == "abandonnee"

    def test_abandonner_does_not_touch_terminee(self, auth_client):
        """Les taches deja terminee restent terminee (filtree par 'en_cours')."""
        client, repo, _, db = auth_client
        profil = _make_profil(repo)
        _create_taches_today(
            db, profil.id,
            [{"id": "t1", "description": "Done", "completee": True}],
            statut="terminee",
        )

        r = client.post("/api/taches/abandonner")
        assert r.status_code == 200, r.text

        row = db.conn.execute(
            "SELECT statut FROM taches_quotidiennes WHERE user_id = ?",
            (profil.id,),
        ).fetchone()
        assert row["statut"] == "terminee"  # Pas modifie

    def test_abandonner_without_profil_returns_404(self, auth_client):
        client, _, _, _ = auth_client
        r = client.post("/api/taches/abandonner")
        assert r.status_code == 404


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/taches/completer
# ════════════════════════════════════════════════════════════════════════════

class TestCompleterTache:
    """Validates que l'endpoint POST /api/taches/completer (migre async)
    applique correctement l'impact + cascade SO + sauvegarde Decision."""

    def test_completer_marks_tache_as_completed(self, auth_client):
        """La tache passe a completee=True dans le JSON."""
        client, repo, _, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=0.0)
        _create_so(db, profil.id, "SO 1", 0, temps_estime=500.0)

        _create_taches_today(
            db, profil.id,
            [
                {"id": "t1", "description": "Tache A", "completee": False},
                {"id": "t2", "description": "Tache B", "completee": False},
            ],
        )

        r = client.post("/api/taches/completer", json={"tache_id": "t1"})
        assert r.status_code == 200, r.text

        # Verifier le JSON mis a jour
        row = db.conn.execute(
            "SELECT taches_json, statut FROM taches_quotidiennes WHERE user_id = ?",
            (profil.id,),
        ).fetchone()
        taches = json.loads(row["taches_json"])
        assert taches[0]["completee"] is True
        assert taches[1]["completee"] is False
        # Pas toutes completees → statut reste en_cours
        assert row["statut"] == "en_cours"

    def test_completer_increments_temps_gagne(self, auth_client):
        """Apres completer, profil.temps_gagne += 0.5j."""
        client, repo, _, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=10.0)
        _create_so(db, profil.id, "SO 1", 0, temps_estime=500.0)
        _create_taches_today(
            db, profil.id,
            [{"id": "t1", "description": "Tache A", "completee": False}],
        )

        r = client.post("/api/taches/completer", json={"tache_id": "t1"})
        assert r.status_code == 200, r.text

        profil_relu = repo.charger(auth_user_id=TEST_USER_ID)
        assert profil_relu.temps_gagne_jours == pytest.approx(10.5, abs=0.01)

    def test_completer_all_taches_marks_day_terminee(self, auth_client):
        """Quand toutes les taches sont completees, statut = 'terminee'."""
        client, repo, _, db = auth_client
        profil = _make_profil(repo)
        _create_so(db, profil.id, "SO 1", 0, temps_estime=500.0)
        _create_taches_today(
            db, profil.id,
            [{"id": "t1", "description": "Solo", "completee": False}],
        )

        r = client.post("/api/taches/completer", json={"tache_id": "t1"})
        assert r.status_code == 200, r.text

        row = db.conn.execute(
            "SELECT statut FROM taches_quotidiennes WHERE user_id = ?",
            (profil.id,),
        ).fetchone()
        assert row["statut"] == "terminee"

    def test_completer_cascade_applies_impact_to_active_so(self, auth_client):
        """L'impact de 0.5j est applique sur le SO actif (1er <100%)
        via cascade invariant-safe."""
        client, repo, _, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=0.0)
        so1_id = _create_so(db, profil.id, "SO 1", 0,
                            temps_estime=500.0, progression=0.0)
        so2_id = _create_so(db, profil.id, "SO 2", 1,
                            temps_estime=500.0, progression=0.0)
        _create_taches_today(
            db, profil.id,
            [{"id": "t1", "description": "Test", "completee": False}],
        )

        r = client.post("/api/taches/completer", json={"tache_id": "t1"})
        assert r.status_code == 200, r.text
        body = r.json()
        # SO actif (1er <100) = SO 1
        assert body["sous_objectif_impacte"] == "SO 1"
        assert len(body["impacts_sous_objectifs"]) == 1
        # Verifier la progression appliquee
        # te_prop_so1 = 500/1000 × 1000 = 500
        # intent_delta = 0.5 / 500 × 100 = 0.1%
        so_row = db.conn.execute(
            "SELECT progression FROM sous_objectifs WHERE id = ?",
            (so1_id,),
        ).fetchone()
        assert so_row["progression"] == pytest.approx(0.1, abs=0.01)
        # SO 2 reste a 0
        so2_row = db.conn.execute(
            "SELECT progression FROM sous_objectifs WHERE id = ?",
            (so2_id,),
        ).fetchone()
        assert so2_row["progression"] == 0.0

    def test_completer_creates_decision_in_history(self, auth_client):
        """Une Decision est inseree dans l'historique avec les bons champs."""
        client, repo, drepo, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=5.0,
                              probabilite_actuelle=0.5)
        _create_so(db, profil.id, "SO 1", 0, temps_estime=500.0)
        _create_taches_today(
            db, profil.id,
            [{"id": "t1", "description": "Test decision", "completee": False}],
        )

        r = client.post("/api/taches/completer", json={"tache_id": "t1"})
        assert r.status_code == 200, r.text

        decisions = drepo.lister_pour_utilisateur(profil.id, limite=10)
        assert len(decisions) == 1
        d = decisions[0]
        assert d.question == "[Tache] Test decision"
        # impact_score = delta_prob = 0.5 / 1000 × 100 = 0.05%
        assert d.options[0].impact_score == pytest.approx(0.05, abs=0.001)
        # temps_gagne_avant = profil.tg post-update (5.5) - impact_jours (0.5) = 5.0
        assert d.temps_gagne_avant == pytest.approx(5.0, abs=0.01)
        assert d.temps_gagne_apres == pytest.approx(5.5, abs=0.01)

    def test_completer_no_active_so_still_works(self, auth_client):
        """Sans SO ou tous a 100%, l'endpoint ne crash pas."""
        client, repo, _, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=0.0)
        # SO deja a 100%
        _create_so(db, profil.id, "SO Done", 0,
                   temps_estime=500.0, progression=100.0)
        _create_taches_today(
            db, profil.id,
            [{"id": "t1", "description": "Test", "completee": False}],
        )

        r = client.post("/api/taches/completer", json={"tache_id": "t1"})
        assert r.status_code == 200, r.text
        body = r.json()
        # Le SO etant deja a 100%, fallback est cherche, mais y'en a pas d'autre
        # Donc sous_objectif_impacte peut etre None ou le SO existant
        # L'important : pas de crash
        assert body["tache"]["id"] == "t1"

    def test_completer_unknown_tache_returns_404(self, auth_client):
        """Tache_id inconnu retourne 404."""
        client, repo, _, db = auth_client
        profil = _make_profil(repo)
        _create_so(db, profil.id, "SO 1", 0)
        _create_taches_today(
            db, profil.id,
            [{"id": "t1", "description": "X", "completee": False}],
        )

        r = client.post("/api/taches/completer", json={"tache_id": "nonexistent"})
        assert r.status_code == 404

    def test_completer_without_today_taches_returns_404(self, auth_client):
        """Sans taches du jour, retourne 404."""
        client, repo, _, db = auth_client
        _make_profil(repo)
        r = client.post("/api/taches/completer", json={"tache_id": "t1"})
        assert r.status_code == 404


# ════════════════════════════════════════════════════════════════════════════
#  Invariant SO apres cascade
# ════════════════════════════════════════════════════════════════════════════

class TestInvariantSOApresCompleter:
    """Verifie que l'invariant Dashboard est preserve apres completer_tache,
    meme avec cascade overflow."""

    def test_invariant_preserved_simple_case(self, auth_client):
        """Cas simple : impact sur SO non-sature, invariant tient."""
        client, repo, _, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=0.0)
        so1_id = _create_so(db, profil.id, "SO A", 0, temps_estime=600.0)
        so2_id = _create_so(db, profil.id, "SO B", 1, temps_estime=400.0)
        _create_taches_today(
            db, profil.id,
            [{"id": "t1", "description": "Test", "completee": False}],
        )

        r = client.post("/api/taches/completer", json={"tache_id": "t1"})
        assert r.status_code == 200, r.text

        # Verifier invariant : sum(te_prop × (1 - prog/100)) ≈ temps_initial - temps_gagne
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
        # Tolerance 1j (impact_jours = 0.5)
        assert abs(temps_restant_so - temps_restant_profil) < 1.0, (
            f"Invariant viole : SO={temps_restant_so:.2f} != profil={temps_restant_profil:.2f}"
        )

    def test_invariant_with_overflow_cascade(self, auth_client):
        """SO actif quasi-sature : overflow cascade sur les autres SO,
        l'invariant doit tenir.

        Setup coherent : on aligne profil.temps_gagne avec l'etat des SO
        pour partir d'un invariant valide.

        SO 1 te=50, prog=99.99% : contribue 50 × 0.9999 = 49.995j
        SO 2 te=950, prog=0%    : contribue 0j
        → profil.temps_gagne doit etre 49.995 (puis +0.5 apres completer)
        """
        client, repo, _, db = auth_client
        profil = _make_profil(
            repo, temps_initial_jours=1000, temps_gagne_jours=49.995,
        )
        # SO 1 quasi-sature (99.99%) avec un petit te (50j)
        # Impact 0.5j → delta_pct = 0.5/50*100 = 1% → 99.99 + 1 = 100.99 (overflow)
        so1_id = _create_so(db, profil.id, "SO 1", 0,
                            temps_estime=50.0, progression=99.99)
        # SO 2 non-sature, recoit l'overflow
        so2_id = _create_so(db, profil.id, "SO 2", 1,
                            temps_estime=950.0, progression=0.0)
        _create_taches_today(
            db, profil.id,
            [{"id": "t1", "description": "Overflow test", "completee": False}],
        )

        r = client.post("/api/taches/completer", json={"tache_id": "t1"})
        assert r.status_code == 200, r.text

        # SO 1 doit etre a 100% (capped)
        so1 = db.conn.execute(
            "SELECT progression FROM sous_objectifs WHERE id = ?", (so1_id,),
        ).fetchone()
        assert so1["progression"] == pytest.approx(100.0, abs=0.1)
        # SO 2 doit avoir absorbe l'overflow (au moins une petite progression)
        so2 = db.conn.execute(
            "SELECT progression FROM sous_objectifs WHERE id = ?", (so2_id,),
        ).fetchone()
        assert so2["progression"] > 0.0  # absorption d'overflow

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
        assert abs(temps_restant_so - temps_restant_profil) < 1.0, (
            f"Invariant overflow viole : SO={temps_restant_so:.2f} != "
            f"profil={temps_restant_profil:.2f}"
        )
