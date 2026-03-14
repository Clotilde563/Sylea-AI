"""
Interface de soumission et analyse de dilemmes.

Ce module gère le flow complet d'un dilemme :
  1. Saisie de la question et des options
  2. Analyse par le moteur (déterministe ou Claude)
  3. Affichage comparatif des options
  4. Choix de l'utilisateur
  5. Mise à jour de la probabilité
  6. Proposition optionnelle de délégation à l'agent
"""

from __future__ import annotations

import os
from typing import Optional, TYPE_CHECKING

from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

if TYPE_CHECKING:
    from sylea.core.models.user import ProfilUtilisateur
    from sylea.core.models.decision import Decision

from sylea.core.engine.analyzer import AnalyseurDilemme
from sylea.core.engine.probability import MoteurProbabilite
from sylea.core.models.decision import Decision, OptionDilemme
from sylea.agent.executor import AgentExecutant
from sylea.agent.validator import ValidateurInstruction
from sylea.interfaces.cli.dashboard import (
    afficher_jauge_probabilite,
    afficher_message_erreur,
    afficher_message_info,
    afficher_message_succes,
    afficher_separateur,
    console,
)


# ── Tentative d'import du client Claude (optionnel) ──────────────────────────

def _charger_agent_claude():
    """Tente de charger l'agent Claude. Retourne None si non disponible."""
    try:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or api_key == "sk-ant-votre-cle-api-ici":
            return None
        from sylea.agent.claude_agent import AgentSylea
        return AgentSylea()
    except Exception:
        return None


def _afficher_tableau_comparatif(options: list[OptionDilemme]) -> None:
    """
    Affiche un tableau comparatif des options analysées.

    Chaque option est présentée avec son impact et son explication.

    Args:
        options: Liste d'OptionDilemme analysées et triées par impact
    """
    table = Table(
        title="[bold]Analyse comparative[/bold]",
        border_style="cyan",
        show_lines=True,
        expand=True,
    )
    table.add_column("#", style="bold", no_wrap=True, width=3)
    table.add_column("Option", min_width=20)
    table.add_column("Impact", justify="center", no_wrap=True, width=12)
    table.add_column("Déléguable", justify="center", no_wrap=True, width=12)
    table.add_column("Temps est.", justify="center", no_wrap=True, width=10)
    table.add_column("Explication", min_width=30)

    for i, opt in enumerate(options, 1):
        # Couleur selon l'impact
        impact_val = opt.impact_score
        if impact_val >= 2:
            couleur_impact = "bold green"
        elif impact_val >= 0:
            couleur_impact = "green"
        elif impact_val >= -1:
            couleur_impact = "yellow"
        else:
            couleur_impact = "red"

        signe = "+" if impact_val >= 0 else ""
        delegable_str = (
            "[cyan]✓ Oui[/cyan]" if opt.est_delegable else "[dim]Non[/dim]"
        )
        temps_str = f"{opt.temps_estime:.1f}h"

        table.add_row(
            str(i),
            opt.description,
            f"[{couleur_impact}]{signe}{impact_val:.2f}%[/{couleur_impact}]",
            delegable_str,
            temps_str,
            opt.explication_impact[:100] + ("…" if len(opt.explication_impact) > 100 else ""),
        )

    console.print(table)


def _afficher_option_detail(num: int, option: OptionDilemme) -> None:
    """Affiche le détail complet d'une option dans un panel."""
    impact_val = option.impact_score
    signe = "+" if impact_val >= 0 else ""
    couleur = "green" if impact_val >= 0 else "red"

    contenu = (
        f"[bold]Description[/bold] : {option.description}\n"
        f"[bold]Impact      [/bold] : [{couleur}]{signe}{impact_val:.2f}%[/{couleur}]\n"
        f"[bold]Déléguable  [/bold] : {'✅ Oui' if option.est_delegable else '❌ Non'}\n"
        f"[bold]Temps estimé[/bold] : {option.temps_estime:.1f}h\n\n"
        f"[italic]{option.explication_impact}[/italic]"
    )
    console.print(
        Panel(
            contenu,
            title=f"[bold]Option {num}[/bold]",
            border_style=couleur,
            padding=(0, 2),
        )
    )


def soumettre_dilemme(profil: "ProfilUtilisateur") -> Optional[Decision]:
    """
    Lance le flow complet de soumission d'un dilemme.

    Args:
        profil: ProfilUtilisateur pour lequel analyser le dilemme

    Returns:
        Decision créée après le choix, ou None si annulé
    """
    if profil.objectif is None:
        afficher_message_erreur("Vous devez définir un objectif avant de soumettre un dilemme.")
        console.input("\n  [dim]Appuyez sur Entrée…[/dim]")
        return None

    console.clear()
    console.print(
        Panel(
            "  Décrivez votre dilemme. L'IA analysera chaque option\n"
            "  et calculera son impact sur votre probabilité de réussite.\n\n"
            f"  [dim]Objectif : {profil.objectif.description[:60]}…[/dim]\n"
            f"  [dim]Probabilité actuelle : {profil.probabilite_actuelle:.2f}%[/dim]",
            title="[bold cyan]Le Conseiller — Analyse de dilemme[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print()

    # ── Étape 1 : Saisie de la question ─────────────────────────────────────
    console.print("[bold]Étape 1[/bold] — Quelle est votre question ?")
    afficher_separateur()
    question = Prompt.ask(
        "  Votre dilemme",
        default="Dois-je travailler ou faire du sport ce soir ?",
    )
    console.print()

    # ── Étape 2 : Saisie des options ─────────────────────────────────────────
    console.print("[bold]Étape 2[/bold] — Listez vos options (2 à 4)")
    afficher_separateur()
    afficher_message_info("Appuyez sur Entrée sans rien saisir pour arrêter.")

    options_texte: list[str] = []
    for i in range(1, 5):
        if i <= 2:
            rep = Prompt.ask(f"  Option {i} (obligatoire)")
        else:
            rep = Prompt.ask(f"  Option {i} (facultative, Entrée pour passer)", default="")
        if rep.strip():
            options_texte.append(rep.strip())
        elif i > 2:
            break

    if len(options_texte) < 2:
        afficher_message_erreur("Vous devez saisir au moins 2 options.")
        console.input("\n  [dim]Appuyez sur Entrée…[/dim]")
        return None

    # ── Étape 3 : Analyse ────────────────────────────────────────────────────
    console.print()
    console.print("[bold]Étape 3[/bold] — Analyse en cours…")
    afficher_separateur()

    with console.status("[cyan]Analyse de vos options…[/cyan]", spinner="dots"):
        # Tentative d'utilisation de Claude (si clé API disponible)
        agent_claude = _charger_agent_claude()
        options_analysees: list[OptionDilemme] = []

        if agent_claude and len(options_texte) == 2:
            try:
                analyse = agent_claude.analyser_dilemme(
                    profil=profil,
                    question=question,
                    option_a=options_texte[0],
                    option_b=options_texte[1],
                )
                # Conversion en OptionDilemme
                analyseur = AnalyseurDilemme()
                options_base = analyseur.analyser(question, options_texte, profil)

                # Enrichir avec les données Claude
                for opt, opt_base in zip(
                    [analyse.option_a, analyse.option_b], options_base
                ):
                    opt_base.impact_score = round(opt.impact_probabilite * 100, 2)
                    opt_base.explication_impact = opt.resume
                options_analysees = options_base
                options_analysees.sort(key=lambda o: o.impact_score, reverse=True)
            except Exception:
                # Fallback sur le moteur déterministe
                analyseur = AnalyseurDilemme()
                options_analysees = analyseur.analyser(question, options_texte, profil)
        else:
            analyseur = AnalyseurDilemme()
            options_analysees = analyseur.analyser(question, options_texte, profil)

    # ── Étape 4 : Affichage des résultats ────────────────────────────────────
    console.print()
    _afficher_tableau_comparatif(options_analysees)
    console.print()

    # Affichage détaillé de chaque option
    for i, opt in enumerate(options_analysees, 1):
        _afficher_option_detail(i, opt)
    console.print()

    # ── Étape 5 : Choix de l'utilisateur ─────────────────────────────────────
    console.print("[bold]Étape 4[/bold] — Quel est votre choix ?")
    afficher_separateur()

    while True:
        try:
            num_choix = IntPrompt.ask(
                f"  Numéro de l'option choisie (1 à {len(options_analysees)})"
            )
            if 1 <= num_choix <= len(options_analysees):
                break
            console.print(
                f"  [red]Entrez un numéro entre 1 et {len(options_analysees)}.[/red]"
            )
        except (ValueError, KeyboardInterrupt):
            console.print("  [red]Entrée invalide.[/red]")

    option_choisie = options_analysees[num_choix - 1]

    # ── Étape 6 : Mise à jour de la probabilité ──────────────────────────────
    moteur = MoteurProbabilite()
    prob_avant = profil.probabilite_actuelle
    prob_apres = moteur.recalculer_apres_choix(prob_avant, option_choisie.impact_score)

    decision = Decision(
        user_id=profil.id,
        question=question,
        options=options_analysees,
        probabilite_avant=prob_avant,
        option_choisie_id=option_choisie.id,
        probabilite_apres=prob_apres,
    )

    profil.probabilite_actuelle = prob_apres

    console.print()
    message_traj = moteur.generer_message_trajectoire(prob_avant, prob_apres)
    delta = prob_apres - prob_avant
    signe = "+" if delta >= 0 else ""
    couleur = "green" if delta >= 0 else "red"

    console.print(
        Panel(
            f"  Probabilité : {prob_avant:.2f}% → "
            f"[bold {couleur}]{prob_apres:.2f}%[/bold {couleur}] "
            f"([{couleur}]{signe}{delta:.2f}%[/{couleur}])\n\n"
            f"  [italic]{message_traj}[/italic]",
            title="[bold]Résultat[/bold]",
            border_style=couleur,
        )
    )
    console.print()
    afficher_jauge_probabilite(prob_apres)
    console.print()

    # ── Étape 7 : Délégation à l'agent (si déléguable) ───────────────────────
    if option_choisie.est_delegable:
        afficher_message_info(
            "Cette option est déléguable à l'agent. Voulez-vous la confier au Double ?"
        )
        deleguer = Confirm.ask("  Déléguer cette tâche à l'agent ?", default=False)

        if deleguer:
            decision = _deleguer_a_agent(decision, option_choisie, profil)

    console.input("\n  [dim]Appuyez sur Entrée pour revenir au menu…[/dim]")
    return decision


def _deleguer_a_agent(
    decision: Decision,
    option: OptionDilemme,
    profil: "ProfilUtilisateur",
) -> Decision:
    """
    Lance le flow de délégation d'une tâche à l'agent.

    Args:
        decision: Decision en cours (à enrichir avec l'action agent)
        option  : Option déléguée
        profil  : Profil utilisateur (pour contexte)

    Returns:
        Decision enrichie avec l'ActionAgent
    """
    console.print()
    console.print(
        Panel(
            "  L'agent attend votre instruction.\n"
            "  [bold]Soyez précis[/bold] : qui, quoi, pour qui, pourquoi.\n\n"
            "  [dim]Exemples valides :[/dim]\n"
            "  [dim]• Prépare le dossier client Martin pour la réunion de demain[/dim]\n"
            "  [dim]• Rédige un email de relance pour le prospect Dupont[/dim]\n"
            "  [dim]• Crée une liste de tâches pour le lancement du produit Alpha[/dim]",
            title="[bold cyan]Le Double — Délégation[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print()

    agent = AgentExecutant()
    validateur = ValidateurInstruction()

    # Boucle de saisie avec validation
    instruction = ""
    for _tentative in range(3):
        instruction = Prompt.ask(
            "  Votre instruction",
            default=f"Prépare {option.description.lower()}",
        )
        resultat = validateur.valider(instruction)

        if resultat.valide:
            afficher_message_succes("Instruction valide ✓")
            break
        else:
            afficher_message_erreur("Instruction invalide :")
            for err in resultat.erreurs:
                console.print(f"  [red]  → {err}[/red]")
            if resultat.suggestions:
                console.print("\n  [dim]Suggestions :[/dim]")
                for sug in resultat.suggestions:
                    console.print(f"  [dim]  → {sug}[/dim]")
            console.print()
    else:
        afficher_message_erreur("Instruction non validée après 3 tentatives. Abandon.")
        return decision

    # Confirmation explicite (opt-in)
    console.print()
    confirme = Confirm.ask(
        f"  Confirmer l'exécution de : [bold]« {instruction} »[/bold] ?",
        default=False,
    )
    if not confirme:
        afficher_message_info("Délégation annulée.")
        return decision

    # Exécution
    with console.status("[cyan]L'agent travaille…[/cyan]", spinner="dots"):
        try:
            action = agent.executer(instruction, validation_confirmee=True)
        except Exception as e:
            afficher_message_erreur(f"Erreur lors de l'exécution : {e}")
            return decision

    if action:
        decision.action_agent = action
        afficher_message_succes("Tâche exécutée par l'agent !")
        console.print(
            Panel(
                action.resultat[:500],
                title="[bold]Rapport de l'agent[/bold]",
                border_style="cyan",
                padding=(0, 2),
            )
        )

    return decision
