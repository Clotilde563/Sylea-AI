"""
Écran d'historique des décisions prises.
"""

from datetime import datetime
from typing import List

from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from sylea.core.models.decision import Decision
from sylea.interfaces.cli.components.ui import (
    console,
    afficher_titre_section,
    afficher_info,
    C_SUCCES,
    C_DANGER,
    C_MUTED,
    C_ACCENT,
    C_PRIMAIRE,
)


def afficher_historique(decisions: List[Decision]) -> None:
    """Affiche l'historique des décisions dans un tableau Rich."""
    afficher_titre_section("Historique de vos décisions")

    if not decisions:
        afficher_info("Aucune décision enregistrée pour l'instant.")
        console.print(
            f"[{C_MUTED}]  Analysez un choix de vie pour commencer à construire votre historique.[/]\n"
        )
        return

    table = Table(
        box=box.ROUNDED,
        border_style=C_PRIMAIRE,
        show_header=True,
        header_style=f"bold {C_PRIMAIRE}",
        expand=True,
    )
    table.add_column("Date", style=C_MUTED, width=12)
    table.add_column("Question", style="white", ratio=3)
    table.add_column("Choix retenu", style=C_ACCENT, ratio=2)
    table.add_column("Avant", justify="right", width=8)
    table.add_column("Après", justify="right", width=8)
    table.add_column("Var.", justify="right", width=8)

    for dec in decisions:
        date_str = dec.cree_le.strftime("%d/%m/%Y") if dec.cree_le else "—"
        option = dec.get_option_choisie()
        choix_desc = option.description[:35] + "…" if option and len(option.description) > 35 else (option.description if option else "—")

        prob_av = f"{dec.probabilite_avant:.2f}%"
        if dec.probabilite_apres is not None:
            prob_ap = f"{dec.probabilite_apres:.2f}%"
            delta = dec.probabilite_apres - dec.probabilite_avant
            signe = "+" if delta >= 0 else ""
            couleur_delta = C_SUCCES if delta >= 0 else C_DANGER
            delta_str = f"[{couleur_delta}]{signe}{delta:.3f}%[/]"
        else:
            prob_ap = "—"
            delta_str = "—"

        question_courte = dec.question[:45] + "…" if len(dec.question) > 45 else dec.question

        table.add_row(date_str, question_courte, choix_desc, prob_av, prob_ap, delta_str)

    console.print()
    console.print(table)

    # Résumé
    nb_positifs = sum(
        1 for d in decisions
        if d.probabilite_apres is not None and d.probabilite_apres > d.probabilite_avant
    )
    nb_negatifs = len([d for d in decisions if d.probabilite_apres is not None]) - nb_positifs

    resume = Text()
    resume.append(f"\n  {len(decisions)} décision(s) analysée(s)  ·  ", style=C_MUTED)
    resume.append(f"{nb_positifs} positive(s)", style=C_SUCCES)
    resume.append("  ·  ", style=C_MUTED)
    resume.append(f"{nb_negatifs} négative(s)\n", style=C_DANGER)
    console.print(resume)
