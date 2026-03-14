"""
Contrôleur principal de l'interface CLI de Syléa.AI.

Ce module orchestre la navigation entre les différentes vues :
  - Accueil / tableau de bord
  - Soumission d'un dilemme
  - Historique des décisions
  - Mise à jour du profil
  - Rapport de l'agent

Point d'entrée de l'application : ApplicationSylea.lancer()
"""

from __future__ import annotations

import sys
from typing import Optional

from rich.prompt import IntPrompt, Prompt

from sylea.core.models.user import ProfilUtilisateur
from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
from sylea.interfaces.cli.dashboard import (
    afficher_dashboard,
    afficher_historique,
    afficher_message_erreur,
    afficher_message_info,
    afficher_rapport_agent,
    console,
)
from sylea.interfaces.cli.profile import (
    creer_profil_interactif,
    mettre_a_jour_profil_interactif,
)
from sylea.interfaces.cli.dilemma import soumettre_dilemme


class ApplicationSylea:
    """
    Contrôleur principal de l'application Syléa.AI.

    Gère le cycle de vie de l'application : initialisation, navigation
    entre les vues et persistance des données.

    Usage :
        app = ApplicationSylea()
        app.lancer()
    """

    def __init__(self) -> None:
        self._db = DatabaseManager()
        self._profil_repo = ProfilRepository(self._db)
        self._decision_repo = DecisionRepository(self._db)
        self._profil: Optional[ProfilUtilisateur] = None

    # ── Lancement ────────────────────────────────────────────────────────────

    def lancer(self) -> None:
        """
        Point d'entrée principal de l'application.

        Initialise la connexion DB, charge ou crée le profil, puis
        lance la boucle principale d'interaction.
        """
        self._db.connect()
        try:
            self._initialiser_profil()
            self._boucle_principale()
        except KeyboardInterrupt:
            console.print("\n\n  [dim]Interruption détectée. À bientôt ![/dim]\n")
        finally:
            self._db.disconnect()

    # ── Initialisation ───────────────────────────────────────────────────────

    def _initialiser_profil(self) -> None:
        """
        Charge le profil existant ou lance la création d'un nouveau profil.
        """
        if self._profil_repo.existe():
            self._profil = self._profil_repo.charger()
            if self._profil is None:
                self._profil = self._creer_nouveau_profil()
        else:
            afficher_message_info(
                "Aucun profil trouvé. Créons votre profil Syléa."
            )
            self._profil = self._creer_nouveau_profil()

    def _creer_nouveau_profil(self) -> ProfilUtilisateur:
        """Lance la création d'un profil et le sauvegarde."""
        profil = creer_profil_interactif()
        self._profil_repo.sauvegarder(profil)
        return profil

    # ── Boucle principale ────────────────────────────────────────────────────

    def _boucle_principale(self) -> None:
        """
        Boucle d'interaction principale.

        Affiche le tableau de bord, attend le choix de l'utilisateur
        et exécute l'action correspondante.
        """
        while True:
            afficher_dashboard(self._profil)

            try:
                choix = IntPrompt.ask("\n  Votre choix", default=0)
            except (ValueError, KeyboardInterrupt):
                choix = 0

            if choix == 1:
                self._action_dilemme()
            elif choix == 2:
                self._action_historique()
            elif choix == 3:
                self._action_maj_profil()
            elif choix == 4:
                self._action_rapport_agent()
            elif choix == 0:
                self._quitter()
                break
            else:
                afficher_message_erreur("Choix invalide. Entrez un numéro entre 0 et 4.")
                console.input("\n  [dim]Appuyez sur Entrée…[/dim]")

    # ── Actions ──────────────────────────────────────────────────────────────

    def _action_dilemme(self) -> None:
        """Lance le flow de soumission d'un dilemme."""
        decision = soumettre_dilemme(self._profil)

        if decision is not None:
            # Sauvegarder la décision
            self._decision_repo.sauvegarder(decision)
            # Sauvegarder la probabilité mise à jour dans le profil
            self._profil_repo.sauvegarder(self._profil)

    def _action_historique(self) -> None:
        """Affiche l'historique des décisions."""
        console.clear()
        decisions = self._decision_repo.lister_pour_utilisateur(
            self._profil.id, limite=20
        )
        afficher_historique(decisions)
        console.input("\n  [dim]Appuyez sur Entrée pour revenir…[/dim]")

    def _action_maj_profil(self) -> None:
        """Lance la mise à jour du profil."""
        self._profil = mettre_a_jour_profil_interactif(self._profil)
        self._profil_repo.sauvegarder(self._profil)

    def _action_rapport_agent(self) -> None:
        """Affiche le rapport des actions de l'agent."""
        console.clear()
        decisions = self._decision_repo.lister_pour_utilisateur(
            self._profil.id, limite=50
        )
        actions = [d.action_agent for d in decisions if d.action_agent is not None]
        afficher_rapport_agent(actions)
        console.input("\n  [dim]Appuyez sur Entrée pour revenir…[/dim]")

    def _quitter(self) -> None:
        """Affiche un message de sortie et ferme proprement l'application."""
        console.clear()
        console.print(
            "\n  [bold cyan]À bientôt sur SYLÉA.AI ![/bold cyan]\n"
            "  Continuez à avancer vers votre objectif. 💡\n"
        )
