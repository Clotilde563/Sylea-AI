"""
Tests unitaires du moteur de probabilité.
"""

import pytest

from sylea.core.engine.probability import (
    MoteurProbabilite,
    _calculer_readiness,
    _calculer_facteur_neuro,
    _classifier_objectif,
    _appliquer_bonus_deadline,
)
from sylea.core.models.user import Objectif, ProfilUtilisateur
from sylea.config.settings import PROB_MIN, PROB_MAX


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _creer_profil(
    categorie: str = "finance",
    description: str = "Devenir milliardaire en 15 ans",
    **kwargs,
) -> ProfilUtilisateur:
    """Crée un profil minimal pour les tests."""
    defaults = dict(
        nom="Test User",
        age=30,
        profession="Entrepreneur",
        ville="Paris",
        situation_familiale="célibataire",
        revenu_annuel=80_000,
        patrimoine_estime=50_000,
        charges_mensuelles=2_000,
        niveau_sante=7,
        niveau_stress=5,
        niveau_energie=7,
        niveau_bonheur=7,
        heures_travail=9.0,
        heures_sommeil=7.5,
        heures_loisirs=2.0,
        heures_transport=1.0,
        competences=["Python", "Finance", "Marketing"],
        objectif=Objectif(description=description, categorie=categorie),
    )
    defaults.update(kwargs)
    return ProfilUtilisateur(**defaults)


# ── Tests _classifier_objectif ────────────────────────────────────────────────

class TestClassifierObjectif:

    def test_milliardaire(self):
        sous_cat, max_prob = _classifier_objectif(
            "Devenir milliardaire en 15 ans", "finance"
        )
        assert sous_cat == "finance_milliardaire"
        assert max_prob < 10  # très difficile

    def test_millionnaire(self):
        sous_cat, max_prob = _classifier_objectif(
            "Gagner mon premier million en 5 ans", "finance"
        )
        assert sous_cat == "finance_millionnaire"
        assert max_prob > 10

    def test_marathon(self):
        sous_cat, max_prob = _classifier_objectif(
            "Courir un marathon en 3h30", "santé"
        )
        assert sous_cat in ("santé_marathon", "santé_marathon_elite")
        assert max_prob > 50

    def test_sante_general(self):
        sous_cat, max_prob = _classifier_objectif(
            "Perdre 10 kilos et être en meilleure forme", "santé"
        )
        assert sous_cat == "santé_general"

    def test_carriere_fondateur(self):
        sous_cat, max_prob = _classifier_objectif(
            "Créer ma startup et lever des fonds", "carrière"
        )
        assert "fondateur" in sous_cat

    def test_developpement(self):
        sous_cat, max_prob = _classifier_objectif(
            "Apprendre l'anglais et le développement web", "développement"
        )
        assert "développement" in sous_cat

    def test_relation(self):
        sous_cat, max_prob = _classifier_objectif(
            "Trouver l'amour et fonder une famille", "relation"
        )
        assert "relation" in sous_cat


# ── Tests _calculer_readiness ─────────────────────────────────────────────────

class TestCalculerReadiness:

    def test_resultat_entre_0_et_1(self):
        profil = _creer_profil()
        score = _calculer_readiness(profil)
        assert 0.0 <= score <= 1.0

    def test_profil_excellent_score_eleve(self):
        """Un profil idéal doit avoir un score de readiness élevé."""
        profil = _creer_profil(
            niveau_sante=10, niveau_stress=1, niveau_energie=10, niveau_bonheur=10,
            revenu_annuel=500_000,
            competences=[f"comp{i}" for i in range(10)],
            heures_travail=8, heures_sommeil=8, heures_transport=0,
        )
        score = _calculer_readiness(profil)
        assert score > 0.6

    def test_profil_mediocre_score_bas(self):
        """Un profil dégradé doit avoir un score plus faible."""
        profil = _creer_profil(
            niveau_sante=2, niveau_stress=9, niveau_energie=2, niveau_bonheur=2,
            revenu_annuel=10_000,
            competences=[],
        )
        score = _calculer_readiness(profil)
        assert score < 0.4


# ── Tests _calculer_facteur_neuro ─────────────────────────────────────────────

class TestCalculerFacteurNeuro:

    def test_resultat_entre_03_et_1(self):
        profil = _creer_profil()
        facteur = _calculer_facteur_neuro(profil)
        assert 0.3 <= facteur <= 1.0

    def test_sommeil_optimal_meilleur_score(self):
        """8h de sommeil doit donner un meilleur score que 5h."""
        profil_8h = _creer_profil(heures_sommeil=8.0, niveau_stress=5, niveau_bonheur=7)
        profil_5h = _creer_profil(heures_sommeil=5.0, niveau_stress=5, niveau_bonheur=7)
        assert _calculer_facteur_neuro(profil_8h) > _calculer_facteur_neuro(profil_5h)

    def test_stress_eleve_reduit_facteur(self):
        """Stress 9/10 doit donner un facteur neuro inférieur à stress 3/10."""
        profil_stresse = _creer_profil(niveau_stress=9, heures_sommeil=7, niveau_bonheur=5)
        profil_calme = _creer_profil(niveau_stress=3, heures_sommeil=7, niveau_bonheur=5)
        assert _calculer_facteur_neuro(profil_stresse) < _calculer_facteur_neuro(profil_calme)


# ── Tests MoteurProbabilite ───────────────────────────────────────────────────

class TestMoteurProbabilite:

    def setup_method(self):
        self.moteur = MoteurProbabilite()

    def test_probabilite_dans_bornes(self):
        """La probabilité doit toujours être dans [PROB_MIN, PROB_MAX]."""
        profil = _creer_profil()
        prob = self.moteur.calculer_probabilite_initiale(profil)
        assert PROB_MIN <= prob <= PROB_MAX

    def test_sans_objectif_leve_erreur(self):
        """Calculer la probabilité sans objectif doit lever ValueError."""
        profil = ProfilUtilisateur(
            nom="Test", age=30, profession="Test", ville="Test",
            situation_familiale="célibataire",
            revenu_annuel=50_000, patrimoine_estime=0, charges_mensuelles=1000,
        )
        with pytest.raises(ValueError, match="objectif"):
            self.moteur.calculer_probabilite_initiale(profil)

    def test_marathon_plus_probable_que_milliardaire(self):
        """Courir un marathon doit être plus probable que devenir milliardaire."""
        profil_marathon = _creer_profil(
            "santé", "Courir un marathon en 3h30"
        )
        profil_milliardaire = _creer_profil(
            "finance", "Devenir milliardaire en 15 ans"
        )
        prob_marathon = self.moteur.calculer_probabilite_initiale(profil_marathon)
        prob_milliard = self.moteur.calculer_probabilite_initiale(profil_milliardaire)
        assert prob_marathon > prob_milliard

    def test_bonne_probabilite_stockee_dans_objectif(self):
        """La probabilité de base doit être stockée dans profil.objectif (± arrondi)."""
        profil = _creer_profil()
        prob = self.moteur.calculer_probabilite_initiale(profil)
        # probabilite_base stocke la valeur brute, prob est arrondie à 2 décimales
        assert round(profil.objectif.probabilite_base, 2) == prob

    def test_recalculer_apres_impact_positif(self):
        """Un impact positif doit augmenter la probabilité."""
        prob_avant = 5.0
        prob_apres = self.moteur.recalculer_apres_choix(prob_avant, 2.5)
        assert prob_apres > prob_avant

    def test_recalculer_apres_impact_negatif(self):
        """Un impact négatif doit diminuer la probabilité."""
        prob_avant = 10.0
        prob_apres = self.moteur.recalculer_apres_choix(prob_avant, -3.0)
        assert prob_apres < prob_avant

    def test_bornes_toujours_respectees(self):
        """La probabilité doit rester dans [PROB_MIN, PROB_MAX] même en cas d'impact extrême."""
        prob_max = self.moteur.recalculer_apres_choix(99.8, 100.0)
        prob_min = self.moteur.recalculer_apres_choix(0.2, -100.0)
        assert prob_max == PROB_MAX
        assert prob_min == PROB_MIN

    def test_message_trajectoire_hausse(self):
        """Un message positif pour une hausse."""
        msg = self.moteur.generer_message_trajectoire(5.0, 8.5)
        assert msg  # non vide

    def test_message_trajectoire_baisse(self):
        """Un message pour une baisse."""
        msg = self.moteur.generer_message_trajectoire(10.0, 7.0)
        assert msg


# ── Tests _appliquer_bonus_deadline ──────────────────────────────────────────

class TestBonusDeadline:

    def test_sans_deadline(self):
        """Sans deadline, le bonus est 0."""
        obj = Objectif(description="Test", categorie="finance")
        assert _appliquer_bonus_deadline(obj) == 0.0

    def test_avec_deadline_futur(self):
        """Avec une deadline dans le futur, le bonus est positif."""
        from datetime import datetime, timedelta
        obj = Objectif(
            description="Test",
            categorie="finance",
            deadline=datetime.now() + timedelta(days=365),
        )
        bonus = _appliquer_bonus_deadline(obj)
        assert bonus > 0

    def test_deadline_passee(self):
        """Une deadline dépassée ne doit pas donner de bonus."""
        from datetime import datetime, timedelta
        obj = Objectif(
            description="Test",
            categorie="finance",
            deadline=datetime.now() - timedelta(days=1),
        )
        assert _appliquer_bonus_deadline(obj) == 0.0
