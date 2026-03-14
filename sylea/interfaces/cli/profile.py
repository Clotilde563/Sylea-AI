"""
Interface de création et mise à jour du profil utilisateur.

Ce module gère le wizard interactif de saisie du profil via Rich Prompt.
Toutes les entrées sont validées à la saisie avec des messages clairs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt

from sylea.core.models.user import (
    CATEGORIES_OBJECTIF,
    SITUATIONS_FAMILIALES,
    Objectif,
    ProfilUtilisateur,
)
from sylea.core.engine.probability import MoteurProbabilite
from sylea.interfaces.cli.dashboard import (
    afficher_banniere,
    afficher_message_erreur,
    afficher_message_info,
    afficher_message_succes,
    afficher_separateur,
    console,
)


def _saisir_entier(
    libelle: str,
    minimum: int,
    maximum: int,
    defaut: Optional[int] = None,
) -> int:
    """
    Saisit un entier dans un intervalle donné, avec re-saisie en cas d'erreur.

    Args:
        libelle : Texte affiché à l'utilisateur
        minimum : Valeur minimale acceptée
        maximum : Valeur maximale acceptée
        defaut  : Valeur par défaut (None = pas de défaut)

    Returns:
        Valeur entière saisie et validée
    """
    while True:
        try:
            valeur = IntPrompt.ask(
                libelle,
                default=defaut,  # type: ignore[arg-type]
            )
            if minimum <= valeur <= maximum:
                return valeur
            console.print(
                f"  [red]→ Valeur hors limites. Entrez un entier "
                f"entre {minimum} et {maximum}.[/red]"
            )
        except (ValueError, KeyboardInterrupt):
            if defaut is not None:
                return defaut
            console.print("  [red]→ Valeur invalide. Réessayez.[/red]")


def _saisir_flottant(
    libelle: str,
    minimum: float = 0.0,
    defaut: Optional[float] = None,
) -> float:
    """
    Saisit un nombre décimal positif.

    Args:
        libelle : Texte affiché à l'utilisateur
        minimum : Valeur minimale acceptée
        defaut  : Valeur par défaut

    Returns:
        Valeur flottante saisie et validée
    """
    defaut_str = f"{defaut:,.0f}" if defaut is not None else None
    while True:
        try:
            rep = Prompt.ask(libelle, default=defaut_str)
            # Nettoyer les séparateurs de milliers
            valeur = float(rep.replace(" ", "").replace(",", ".").replace("\u202f", ""))
            if valeur >= minimum:
                return valeur
            console.print(
                f"  [red]→ La valeur doit être ≥ {minimum}.[/red]"
            )
        except (ValueError, KeyboardInterrupt):
            if defaut is not None:
                return defaut
            console.print("  [red]→ Nombre invalide. Réessayez (ex: 50000).[/red]")


def _saisir_liste(libelle: str, exemple: str = "") -> list[str]:
    """
    Saisit une liste d'éléments séparés par des virgules.

    Args:
        libelle : Texte affiché
        exemple : Exemple de saisie affiché dans le prompt

    Returns:
        Liste de chaînes nettoyées (peut être vide)
    """
    aide = f" (ex: {exemple})" if exemple else " (séparés par des virgules, ou vide)"
    rep = Prompt.ask(f"{libelle}{aide}", default="")
    if not rep.strip():
        return []
    return [item.strip() for item in rep.split(",") if item.strip()]


def _choisir_dans_liste(libelle: str, choix: list[str]) -> str:
    """
    Présente une liste de choix numérotés et retourne la valeur choisie.

    Args:
        libelle : Question à afficher
        choix   : Liste d'options disponibles

    Returns:
        Valeur choisie
    """
    console.print(f"\n  [bold]{libelle}[/bold]")
    for i, opt in enumerate(choix, 1):
        console.print(f"  [{i}] {opt.capitalize()}")

    while True:
        try:
            idx = IntPrompt.ask("  → Votre choix (numéro)")
            if 1 <= idx <= len(choix):
                return choix[idx - 1]
            console.print(f"  [red]Entrez un numéro entre 1 et {len(choix)}.[/red]")
        except (ValueError, KeyboardInterrupt):
            console.print("  [red]Entrée invalide.[/red]")


# ── Wizard de création ───────────────────────────────────────────────────────

def creer_profil_interactif() -> ProfilUtilisateur:
    """
    Lance le wizard interactif de création d'un profil utilisateur.

    Collecte toutes les informations nécessaires via des prompts Rich,
    valide chaque entrée et retourne un ProfilUtilisateur complet.

    Returns:
        ProfilUtilisateur nouvellement créé avec probabilité calculée
    """
    console.clear()
    afficher_banniere()
    console.print(
        Panel(
            "  Bienvenue ! Créons votre profil ensemble.\n"
            "  Plus vous fournissez d'informations, plus l'analyse sera précise.\n"
            "  [dim]Toutes les données restent locales sur votre machine.[/dim]",
            title="[bold cyan]Création du profil[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print()

    # ── 1. Identité ──────────────────────────────────────────────────────────
    console.print("[bold cyan]— 1 / 6  Identité[/bold cyan]")
    afficher_separateur()

    nom = Prompt.ask("  Votre prénom et nom")
    age = _saisir_entier("  Votre âge", 16, 100)
    profession = Prompt.ask("  Votre profession actuelle")
    ville = Prompt.ask("  Votre ville")
    situation_familiale = _choisir_dans_liste(
        "Situation familiale", SITUATIONS_FAMILIALES
    )
    console.print()

    # ── 2. Finances ──────────────────────────────────────────────────────────
    console.print("[bold cyan]— 2 / 6  Données financières[/bold cyan]")
    afficher_separateur()
    afficher_message_info("Ces données ne quittent jamais votre machine.")

    revenu_annuel = _saisir_flottant("  Revenu annuel (€)", defaut=50000.0)
    patrimoine = _saisir_flottant("  Patrimoine estimé (€)", defaut=0.0)
    charges = _saisir_flottant("  Charges mensuelles (€)", defaut=1500.0)
    console.print()

    # ── 3. Temps quotidien ───────────────────────────────────────────────────
    console.print("[bold cyan]— 3 / 6  Emploi du temps quotidien (heures/jour)[/bold cyan]")
    afficher_separateur()

    h_travail = _saisir_flottant("  Heures de travail/jour", defaut=8.0)
    h_sommeil = _saisir_flottant("  Heures de sommeil/nuit", defaut=7.0)
    h_loisirs = _saisir_flottant("  Heures de loisirs/jour", defaut=2.0)
    h_transport = _saisir_flottant("  Heures de transport/jour", defaut=1.0)
    console.print()

    # ── 4. Auto-évaluations ──────────────────────────────────────────────────
    console.print("[bold cyan]— 4 / 6  Auto-évaluations (1 = très faible, 10 = excellent)[/bold cyan]")
    afficher_separateur()

    n_sante = _saisir_entier("  Niveau de santé", 1, 10, defaut=7)
    n_stress = _saisir_entier("  Niveau de stress (10 = très stressé)", 1, 10, defaut=5)
    n_energie = _saisir_entier("  Niveau d'énergie", 1, 10, defaut=7)
    n_bonheur = _saisir_entier("  Niveau de bonheur", 1, 10, defaut=7)
    console.print()

    # ── 5. Compétences ───────────────────────────────────────────────────────
    console.print("[bold cyan]— 5 / 6  Compétences et ressources[/bold cyan]")
    afficher_separateur()

    competences = _saisir_liste(
        "  Compétences clés", "Python, Marketing, Vente, Finance"
    )
    diplomes = _saisir_liste("  Diplômes", "Master Finance, BTS Commerce")
    langues = _saisir_liste("  Langues parlées", "Français, Anglais")
    console.print()

    # ── 6. Objectif principal ────────────────────────────────────────────────
    console.print("[bold cyan]— 6 / 6  Objectif de vie principal[/bold cyan]")
    afficher_separateur()

    objectif_desc = Prompt.ask(
        "  Décrivez votre objectif principal en une phrase",
        default="Devenir indépendant financièrement dans 10 ans",
    )
    categorie_obj = _choisir_dans_liste(
        "Catégorie de l'objectif", CATEGORIES_OBJECTIF
    )

    # Deadline optionnelle
    a_deadline = Confirm.ask("  Avez-vous une date limite pour cet objectif ?", default=False)
    deadline = None
    if a_deadline:
        while True:
            try:
                date_str = Prompt.ask(
                    "  Date limite (format JJ/MM/AAAA)",
                    default="01/01/2030",
                )
                deadline = datetime.strptime(date_str, "%d/%m/%Y")
                if deadline > datetime.now():
                    break
                console.print("  [red]La date doit être dans le futur.[/red]")
            except ValueError:
                console.print("  [red]Format invalide. Utilisez JJ/MM/AAAA.[/red]")

    objectif = Objectif(
        description=objectif_desc,
        categorie=categorie_obj,
        deadline=deadline,
    )

    # ── Assemblage du profil ─────────────────────────────────────────────────
    profil = ProfilUtilisateur(
        nom=nom,
        age=age,
        profession=profession,
        ville=ville,
        situation_familiale=situation_familiale,
        revenu_annuel=revenu_annuel,
        patrimoine_estime=patrimoine,
        charges_mensuelles=charges,
        heures_travail=h_travail,
        heures_sommeil=h_sommeil,
        heures_loisirs=h_loisirs,
        heures_transport=h_transport,
        niveau_sante=n_sante,
        niveau_stress=n_stress,
        niveau_energie=n_energie,
        niveau_bonheur=n_bonheur,
        competences=competences,
        diplomes=diplomes,
        langues=langues,
        objectif=objectif,
    )

    # ── Calcul de la probabilité initiale ────────────────────────────────────
    moteur = MoteurProbabilite()
    probabilite = moteur.calculer_probabilite_initiale(profil)
    profil.probabilite_actuelle = probabilite

    afficher_message_succes(
        f"Profil créé ! Probabilité initiale de réussite : [bold]{probabilite:.2f}%[/bold]"
    )
    console.input("\n  [dim]Appuyez sur Entrée pour continuer…[/dim]")
    return profil


def mettre_a_jour_profil_interactif(profil: ProfilUtilisateur) -> ProfilUtilisateur:
    """
    Interface de mise à jour partielle du profil.

    Permet à l'utilisateur de modifier uniquement les champs qui ont changé.

    Args:
        profil: ProfilUtilisateur existant à modifier

    Returns:
        ProfilUtilisateur mis à jour
    """
    console.clear()
    afficher_banniere()
    console.print(
        Panel(
            "  Mettez à jour les informations qui ont changé.\n"
            "  [dim]Appuyez sur Entrée pour conserver la valeur actuelle.[/dim]",
            title="[bold cyan]Mise à jour du profil[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print()

    sections = [
        "Auto-évaluations (santé, stress, énergie, bonheur)",
        "Données financières (revenu, charges)",
        "Emploi du temps (heures de travail, sommeil)",
        "Compétences et langues",
        "Objectif principal",
    ]
    section = _choisir_dans_liste("Quelle section mettre à jour ?", sections)

    if "évaluations" in section:
        profil.niveau_sante = _saisir_entier(
            "  Santé", 1, 10, defaut=profil.niveau_sante
        )
        profil.niveau_stress = _saisir_entier(
            "  Stress", 1, 10, defaut=profil.niveau_stress
        )
        profil.niveau_energie = _saisir_entier(
            "  Énergie", 1, 10, defaut=profil.niveau_energie
        )
        profil.niveau_bonheur = _saisir_entier(
            "  Bonheur", 1, 10, defaut=profil.niveau_bonheur
        )

    elif "financières" in section:
        profil.revenu_annuel = _saisir_flottant(
            "  Revenu annuel (€)", defaut=profil.revenu_annuel
        )
        profil.charges_mensuelles = _saisir_flottant(
            "  Charges mensuelles (€)", defaut=profil.charges_mensuelles
        )
        profil.patrimoine_estime = _saisir_flottant(
            "  Patrimoine estimé (€)", defaut=profil.patrimoine_estime
        )

    elif "emploi" in section:
        profil.heures_travail = _saisir_flottant(
            "  Heures de travail/jour", defaut=profil.heures_travail
        )
        profil.heures_sommeil = _saisir_flottant(
            "  Heures de sommeil/nuit", defaut=profil.heures_sommeil
        )

    elif "compétences" in section:
        profil.competences = _saisir_liste(
            "  Compétences", ", ".join(profil.competences)
        ) or profil.competences
        profil.langues = _saisir_liste(
            "  Langues", ", ".join(profil.langues)
        ) or profil.langues

    elif "objectif" in section:
        desc = Prompt.ask(
            "  Nouvel objectif",
            default=profil.objectif.description if profil.objectif else "",
        )
        cat = _choisir_dans_liste("Catégorie", CATEGORIES_OBJECTIF)
        profil.objectif = Objectif(description=desc, categorie=cat)
        # Recalculer la probabilité de base
        moteur = MoteurProbabilite()
        profil.probabilite_actuelle = moteur.calculer_probabilite_initiale(profil)

    profil.marquer_modification()
    afficher_message_succes("Profil mis à jour avec succès.")
    console.input("\n  [dim]Appuyez sur Entrée pour continuer…[/dim]")
    return profil
