#!/usr/bin/env python3
"""
Script de démonstration de Syléa.AI — Édition Luxe Futuriste.

Crée deux profils test (Alex et Claire) et simule une session complète :
calcul de probabilité, analyse de dilemme, délégation à l'agent.
Aucune saisie utilisateur, aucune API externe requise.

Usage :
    python demo.py
    python demo.py --complet    # affiche tous les détails
"""

import sys
import time

# Force UTF-8 so Rich box-drawing chars work on any Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich.text import Text
from rich.align import Align
from rich import box

from sylea.core.models.user import Objectif, ProfilUtilisateur
from sylea.core.engine.probability import MoteurProbabilite
from sylea.core.engine.analyzer import AnalyseurDilemme
from sylea.agent.executor import AgentExecutant
from sylea.agent.validator import ValidateurInstruction

console = Console(highlight=False)
COMPLET = "--complet" in sys.argv

# ── Palette Luxe Futuriste ────────────────────────────────────────────────────
ARGENT  = "bright_white"    # Argent platine — primaire
OR      = "gold1"           # Or             — accent luxe
VIOLET  = "medium_purple"   # Violet         — UI chrome
PLATINE = "grey82"          # Platine        — secondaire
GRIS    = "grey54"          # Gris           — discret
SOMBRE  = "grey30"          # Gris foncé     — décoratif
VERT    = "bright_green"    # Positif
ROUGE   = "bright_red"      # Négatif
ORANGE  = "dark_orange"     # Avertissement


def section(texte: str) -> None:
    """Titre de section — règle violette, texte argent."""
    console.print()
    console.print(Rule(title=f"[bold {ARGENT}]{texte}[/]", style=VIOLET))
    console.print()


def pause(duree: float = 0.5) -> None:
    time.sleep(duree)


# ── Profil Alex ───────────────────────────────────────────────────────────────

def demo_alex() -> None:
    """Démo complète — Alex Martin, entrepreneur ambitieux."""
    console.print(
        Panel(
            Text.from_markup(
                f"\n  [bold {ARGENT}]Alex Martin[/]  [{GRIS}]— Entrepreneur tech, 32 ans[/]\n"
                f"\n  Objectif  [{OR}]Devenir milliardaire en 15 ans[/]\n"
                f"  Situation [{GRIS}]Stress élevé (8/10) · Revenu 85k€/an[/]\n"
            ),
            title=f"[bold {OR}]Profil 1[/]",
            border_style=VIOLET,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )

    objectif = Objectif(description="Devenir milliardaire en 15 ans", categorie="finance")
    profil = ProfilUtilisateur(
        nom="Alex Martin", age=32, profession="Entrepreneur tech",
        ville="Paris", situation_familiale="célibataire",
        revenu_annuel=85_000, patrimoine_estime=50_000, charges_mensuelles=2_500,
        heures_travail=10.0, heures_sommeil=6.5, heures_loisirs=1.5, heures_transport=1.0,
        niveau_sante=7, niveau_stress=8, niveau_energie=7, niveau_bonheur=7,
        competences=["Python", "Marketing", "Business Development", "Finance"],
        diplomes=["Master Finance"], langues=["Français", "Anglais"],
        objectif=objectif,
    )

    with console.status(f"[{VIOLET}]Calcul de la probabilité initiale...[/]", spinner="line"):
        pause()
        moteur = MoteurProbabilite()
        prob = moteur.calculer_probabilite_initiale(profil)
        profil.probabilite_actuelle = prob

    c_prob = VERT if prob > 5 else ORANGE
    console.print(
        f"\n  [{GRIS}]Probabilité initiale :[/]  [bold {c_prob}]{prob:.2f}%[/]\n"
    )

    section("Dilemme soumis par Alex")
    console.print(
        f"  [{GRIS}]\"Je dois choisir entre courir ce soir ou travailler"
        f" sur mon business plan.\"[/]\n"
    )

    with console.status(f"[{VIOLET}]Analyse des options...[/]", spinner="line"):
        pause(0.8)
        analyseur = AnalyseurDilemme()
        options = analyseur.analyser(
            question="Courir ou travailler sur mon business plan ce soir ?",
            descriptions_options=[
                "Courir 10km au parc",
                "Travailler sur le business plan et les projections financières",
            ],
            profil=profil,
        )

    table = Table(
        title=f"[bold {ARGENT}]Analyse comparative[/]",
        border_style=VIOLET,
        box=box.ROUNDED,
        show_lines=True,
        header_style=f"bold {ARGENT}",
        padding=(0, 1),
    )
    table.add_column("Option",    min_width=35, style=ARGENT)
    table.add_column("Impact",    justify="center", width=10)
    table.add_column("Delegable", justify="center", width=10)
    table.add_column("Temps",     justify="center", width=7)

    for opt in options:
        signe = "+" if opt.impact_score >= 0 else ""
        c = VERT if opt.impact_score >= 0 else ROUGE
        delegable = f"[{VERT}]Oui[/]" if opt.est_delegable else f"[{GRIS}]Non[/]"
        table.add_row(
            opt.description,
            f"[{c}]{signe}{opt.impact_score:.2f}%[/]",
            delegable,
            f"[{GRIS}]{opt.temps_estime:.1f}h[/]",
        )
    console.print(table)

    if COMPLET:
        console.print()
        for i, opt in enumerate(options, 1):
            console.print(f"  [{OR}]{i}[/]  [{ARGENT}]{opt.description}[/]")
            console.print(f"     [{GRIS}]{opt.explication_impact}[/]")

    option_choisie = options[0]
    prob_avant  = profil.probabilite_actuelle
    prob_apres  = moteur.recalculer_apres_choix(prob_avant, option_choisie.impact_score)
    profil.probabilite_actuelle = prob_apres

    delta  = prob_apres - prob_avant
    signe  = "+" if delta >= 0 else ""
    c_d    = VERT if delta >= 0 else ROUGE

    console.print(
        f"\n  [{GRIS}]Choix d'Alex :[/]  [{ARGENT}]{option_choisie.description}[/]\n"
        f"  [{GRIS}]{prob_avant:.2f}%  ->  [/][bold {c_d}]{prob_apres:.2f}%[/]"
        f"  [{c_d}]({signe}{delta:.2f}%)[/]"
    )
    msg = moteur.generer_message_trajectoire(prob_avant, prob_apres)
    console.print(f"  [{GRIS}]{msg}[/]\n")

    if option_choisie.est_delegable:
        section("Délégation à l'agent")
        instruction = (
            "Prépare le business plan financier avec les projections sur 5 ans"
            " pour notre startup"
        )

        with console.status(f"[{VIOLET}]Validation de l'instruction...[/]", spinner="line"):
            pause(0.3)
            validateur = ValidateurInstruction()
            res = validateur.valider(instruction)

        c_statut = VERT if res.valide else ROUGE
        label    = "Valide" if res.valide else "Invalide"
        console.print(f"  [{GRIS}]Instruction :[/] [{ARGENT}]{instruction}[/]")
        console.print(f"  [{GRIS}]Statut      :[/] [bold {c_statut}]{label}[/]\n")

        if res.valide:
            with console.status(f"[{VIOLET}]L'agent travaille...[/]", spinner="line"):
                pause(1.0)
                agent  = AgentExecutant()
                action = agent.executer(instruction, validation_confirmee=True)

            console.print(f"  [{GRIS}]Skill  :[/] [{OR}]{action.skill_utilise.upper()}[/]")
            console.print(f"  [{GRIS}]Statut :[/] [{VERT}]{action.statut}[/]\n")

            if COMPLET:
                console.print(
                    Panel(
                        action.resultat[:800],
                        title=f"[bold {OR}]Rapport de l'agent[/]",
                        border_style=VIOLET,
                        box=box.ROUNDED,
                        padding=(0, 2),
                    )
                )
            else:
                extrait = action.resultat[:200]
                console.print(
                    Panel(
                        f"[{GRIS}]{extrait}...[/]",
                        title=f"[{OR}]Extrait du rapport[/]",
                        border_style=SOMBRE,
                        box=box.ROUNDED,
                        padding=(0, 1),
                    )
                )


# ── Profil Claire ─────────────────────────────────────────────────────────────

def demo_claire() -> None:
    """Démo avec Claire Dupont — profil athlète."""
    console.print(
        Panel(
            Text.from_markup(
                f"\n  [bold {ARGENT}]Claire Dupont[/]  [{GRIS}]— Coach sportive, 28 ans[/]\n"
                f"\n  Objectif  [{VERT}]Courir un marathon en 3h30[/]\n"
                f"  Situation [{GRIS}]Santé excellente (9/10) · Stress faible (3/10)[/]\n"
            ),
            title=f"[bold {OR}]Profil 2[/]",
            border_style=VIOLET,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )

    objectif = Objectif(description="Courir un marathon en 3h30", categorie="santé")
    profil = ProfilUtilisateur(
        nom="Claire Dupont", age=28, profession="Coach sportive",
        ville="Lyon", situation_familiale="en couple",
        revenu_annuel=42_000, patrimoine_estime=15_000, charges_mensuelles=1_200,
        niveau_sante=9, niveau_stress=3, niveau_energie=9, niveau_bonheur=8,
        competences=["Coaching", "Nutrition sportive", "Athlétisme", "Préparation mentale"],
        langues=["Français", "Anglais"],
        objectif=objectif,
    )

    with console.status(f"[{VIOLET}]Calcul de la probabilité...[/]", spinner="line"):
        pause()
        moteur = MoteurProbabilite()
        prob   = moteur.calculer_probabilite_initiale(profil)
        profil.probabilite_actuelle = prob

    console.print(
        f"\n  [{GRIS}]Probabilité initiale :[/]  [bold {VERT}]{prob:.2f}%[/]"
        f"  [{GRIS}](objectif réaliste pour son profil)[/]\n"
    )

    section("Dilemme soumis par Claire")
    console.print(f'  [{GRIS}]"Séance fractionnée ou repos actif aujourd\'hui ?"[/]\n')

    with console.status(f"[{VIOLET}]Analyse...[/]", spinner="line"):
        pause(0.8)
        analyseur = AnalyseurDilemme()
        options   = analyseur.analyser(
            "Séance fractionnée ou repos actif ?",
            ["Faire une séance fractionnée intensive", "Faire une séance de repos actif (yoga)"],
            profil,
        )

    for opt in options:
        signe = "+" if opt.impact_score >= 0 else ""
        c = VERT if opt.impact_score >= 0 else ROUGE
        console.print(
            f"  [bold {c}]{signe}{opt.impact_score:.2f}%[/]"
            f"  [{ARGENT}]{opt.description}[/]"
        )

    option_choisie = options[0]
    prob_avant = profil.probabilite_actuelle
    prob_apres = moteur.recalculer_apres_choix(prob_avant, option_choisie.impact_score)
    delta      = prob_apres - prob_avant

    console.print(
        f"\n  [{GRIS}]Choix de Claire :[/]  [{ARGENT}]{option_choisie.description}[/]\n"
        f"  [{GRIS}]{prob_avant:.2f}%  ->  [/][bold {VERT}]{prob_apres:.2f}%[/]"
        f"  [{VERT}](+{delta:.2f}%)[/]\n"
    )


# ── Validateur d'instructions ─────────────────────────────────────────────────

def demo_validation_agent() -> None:
    """Démo du validateur d'instructions — Luxe Futuriste."""
    section("Validateur d'instructions de l'agent")

    agent = AgentExecutant()
    cas_test = [
        ("Fais ça",                                                             False),
        ("Prépare truc pour le client",                                         False),
        ("Rédige",                                                              False),
        ("Prépare le dossier client Dupont pour la réunion de demain matin",    True),
        ("Recherche les 5 concurrents principaux de notre marché e-commerce",   True),
        ("Crée une liste de tâches pour le lancement du produit Alpha en avril", True),
    ]

    table = Table(
        title=f"[bold {ARGENT}]Validation des instructions[/]",
        border_style=VIOLET,
        box=box.ROUNDED,
        show_lines=True,
        header_style=f"bold {ARGENT}",
        padding=(0, 1),
    )
    table.add_column("Instruction", min_width=42, max_width=55, style=ARGENT)
    table.add_column("Attendu",  justify="center", width=9)
    table.add_column("Résultat", justify="center", width=9)
    table.add_column("Correct",  justify="center", width=8)

    for instruction, attendu in cas_test:
        res = agent.valider_instruction(instruction)
        ok  = res.valide == attendu

        att_str = f"[{VERT}]Oui[/]" if attendu      else f"[{GRIS}]Non[/]"
        res_str = f"[{VERT}]Oui[/]" if res.valide   else f"[{ROUGE}]Non[/]"
        ok_str  = f"[{VERT}]OK[/]"  if ok            else f"[{ROUGE}]X[/]"

        table.add_row(instruction[:55], att_str, res_str, ok_str)

    console.print(table)


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main() -> None:
    console.clear()
    console.print()
    console.print(Rule(style=VIOLET))
    console.print()

    def ligne(*parties):
        t = Text(justify="center")
        for texte, style in parties:
            t.append(texte, style=style)
        console.print(Align.center(t))

    # Logo Syléa — spirale argentée + atome moléculaire doré
    ligne(
        ("      ◦  ─  ○  ─  ◦   ", SOMBRE),
        ("            ─◈─", f"bold {OR}"),
    )
    ligne(
        ("    (    ╭─────╮    )  ", SOMBRE),
        ("          ─ ◉ ─", f"bold {OR}"),
    )
    ligne(
        ("   (    │ ", SOMBRE),
        ("≋  ≋  ≋", f"bold {ARGENT}"),
        ("  │    )  ", SOMBRE),
        ("            ─◈─", f"bold {OR}"),
    )
    ligne(
        ("   (    │ ", SOMBRE),
        ("≋≋≋≋≋≋", f"bold {ARGENT}"),
        ("  │    )", SOMBRE),
    )
    ligne(("    (    ╰─────╯    )", SOMBRE))
    ligne(("      ◦  ─  ○  ─  ◦", SOMBRE))

    console.print()

    intro = Text(justify="center")
    intro.append("  S  Y  L  É  A  ", style=f"bold {ARGENT}")
    intro.append("· A I\n", style=f"bold {OR}")
    intro.append(f"  {'─' * 24}\n", style=VIOLET)
    intro.append("  Script de démonstration  —  v1.0.0\n\n", style=f"italic {PLATINE}")
    intro.append("  ◆ Calcul de probabilité (moteur déterministe)\n", style=GRIS)
    intro.append("  ◆ Analyse de dilemmes (règles locales)\n",         style=GRIS)
    intro.append("  ◆ Délégation à l'agent (simulation)\n",            style=GRIS)
    intro.append("  ◆ Validation d'instructions\n\n",                  style=GRIS)
    intro.append("  Aucune API externe requise.\n", style=f"italic {GRIS}")
    console.print(Align.center(intro))

    console.print()
    console.print(Rule(style=VIOLET))

    console.print()
    demo_alex()

    console.print()
    console.print(Rule(style=SOMBRE))
    console.print()
    demo_claire()

    console.print()
    console.print(Rule(style=SOMBRE))
    console.print()
    demo_validation_agent()

    console.print()
    console.print(
        Panel(
            Text.from_markup(
                f"\n  [bold {VERT}]Démonstration terminée[/]\n\n"
                f"  [{GRIS}]Pour lancer l'application complète :[/]\n"
                f"  [{OR}]  python main.py[/]\n\n"
                f"  [{GRIS}]Pour les tests unitaires :[/]\n"
                f"  [{OR}]  pytest tests/ -v[/]\n"
            ),
            border_style=VIOLET,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


if __name__ == "__main__":
    main()
