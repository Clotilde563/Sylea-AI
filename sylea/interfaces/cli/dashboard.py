"""
Tableau de bord de Syléa.AI ("Le Miroir" — vue synthétique).

Ce module gère l'affichage Rich du tableau de bord principal :
  - Bannière de l'application
  - Indicateurs clés du profil
  - Jauge de probabilité visuelle
  - Menu principal
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text

if TYPE_CHECKING:
    from sylea.core.models.user import ProfilUtilisateur

from sylea.config.settings import APP_NAME, APP_VERSION, APP_TAGLINE


console = Console()


def afficher_banniere() -> None:
    """Affiche la bannière d'accueil de Syléa.AI."""
    titre = Text(f"\n  {APP_NAME}  v{APP_VERSION}", style="bold cyan")
    sous_titre = Text(f"  {APP_TAGLINE}\n", style="dim white")
    bloc = Text()
    bloc.append(str(titre))
    bloc.append("\n")
    bloc.append(str(sous_titre))
    console.print(
        Panel(
            Align.center(f"[bold cyan]{APP_NAME}[/bold cyan]  [dim]v{APP_VERSION}[/dim]\n"
                         f"[italic dim white]{APP_TAGLINE}[/italic dim white]"),
            border_style="cyan",
            padding=(1, 4),
        )
    )


def afficher_jauge_probabilite(probabilite: float) -> None:
    """
    Affiche une jauge visuelle de la probabilité de réussite.

    Couleur de la jauge :
      - Rouge   : < 20%
      - Jaune   : 20% – 50%
      - Vert    : > 50%

    Args:
        probabilite: Valeur en % (0.01 – 99.9)
    """
    couleur = "red" if probabilite < 20 else ("yellow" if probabilite < 50 else "green")

    with Progress(
        TextColumn("  [bold]Probabilité de réussite[/bold]"),
        BarColumn(bar_width=36, complete_style=couleur, finished_style=couleur),
        TextColumn(f"[bold {couleur}]{probabilite:.2f}%[/bold {couleur}]"),
        expand=False,
        transient=False,
    ) as progress:
        tache = progress.add_task("", total=100)
        progress.update(tache, completed=probabilite)


def afficher_indicateur(nom: str, valeur: int, couleur_seuil: int = 5) -> str:
    """
    Génère une ligne d'indicateur avec barre ASCII et code couleur.

    Args:
        nom           : Nom de l'indicateur
        valeur        : Valeur 1-10
        couleur_seuil : Seuil en dessous duquel la couleur est rouge (défaut : 5)

    Returns:
        Texte Rich formaté
    """
    barres = "█" * valeur + "░" * (10 - valeur)
    couleur = "red" if valeur < couleur_seuil else ("yellow" if valeur <= 6 else "green")
    return (
        f"  {nom:<12} [{couleur}]{barres}[/{couleur}] "
        f"[bold {couleur}]{valeur}/10[/bold {couleur}]"
    )


def afficher_indicateur_stress(valeur: int) -> str:
    """
    Indicateur de stress inversé (plus c'est bas, mieux c'est).

    Args:
        valeur: Valeur 1-10 (10 = très stressé)
    """
    barres = "█" * valeur + "░" * (10 - valeur)
    couleur = "green" if valeur < 4 else ("yellow" if valeur <= 7 else "red")
    warning = " [blink red]⚠ ÉLEVÉ[/blink red]" if valeur >= 8 else ""
    return (
        f"  {'Stress':<12} [{couleur}]{barres}[/{couleur}] "
        f"[bold {couleur}]{valeur}/10[/bold {couleur}]{warning}"
    )


def afficher_dashboard(profil: "ProfilUtilisateur") -> None:
    """
    Affiche le tableau de bord complet de l'utilisateur.

    Args:
        profil: ProfilUtilisateur à afficher
    """
    console.clear()
    afficher_banniere()

    # ── Section profil ───────────────────────────────────────────────────────
    objectif_desc = (
        profil.objectif.description[:60] + "…"
        if profil.objectif and len(profil.objectif.description) > 60
        else (profil.objectif.description if profil.objectif else "Non défini")
    )
    categorie = (
        f" [{profil.objectif.categorie}]"
        if profil.objectif
        else ""
    )

    infos = (
        f"  [bold white]{profil.nom}[/bold white] — "
        f"{profil.age} ans — {profil.profession}\n"
        f"  {profil.ville} — {profil.situation_familiale}\n\n"
        f"  [bold]Objectif{categorie} :[/bold]\n"
        f"  [italic cyan]{objectif_desc}[/italic cyan]"
    )
    console.print(Panel(infos, title="[bold]Profil[/bold]", border_style="blue", padding=(0, 2)))

    # ── Jauge probabilité ────────────────────────────────────────────────────
    console.print()
    afficher_jauge_probabilite(profil.probabilite_actuelle)
    console.print()

    # ── Indicateurs clés ─────────────────────────────────────────────────────
    lignes_indicateurs = "\n".join([
        afficher_indicateur("Santé", profil.niveau_sante),
        afficher_indicateur_stress(profil.niveau_stress),
        afficher_indicateur("Énergie", profil.niveau_energie),
        afficher_indicateur("Bonheur", profil.niveau_bonheur, couleur_seuil=4),
    ])
    console.print(
        Panel(
            lignes_indicateurs,
            title="[bold]Indicateurs[/bold]",
            border_style="blue",
            padding=(0, 0),
        )
    )

    # ── Menu ─────────────────────────────────────────────────────────────────
    console.print()
    afficher_menu_principal()


def afficher_menu_principal() -> None:
    """Affiche le menu principal interactif."""
    menu_items = [
        ("1", "Confronter un dilemme", "cyan"),
        ("2", "Historique des décisions", "white"),
        ("3", "Mettre à jour le profil", "white"),
        ("4", "Rapport de l'agent", "white"),
        ("0", "Quitter", "red"),
    ]

    table = Table(
        show_header=False,
        box=None,
        padding=(0, 2),
    )
    table.add_column(style="bold", no_wrap=True)
    table.add_column()

    for num, label, couleur in menu_items:
        table.add_row(
            f"[{couleur}][ {num} ][/{couleur}]",
            f"[{couleur}]{label}[/{couleur}]",
        )

    console.print(
        Panel(table, title="[bold]Menu[/bold]", border_style="dim", padding=(0, 2))
    )


def afficher_message_succes(message: str) -> None:
    """Affiche un message de succès."""
    console.print(f"\n  [bold green]✅ {message}[/bold green]\n")


def afficher_message_erreur(message: str) -> None:
    """Affiche un message d'erreur."""
    console.print(f"\n  [bold red]❌ {message}[/bold red]\n")


def afficher_message_info(message: str) -> None:
    """Affiche un message informatif."""
    console.print(f"\n  [bold cyan]ℹ {message}[/bold cyan]\n")


def afficher_separateur() -> None:
    """Affiche un séparateur horizontal."""
    console.print("  " + "─" * 55, style="dim")


def afficher_historique(decisions: list, limite: int = 10) -> None:
    """
    Affiche l'historique des décisions sous forme de tableau.

    Args:
        decisions: Liste de Decision
        limite   : Nombre maximum de décisions à afficher
    """
    if not decisions:
        console.print(
            Panel(
                "  Aucune décision enregistrée. Soumettez votre premier dilemme !",
                title="[bold]Historique des décisions[/bold]",
                border_style="blue",
            )
        )
        return

    table = Table(
        title="Historique des décisions",
        border_style="blue",
        show_lines=True,
    )
    table.add_column("Date", style="dim", no_wrap=True)
    table.add_column("Question", max_width=35)
    table.add_column("Choix", max_width=25)
    table.add_column("Avant", justify="right")
    table.add_column("Après", justify="right")
    table.add_column("Δ", justify="right")

    for decision in decisions[:limite]:
        choix = decision.get_option_choisie()
        delta = (
            decision.probabilite_apres - decision.probabilite_avant
            if decision.probabilite_apres is not None
            else None
        )
        delta_str = ""
        if delta is not None:
            couleur = "green" if delta >= 0 else "red"
            signe = "+" if delta >= 0 else ""
            delta_str = f"[{couleur}]{signe}{delta:.2f}%[/{couleur}]"

        table.add_row(
            decision.cree_le.strftime("%d/%m %H:%M"),
            decision.question[:35],
            choix.description[:25] if choix else "—",
            f"{decision.probabilite_avant:.2f}%",
            f"{decision.probabilite_apres:.2f}%" if decision.probabilite_apres else "—",
            delta_str,
        )

    console.print(table)


def afficher_rapport_agent(actions: list) -> None:
    """
    Affiche le rapport d'activité de l'agent.

    Args:
        actions: Liste d'ActionAgent
    """
    if not actions:
        console.print(
            Panel(
                "  L'agent n'a effectué aucune tâche pour l'instant.",
                title="[bold]Rapport de l'agent[/bold]",
                border_style="blue",
            )
        )
        return

    table = Table(
        title="Rapport de l'agent exécutant",
        border_style="blue",
        show_lines=True,
    )
    table.add_column("Date", style="dim", no_wrap=True)
    table.add_column("Skill", style="cyan", no_wrap=True)
    table.add_column("Instruction", max_width=35)
    table.add_column("Statut", justify="center")

    for action in actions:
        statut_emoji = "✅" if action.statut == "terminé" else "❌"
        table.add_row(
            action.execute_le.strftime("%d/%m %H:%M"),
            action.skill_utilise.upper(),
            action.instruction[:35],
            statut_emoji,
        )

    console.print(table)
