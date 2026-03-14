"""
Validateur d'instructions pour l'agent Syléa.AI ("Le Double").

Ce module garantit qu'aucune instruction vague ou ambiguë n'est transmise
à l'agent exécutant. Une instruction valide doit être :
  - Suffisamment longue (≥ 4 mots)
  - Contenir un verbe d'action reconnu
  - Ne pas contenir de termes vagues
  - Décrire clairement quoi faire

Principe de sécurité : l'agent n'agit JAMAIS sur une instruction invalide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional


# ── Verbes d'action valides ──────────────────────────────────────────────────
# Doivent figurer dans l'instruction pour qu'elle soit considérée comme actionnable.

VERBES_ACTION = frozenset([
    # Création
    "créer", "crée", "créez", "rédiger", "rédige", "écrire", "écris",
    "préparer", "prépare", "préparez", "produire", "produis",
    "générer", "génère", "structurer", "structure",
    # Recherche
    "rechercher", "recherche", "trouver", "trouve", "identifier", "identifie",
    "analyser", "analyse", "comparer", "compare", "synthétiser", "synthétise",
    "résumer", "résume",
    # Organisation
    "organiser", "organise", "planifier", "planifie", "classer", "classe",
    "prioriser", "priorise", "lister", "liste", "trier", "trie",
    # Communication
    "envoyer", "envoie", "transmettre", "transmet", "partager", "partage",
    "répondre", "réponds", "contacter", "contacte",
    # Traitement
    "corriger", "corrige", "mettre à jour", "actualiser", "actualise",
    "modifier", "modifie", "vérifier", "vérifie", "compléter", "complète",
    # Divers
    "calculer", "calcule", "convertir", "convertis", "extraire", "extrais",
    "compiler", "compile", "formater", "formate",
])

# ── Mots vagues à rejeter ────────────────────────────────────────────────────

MOTS_VAGUES = frozenset([
    "truc", "trucs", "chose", "choses", "machin", "machins", "bidule",
    "bidules", "quelque chose", "quelques choses", "ça", "cela", "eux",
    "elles", "certains", "certaines", "des affaires", "du boulot",
    "des trucs", "un peu", "vaguement", "globalement", "en gros",
])

# ── Nombre minimum de mots ───────────────────────────────────────────────────

NB_MOTS_MINIMUM = 4


@dataclass
class ResultatValidation:
    """
    Résultat du processus de validation d'une instruction.

    Attributs :
        valide     : True si l'instruction est acceptée
        instruction: Instruction normalisée (si valide)
        erreurs    : Liste des problèmes détectés (si invalide)
        suggestions: Suggestions pour améliorer l'instruction
    """

    valide: bool
    instruction: str
    erreurs: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def __str__(self) -> str:
        if self.valide:
            return f"✅ Instruction valide : « {self.instruction} »"
        erreurs_str = "\n  - ".join(self.erreurs)
        suggestions_str = "\n  → ".join(self.suggestions)
        return (
            f"❌ Instruction invalide :\n  - {erreurs_str}\n"
            f"Suggestions :\n  → {suggestions_str}"
        )


class ValidateurInstruction:
    """
    Validateur d'instructions pour l'agent exécutant de Syléa.AI.

    Applique une série de règles métier pour garantir qu'une instruction
    est suffisamment claire et actionnable avant toute exécution.

    Usage :
        validateur = ValidateurInstruction()
        resultat = validateur.valider("Prépare le dossier client Dupont pour demain")
        if resultat.valide:
            agent.executer(resultat.instruction)
    """

    def valider(self, instruction: str) -> ResultatValidation:
        """
        Valide une instruction et retourne un résultat détaillé.

        Args:
            instruction: Texte brut de l'instruction saisie par l'utilisateur

        Returns:
            ResultatValidation avec statut, erreurs et suggestions
        """
        instruction_propre = self._normaliser(instruction)
        erreurs: List[str] = []
        suggestions: List[str] = []

        # ── Règle 1 : longueur minimale ─────────────────────────────────────
        mots = instruction_propre.split()
        if len(mots) < NB_MOTS_MINIMUM:
            erreurs.append(
                f"L'instruction est trop courte ({len(mots)} mot(s)). "
                f"Minimum : {NB_MOTS_MINIMUM} mots."
            )
            suggestions.append(
                "Développez votre demande en précisant quoi faire, "
                "sur quel sujet et pour quelle fin."
            )

        # ── Règle 2 : verbe d'action ─────────────────────────────────────────
        if not self._contient_verbe_action(instruction_propre):
            erreurs.append(
                "Aucun verbe d'action reconnu. "
                "L'instruction doit décrire clairement l'action à effectuer."
            )
            suggestions.append(
                f"Commencez par un verbe comme : créer, préparer, rechercher, "
                f"organiser, rédiger, analyser, etc."
            )

        # ── Règle 3 : termes vagues ──────────────────────────────────────────
        termes_vagues_trouves = self._detecter_termes_vagues(instruction_propre)
        if termes_vagues_trouves:
            termes_str = ", ".join(f"« {t} »" for t in termes_vagues_trouves)
            erreurs.append(
                f"Termes vagues détectés : {termes_str}. "
                "Soyez précis sur l'objet de la demande."
            )
            suggestions.append(
                "Remplacez les termes vagues par le nom exact de l'objet, "
                "du document ou de la personne concernée."
            )

        # ── Règle 4 : instruction vide ou trop courte ────────────────────────
        if len(instruction_propre.strip()) < 10:
            erreurs.append("L'instruction est presque vide.")
            suggestions.append(
                "Exemple d'instruction valide : "
                "« Prépare le dossier client Dupont pour la réunion de demain »"
            )

        valide = len(erreurs) == 0
        return ResultatValidation(
            valide=valide,
            instruction=instruction_propre if valide else instruction,
            erreurs=erreurs,
            suggestions=suggestions,
        )

    # ── Méthodes internes ────────────────────────────────────────────────────

    @staticmethod
    def _normaliser(instruction: str) -> str:
        """
        Normalise l'instruction : supprime les espaces superflus et
        met en minuscules pour la comparaison (conserve la casse originale).
        """
        return re.sub(r"\s+", " ", instruction.strip())

    @staticmethod
    def _contient_verbe_action(instruction: str) -> bool:
        """
        Vérifie si l'instruction contient au moins un verbe d'action reconnu.

        La détection est insensible à la casse.
        """
        instruction_lower = instruction.lower()
        return any(verbe in instruction_lower for verbe in VERBES_ACTION)

    @staticmethod
    def _detecter_termes_vagues(instruction: str) -> List[str]:
        """
        Retourne la liste des termes vagues trouvés dans l'instruction.
        """
        instruction_lower = instruction.lower()
        return [terme for terme in MOTS_VAGUES if terme in instruction_lower]

    def generer_exemple(self, categorie: str = "general") -> str:
        """
        Génère un exemple d'instruction valide selon la catégorie.

        Args:
            categorie: 'email', 'document', 'recherche', 'calendrier',
                       'todo', ou 'general'

        Returns:
            Exemple d'instruction valide sous forme de texte
        """
        exemples = {
            "email": (
                "Rédige un email de relance pour le client Martin "
                "concernant le devis du 15 mars"
            ),
            "document": (
                "Prépare un dossier de présentation pour le projet Alpha "
                "avec les sections : contexte, objectifs et budget"
            ),
            "recherche": (
                "Recherche les 5 principaux concurrents de notre marché "
                "et résume leurs points forts"
            ),
            "calendrier": (
                "Planifie mes tâches de la semaine prochaine "
                "en priorisant le projet client Dupont"
            ),
            "todo": (
                "Crée une liste de tâches pour le lancement "
                "du produit bêta prévu le 1er avril"
            ),
            "general": (
                "Prépare le dossier client Dupont pour la réunion "
                "de présentation de demain matin"
            ),
        }
        return exemples.get(categorie, exemples["general"])
