"""
Composants UI — Syléa.AI  Édition Luxe Futuriste.

Palette : argent platine (primaire), or (accents luxe), violet (UI chrome).
Inspiré du logo Syléa : spirale argentée dans des orbites, atome doré.
"""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.rule import Rule
from rich.align import Align
from rich.columns import Columns
from rich import box
from typing import List, Optional

console = Console()

# ── Palette Luxe Futuriste ────────────────────────────────────────────────────
C_ARGENT  = "bright_white"    # Argent platine — identité primaire
C_OR      = "gold1"           # Or             — accent luxe
C_VIOLET  = "medium_purple"   # Violet         — UI chrome futuriste
C_PLATINE = "grey82"          # Platine clair  — texte secondaire
C_MUTED   = "grey54"          # Gris moyen     — texte discret
C_SOMBRE  = "grey30"          # Gris foncé     — éléments décoratifs
C_SUCCES  = "bright_green"    # Vert           — positif / hausse
C_DANGER  = "bright_red"      # Rouge          — négatif / erreur
C_WARNING = "dark_orange"     # Orange         — avertissement
C_DATA    = "gold1"           # Or             — données clés

# Alias de compatibilité (utilisés dans les screens existants)
C_PRIMAIRE = C_VIOLET
C_ACCENT   = C_ARGENT
C_TITRE    = f"bold {C_ARGENT}"


# ── Splash ────────────────────────────────────────────────────────────────────

def afficher_splash() -> None:
    """Splash screen Luxe Futuriste — spirale argentée + atome doré."""
    console.print()
    console.print(Rule(style=C_VIOLET))
    console.print()

    def ligne(*parties):
        t = Text(justify="center")
        for texte, style in parties:
            t.append(texte, style=style)
        console.print(Align.center(t))

    # Logo : S-wave dans orbite argentée + atome moléculaire doré
    ligne(
        ("      ◦  ─  ○  ─  ◦   ", C_SOMBRE),
        ("            ─◈─", f"bold {C_OR}"),
    )
    ligne(
        ("    (    ╭─────╮    )  ", C_SOMBRE),
        ("          ─ ◉ ─", f"bold {C_OR}"),
    )
    ligne(
        ("   (    │ ", C_SOMBRE),
        ("≋  ≋  ≋", f"bold {C_ARGENT}"),
        ("  │    )  ", C_SOMBRE),
        ("            ─◈─", f"bold {C_OR}"),
    )
    ligne(
        ("   (    │ ", C_SOMBRE),
        ("≋≋≋≋≋≋", f"bold {C_ARGENT}"),
        ("  │    )", C_SOMBRE),
    )
    ligne(("    (    ╰─────╯    )", C_SOMBRE))
    ligne(("      ◦  ─  ○  ─  ◦", C_SOMBRE))

    console.print()

    # Wordmark
    brand = Text(justify="center")
    brand.append("  S  Y  L  É  A  ", style=f"bold {C_ARGENT}")
    brand.append("· A I\n", style=f"bold {C_OR}")
    brand.append(f"  {'─' * 24}\n", style=C_VIOLET)
    brand.append("  Votre assistant de vie augmenté\n\n", style=f"italic {C_PLATINE}")
    console.print(Align.center(brand))

    console.print(Rule(style=C_VIOLET))
    console.print()


# ── Jauge de probabilité ──────────────────────────────────────────────────────

def afficher_jauge_probabilite(
    prob: float,
    objectif: str,
    prob_avant: Optional[float] = None,
) -> None:
    """Jauge Luxe Futuriste — ━ plein vs ─ vide, couleur dynamique."""
    if prob >= 50:
        c_prob = C_SUCCES
    elif prob >= 20:
        c_prob = C_OR
    elif prob >= 5:
        c_prob = C_WARNING
    else:
        c_prob = C_DANGER

    nb = int(prob / 100 * 38)
    barre_pleine = "━" * nb
    barre_vide   = "─" * (38 - nb)

    delta_markup = ""
    if prob_avant is not None:
        delta = prob - prob_avant
        signe = "+" if delta >= 0 else ""
        c_d = C_SUCCES if delta >= 0 else C_DANGER
        delta_markup = f"  [{c_d}]{signe}{delta:.2f}%[/{c_d}]"

    corps = Text()
    corps.append(f"  {objectif[:60]}\n\n", style=f"italic {C_PLATINE}")
    corps.append("  ")
    corps.append(barre_pleine, style=f"bold {c_prob}")
    corps.append(barre_vide, style=C_SOMBRE)
    corps.append(f"  {prob:.2f}%", style=f"bold {c_prob}")
    if delta_markup:
        corps.append_text(Text.from_markup(delta_markup))
    corps.append("\n")

    console.print(
        Panel(
            corps,
            title=f"[bold {C_OR}] ◈  OBJECTIF [/]",
            border_style=C_VIOLET,
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )


# ── Titres de section ─────────────────────────────────────────────────────────

def afficher_titre_section(titre: str) -> None:
    """Titre de section — règle violette, texte argent."""
    console.print()
    console.print(Rule(title=f"[bold {C_ARGENT}]{titre}[/]", style=C_VIOLET))
    console.print()


# ── Messages système ──────────────────────────────────────────────────────────

def afficher_succes(message: str) -> None:
    console.print(f"[{C_SUCCES}]◆[/] [{C_ARGENT}]{message}[/]")


def afficher_erreur(message: str) -> None:
    console.print(f"[{C_DANGER}]![/] [{C_DANGER}]{message}[/]")


def afficher_info(message: str) -> None:
    console.print(f"[{C_VIOLET}]◈[/] {message}")


def afficher_avertissement(message: str) -> None:
    console.print(f"[{C_WARNING}]![/] [{C_WARNING}]{message}[/]")


# ── Saisies ───────────────────────────────────────────────────────────────────

def demander(invite: str, defaut: str = "") -> str:
    """Invite de saisie Luxe Futuriste."""
    defaut_affiche = f" [{C_SOMBRE}]({defaut})[/]" if defaut else ""
    console.print(
        f"[{C_OR}]◇[/] [{C_ARGENT}]{invite}[/]{defaut_affiche}",
        end=" ",
    )
    try:
        reponse = input().strip()
    except (KeyboardInterrupt, EOFError):
        return defaut
    return reponse if reponse else defaut


def demander_nombre(
    invite: str,
    min_val: float = None,
    max_val: float = None,
    defaut: float = None,
) -> float:
    """Demande un nombre valide avec validation."""
    while True:
        raw = demander(invite, str(defaut) if defaut is not None else "")
        try:
            val = float(raw.replace(",", ".").replace(" ", "").replace("\xa0", ""))
            if min_val is not None and val < min_val:
                afficher_erreur(f"Minimum : {min_val}")
                continue
            if max_val is not None and val > max_val:
                afficher_erreur(f"Maximum : {max_val}")
                continue
            return val
        except ValueError:
            afficher_erreur("Entrez un nombre valide.")


def demander_entier(
    invite: str,
    min_val: int = None,
    max_val: int = None,
    defaut: int = None,
) -> int:
    return int(demander_nombre(invite, min_val, max_val, defaut))


def choisir_dans_liste(invite: str, options: List[str]) -> str:
    """Menu numéroté Luxe Futuriste."""
    console.print()
    for i, opt in enumerate(options, 1):
        console.print(f"  [{C_VIOLET}]{i}[/]  [{C_ARGENT}]{opt}[/]")
    console.print()
    while True:
        raw = demander(f"{invite} (1-{len(options)})")
        try:
            idx = int(raw)
            if 1 <= idx <= len(options):
                return options[idx - 1]
            afficher_erreur(f"Entre 1 et {len(options)}.")
        except ValueError:
            afficher_erreur("Entrez un nombre.")


# ── Menu principal ────────────────────────────────────────────────────────────

def afficher_menu_principal(nom: str, prob: float, objectif: str) -> str:
    """Menu principal Luxe Futuriste — argent, or & violet."""
    from datetime import datetime
    date_str = datetime.now().strftime("%d %b %Y")

    console.print()
    padding = " " * max(1, 46 - len(nom) - len(date_str))
    console.print(f"  [{C_PLATINE}]{nom}[/]{padding}[{C_MUTED}]{date_str}[/]")
    console.print(f"  [{C_VIOLET}]{'─' * 46}[/]")
    console.print()

    items = [
        ("1", "Analyser un choix de vie", True),
        ("2", "Modifier mon profil",      False),
        ("3", "Changer d'objectif",       False),
        ("4", "Historique des décisions", False),
        ("5", "Quitter",                  False),
    ]

    for num, label, highlight in items:
        if highlight:
            console.print(f"  [{C_OR}]{num}[/]  [bold {C_ARGENT}]{label}[/]")
        else:
            console.print(f"  [{C_VIOLET}]{num}[/]  [{C_MUTED}]{label}[/]")

    console.print()
    choix_map = {
        "1": "analyser", "2": "profil", "3": "objectif",
        "4": "historique", "5": "quitter",
    }
    while True:
        raw = demander("Votre choix")
        if raw in choix_map:
            return choix_map[raw]
        afficher_erreur("Touche invalide (1-5).")


# ── Analyse d'option ──────────────────────────────────────────────────────────

def afficher_analyse_option(
    lettre: str,
    description: str,
    pros: List[str],
    cons: List[str],
    impact: float,
    couleur: str,
) -> None:
    """Affiche l'analyse comparative d'une option — Luxe Futuriste."""
    corps = Text()

    corps.append("Pour\n", style=f"bold {C_SUCCES}")
    for pro in pros:
        corps.append(f"  ◆ {pro}\n", style=C_ARGENT)

    corps.append(f"\nContre\n", style=f"bold {C_DANGER}")
    for con in cons:
        corps.append(f"  ◇ {con}\n", style=C_MUTED)

    signe = "+" if impact >= 0 else ""
    c_impact = C_SUCCES if impact >= 0 else C_DANGER
    corps.append(f"\nImpact sur la probabilité : ", style=C_MUTED)
    corps.append(f"{signe}{impact:.3f}%", style=f"bold {c_impact}")

    console.print(
        Panel(
            corps,
            title=f"[bold {C_OR}]Option {lettre}[/]  [{C_PLATINE}]{description[:50]}[/]",
            border_style=C_VIOLET,
            box=box.ROUNDED,
            padding=(0, 2),
        )
    )


# ── Spinner ───────────────────────────────────────────────────────────────────

def spinner(message: str):
    """Contexte spinner Luxe Futuriste."""
    return console.status(f"[{C_VIOLET}]{message}[/]", spinner="line")
