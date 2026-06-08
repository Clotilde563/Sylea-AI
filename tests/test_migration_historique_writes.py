"""
Tests E2E pour la migration PG des endpoints d'ecriture de historique.py.

Endpoints couverts :
  - DELETE /api/historique/{decision_id}   (recompute SO + cleanup agent + delete)
  - POST   /api/historique/recompute-so-progressions

Ces endpoints utilisent les helpers async migres :
  - _recompute_so_progressions_async
  - _cleanup_collected_info_for_decision_async
  - _cleanup_agent_messages_for_decision_async
  - _cleanup_pending_for_decision_async

Strategie test : DB SQLite partagee (temp file) entre :
  - DatabaseManager (sync, utilise par les repositories)
  - get_session_factory() (async, utilise par les helpers migres)

Cela garantit que les writes async hit la meme DB que les reads sync.
"""

from __future__ import annotations

import asyncio
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
    get_optional_user, get_profil_repo, get_decision_repo, get_db,
)
from api.main import app


TEST_USER_ID = "test-user-migration-hist"


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture()
def shared_db(tmp_path, monkeypatch):
    """DB SQLite fichier partagee entre sync DatabaseManager et async session_factory.

    Le test ne peut pas utiliser ':memory:' car async (aiosqlite) et sync (sqlite3)
    ouvriraient deux DBs independantes. Un fichier sur disque est partage via WAL.
    """
    db_path = tmp_path / "test_sylea.db"
    db_path_str = str(db_path).replace("\\", "/")

    # Init le schema via DatabaseManager (sync) avec check_same_thread=False
    db = DatabaseManager(db_path)
    db._conn = sqlite3.connect(str(db_path), check_same_thread=False)
    db._conn.row_factory = sqlite3.Row
    db._conn.execute("PRAGMA journal_mode=WAL;")
    db._conn.execute("PRAGMA foreign_keys=ON;")
    db._initialiser_schema()

    # Reconfigure le session_factory async pour pointer sur le meme fichier
    import api.database.engine as engine_module
    new_url = f"sqlite+aiosqlite:///{db_path_str}"
    monkeypatch.setattr(engine_module, "DATABASE_URL", new_url)
    monkeypatch.setattr(engine_module, "is_sqlite", True)
    monkeypatch.setattr(engine_module, "is_postgres", False)
    monkeypatch.setattr(engine_module, "_engine", None)
    monkeypatch.setattr(engine_module, "_engine_read", None)
    monkeypatch.setattr(engine_module, "_session_factory", None)

    yield db

    # Cleanup : dispose le engine async pour liberer le fichier
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
        objectif=Objectif(
            description="Migration test", categorie="carrière",
        ),
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


def _make_decision(profil_id: str, impact_jours: float = 30.0,
                   temps_initial: int = 1000,
                   tg_avant: float = 0.0, tg_apres: float = 0.0,
                   so_id: str | None = None, impact_so: float = 0.0,
                   cree_le: datetime | None = None) -> Decision:
    """Cree une Decision."""
    delta_prob = (impact_jours / temps_initial * 100) if temps_initial > 0 else 0.0
    return Decision(
        user_id=profil_id,
        question="Test question migration",
        options=[OptionDilemme(description="opt A", impact_score=delta_prob)],
        probabilite_avant=0.0,
        probabilite_apres=delta_prob,
        temps_gagne_avant=tg_avant,
        temps_gagne_apres=tg_apres,
        sous_objectif_id=so_id,
        impact_sous_objectif=impact_so,
        cree_le=cree_le or datetime.utcnow(),
    )


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/historique/recompute-so-progressions
# ════════════════════════════════════════════════════════════════════════════

class TestPostRecomputeSoProgressions:
    """Validates que l'endpoint POST (migration async) marche correctement."""

    def test_recompute_distributes_progression_equitably_when_no_impact(
        self, auth_client
    ):
        """Sans decisions impactant des SO, chaque SO recoit la meme prog
        (= progression globale du profil)."""
        client, repo, drepo, db = auth_client
        # Profil 1000j initial, 200j gagnes = 20% progression globale
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=200.0)
        # 3 SO de meme temps_estime
        _create_so(db, profil.id, "SO 1", 0, temps_estime=300.0)
        _create_so(db, profil.id, "SO 2", 1, temps_estime=300.0)
        _create_so(db, profil.id, "SO 3", 2, temps_estime=300.0)

        r = client.post("/api/historique/recompute-so-progressions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert len(body["sous_objectifs"]) == 3
        # Sans cumul, distribution equitable = 20% pour chacun
        for so in body["sous_objectifs"]:
            assert abs(so["progression"] - 20.0) < 0.5, \
                f"SO {so['titre']} prog={so['progression']} (attendu ~20.0)"

    def test_recompute_scales_per_cumul_when_impacts_exist(self, auth_client):
        """Avec des decisions impactant des SO, les progressions sont
        scaled proportionnellement au cumul des impacts, en respectant
        l'invariant Dashboard."""
        client, repo, drepo, db = auth_client
        # Profil 1000j initial, 100j gagnes = 10% progression globale
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=100.0)
        # 2 SO de meme temps_estime (sum_te=400)
        so1_id = _create_so(db, profil.id, "SO A", 0, temps_estime=200.0)
        so2_id = _create_so(db, profil.id, "SO B", 1, temps_estime=200.0)
        # 3 decisions : 2 impactent SO_A (cumul 30), 1 impacte SO_B (cumul 10)
        # Cumul total weighted: te×cumul = 200*30 + 200*10 = 8000
        # Target: temps_gagne × sum_te / temps_initial × 100 = 100 * 400 / 1000 * 100 = 4000
        # Scale = 4000 / 8000 = 0.5
        # SO_A: cumul=30 × 0.5 = 15%
        # SO_B: cumul=10 × 0.5 = 5%
        drepo.sauvegarder(_make_decision(profil.id, so_id=so1_id, impact_so=20.0))
        drepo.sauvegarder(_make_decision(profil.id, so_id=so1_id, impact_so=10.0))
        drepo.sauvegarder(_make_decision(profil.id, so_id=so2_id, impact_so=10.0))

        r = client.post("/api/historique/recompute-so-progressions")
        assert r.status_code == 200, r.text
        body = r.json()
        sos = {so["titre"]: so["progression"] for so in body["sous_objectifs"]}
        assert abs(sos["SO A"] - 15.0) < 0.5, f"SO A: {sos['SO A']} (attendu 15.0)"
        assert abs(sos["SO B"] - 5.0) < 0.5, f"SO B: {sos['SO B']} (attendu 5.0)"

    def test_recompute_no_so_returns_ok_empty(self, auth_client):
        """Sans SO, l'endpoint retourne ok=True avec liste vide."""
        client, repo, _, _ = auth_client
        _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=50.0)

        r = client.post("/api/historique/recompute-so-progressions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["sous_objectifs"] == []

    def test_recompute_without_profil_returns_404(self, auth_client):
        """Sans profil, l'endpoint retourne 404."""
        client, _, _, _ = auth_client
        r = client.post("/api/historique/recompute-so-progressions")
        assert r.status_code == 404


# ════════════════════════════════════════════════════════════════════════════
#  DELETE /api/historique/{decision_id}
# ════════════════════════════════════════════════════════════════════════════

class TestDeleteDecision:
    """Validates que la suppression d'une decision cascade correctement :
      - decision supprimee de la DB
      - SO progressions recomputees (sans la decision supprimee)
      - profil.temps_gagne mis a jour
      - profil.probabilite_actuelle realignee sur progression
    """

    def test_delete_decision_removes_it_from_db(self, auth_client):
        """La decision supprimee n'existe plus en DB apres DELETE."""
        client, repo, drepo, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=50.0)
        decision = _make_decision(profil.id, tg_avant=0.0, tg_apres=50.0)
        drepo.sauvegarder(decision)

        # Verifier qu'elle existe
        row = db.conn.execute(
            "SELECT id FROM decisions WHERE id = ?", (decision.id,)
        ).fetchone()
        assert row is not None

        # DELETE
        r = client.delete(f"/api/historique/{decision.id}")
        assert r.status_code == 200, r.text

        # Verifier qu'elle a disparu
        row = db.conn.execute(
            "SELECT id FROM decisions WHERE id = ?", (decision.id,)
        ).fetchone()
        assert row is None

    def test_delete_decision_reverses_temps_gagne(self, auth_client):
        """temps_gagne_jours est decremente de l'impact_temps de la decision."""
        client, repo, drepo, _ = auth_client
        # Profil avec 50j deja gagnes (provenant de la decision)
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=50.0)
        decision = _make_decision(
            profil.id, tg_avant=0.0, tg_apres=50.0,  # impact = +50j
        )
        drepo.sauvegarder(decision)

        r = client.delete(f"/api/historique/{decision.id}")
        assert r.status_code == 200, r.text
        body = r.json()
        # temps_gagne doit etre 50 - 50 = 0
        assert body["temps_gagne_jours"] == pytest.approx(0.0, abs=0.5)
        # Profil reload : meme valeur
        profil_relu = repo.charger(auth_user_id=TEST_USER_ID)
        assert profil_relu.temps_gagne_jours == pytest.approx(0.0, abs=0.5)

    def test_delete_decision_resyncs_probabilite_on_progression(self, auth_client):
        """Apres DELETE, probabilite_actuelle = temps_gagne/temps_initial × 100."""
        client, repo, drepo, _ = auth_client
        # 1000j initial, 200j gagnes apres decision (20%), prob=20%
        profil = _make_profil(repo, temps_initial_jours=1000,
                              temps_gagne_jours=200.0, probabilite_actuelle=20.0)
        # Decision qui a apporte 100j
        decision = _make_decision(profil.id, tg_avant=100.0, tg_apres=200.0)
        drepo.sauvegarder(decision)

        r = client.delete(f"/api/historique/{decision.id}")
        body = r.json()
        # temps_gagne = 200 - 100 = 100j → 10% progression
        assert body["temps_gagne_jours"] == pytest.approx(100.0, abs=0.5)
        assert body["probabilite_actuelle"] == pytest.approx(10.0, abs=0.5)

    def test_delete_decision_recomputes_so_progressions(self, auth_client):
        """Apres DELETE d'une decision liee a un SO, les progressions
        SO sont recomputees a partir des decisions restantes.

        FIX (2026-05-13) : le recompute utilise maintenant le temps_gagne
        POST-DELETE (via temps_gagne_override) au lieu de la valeur PRE-DELETE
        lue depuis la DB. Resultat : l'invariant Dashboard tient EXACTEMENT
        apres DELETE, sans avoir besoin d'appeler POST /recompute en plus.
        """
        client, repo, drepo, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=100.0)
        so1_id = _create_so(db, profil.id, "SO 1", 0, temps_estime=200.0)
        so2_id = _create_so(db, profil.id, "SO 2", 1, temps_estime=200.0)

        # 2 decisions : la 1ere sera supprimee, la 2e doit rester
        d_supprimer = _make_decision(
            profil.id, tg_avant=0.0, tg_apres=50.0,
            so_id=so1_id, impact_so=30.0,
        )
        d_garder = _make_decision(
            profil.id, tg_avant=50.0, tg_apres=100.0,
            so_id=so2_id, impact_so=20.0,
        )
        drepo.sauvegarder(d_supprimer)
        drepo.sauvegarder(d_garder)

        # DELETE la 1ere
        r = client.delete(f"/api/historique/{d_supprimer.id}")
        assert r.status_code == 200, r.text

        # Recompute utilise maintenant temps_gagne POST-DELETE = 100 - 50 = 50:
        #   cumul restant = {so1_id: 0, so2_id: 20}
        #   weighted_cumul = 200×0 + 200×20 = 4000
        #   target_weighted = 50 × 400 / 1000 × 100 = 2000
        #   scale = 2000 / 4000 = 0.5
        #   SO 1 prog = 0 × 0.5 = 0%
        #   SO 2 prog = 20 × 0.5 = 10%
        so_rows = db.conn.execute(
            "SELECT titre, progression FROM sous_objectifs WHERE user_id = ? ORDER BY ordre",
            (profil.id,),
        ).fetchall()
        progressions = {r["titre"]: r["progression"] for r in so_rows}
        assert abs(progressions["SO 1"] - 0.0) < 0.5, \
            f"SO 1: {progressions['SO 1']} (attendu 0.0)"
        assert abs(progressions["SO 2"] - 10.0) < 0.5, \
            f"SO 2: {progressions['SO 2']} (attendu 10.0)"

    def test_delete_decision_not_found_returns_404(self, auth_client):
        """DELETE d'une decision inexistante retourne 404."""
        client, repo, _, _ = auth_client
        _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=0.0)
        r = client.delete("/api/historique/nonexistent-id")
        assert r.status_code == 404

    def test_delete_decision_without_profil_returns_404(self, auth_client):
        """DELETE sans profil retourne 404."""
        client, _, _, _ = auth_client
        r = client.delete("/api/historique/any-id")
        assert r.status_code == 404


# ════════════════════════════════════════════════════════════════════════════
#  Invariant Dashboard apres DELETE
# ════════════════════════════════════════════════════════════════════════════

class TestInvariantDashboardApresDelete:
    """Verifie que l'invariant Dashboard est preserve apres DELETE.

    FIX (2026-05-13) : le recompute utilise maintenant le temps_gagne
    POST-DELETE via temps_gagne_override. L'invariant tient exactement
    apres DELETE — plus besoin d'appeler POST /recompute manuellement.
    """

    def _verify_invariant(self, repo, db, profil_id, tolerance=1.0):
        """Helper : retourne (temps_restant_so, temps_restant_profil)
        et asserte qu'ils sont egaux a tolerance pres."""
        profil_relu = repo.charger(auth_user_id=TEST_USER_ID)
        so_rows = db.conn.execute(
            "SELECT temps_estime, progression FROM sous_objectifs WHERE user_id = ?",
            (profil_id,),
        ).fetchall()
        sum_te = sum(max(30, r["temps_estime"] or 180) for r in so_rows)
        temps_restant_so = sum(
            (max(30, r["temps_estime"] or 180) / sum_te) *
            profil_relu.temps_initial_jours *
            (1 - (r["progression"] or 0) / 100)
            for r in so_rows
        )
        temps_restant_profil = profil_relu.temps_initial_jours - profil_relu.temps_gagne_jours
        return temps_restant_so, temps_restant_profil

    def test_invariant_holds_directly_after_delete(self, auth_client):
        """Apres DELETE (sans recompute manuel), l'invariant Dashboard tient."""
        client, repo, drepo, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=150.0)
        so1_id = _create_so(db, profil.id, "SO A", 0, temps_estime=300.0)
        so2_id = _create_so(db, profil.id, "SO B", 1, temps_estime=500.0)

        d1 = _make_decision(profil.id, tg_avant=0.0, tg_apres=80.0,
                            so_id=so1_id, impact_so=20.0)
        d2 = _make_decision(profil.id, tg_avant=80.0, tg_apres=150.0,
                            so_id=so2_id, impact_so=25.0)
        d_supprimer = _make_decision(profil.id, tg_avant=50.0, tg_apres=100.0,
                                     so_id=so1_id, impact_so=15.0)
        drepo.sauvegarder(d1)
        drepo.sauvegarder(d2)
        drepo.sauvegarder(d_supprimer)

        r = client.delete(f"/api/historique/{d_supprimer.id}")
        assert r.status_code == 200, r.text

        # PAS d'appel a POST /recompute — l'invariant doit tenir directement.
        temps_restant_so, temps_restant_profil = self._verify_invariant(
            repo, db, profil.id,
        )
        # Tolerance large (5%) pour absorber les arrondis et clamp [0,100]
        tolerance = max(5.0, abs(temps_restant_profil) * 0.05)
        assert abs(temps_restant_so - temps_restant_profil) < tolerance, (
            f"Invariant Dashboard viole (post-DELETE direct) : "
            f"SO={temps_restant_so:.2f}, profil={temps_restant_profil:.2f}"
        )

    def test_invariant_still_holds_after_explicit_recompute(self, auth_client):
        """Idempotence : appeler POST /recompute apres un DELETE donne le
        meme resultat (pas de drift en double-fix)."""
        client, repo, drepo, db = auth_client
        profil = _make_profil(repo, temps_initial_jours=1000, temps_gagne_jours=150.0)
        so1_id = _create_so(db, profil.id, "SO A", 0, temps_estime=300.0)
        so2_id = _create_so(db, profil.id, "SO B", 1, temps_estime=500.0)

        d1 = _make_decision(profil.id, tg_avant=0.0, tg_apres=80.0,
                            so_id=so1_id, impact_so=20.0)
        d_supprimer = _make_decision(profil.id, tg_avant=80.0, tg_apres=150.0,
                                     so_id=so2_id, impact_so=25.0)
        drepo.sauvegarder(d1)
        drepo.sauvegarder(d_supprimer)

        client.delete(f"/api/historique/{d_supprimer.id}")
        # Snapshot post-DELETE
        before = db.conn.execute(
            "SELECT id, progression FROM sous_objectifs WHERE user_id = ? ORDER BY ordre",
            (profil.id,),
        ).fetchall()
        before_progs = {r["id"]: r["progression"] for r in before}

        # POST /recompute
        r2 = client.post("/api/historique/recompute-so-progressions")
        assert r2.status_code == 200, r2.text

        # Verifier idempotence : meme progression apres recompute
        after = db.conn.execute(
            "SELECT id, progression FROM sous_objectifs WHERE user_id = ? ORDER BY ordre",
            (profil.id,),
        ).fetchall()
        for r in after:
            assert abs(r["progression"] - before_progs[r["id"]]) < 0.1, (
                f"Recompute non-idempotent : SO {r['id']} avant="
                f"{before_progs[r['id']]:.2f} apres={r['progression']:.2f}"
            )
