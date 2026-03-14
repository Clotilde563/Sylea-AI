"""
Tests unitaires des modèles de données (ProfilUtilisateur, Objectif, Decision).
"""

import pytest
from datetime import datetime

from sylea.core.models.user import Objectif, ProfilUtilisateur, CATEGORIES_OBJECTIF
from sylea.core.models.decision import ActionAgent, Decision, OptionDilemme


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def objectif_marathon() -> Objectif:
    """Objectif de santé — courir un marathon."""
    return Objectif(
        description="Courir un marathon en moins de 3h30",
        categorie="santé",
    )


@pytest.fixture
def objectif_finance() -> Objectif:
    """Objectif financier — devenir milliardaire."""
    return Objectif(
        description="Devenir milliardaire en 15 ans",
        categorie="finance",
    )


@pytest.fixture
def profil_alex(objectif_finance) -> ProfilUtilisateur:
    """Profil complet — Alex, entrepreneur ambitieux."""
    return ProfilUtilisateur(
        nom="Alex Martin",
        age=32,
        profession="Entrepreneur tech",
        ville="Paris",
        situation_familiale="célibataire",
        revenu_annuel=85_000.0,
        patrimoine_estime=50_000.0,
        charges_mensuelles=2_500.0,
        heures_travail=10.0,
        heures_sommeil=6.5,
        heures_loisirs=1.5,
        heures_transport=1.0,
        niveau_sante=7,
        niveau_stress=8,
        niveau_energie=7,
        niveau_bonheur=7,
        competences=["Python", "Marketing", "Business Development"],
        diplomes=["Master Finance", "École de Commerce"],
        langues=["Français", "Anglais"],
        objectif=objectif_finance,
    )


@pytest.fixture
def profil_claire(objectif_marathon) -> ProfilUtilisateur:
    """Profil complet — Claire, coach sportive."""
    return ProfilUtilisateur(
        nom="Claire Dupont",
        age=28,
        profession="Coach sportive",
        ville="Lyon",
        situation_familiale="en couple",
        revenu_annuel=42_000.0,
        patrimoine_estime=15_000.0,
        charges_mensuelles=1_200.0,
        niveau_sante=9,
        niveau_stress=3,
        niveau_energie=9,
        niveau_bonheur=8,
        competences=["Coaching", "Nutrition", "Athlétisme"],
        langues=["Français"],
        objectif=objectif_marathon,
    )


# ── Tests Objectif ────────────────────────────────────────────────────────────

class TestObjectif:

    def test_creation_valide(self, objectif_marathon):
        """Un objectif valide doit être créé sans erreur."""
        assert objectif_marathon.description == "Courir un marathon en moins de 3h30"
        assert objectif_marathon.categorie == "santé"
        assert objectif_marathon.deadline is None
        assert objectif_marathon.probabilite_base == 0.0

    def test_categorie_invalide(self):
        """Une catégorie invalide doit lever ValueError."""
        with pytest.raises(ValueError, match="Catégorie invalide"):
            Objectif(description="Test", categorie="bonheur")

    def test_toutes_categories_valides(self):
        """Toutes les catégories déclarées doivent être acceptées."""
        for cat in CATEGORIES_OBJECTIF:
            obj = Objectif(description="Objectif test", categorie=cat)
            assert obj.categorie == cat

    def test_serialisation_roundtrip(self, objectif_marathon):
        """to_dict() puis from_dict() doit donner un objet identique."""
        d = objectif_marathon.to_dict()
        obj2 = Objectif.from_dict(d)
        assert obj2.description == objectif_marathon.description
        assert obj2.categorie == objectif_marathon.categorie

    def test_deadline_serialisation(self):
        """La deadline doit être correctement sérialisée/désérialisée."""
        deadline = datetime(2028, 12, 31)
        obj = Objectif(description="Test", categorie="finance", deadline=deadline)
        d = obj.to_dict()
        obj2 = Objectif.from_dict(d)
        assert obj2.deadline == deadline


# ── Tests ProfilUtilisateur ───────────────────────────────────────────────────

class TestProfilUtilisateur:

    def test_creation_valide(self, profil_alex):
        """Un profil valide doit être créé sans erreur."""
        assert profil_alex.nom == "Alex Martin"
        assert profil_alex.age == 32
        assert profil_alex.niveau_sante == 7

    def test_id_auto_genere(self, profil_alex):
        """L'ID doit être généré automatiquement."""
        assert profil_alex.id is not None
        assert len(profil_alex.id) == 36  # UUID format

    def test_niveau_hors_limites(self):
        """Un niveau hors de [1, 10] doit lever ValueError."""
        with pytest.raises(ValueError):
            ProfilUtilisateur(
                nom="Test", age=30, profession="Test", ville="Test",
                situation_familiale="célibataire",
                revenu_annuel=50_000, patrimoine_estime=0, charges_mensuelles=1000,
                niveau_sante=11,  # invalide
            )

    def test_age_negatif(self):
        """Un âge négatif doit lever ValueError."""
        with pytest.raises(ValueError):
            ProfilUtilisateur(
                nom="Test", age=-1, profession="Test", ville="Test",
                situation_familiale="célibataire",
                revenu_annuel=50_000, patrimoine_estime=0, charges_mensuelles=1000,
            )

    def test_serialisation_roundtrip(self, profil_alex):
        """to_dict() → from_dict() doit reconstruire le profil identiquement."""
        d = profil_alex.to_dict()
        profil2 = ProfilUtilisateur.from_dict(d)

        assert profil2.nom == profil_alex.nom
        assert profil2.age == profil_alex.age
        assert profil2.niveau_stress == profil_alex.niveau_stress
        assert profil2.competences == profil_alex.competences
        assert profil2.objectif.description == profil_alex.objectif.description

    def test_marqueur_modification(self, profil_alex):
        """marquer_modification() doit mettre à jour mis_a_jour_le."""
        avant = profil_alex.mis_a_jour_le
        profil_alex.marquer_modification()
        assert profil_alex.mis_a_jour_le >= avant

    def test_profil_sans_objectif(self):
        """Un profil peut être créé sans objectif."""
        profil = ProfilUtilisateur(
            nom="Test", age=25, profession="Dev", ville="Paris",
            situation_familiale="célibataire",
            revenu_annuel=40_000, patrimoine_estime=0, charges_mensuelles=800,
        )
        assert profil.objectif is None


# ── Tests Decision ────────────────────────────────────────────────────────────

class TestDecision:

    @pytest.fixture
    def options(self) -> list[OptionDilemme]:
        return [
            OptionDilemme(description="Courir", impact_score=3.5, est_delegable=False),
            OptionDilemme(description="Travailler", impact_score=2.5, est_delegable=True),
        ]

    def test_creation_decision(self, profil_alex, options):
        """Une décision doit être créée avec les bonnes données."""
        decision = Decision(
            user_id=profil_alex.id,
            question="Courir ou travailler ?",
            options=options,
            probabilite_avant=3.2,
        )
        assert decision.user_id == profil_alex.id
        assert len(decision.options) == 2
        assert decision.option_choisie_id is None

    def test_get_option_choisie(self, profil_alex, options):
        """get_option_choisie() doit retourner la bonne option."""
        decision = Decision(
            user_id=profil_alex.id,
            question="Test",
            options=options,
            probabilite_avant=5.0,
            option_choisie_id=options[0].id,
        )
        choisie = decision.get_option_choisie()
        assert choisie is not None
        assert choisie.description == "Courir"

    def test_get_option_choisie_none(self, profil_alex, options):
        """get_option_choisie() doit retourner None si pas de choix."""
        decision = Decision(
            user_id=profil_alex.id,
            question="Test",
            options=options,
            probabilite_avant=5.0,
        )
        assert decision.get_option_choisie() is None

    def test_serialisation_roundtrip(self, profil_alex, options):
        """to_dict() → from_dict() doit reconstruire la décision."""
        decision = Decision(
            user_id=profil_alex.id,
            question="Courir ou travailler ?",
            options=options,
            probabilite_avant=3.2,
            option_choisie_id=options[1].id,
            probabilite_apres=5.7,
        )
        d = decision.to_dict()
        decision2 = Decision.from_dict(d)

        assert decision2.question == decision.question
        assert len(decision2.options) == 2
        assert decision2.probabilite_avant == 3.2
        assert decision2.probabilite_apres == 5.7
        assert decision2.option_choisie_id == options[1].id
