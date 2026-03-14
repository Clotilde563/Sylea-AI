"""
Tests unitaires de l'analyseur de dilemmes et de l'exécuteur de l'agent.
"""

import pytest

from sylea.core.engine.analyzer import AnalyseurDilemme, _detecter_activite
from sylea.core.models.user import Objectif, ProfilUtilisateur
from sylea.agent.executor import AgentExecutant, _detecter_skill


# ── Fixtures ─────────────────────────────────────────────────────────────────

def _creer_profil(categorie: str, description: str) -> ProfilUtilisateur:
    return ProfilUtilisateur(
        nom="Test",
        age=30,
        profession="Entrepreneur",
        ville="Paris",
        situation_familiale="célibataire",
        revenu_annuel=80_000,
        patrimoine_estime=10_000,
        charges_mensuelles=2_000,
        niveau_sante=7,
        niveau_stress=6,
        niveau_energie=7,
        niveau_bonheur=7,
        competences=["Python", "Vente"],
        objectif=Objectif(description=description, categorie=categorie),
        probabilite_actuelle=5.0,
    )


# ── Tests _detecter_activite ──────────────────────────────────────────────────

class TestDetecterActivite:

    def test_detecter_exercice(self):
        assert _detecter_activite("Courir 10km au parc") == "exercice"

    def test_detecter_travail(self):
        assert _detecter_activite("Travailler sur le dossier client") == "travail_productif"

    def test_detecter_repos(self):
        assert _detecter_activite("Se reposer et méditer") == "repos"

    def test_detecter_formation(self):
        assert _detecter_activite("Lire un livre sur le marketing") == "formation"

    def test_detecter_social(self):
        assert _detecter_activite("Voir des amis pour dîner") == "social"

    def test_sans_correspondance(self):
        """Sans mot-clé reconnu, retourner le skill par défaut."""
        activite = _detecter_activite("Quelque chose d'indéfini")
        assert activite in ("travail_productif",)  # fallback


# ── Tests AnalyseurDilemme ────────────────────────────────────────────────────

class TestAnalyseurDilemme:

    def setup_method(self):
        self.analyseur = AnalyseurDilemme()

    def test_analyse_basique(self):
        """L'analyse doit retourner autant d'options que soumises."""
        profil = _creer_profil("finance", "Devenir milliardaire")
        options = self.analyseur.analyser(
            "Courir ou travailler ce soir ?",
            ["Courir 10km", "Travailler sur mon business plan"],
            profil,
        )
        assert len(options) == 2

    def test_options_triees_par_impact(self):
        """Les options doivent être triées par impact décroissant."""
        profil = _creer_profil("finance", "Devenir milliardaire")
        options = self.analyseur.analyser(
            "Que faire ce soir ?",
            ["Courir", "Travailler sur le business"],
            profil,
        )
        assert options[0].impact_score >= options[1].impact_score

    def test_impact_finance_travail_superieur_repos(self):
        """Pour un objectif finance, travailler > se reposer."""
        profil = _creer_profil("finance", "Atteindre 1 million d'euros")
        options = self.analyseur.analyser(
            "Travailler ou se reposer ?",
            ["Travailler sur mes projets business", "Me reposer et regarder Netflix"],
            profil,
        )
        # L'option travail doit avoir un meilleur impact que repos pour la finance
        travail = next(o for o in options if "travaill" in o.description.lower())
        repos = next(o for o in options if "repos" in o.description.lower())
        assert travail.impact_score > repos.impact_score

    def test_impact_sante_sport_superieur_travail(self):
        """Pour un objectif santé, faire du sport > travailler."""
        profil = _creer_profil("santé", "Courir un marathon en 3h30")
        options = self.analyseur.analyser(
            "Sport ou travail ?",
            ["Faire une séance fractionnée", "Travailler toute la journée"],
            profil,
        )
        sport = next(o for o in options if "fractionné" in o.description.lower())
        travail = next(o for o in options if "travaill" in o.description.lower())
        assert sport.impact_score > travail.impact_score

    def test_explication_non_vide(self):
        """Chaque option doit avoir une explication."""
        profil = _creer_profil("carrière", "Devenir directeur")
        options = self.analyseur.analyser(
            "Networking ou formation ?",
            ["Faire du networking", "Suivre une formation en ligne"],
            profil,
        )
        for opt in options:
            assert opt.explication_impact
            assert len(opt.explication_impact) > 10

    def test_delegabilite_travail(self):
        """Les tâches de travail/administration doivent être déléguables."""
        profil = _creer_profil("finance", "Atteindre 1 million")
        options = self.analyseur.analyser(
            "Préparer un email ou aller courir ?",
            ["Rédiger les emails en attente", "Courir 30 minutes"],
            profil,
        )
        email_opt = next(o for o in options if "email" in o.description.lower())
        course_opt = next(o for o in options if "courir" in o.description.lower())
        assert email_opt.est_delegable is True
        assert course_opt.est_delegable is False

    def test_erreur_moins_de_2_options(self):
        """Moins de 2 options doit lever ValueError."""
        profil = _creer_profil("finance", "Test")
        with pytest.raises(ValueError):
            self.analyseur.analyser("Question ?", ["Une seule option"], profil)

    def test_erreur_plus_de_4_options(self):
        """Plus de 4 options doit lever ValueError."""
        profil = _creer_profil("finance", "Test")
        with pytest.raises(ValueError):
            self.analyseur.analyser(
                "Question ?",
                ["A", "B", "C", "D", "E"],
                profil,
            )

    def test_erreur_sans_objectif(self):
        """Un profil sans objectif doit lever ValueError."""
        profil = ProfilUtilisateur(
            nom="Test", age=30, profession="Test", ville="Test",
            situation_familiale="célibataire",
            revenu_annuel=50_000, patrimoine_estime=0, charges_mensuelles=1000,
        )
        with pytest.raises(ValueError, match="objectif"):
            self.analyseur.analyser("Question ?", ["Option A", "Option B"], profil)

    def test_recommander_meilleure_option(self):
        """recommander() doit retourner l'option avec l'impact le plus élevé."""
        profil = _creer_profil("santé", "Marathon")
        options = self.analyseur.analyser(
            "Sport ou repos ?",
            ["Faire du sport intensif", "Se reposer"],
            profil,
        )
        recommandee = self.analyseur.recommander(options)
        max_impact = max(o.impact_score for o in options)
        assert recommandee.impact_score == max_impact


# ── Tests _detecter_skill (AgentExecutant) ────────────────────────────────────

class TestDetecterSkill:

    def test_detecter_email(self):
        assert _detecter_skill("Rédige un email de relance pour le client") == "email"

    def test_detecter_document(self):
        assert _detecter_skill("Prépare un dossier de présentation") == "document"

    def test_detecter_recherche(self):
        assert _detecter_skill("Recherche les concurrents de notre marché") == "recherche"

    def test_detecter_calendrier(self):
        assert _detecter_skill("Organise mon planning de la semaine prochaine") == "calendrier"

    def test_detecter_todo(self):
        assert _detecter_skill("Crée une liste de tâches pour le projet") == "todo"

    def test_skill_defaut_si_inconnu(self):
        """Sans mots-clés reconnus, retourner le skill par défaut (document)."""
        skill = _detecter_skill("Quelque chose de très vague et indéfini")
        assert skill == "document"


# ── Tests AgentExecutant ──────────────────────────────────────────────────────

class TestAgentExecutant:

    def setup_method(self):
        self.agent = AgentExecutant()

    def test_valider_instruction_valide(self):
        res = self.agent.valider_instruction(
            "Prépare le rapport mensuel des ventes pour le directeur"
        )
        assert res.valide is True

    def test_valider_instruction_invalide(self):
        res = self.agent.valider_instruction("Fais ça")
        assert res.valide is False

    def test_executer_sans_confirmation_leve_erreur(self):
        """L'exécution sans confirmation doit lever PermissionError."""
        with pytest.raises(PermissionError):
            self.agent.executer(
                "Prépare le dossier client Dupont pour demain",
                validation_confirmee=False,
            )

    def test_executer_instruction_invalide_leve_erreur(self):
        """Une instruction invalide doit lever ValueError."""
        with pytest.raises(ValueError):
            self.agent.executer(
                "Fais ça",
                validation_confirmee=True,
            )

    def test_executer_valide_retourne_action(self):
        """Une exécution valide doit retourner un ActionAgent."""
        action = self.agent.executer(
            "Prépare le dossier client Dupont pour la réunion de demain",
            validation_confirmee=True,
        )
        assert action is not None
        assert action.statut == "terminé"
        assert action.skill_utilise in self.agent.lister_skills()
        assert len(action.resultat) > 0

    def test_lister_skills(self):
        """lister_skills() doit retourner 5 skills avec descriptions."""
        skills = self.agent.lister_skills()
        assert len(skills) == 5
        assert "email" in skills
        assert "document" in skills
        assert "recherche" in skills
        assert "calendrier" in skills
        assert "todo" in skills
        for nom, desc in skills.items():
            assert isinstance(desc, str)
            assert len(desc) > 5

    def test_rapport_sans_actions(self):
        """Un rapport sans actions doit indiquer l'absence de tâches."""
        rapport = self.agent.generer_rapport([])
        assert "Aucune" in rapport

    def test_rapport_avec_actions(self):
        """Un rapport avec actions doit lister les tâches."""
        action = self.agent.executer(
            "Recherche les tendances du marché de l'IA en France",
            validation_confirmee=True,
        )
        rapport = self.agent.generer_rapport([action])
        assert action.instruction[:20] in rapport
