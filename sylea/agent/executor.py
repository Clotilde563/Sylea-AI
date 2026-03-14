"""
Agent exécutant de Syléa.AI ("Le Double").

Ce module orchestre l'exécution des tâches déléguées par l'utilisateur.
Il :
  1. Reçoit une instruction validée
  2. Identifie le skill approprié
  3. Exécute la tâche (simulation)
  4. Retourne un rapport détaillé

Règles fondamentales :
  - JAMAIS d'exécution sans validation préalable (ValidateurInstruction)
  - L'agent est un exécutant, PAS un décideur
  - Rapport systématique après chaque exécution
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from sylea.agent.validator import ValidateurInstruction, ResultatValidation
from sylea.agent.skills.email_skill import SkillEmail
from sylea.agent.skills.document_skill import SkillDocument
from sylea.agent.skills.research_skill import SkillRecherche
from sylea.agent.skills.calendar_skill import SkillCalendrier
from sylea.agent.skills.todo_skill import SkillTodo
from sylea.core.models.decision import ActionAgent


# ── Mots-clés de détection du skill approprié ───────────────────────────────

_MOTS_EMAIL = frozenset([
    "email", "mail", "courriel", "message", "envoyer", "répondre",
    "relance", "contact", "destinataire",
])

_MOTS_DOCUMENT = frozenset([
    "dossier", "document", "rapport", "présentation", "powerpoint", "word",
    "fiche", "synthèse", "note de", "compte rendu", "brief", "cahier des charges",
])

_MOTS_RECHERCHE = frozenset([
    "recherche", "cherche", "trouve", "analyse", "identifie", "liste",
    "compare", "résume", "synthétise", "information", "données",
])

_MOTS_CALENDRIER = frozenset([
    "planning", "calendrier", "agenda", "planifie", "créneau", "rendez-vous",
    "réunion", "semaine", "programme", "emploi du temps",
])

_MOTS_TODO = frozenset([
    "tâche", "tâches", "todo", "to-do", "to do", "liste de tâches",
    "priorise", "étapes", "actions à", "checklist",
])


def _detecter_skill(instruction: str) -> str:
    """
    Identifie le skill le plus adapté à une instruction.

    Utilise un système de score par mots-clés. En cas d'égalité,
    le skill Document est choisi par défaut.

    Args:
        instruction: Texte de l'instruction normalisée

    Returns:
        Nom du skill : 'email' | 'document' | 'recherche' | 'calendrier' | 'todo'
    """
    inst = instruction.lower()
    scores = {
        "email": sum(1 for m in _MOTS_EMAIL if m in inst),
        "document": sum(1 for m in _MOTS_DOCUMENT if m in inst),
        "recherche": sum(1 for m in _MOTS_RECHERCHE if m in inst),
        "calendrier": sum(1 for m in _MOTS_CALENDRIER if m in inst),
        "todo": sum(1 for m in _MOTS_TODO if m in inst),
    }
    # Retourner le skill avec le score le plus haut
    meilleur = max(scores, key=lambda k: scores[k])
    # Si aucun mot-clé ne correspond, utiliser Document par défaut
    if scores[meilleur] == 0:
        return "document"
    return meilleur


class AgentExecutant:
    """
    Orchestrateur des tâches déléguées à Syléa.AI.

    Expose une interface simple : recevoir une instruction → retourner un rapport.
    Intègre la validation automatique et la sélection du skill.

    Usage :
        agent = AgentExecutant()
        resultat = agent.executer("Prépare le dossier client Dupont pour demain")
        if resultat:
            print(resultat.resultat)
    """

    def __init__(self) -> None:
        self._validateur = ValidateurInstruction()
        self._skills = {
            "email": SkillEmail(),
            "document": SkillDocument(),
            "recherche": SkillRecherche(),
            "calendrier": SkillCalendrier(),
            "todo": SkillTodo(),
        }

    def valider_instruction(self, instruction: str) -> ResultatValidation:
        """
        Valide une instruction sans l'exécuter.

        À appeler avant executer() pour afficher les erreurs à l'utilisateur
        et lui permettre de corriger avant confirmation.

        Args:
            instruction: Texte brut de l'instruction

        Returns:
            ResultatValidation avec statut et suggestions
        """
        return self._validateur.valider(instruction)

    def executer(
        self,
        instruction: str,
        validation_confirmee: bool = False,
    ) -> Optional[ActionAgent]:
        """
        Valide et exécute une instruction déléguée.

        L'exécution ne se produit QUE si l'instruction est valide ET si
        `validation_confirmee` est True (opt-in explicite).

        Args:
            instruction          : Texte de l'instruction
            validation_confirmee : Doit être True pour autoriser l'exécution

        Returns:
            ActionAgent avec le rapport d'exécution, ou None si refusé.

        Raises:
            PermissionError: si validation_confirmee est False
            ValueError     : si l'instruction est invalide
        """
        # ── 1. Validation ────────────────────────────────────────────────────
        resultat_validation = self._validateur.valider(instruction)
        if not resultat_validation.valide:
            raise ValueError(str(resultat_validation))

        # ── 2. Opt-in obligatoire ────────────────────────────────────────────
        if not validation_confirmee:
            raise PermissionError(
                "L'exécution requiert une confirmation explicite de l'utilisateur. "
                "Appelez executer() avec validation_confirmee=True."
            )

        # ── 3. Sélection du skill ────────────────────────────────────────────
        nom_skill = _detecter_skill(resultat_validation.instruction)
        skill = self._skills[nom_skill]

        # ── 4. Exécution ─────────────────────────────────────────────────────
        debut = time.monotonic()
        try:
            resultat_texte = skill.executer(resultat_validation.instruction)
            statut = "terminé"
        except Exception as e:
            resultat_texte = f"Erreur lors de l'exécution : {e}"
            statut = "échec"

        temps_passe = round(time.monotonic() - debut, 3)

        # ── 5. Construction du rapport ───────────────────────────────────────
        action = ActionAgent(
            instruction=resultat_validation.instruction,
            skill_utilise=nom_skill,
            statut=statut,
            resultat=resultat_texte,
            temps_passe=temps_passe,
            execute_le=datetime.now(),
        )
        return action

    def lister_skills(self) -> dict[str, str]:
        """
        Retourne la liste des skills disponibles avec leur description.

        Returns:
            Dictionnaire {nom_skill: description}
        """
        return {
            nom: skill.description
            for nom, skill in self._skills.items()
        }

    def generer_rapport(self, actions: list[ActionAgent]) -> str:
        """
        Génère un rapport textuel de toutes les actions effectuées.

        Args:
            actions: Liste d'ActionAgent à synthétiser

        Returns:
            Rapport formaté en texte
        """
        if not actions:
            return "Aucune action n'a été effectuée par l'agent."

        lignes = [
            f"=== Rapport d'activité de l'agent ({len(actions)} action(s)) ===\n"
        ]
        for i, action in enumerate(actions, 1):
            statut_emoji = "✅" if action.statut == "terminé" else "❌"
            lignes.append(
                f"{i}. {statut_emoji} [{action.execute_le.strftime('%d/%m %H:%M')}] "
                f"[{action.skill_utilise.upper()}] {action.instruction}"
            )
            lignes.append(f"   → {action.resultat[:150]}...")
            lignes.append("")

        temps_total = sum(a.temps_passe for a in actions)
        lignes.append(f"Temps total d'exécution : {temps_total:.2f}s")
        return "\n".join(lignes)
