"""
Application CLI principale de Syléa.AI.

Orchestre le cycle de vie complet :
  - Initialisation de la base de données
  - Chargement / création du profil
  - Calcul de la probabilité initiale
  - Boucle principale (menu → actions → sauvegarde)
"""

import sys
from typing import Optional

from rich.panel import Panel
from rich.text import Text
from rich import box

from sylea.config.settings import APP_NAME, APP_VERSION
from sylea.core.engine.probability import MoteurProbabilite
from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
from sylea.core.models.user import ProfilUtilisateur
from sylea.agent.claude_agent import AgentSylea

from sylea.interfaces.cli.components.ui import (
    console,
    afficher_splash,
    afficher_jauge_probabilite,
    afficher_titre_section,
    afficher_succes,
    afficher_erreur,
    afficher_info,
    afficher_avertissement,
    afficher_menu_principal,
    demander,
    choisir_dans_liste,
    spinner,
    C_PRIMAIRE,
    C_MUTED,
    C_ACCENT,
)
from sylea.interfaces.cli.screens.profil_wizard import lancer_wizard
from sylea.interfaces.cli.screens.decision_screen import lancer_analyse
from sylea.interfaces.cli.screens.historique_screen import afficher_historique


class AppSylea:
    """Contrôleur principal de l'application Syléa.AI."""

    def __init__(self) -> None:
        self._db     = DatabaseManager()
        self._moteur = MoteurProbabilite()
        self._agent: Optional[AgentSylea] = None
        self._profil: Optional[ProfilUtilisateur] = None
        self._profil_repo: Optional[ProfilRepository] = None
        self._decision_repo: Optional[DecisionRepository] = None

    # ── Démarrage ─────────────────────────────────────────────────────────────

    def demarrer(self) -> None:
        """Point d'entrée principal — initialise et lance la boucle."""
        afficher_splash()
        self._db.connect()
        self._profil_repo = ProfilRepository(self._db)
        self._decision_repo = DecisionRepository(self._db)

        try:
            self._initialiser_agent()
            self._charger_ou_creer_profil()
            self._boucle_principale()
        except KeyboardInterrupt:
            self._au_revoir()
        finally:
            self._db.disconnect()

    # ── Initialisation ────────────────────────────────────────────────────────

    def _initialiser_agent(self) -> None:
        """Initialise l'agent Claude (vérifie la clé API)."""
        try:
            self._agent = AgentSylea()
        except ValueError as e:
            afficher_erreur(str(e))
            console.print(
                f"\n[{C_MUTED}]Créez un fichier .env à la racine du projet avec :[/]"
                f"\n[{C_ACCENT}]  ANTHROPIC_API_KEY=sk-ant-votre-cle[/]\n"
            )
            sys.exit(1)

    def _charger_ou_creer_profil(self) -> None:
        """Charge le profil existant ou lance le wizard de création."""
        if self._profil_repo.existe():
            self._profil = self._profil_repo.charger()
            afficher_succes(f"Bon retour, {self._profil.nom} !")

            # Si pas de probabilité, on la calcule
            if self._profil.probabilite_actuelle == 0.0 and self._profil.objectif:
                self._calculer_probabilite_initiale()
        else:
            afficher_info("Première utilisation de Syléa — configurons votre profil.")
            self._profil = lancer_wizard()
            self._profil_repo.sauvegarder(self._profil)
            self._calculer_probabilite_initiale()

    def _calculer_probabilite_initiale(self) -> None:
        """Calcule et affiche la probabilité initiale via moteur + agent."""
        if not self._profil or not self._profil.objectif:
            return

        with spinner("Calcul de votre probabilité de réussite…"):
            # 1. Calcul déterministe
            prob_locale = self._moteur.calculer_probabilite_initiale(self._profil)

        with spinner("Analyse qualitative par Syléa…"):
            try:
                # 2. Enrichissement par Claude
                analyse = self._agent.analyser_probabilite(self._profil, prob_locale)
                self._profil.probabilite_actuelle = analyse.probabilite

                # Afficher l'analyse
                self._afficher_analyse_initiale(analyse)
            except Exception as e:
                afficher_avertissement(f"Analyse IA indisponible ({e}). Calcul local utilisé.")
                self._profil.probabilite_actuelle = prob_locale

        self._profil.marquer_modification()
        self._profil_repo.sauvegarder(self._profil)

    # ── Boucle principale ─────────────────────────────────────────────────────

    def _boucle_principale(self) -> None:
        """Boucle menu → action → sauvegarde."""
        while True:
            console.print()
            afficher_jauge_probabilite(
                self._profil.probabilite_actuelle,
                self._profil.objectif.description if self._profil.objectif else "Aucun objectif",
            )

            action = afficher_menu_principal(
                nom=self._profil.nom,
                prob=self._profil.probabilite_actuelle,
                objectif=(
                    self._profil.objectif.description
                    if self._profil.objectif else "Aucun objectif"
                ),
            )

            if action == "analyser":
                self._action_analyser()
            elif action == "profil":
                self._action_modifier_profil()
            elif action == "objectif":
                self._action_changer_objectif()
            elif action == "historique":
                self._action_historique()
            elif action == "quitter":
                self._au_revoir()
                break

    # ── Actions ───────────────────────────────────────────────────────────────

    def _action_analyser(self) -> None:
        """Lance l'analyse d'un dilemme et sauvegarde."""
        profil_maj = lancer_analyse(self._profil, self._agent)

        # Récupérer la décision créée (stockée temporairement)
        decision = getattr(profil_maj, "_derniere_decision", None)
        if hasattr(profil_maj, "_derniere_decision"):
            delattr(profil_maj, "_derniere_decision")

        self._profil = profil_maj
        self._profil_repo.sauvegarder(self._profil)

        if decision:
            self._decision_repo.sauvegarder(decision)
            afficher_succes("Décision enregistrée dans l'historique.")

    def _action_modifier_profil(self) -> None:
        """Lance le wizard de modification puis recalcule la probabilité."""
        self._profil = lancer_wizard(profil_existant=self._profil)
        afficher_info("Recalcul de votre probabilité suite aux modifications…")
        self._calculer_probabilite_initiale()

    def _action_changer_objectif(self) -> None:
        """Permet de changer l'objectif principal et recalcule."""
        from sylea.core.models.user import Objectif, CATEGORIES_OBJECTIF
        from sylea.interfaces.cli.components.ui import demander_entier
        from datetime import datetime

        afficher_titre_section("Changer d'objectif")
        afficher_avertissement(
            "Changer d'objectif réinitialisera votre probabilité de réussite."
        )
        confirmer = demander("Confirmer ? (oui/non)", defaut="non")
        if confirmer.lower() not in ("oui", "o", "yes", "y"):
            afficher_info("Changement d'objectif annulé.")
            return

        desc = demander("Nouvel objectif")
        if not desc:
            afficher_erreur("L'objectif ne peut pas être vide.")
            return

        console.print(f"\n[{C_MUTED}]Catégorie :[/]")
        cat = choisir_dans_liste("Choisissez", CATEGORIES_OBJECTIF)

        deadline_raw = demander("Date limite (JJ/MM/AAAA, facultatif)", defaut="")
        deadline = None
        if deadline_raw:
            try:
                deadline = datetime.strptime(deadline_raw, "%d/%m/%Y")
            except ValueError:
                afficher_avertissement("Format de date invalide, ignoré.")

        self._profil.objectif = Objectif(
            description=desc,
            categorie=cat,
            deadline=deadline,
        )
        self._profil.probabilite_actuelle = 0.0
        self._calculer_probabilite_initiale()

    def _action_historique(self) -> None:
        """Affiche l'historique des décisions."""
        decisions = self._decision_repo.lister_pour_utilisateur(self._profil.id)
        afficher_historique(decisions)
        demander("Appuyez sur Entrée pour revenir au menu")

    # ── Affichage analyse initiale ─────────────────────────────────────────────

    def _afficher_analyse_initiale(self, analyse) -> None:
        """Affiche le rapport d'analyse initiale de la probabilité."""
        from rich.columns import Columns
        from rich.text import Text

        console.print()

        # Résumé
        afficher_jauge_probabilite(analyse.probabilite, self._profil.objectif.description)

        console.print(f"\n  [{C_MUTED}]{analyse.resume}[/]\n")

        # Points forts / faibles
        if analyse.points_forts or analyse.points_faibles:
            t_forts = "\n".join(f"  [bright_green][OK][/] {p}" for p in analyse.points_forts)
            t_faibles = "\n".join(f"  [bright_red][X][/] {p}" for p in analyse.points_faibles)

            p_forts = Panel(
                t_forts or "—",
                title="[bold bright_green]Points forts[/]",
                border_style="bright_green",
                box=box.ROUNDED,
            )
            p_faibles = Panel(
                t_faibles or "—",
                title="[bold bright_red]Points faibles[/]",
                border_style="bright_red",
                box=box.ROUNDED,
            )
            console.print(Columns([p_forts, p_faibles]))

        # Conseil prioritaire
        if analyse.conseil_prioritaire:
            console.print(
                Panel(
                    f"[bold yellow]*[/] {analyse.conseil_prioritaire}",
                    title="[bold]Action prioritaire recommandée[/]",
                    border_style=C_PRIMAIRE,
                    box=box.ROUNDED,
                )
            )
        console.print()

    # ── Au revoir ─────────────────────────────────────────────────────────────

    def _au_revoir(self) -> None:
        console.print(
            f"\n[{C_PRIMAIRE}]À bientôt sur Syléa.AI — continuez sur votre trajectoire ![/]\n"
        )
