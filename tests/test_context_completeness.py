"""Regression test: ensure ALL AI features use the full user context."""
import os
import sys
import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_build_full_user_context_includes_all_fields(tmp_path, monkeypatch):
    """Verify that build_full_user_context_async includes all critical fields."""
    import asyncio
    from tests.conftest import make_shared_db, dispose_shared_db
    from api.context_helper import build_full_user_context_async
    from sylea.core.models.user import ProfilUtilisateur, Objectif

    db = make_shared_db(tmp_path, monkeypatch)

    profil = ProfilUtilisateur(
        nom="Test User",
        age=25,
        profession="dev",
        ville="Paris",
        situation_familiale="celibataire",
        revenu_annuel=45000,
        patrimoine_estime=10000,
        charges_mensuelles=1500,
    )
    profil.genre = "Homme"
    profil.objectif = Objectif(
        description="Devenir freelance\n--- Contexte personnalise ---\nQ: Motivation? R: Independance",
        categorie="carri\u00e8re",
    )
    profil.niveau_sante = 7
    profil.niveau_stress = 5
    profil.niveau_energie = 6
    profil.niveau_bonheur = 8
    profil.heures_travail = 8
    profil.heures_sommeil = 7
    profil.heures_objectif = 2
    profil.competences = ["Python", "React"]
    profil.diplomes = ["Licence informatique"]
    profil.langues = ["Francais", "Anglais"]

    try:
        ctx = asyncio.run(build_full_user_context_async(
            db, user_id=None, profil=profil,
            include_collected_info=False,
            include_decisions=False,
            include_sous_objectifs=False,
        ))

        # ALL these must be present
        assert "Test User" in ctx
        assert "25" in ctx
        assert "Homme" in ctx
        assert "dev" in ctx
        assert "Paris" in ctx
        assert "celibataire" in ctx
        assert "Devenir freelance" in ctx
        assert "carri\u00e8re" in ctx
        assert "Independance" in ctx  # Q&A context
        assert "7/10" in ctx  # sante
        assert "5/10" in ctx  # stress
        assert "8h/jour" in ctx  # heures_travail
        assert "2h/jour" in ctx  # heures_objectif
        assert "Python" in ctx
        assert "Licence informatique" in ctx
        assert "Anglais" in ctx
    finally:
        dispose_shared_db(db)


def test_build_full_user_context_empty_when_no_profil():
    """Verify that build_full_user_context_async returns empty string when no profile."""
    import asyncio
    from api.context_helper import build_full_user_context_async

    ctx = asyncio.run(build_full_user_context_async(db=None, user_id=None, profil=None))
    assert ctx == ""


def test_all_features_import_build_full_user_context():
    """Verify that all AI feature files reference the universal helper."""
    files_that_must_use_it = [
        os.path.join("api", "routers", "dilemme.py"),
        os.path.join("api", "routers", "evenement.py"),
        os.path.join("api", "routers", "profil.py"),
        os.path.join("api", "routers", "objectifs.py"),
        os.path.join("api", "routers", "agent_companion.py"),
        os.path.join("api", "routers", "agent_assistant.py"),
    ]

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    for rel_path in files_that_must_use_it:
        full_path = os.path.join(project_root, rel_path)
        assert os.path.exists(full_path), f"{rel_path} does not exist!"
        with open(full_path, "r", encoding="utf-8") as f:
            source = f.read()
        # Accept either the sync OR async variant (migration-friendly)
        assert ("build_full_user_context" in source
                or "build_full_user_context_async" in source), \
            f"{rel_path} does NOT use build_full_user_context (sync or async)!"
