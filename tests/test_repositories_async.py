"""
Tests des Repositories async (migration PG, 2026-05-15).

Verifient que ProfilRepositoryAsync et DecisionRepositoryAsync :
- Stockent et lisent correctement
- Respectent l'isolation par auth_user_id
- Renvoient les memes resultats que les versions sync
- Marchent sur SQLite (via shared-DB) — PG-compatible par construction
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from sylea.core.models.user import ProfilUtilisateur
from sylea.core.models.decision import Decision
from sylea.core.storage.repositories_async import (
    ProfilRepositoryAsync, DecisionRepositoryAsync,
)
from tests.conftest import make_shared_db, dispose_shared_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """DB SQLite partagee (sync + async) via fichier temp."""
    manager = make_shared_db(tmp_path, monkeypatch)
    yield manager
    dispose_shared_db(manager)


def _make_profil(user_id: str = None) -> ProfilUtilisateur:
    """Cree un profil de test (auth_user_id passe au repo, pas au constructeur)."""
    pid = user_id or str(uuid.uuid4())
    return ProfilUtilisateur(
        id=pid,
        nom="Test User",
        age=30,
        profession="Developpeur",
        ville="Lyon",
        situation_familiale="celibataire",
        revenu_annuel=50000.0,
        patrimoine_estime=10000.0,
        charges_mensuelles=1500.0,
    )


class TestProfilRepositoryAsync:
    def test_existe_returns_false_when_empty(self, db):
        repo = ProfilRepositoryAsync()
        assert asyncio.run(repo.existe_async("nope")) is False

    def test_sauvegarder_then_existe(self, db):
        repo = ProfilRepositoryAsync()
        profil = _make_profil()
        asyncio.run(repo.sauvegarder_async(profil, auth_user_id="auth-A"))
        assert asyncio.run(repo.existe_async("auth-A")) is True
        assert asyncio.run(repo.existe_async("auth-OTHER")) is False

    def test_charger_returns_profil(self, db):
        repo = ProfilRepositoryAsync()
        profil = _make_profil()
        asyncio.run(repo.sauvegarder_async(profil, auth_user_id="auth-B"))
        loaded = asyncio.run(repo.charger_async("auth-B"))
        assert loaded is not None
        assert loaded.nom == "Test User"
        assert loaded.ville == "Lyon"

    def test_charger_returns_none_for_unknown_user(self, db):
        repo = ProfilRepositoryAsync()
        assert asyncio.run(repo.charger_async("inexistent")) is None

    def test_isolation_between_users(self, db):
        """Verifie qu'un user A ne voit jamais le profil d'un user B."""
        repo = ProfilRepositoryAsync()
        profil_a = _make_profil()
        profil_b = _make_profil()
        profil_b.nom = "Bob"
        asyncio.run(repo.sauvegarder_async(profil_a, auth_user_id="user-A"))
        asyncio.run(repo.sauvegarder_async(profil_b, auth_user_id="user-B"))

        loaded_a = asyncio.run(repo.charger_async("user-A"))
        loaded_b = asyncio.run(repo.charger_async("user-B"))
        assert loaded_a.nom == "Test User"
        assert loaded_b.nom == "Bob"

    def test_supprimer_removes_profil(self, db):
        repo = ProfilRepositoryAsync()
        profil = _make_profil()
        asyncio.run(repo.sauvegarder_async(profil, auth_user_id="auth-C"))
        asyncio.run(repo.supprimer_async(profil.id, auth_user_id="auth-C"))
        assert asyncio.run(repo.existe_async("auth-C")) is False


class TestDecisionRepositoryAsync:
    def _setup_user(self, db, auth_user_id: str = "auth-dec") -> ProfilUtilisateur:
        profil_repo = ProfilRepositoryAsync()
        profil = _make_profil()
        asyncio.run(profil_repo.sauvegarder_async(profil, auth_user_id=auth_user_id))
        return profil

    def test_compter_returns_zero_when_empty(self, db):
        repo = DecisionRepositoryAsync()
        assert asyncio.run(repo.compter_async("u")) == 0

    def test_sauvegarder_then_compter(self, db):
        profil = self._setup_user(db)
        repo = DecisionRepositoryAsync()

        from sylea.core.models.decision import OptionDilemme as Option
        decision = Decision(
            id=str(uuid.uuid4()),
            user_id=profil.id,
            question="Acheter une maison ?",
            options=[Option(id="A", description="Oui"), Option(id="B", description="Non")],
            probabilite_avant=50.0,
        )
        asyncio.run(repo.sauvegarder_async(decision))
        assert asyncio.run(repo.compter_async(profil.id)) == 1

    def test_lister_pour_utilisateur(self, db):
        profil = self._setup_user(db)
        repo = DecisionRepositoryAsync()
        from sylea.core.models.decision import OptionDilemme as Option
        for i in range(3):
            d = Decision(
                id=str(uuid.uuid4()),
                user_id=profil.id,
                question=f"Decision {i}",
                options=[Option(id="A", description="Oui")],
                probabilite_avant=50.0,
            )
            asyncio.run(repo.sauvegarder_async(d))
        decisions = asyncio.run(repo.lister_pour_utilisateur_async(profil.id, limite=5))
        assert len(decisions) == 3

    def test_supprimer_par_id(self, db):
        profil = self._setup_user(db)
        repo = DecisionRepositoryAsync()
        from sylea.core.models.decision import OptionDilemme as Option
        d = Decision(
            id=str(uuid.uuid4()),
            user_id=profil.id,
            question="Test",
            options=[Option(id="A", description="Oui")],
            probabilite_avant=50.0,
        )
        asyncio.run(repo.sauvegarder_async(d))
        assert asyncio.run(repo.supprimer_par_id_async(d.id, profil.id)) is True
        assert asyncio.run(repo.compter_async(profil.id)) == 0
