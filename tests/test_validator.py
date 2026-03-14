"""
Tests unitaires du validateur d'instructions de l'agent.
"""

import pytest

from sylea.agent.validator import ValidateurInstruction, NB_MOTS_MINIMUM


@pytest.fixture
def validateur() -> ValidateurInstruction:
    return ValidateurInstruction()


# ── Tests instructions valides ────────────────────────────────────────────────

class TestInstructionsValides:

    def test_instruction_simple_valide(self, validateur):
        """Une instruction claire et complète doit être acceptée."""
        res = validateur.valider(
            "Prépare le dossier client Dupont pour la réunion de demain"
        )
        assert res.valide is True
        assert len(res.erreurs) == 0

    def test_instruction_email(self, validateur):
        """Rédiger un email est une instruction valide."""
        res = validateur.valider(
            "Rédige un email de relance pour le client Martin concernant le devis"
        )
        assert res.valide is True

    def test_instruction_recherche(self, validateur):
        """Rechercher des informations est une instruction valide."""
        res = validateur.valider(
            "Recherche les 5 principaux concurrents de notre marché e-commerce"
        )
        assert res.valide is True

    def test_instruction_todo(self, validateur):
        """Créer une liste de tâches est une instruction valide."""
        res = validateur.valider(
            "Crée une liste de tâches pour le lancement du produit Alpha"
        )
        assert res.valide is True

    def test_instruction_normalisee(self, validateur):
        """Les espaces multiples doivent être normalisés."""
        res = validateur.valider(
            "Prépare   le  dossier  client   Dupont"
        )
        assert res.valide is True
        assert "  " not in res.instruction  # plus de doubles espaces


# ── Tests instructions invalides ──────────────────────────────────────────────

class TestInstructionsInvalides:

    def test_instruction_trop_courte(self, validateur):
        """Moins de 4 mots → invalide."""
        res = validateur.valider("Fais ça")
        assert res.valide is False
        assert any("court" in e.lower() or "mots" in e.lower() for e in res.erreurs)

    def test_instruction_vide(self, validateur):
        """Instruction vide → invalide."""
        res = validateur.valider("")
        assert res.valide is False

    def test_instruction_sans_verbe(self, validateur):
        """Sans verbe d'action → invalide."""
        res = validateur.valider("Le dossier client Dupont important")
        assert res.valide is False
        assert any("verbe" in e.lower() for e in res.erreurs)

    def test_instruction_avec_mot_vague(self, validateur):
        """Contenir 'truc' ou 'chose' → invalide."""
        res = validateur.valider(
            "Prépare le truc pour le client demain matin"
        )
        assert res.valide is False
        assert any("vague" in e.lower() for e in res.erreurs)

    def test_instruction_avec_chose(self, validateur):
        """Le mot 'chose' est interdit."""
        res = validateur.valider(
            "Crée une chose pour le projet des affaires"
        )
        assert res.valide is False

    def test_instructions_invalides_ont_suggestions(self, validateur):
        """Les instructions invalides doivent proposer des suggestions."""
        res = validateur.valider("Fais ça")
        assert res.valide is False
        assert len(res.suggestions) > 0


# ── Tests de robustesse ───────────────────────────────────────────────────────

class TestRobustesse:

    def test_instruction_uniquement_espaces(self, validateur):
        """Une instruction d'espaces seuls → invalide."""
        res = validateur.valider("   ")
        assert res.valide is False

    def test_casse_verbe_insensible(self, validateur):
        """La détection de verbe doit être insensible à la casse."""
        res = validateur.valider("PRÉPARE le dossier client Dupont demain matin")
        assert res.valide is True

    def test_generer_exemple_general(self, validateur):
        """generer_exemple() doit retourner une chaîne non vide."""
        exemple = validateur.generer_exemple("general")
        assert isinstance(exemple, str)
        assert len(exemple) > 10

    def test_generer_exemple_toutes_categories(self, validateur):
        """generer_exemple() doit fonctionner pour toutes les catégories."""
        categories = ["email", "document", "recherche", "calendrier", "todo", "general"]
        for cat in categories:
            exemple = validateur.generer_exemple(cat)
            # L'exemple généré doit lui-même être une instruction valide
            res = validateur.valider(exemple)
            assert res.valide is True, f"L'exemple pour '{cat}' n'est pas valide : {exemple}"

    def test_repr_resultat_valide(self, validateur):
        """str(ResultatValidation) doit contenir ✅ pour une instruction valide."""
        res = validateur.valider(
            "Prépare le rapport mensuel pour le directeur commercial"
        )
        assert "✅" in str(res)

    def test_repr_resultat_invalide(self, validateur):
        """str(ResultatValidation) doit contenir ❌ pour une instruction invalide."""
        res = validateur.valider("Fais ça")
        assert "❌" in str(res)
