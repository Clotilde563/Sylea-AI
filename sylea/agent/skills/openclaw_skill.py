"""
Skill OpenClaw de l'agent Syléa.AI.

Capacités :
  - Identifier les requêtes qui relèvent des 25 tools OpenClaw Gateway
    (web_search, browser, exec, read/write files, sessions, memory, cron, etc.)
  - Guider l'utilisateur vers l'Agent 3 OpenClaw pour l'exécution réelle
  - Proposer le tool le plus adapté et sa syntaxe d'invocation

Architecture :
  Ce skill est un *redirecteur* déterministe. Il ne fait PAS d'appel HTTP
  direct au gateway OpenClaw (ce serait un import croisé api/ -> sylea/).
  L'exécution réelle se fait via l'Agent 3 (api/routers/agent3_openclaw.py)
  qui est le dispatcher autoritatif des tool_use natifs.

Le rôle du skill ici : détection précoce dans le pipeline classique de
AgentExecutant pour produire un rapport informatif quand l'utilisateur
formule une demande qui gagnerait à être exécutée via OpenClaw.
"""
from __future__ import annotations

from datetime import datetime

# ── Taxonomie des 25 outils OpenClaw Gateway ─────────────────────────────────

# Cette table miroir ALL_OPENCLAW_TOOLS de api/openclaw_bridge.py.
# Ne PAS importer api/ ici (respect des couches : sylea ne dépend pas d'api).

_TOOL_KEYWORDS: dict[str, tuple[str, ...]] = {
    # Web
    "web_search":       ("recherche web", "cherche sur le web", "google", "web"),
    "web_fetch":        ("récupère la page", "fetch url", "contenu de l'url"),
    "x_search":         ("twitter", " x.com", " x ", "tweet"),
    # UI
    "browser":          ("navigateur", "browser", "automatise le navigateur", "playwright"),
    "canvas":           ("canvas", "dessine", "génère une image vectorielle"),
    # Runtime
    "exec":             ("exécute la commande", "lance le programme", "run command"),
    "bash":             ("shell", "bash", "terminal"),
    "process":          ("process", "processus", "daemon"),
    # Filesystem
    "read":             ("lis le fichier", "contenu du fichier", "cat "),
    "write":            ("écris le fichier", "sauvegarde dans un fichier"),
    "edit":             ("édite le fichier", "modifie la ligne"),
    "apply_patch":      ("applique un patch", "diff", "patch"),
    # Sessions
    "sessions_spawn":   ("sub-agent", "sous-agent", "spawn session", "delègue à un autre agent"),
    "sessions_send":    ("envoie au sub-agent", "continue la session"),
    "sessions_list":    ("liste les sessions", "quelles sessions"),
    "sessions_history": ("historique des sessions", "session logs"),
    # Memory
    "memory_search":    ("mémoire openclaw", "cherche dans la mémoire", "souviens"),
    "memory_get":       ("récupère en mémoire", "get memory"),
    # Automation
    "cron":             ("cron", "planifie une tâche récurrente", "every day"),
    "gateway":          ("gateway openclaw", "statut du gateway"),
    # Messaging
    "message":          ("envoie un message openclaw",),
    # Special
    "image":            ("analyse cette image", "décris l'image"),
    "image_generate":   ("génère une image", "create image", "dall-e"),
    "llm_task":         ("délègue au llm", "llm task"),
    "lobster":          ("lobster", "🦞"),
    "subagents":        ("sous-agents", "multi-agent"),
}


class SkillOpenClaw:
    """
    Skill de routage vers OpenClaw Gateway.

    Détecte l'intention de l'utilisateur parmi les 25 tools OpenClaw et
    produit un rapport guidant vers l'Agent 3 pour l'exécution réelle.

    Exemple :
      Instruction : "Cherche sur le web les dernières nouvelles sur l'IA"
      -> Tool détecté : web_search
      -> Rapport : "Je recommande l'Agent 3 OpenClaw avec le tool web_search..."
    """

    description = (
        "Routage vers les 25 outils OpenClaw Gateway "
        "(web, fichiers, exécution, sessions, mémoire, cron)"
    )

    def executer(self, instruction: str) -> str:
        """
        Analyse l'instruction et produit un guide d'exécution via Agent 3.

        Args:
            instruction: Instruction validée

        Returns:
            Rapport textuel avec le tool recommandé et les prochaines étapes
        """
        tool_scores = self._scorer_tools(instruction)
        meilleur_tool, score = self._meilleur_tool(tool_scores)
        categorie = self._categoriser(meilleur_tool)

        lignes = [
            "RAPPORT OPENCLAW GATEWAY -- "
            f"{datetime.now().strftime('%d/%m/%Y a %H:%M')}",
            "=" * 55,
            "",
            f"  INSTRUCTION : {instruction[:200]}",
            f"  TOOL DETECTE: {meilleur_tool} (categorie: {categorie})",
            f"  CONFIANCE   : {score}/3",
            "",
            "-" * 55,
            "RECOMMANDATION",
            "-" * 55,
        ]

        if score == 0:
            lignes.extend([
                "Aucun tool OpenClaw evident. Suggestions :",
                "  - Reformule avec un verbe d'action (cherche, lis, execute, ecris)",
                "  - Precise si c'est du web, un fichier local, ou du code a executer",
                "",
                "Tools disponibles (25) : web_search, web_fetch, browser, exec,",
                "bash, read, write, edit, sessions_spawn, memory_search, cron,",
                "image_generate, ... (voir /api/agent3/capabilities).",
            ])
        else:
            lignes.extend([
                f"Pour executer cette instruction reellement, utilise l'Agent 3",
                f"OpenClaw qui dispatche automatiquement vers le tool '{meilleur_tool}'.",
                "",
                "Appel REST :",
                "  POST /api/agent3/chat/native",
                f"  {{ \"messages\": [{{\"role\":\"user\",\"content\":\"{instruction[:80]}\"}}] }}",
                "",
                "Ou depuis l'UI Syléa : Mes agents -> Agent 3 OpenClaw -> saisis ta demande.",
            ])

        lignes.extend([
            "",
            "-" * 55,
            "NOTE DE SECURITE",
            "-" * 55,
            "Les tools OpenClaw passent par le circuit breaker (failure_threshold=5,",
            "recovery_timeout=60s). Les actions destructives (write/delete/exec) ",
            "requierent confirmation explicite de l'utilisateur.",
        ])

        return "\n".join(lignes)

    # ── Méthodes internes ────────────────────────────────────────────────────

    @staticmethod
    def _scorer_tools(instruction: str) -> dict[str, int]:
        """Retourne un score (0+) par tool selon les mots-clés trouvés."""
        inst = instruction.lower()
        scores: dict[str, int] = {}
        for tool, keywords in _TOOL_KEYWORDS.items():
            scores[tool] = sum(1 for kw in keywords if kw in inst)
        return scores

    @staticmethod
    def _meilleur_tool(scores: dict[str, int]) -> tuple[str, int]:
        """Retourne le tool avec le plus haut score (tie-break alphabétique)."""
        if not scores:
            return ("web_search", 0)
        max_score = max(scores.values())
        if max_score == 0:
            return ("web_search", 0)  # fallback généraliste
        candidats = sorted(t for t, s in scores.items() if s == max_score)
        return (candidats[0], max_score)

    @staticmethod
    def _categoriser(tool: str) -> str:
        """Mappe un tool à sa catégorie (web/ui/runtime/fs/...)."""
        categories = {
            "web":        {"web_search", "web_fetch", "x_search"},
            "ui":         {"browser", "canvas"},
            "runtime":    {"exec", "bash", "process"},
            "fs":         {"read", "write", "edit", "apply_patch"},
            "sessions":   {"sessions_spawn", "sessions_send",
                           "sessions_list", "sessions_history"},
            "memory":     {"memory_search", "memory_get"},
            "automation": {"cron", "gateway"},
            "messaging":  {"message"},
            "special":    {"image", "image_generate", "llm_task",
                           "lobster", "subagents"},
        }
        for cat, tools in categories.items():
            if tool in tools:
                return cat
        return "unknown"
