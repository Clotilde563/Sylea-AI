"""
Skill ClawHub de l'agent Syléa.AI.

Capacités :
  - Détecter les demandes liées au marketplace ClawHub (recherche/installation
    de skills tiers, gestion des skills installées localement)
  - Produire un rapport guidant l'utilisateur vers la page /marketplace
    ou les endpoints REST /api/marketplace/*

Architecture :
  Skill *redirecteur* — ne fait pas d'appel HTTP direct au registry ClawHub
  (cela passe par api/clawhub.py via subprocess CLI). L'exécution réelle
  se fait via le router /api/marketplace/* qui wrappe clawhub_*.
"""
from __future__ import annotations

from datetime import datetime

# ── Taxonomie des actions marketplace ────────────────────────────────────────

_ACTIONS: dict[str, tuple[str, ...]] = {
    "search":    ("cherche un skill", "trouve un skill", "quel skill",
                  "marketplace clawhub", "marketplace", "existe-t-il un skill"),
    "install":   ("installe le skill", "ajoute le skill", "install skill",
                  "télécharge le skill"),
    "uninstall": ("désinstalle", "supprime le skill", "retire le skill",
                  "uninstall"),
    "list":      ("liste mes skills", "skills installés", "what skills"),
    "info":      ("détails du skill", "infos sur le skill", "skill info"),
    "publish":   ("publier mon skill", "publish skill", "partager mon skill",
                  "sylea sur clawhub", "publier sur clawhub"),
}


class SkillClawHub:
    """
    Skill de gestion du marketplace ClawHub.

    Détecte l'intention (search/install/uninstall/list/info/publish) et
    produit un rapport guidant vers la page /marketplace ou l'endpoint REST.

    Exemple :
      Instruction : "Cherche-moi un skill pour traduire des documents"
      -> Action détectée : search
      -> Rapport : "Utilise POST /api/marketplace/search avec query=..."
    """

    description = (
        "Gestion du marketplace ClawHub "
        "(recherche, installation, publication de skills tiers)"
    )

    def executer(self, instruction: str) -> str:
        """
        Analyse l'instruction et produit un guide d'utilisation du marketplace.

        Args:
            instruction: Instruction validée

        Returns:
            Rapport textuel avec l'action recommandée
        """
        action, score = self._detecter_action(instruction)
        query = self._extraire_query(instruction)

        lignes = [
            "RAPPORT CLAWHUB MARKETPLACE -- "
            f"{datetime.now().strftime('%d/%m/%Y a %H:%M')}",
            "=" * 55,
            "",
            f"  INSTRUCTION : {instruction[:200]}",
            f"  ACTION      : {action} (confiance: {score}/3)",
        ]
        if query and action == "search":
            lignes.append(f"  QUERY       : {query}")
        lignes.extend(["", "-" * 55, "COMMENT FAIRE", "-" * 55])

        if action == "search":
            lignes.extend([
                f"Recherche sur clawhub.ai (52 700+ skills communautaires) :",
                "",
                "  POST /api/marketplace/search",
                f'  {{ "query": "{query or "..."}", "limit": 20 }}',
                "",
                "Ou depuis l'UI : clique sur l'onglet 'Skills' du NavBar Syléa.",
            ])
        elif action == "install":
            lignes.extend([
                "Installation d'un skill dans ~/.openclaw/skills/<slug>/ :",
                "",
                "  POST /api/marketplace/install/<slug>",
                "",
                "Depuis l'UI : page /marketplace -> bouton 'Installer' sur la carte.",
                "Note : l'install declenche clawhub install <slug> en subprocess.",
            ])
        elif action == "uninstall":
            lignes.extend([
                "Desinstallation locale :",
                "",
                "  DELETE /api/marketplace/skill/<slug>",
                "",
                "Le skill est retire de ~/.openclaw/skills/ mais reste disponible",
                "sur le registry (re-install possible a tout moment).",
            ])
        elif action == "list":
            lignes.extend([
                "Liste des skills installees localement :",
                "",
                "  GET /api/marketplace/installed",
                "",
                "Ou : openclaw skills list (en ligne de commande).",
            ])
        elif action == "info":
            lignes.extend([
                "Details d'un skill particulier :",
                "",
                "  GET /api/marketplace/skill/<slug>",
                "",
                "Retourne : description complete, frontmatter YAML, fichiers inclus.",
            ])
        elif action == "publish":
            lignes.extend([
                "Pour publier ton propre skill sur ClawHub :",
                "",
                "  1. Prepare un dossier avec SKILL.md + README.md + LICENSE.md",
                "  2. Rends-toi sur https://clawhub.ai/publish-skill",
                "  3. Drag & drop le dossier, remplis le formulaire, Publish.",
                "",
                "Syléa elle-meme est deja publiee :",
                "  -> https://clawhub.ai/clotilde563/sylea",
            ])
        else:
            lignes.extend([
                "Action marketplace non identifiee. Reformule avec :",
                "  - 'cherche un skill pour ...' (search)",
                "  - 'installe le skill xyz' (install)",
                "  - 'desinstalle xyz' (uninstall)",
                "  - 'liste mes skills' (list)",
                "",
                "Endpoints disponibles : /api/marketplace/* (search, install,",
                "uninstall, installed, skill, check, featured).",
            ])

        lignes.extend([
            "",
            "-" * 55,
            "ECOSYSTEME",
            "-" * 55,
            "Syléa est une skill parmi 52 700+ sur ClawHub. La marketplace",
            "permet d'ajouter des skills tiers (traduction, code, design, etc.)",
            "qui s'executeront dans l'Agent 3 OpenClaw sans quitter Syléa.",
        ])

        return "\n".join(lignes)

    # ── Méthodes internes ────────────────────────────────────────────────────

    @staticmethod
    def _detecter_action(instruction: str) -> tuple[str, int]:
        """Retourne (action, score) la plus probable parmi _ACTIONS."""
        inst = instruction.lower()
        scores = {
            action: sum(1 for kw in keywords if kw in inst)
            for action, keywords in _ACTIONS.items()
        }
        max_score = max(scores.values()) if scores else 0
        if max_score == 0:
            return ("unknown", 0)
        # Priorité stable : search > install > list > info > uninstall > publish
        priority = ["search", "install", "list", "info", "uninstall", "publish"]
        for action in priority:
            if scores[action] == max_score:
                return (action, max_score)
        return ("search", max_score)

    @staticmethod
    def _extraire_query(instruction: str) -> str:
        """Extrait un terme de recherche probable depuis l'instruction."""
        inst = instruction.lower()
        # Heuristique simple : après "pour" ou "qui" ou "skill"
        for marker in (" pour ", " qui ", " skill ", " de "):
            if marker in inst:
                tail = inst.split(marker, 1)[1].strip()
                # Nettoyer ponctuation finale
                tail = tail.rstrip(".?!,;:")
                if tail:
                    return tail[:60]
        return ""
