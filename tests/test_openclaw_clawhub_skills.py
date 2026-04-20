"""
Tests des skills Phase 2 — SkillOpenClaw et SkillClawHub + dispatch executor.

Vérifie :
  - Détection correcte des mots-clés OpenClaw / ClawHub dans _detecter_skill
  - Génération de rapports non vides et contenant les indices attendus
  - Intégration dans AgentExecutant (les skills sont bien enregistrés)
"""
from __future__ import annotations

import pytest

from sylea.agent.executor import AgentExecutant, _detecter_skill
from sylea.agent.skills.clawhub_skill import SkillClawHub
from sylea.agent.skills.openclaw_skill import SkillOpenClaw


# ── _detecter_skill — dispatch vers openclaw ────────────────────────────────


class TestDetectionOpenClaw:
    def test_recherche_web_explicit(self):
        assert _detecter_skill(
            "Fais une recherche web sur les dernières nouvelles en IA"
        ) == "openclaw"

    def test_execute_commande_shell(self):
        assert _detecter_skill(
            "Exécute la commande suivante pour compiler le projet"
        ) == "openclaw"

    def test_sous_agent_spawn(self):
        assert _detecter_skill(
            "Délègue cette tâche à un sous-agent openclaw"
        ) == "openclaw"

    def test_memory_search(self):
        assert _detecter_skill(
            "Cherche dans la mémoire openclaw ce que j'avais noté"
        ) == "openclaw"

    def test_keyword_openclaw_direct(self):
        assert _detecter_skill(
            "Utilise openclaw pour générer cette image"
        ) == "openclaw"


# ── _detecter_skill — dispatch vers clawhub ─────────────────────────────────


class TestDetectionClawHub:
    def test_cherche_un_skill(self):
        assert _detecter_skill(
            "Cherche un skill pour traduire des documents PDF"
        ) == "clawhub"

    def test_installe_un_skill(self):
        assert _detecter_skill(
            "Installe le skill 'markdown-formatter' sur mon système"
        ) == "clawhub"

    def test_marketplace(self):
        assert _detecter_skill(
            "Montre-moi le marketplace ClawHub"
        ) == "clawhub"

    def test_liste_mes_skills(self):
        assert _detecter_skill(
            "Liste mes skills installés localement"
        ) == "clawhub"

    def test_publier_mon_skill(self):
        assert _detecter_skill(
            "Je veux publier mon skill sur ClawHub"
        ) == "clawhub"


# ── Régression : les dispatches existants ne sont pas cassés ────────────────


class TestDetectionNonRegression:
    def test_email_toujours_detecte(self):
        assert _detecter_skill("Rédige un email de relance au client") == "email"

    def test_document_toujours_detecte(self):
        assert _detecter_skill("Prépare un dossier de présentation") == "document"

    def test_calendrier_toujours_detecte(self):
        assert _detecter_skill(
            "Organise mon planning de la semaine prochaine"
        ) == "calendrier"

    def test_fallback_document_si_rien(self):
        # Sans aucun mot-clé reconnu, on retombe sur document (comportement v1)
        assert _detecter_skill("Quelque chose d'indéfini") == "document"


# ── SkillOpenClaw — rapport ─────────────────────────────────────────────────


class TestSkillOpenClaw:
    def setup_method(self):
        self.skill = SkillOpenClaw()

    def test_description_non_vide(self):
        assert self.skill.description
        assert "openclaw" in self.skill.description.lower()

    def test_executer_produit_rapport(self):
        rapport = self.skill.executer(
            "Fais une recherche web sur la psychologie positive"
        )
        assert "OPENCLAW GATEWAY" in rapport
        assert "web_search" in rapport  # tool détecté
        assert "RECOMMANDATION" in rapport

    def test_executer_tool_exec(self):
        rapport = self.skill.executer(
            "Exécute la commande npm install pour installer les deps"
        )
        assert "exec" in rapport.lower()

    def test_executer_fallback_generaliste(self):
        # Pas de keyword tool-spécifique → fallback web_search mais score=0
        rapport = self.skill.executer("peu importe")
        assert "CONFIANCE" in rapport
        assert "0/3" in rapport  # confiance nulle → fallback

    def test_executer_mentionne_securite(self):
        rapport = self.skill.executer("Exécute bash sur le serveur")
        assert "SECURITE" in rapport
        assert "circuit breaker" in rapport.lower()


# ── SkillClawHub — rapport ──────────────────────────────────────────────────


class TestSkillClawHub:
    def setup_method(self):
        self.skill = SkillClawHub()

    def test_description_non_vide(self):
        assert self.skill.description
        assert "clawhub" in self.skill.description.lower()

    def test_executer_action_search(self):
        rapport = self.skill.executer(
            "Cherche un skill pour gérer mes tâches quotidiennes"
        )
        assert "CLAWHUB" in rapport
        assert "search" in rapport.lower()
        assert "/api/marketplace/search" in rapport

    def test_executer_action_install(self):
        rapport = self.skill.executer(
            "Installe le skill markdown-formatter"
        )
        assert "install" in rapport.lower()
        assert "/api/marketplace/install/" in rapport

    def test_executer_action_publish(self):
        rapport = self.skill.executer(
            "Je voudrais publier mon skill sur clawhub"
        )
        assert "publish" in rapport.lower()
        assert "clawhub.ai/clotilde563/sylea" in rapport

    def test_executer_action_list(self):
        rapport = self.skill.executer("Liste mes skills installés")
        assert "list" in rapport.lower()
        assert "/api/marketplace/installed" in rapport

    def test_mentionne_ecosysteme(self):
        rapport = self.skill.executer("marketplace clawhub")
        assert "ECOSYSTEME" in rapport
        assert "52 700" in rapport  # compteur skills


# ── AgentExecutant — intégration ────────────────────────────────────────────


class TestIntegrationExecutor:
    def setup_method(self):
        self.agent = AgentExecutant()

    def test_skills_openclaw_enregistre(self):
        skills = self.agent.lister_skills()
        assert "openclaw" in skills
        assert "clawhub" in skills

    def test_skills_preexistants_intacts(self):
        skills = self.agent.lister_skills()
        for k in ("email", "document", "recherche", "calendrier", "todo"):
            assert k in skills

    def test_executer_opt_in_toujours_requis(self):
        with pytest.raises(PermissionError):
            self.agent.executer(
                "Fais une recherche web sur l'IA",
                validation_confirmee=False,
            )

    def test_executer_openclaw_flow_complet(self):
        action = self.agent.executer(
            "Fais une recherche web pour moi sur la psychologie positive",
            validation_confirmee=True,
        )
        assert action is not None
        assert action.skill_utilise == "openclaw"
        assert action.statut == "terminé"
        assert "OPENCLAW" in action.resultat

    def test_executer_clawhub_flow_complet(self):
        action = self.agent.executer(
            "Cherche un skill ClawHub pour générer des présentations",
            validation_confirmee=True,
        )
        assert action is not None
        assert action.skill_utilise == "clawhub"
        assert action.statut == "terminé"
        assert "CLAWHUB" in action.resultat
