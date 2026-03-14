"""
Écran d'analyse de dilemme décisionnel.

Guide l'utilisateur pour formuler son dilemme, affiche l'analyse
de l'agent Claude et met à jour la probabilité après le choix.
"""

from rich.panel import Panel
from rich.text import Text
from rich import box

from sylea.core.models.user import ProfilUtilisateur
from sylea.core.models.decision import Decision, OptionDilemme
from sylea.core.engine.probability import MoteurProbabilite
from sylea.agent.claude_agent import AgentSylea, AnalyseDilemme
from sylea.interfaces.cli.components.ui import (
    console,
    afficher_titre_section,
    afficher_succes,
    afficher_erreur,
    afficher_info,
    afficher_analyse_option,
    afficher_jauge_probabilite,
    demander,
    choisir_dans_liste,
    spinner,
    C_PRIMAIRE,
    C_SUCCES,
    C_DANGER,
    C_MUTED,
    C_ACCENT,
    C_WARNING,
)


_moteur = MoteurProbabilite()


def lancer_analyse(
    profil: ProfilUtilisateur,
    agent: AgentSylea,
) -> ProfilUtilisateur:
    """
    Lance le flux complet d'analyse d'un dilemme.

    1. Demande la question et les deux options
    2. Appelle Claude pour l'analyse
    3. Affiche les résultats
    4. Demande le choix final et met à jour le profil

    Returns:
        Le profil mis à jour avec la nouvelle probabilité
    """
    afficher_titre_section("Analyser un choix de vie")

    if not profil.objectif:
        afficher_erreur("Aucun objectif défini. Définissez d'abord un objectif.")
        return profil

    # ── Saisie du dilemme ────────────────────────────────────────────────────
    console.print(
        f"\n[{C_MUTED}]Décrivez le choix auquel vous faites face.[/]\n"
    )

    question = demander("Question (ex: 'Que faire ce soir ?')")
    if not question:
        afficher_erreur("La question est obligatoire.")
        return profil

    console.print()
    option_a = demander("Option A")
    option_b = demander("Option B")

    if not option_a or not option_b:
        afficher_erreur("Les deux options sont obligatoires.")
        return profil

    # ── Analyse par Claude ───────────────────────────────────────────────────
    analyse: AnalyseDilemme
    with spinner("Syléa analyse votre dilemme…"):
        try:
            analyse = agent.analyser_dilemme(profil, question, option_a, option_b)
        except Exception as e:
            afficher_erreur(f"Erreur lors de l'analyse : {e}")
            return profil

    # ── Affichage des analyses ───────────────────────────────────────────────
    console.print()
    afficher_analyse_option(
        "A", option_a,
        analyse.option_a.pros,
        analyse.option_a.cons,
        analyse.option_a.impact_probabilite,
        couleur="bright_cyan",
    )

    afficher_analyse_option(
        "B", option_b,
        analyse.option_b.pros,
        analyse.option_b.cons,
        analyse.option_b.impact_probabilite,
        couleur=C_PRIMAIRE,
    )

    # ── Verdict ──────────────────────────────────────────────────────────────
    recommandee = analyse.option_recommandee
    couleur_verdict = "bright_cyan" if recommandee == "A" else C_PRIMAIRE
    verdict_texte = Text()
    verdict_texte.append(f"Recommandation : Option {recommandee}\n\n", style=f"bold {couleur_verdict}")
    verdict_texte.append(analyse.verdict, style="white")

    console.print(
        Panel(
            verdict_texte,
            title=f"[bold]>> VERDICT SYLEA[/]",
            border_style=C_PRIMAIRE,
            box=box.DOUBLE_EDGE,
        )
    )

    # ── Choix de l'utilisateur ───────────────────────────────────────────────
    console.print()
    choix_raw = choisir_dans_liste(
        "Quelle option choisissez-vous ?",
        ["A", "B", "Aucune (annuler)"],
    )

    if choix_raw == "Aucune (annuler)":
        afficher_info("Analyse annulée — probabilité inchangée.")
        return profil

    # Déterminer l'impact selon le choix
    if choix_raw == "A":
        impact = analyse.option_a.impact_probabilite
        description_choisie = option_a
        analyse_choisie = analyse.option_a
    else:
        impact = analyse.option_b.impact_probabilite
        description_choisie = option_b
        analyse_choisie = analyse.option_b

    # ── Calcul de la nouvelle probabilité ────────────────────────────────────
    prob_avant = profil.probabilite_actuelle
    prob_apres = _moteur.recalculer_apres_choix(prob_avant, impact)
    message_traj = _moteur.generer_message_trajectoire(prob_avant, prob_apres)

    # Mise à jour du profil
    profil.probabilite_actuelle = prob_apres
    profil.marquer_modification()

    # ── Affichage du résultat ─────────────────────────────────────────────────
    console.print()
    afficher_jauge_probabilite(
        prob_apres,
        profil.objectif.description,
        prob_avant=prob_avant,
    )

    couleur_msg = C_SUCCES if prob_apres >= prob_avant else C_WARNING
    console.print(f"\n[{couleur_msg}]  {message_traj}[/]\n")

    # ── Enregistrement de la décision ─────────────────────────────────────────
    opt_a_obj = OptionDilemme(
        description=option_a,
        impact_score=analyse.option_a.impact_probabilite,
        explication_impact=analyse.option_a.resume,
    )
    opt_b_obj = OptionDilemme(
        description=option_b,
        impact_score=analyse.option_b.impact_probabilite,
        explication_impact=analyse.option_b.resume,
    )
    option_choisie_id = opt_a_obj.id if choix_raw == "A" else opt_b_obj.id

    decision = Decision(
        user_id=profil.id,
        question=question,
        options=[opt_a_obj, opt_b_obj],
        probabilite_avant=prob_avant,
        option_choisie_id=option_choisie_id,
        probabilite_apres=prob_apres,
    )

    # Retourner (profil, decision) pour que l'app puisse persister les deux
    profil._derniere_decision = decision  # stocké temporairement
    return profil
