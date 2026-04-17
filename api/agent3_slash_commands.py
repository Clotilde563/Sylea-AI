"""
Agent 3 — Slash Commands.

Parseur et registre de commandes /slash dans le chat.
L'utilisateur tape "/commande args" et le backend intercepte
AVANT d'envoyer au LLM.

Inspire des slash commands de Claude Code (/help, /clear, /compact, etc.).

Commands built-in :
  /help              — Liste des commandes disponibles
  /clear             — Efface l'historique de conversation
  /memory            — Affiche / recherche les memoires
  /memory clear      — Efface toutes les memoires
  /undo              — Annule la derniere action
  /undo history      — Affiche l'historique des actions annulables
  /skills            — Liste les skills disponibles
  /status            — Statut de l'agent (tokens, cout, uptime)
  /extract           — Force l'extraction de memoires
  /compact           — Force la compaction du contexte
  /cost              — Affiche le cout de la session
  /plan <task>       — Active le mode plan pour une tache
  /hooks             — Liste les hooks actifs
  /todo              — Affiche les todos en cours

Usage :
    parser = get_slash_parser()
    if parser.is_command(user_msg):
        result = await parser.execute(user_msg, context)
        # result.handled = True -> ne pas envoyer au LLM
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("sylea.agent3.slash_commands")


@dataclass
class SlashCommandResult:
    """Resultat d'une slash command."""

    handled: bool = True           # True = le message est traite, pas d'appel LLM
    response: str = ""             # Reponse a afficher a l'utilisateur
    data: dict = field(default_factory=dict)  # Donnees structurees
    error: str = ""
    actions: list[dict] = field(default_factory=list)  # Actions a executer cote frontend
    silent: bool = False           # True = pas de message affiche

    def to_dict(self) -> dict:
        return {
            "handled": self.handled,
            "response": self.response,
            "data": self.data,
            "error": self.error,
            "actions": self.actions,
        }


@dataclass
class SlashCommand:
    """Definition d'une slash command."""

    name: str                      # Sans le /  ("help", "clear", ...)
    description: str               # Description courte
    usage: str = ""                # Exemple d'usage ("/memory search <query>")
    handler: Optional[Callable] = None  # async fn(args: str, context: dict) -> SlashCommandResult
    aliases: list[str] = field(default_factory=list)
    hidden: bool = False           # True = pas listee dans /help
    category: str = "general"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "usage": self.usage or f"/{self.name}",
            "aliases": self.aliases,
            "category": self.category,
        }


class SlashCommandParser:
    """Parseur et registre de slash commands."""

    def __init__(self):
        self._commands: dict[str, SlashCommand] = {}
        self._aliases: dict[str, str] = {}  # alias -> command name

    def register(self, command: SlashCommand) -> None:
        self._commands[command.name] = command
        for alias in command.aliases:
            self._aliases[alias] = command.name
        logger.debug(f"Slash command registered: /{command.name}")

    def unregister(self, name: str) -> bool:
        cmd = self._commands.pop(name, None)
        if cmd:
            for alias in cmd.aliases:
                self._aliases.pop(alias, None)
            return True
        return False

    def is_command(self, text: str) -> bool:
        """Verifie si le texte commence par une commande valide."""
        text = text.strip()
        if not text.startswith("/"):
            return False
        cmd_name = text.split()[0][1:].lower()
        return cmd_name in self._commands or cmd_name in self._aliases

    def parse(self, text: str) -> tuple[Optional[SlashCommand], str]:
        """Parse le texte et retourne (command, args). None si pas une commande."""
        text = text.strip()
        if not text.startswith("/"):
            return None, text

        parts = text.split(maxsplit=1)
        cmd_name = parts[0][1:].lower()
        args = parts[1] if len(parts) > 1 else ""

        # Resoudre les aliases
        if cmd_name in self._aliases:
            cmd_name = self._aliases[cmd_name]

        cmd = self._commands.get(cmd_name)
        return cmd, args

    async def execute(self, text: str, context: Optional[dict] = None) -> SlashCommandResult:
        """Parse et execute une commande. Retourne le resultat."""
        cmd, args = self.parse(text)
        if not cmd:
            return SlashCommandResult(
                handled=False,
                response="",
            )
        if not cmd.handler:
            return SlashCommandResult(
                handled=True,
                error=f"Commande /{cmd.name} non implementee",
            )

        try:
            import asyncio
            if asyncio.iscoroutinefunction(cmd.handler):
                result = await cmd.handler(args, context or {})
            else:
                result = cmd.handler(args, context or {})
            if not isinstance(result, SlashCommandResult):
                result = SlashCommandResult(handled=True, response=str(result))
            return result
        except Exception as e:
            logger.error(f"Slash command /{cmd.name} failed: {e}")
            return SlashCommandResult(
                handled=True,
                error=f"Erreur : {e}",
            )

    def list_commands(self, include_hidden: bool = False) -> list[dict]:
        return [
            cmd.to_dict()
            for cmd in sorted(self._commands.values(), key=lambda c: c.name)
            if include_hidden or not cmd.hidden
        ]


# ── Built-in command handlers ──

def _help_handler(args: str, context: dict) -> SlashCommandResult:
    """Liste les commandes disponibles."""
    parser = get_slash_parser()
    commands = parser.list_commands()
    by_cat: dict[str, list] = {}
    for cmd in commands:
        by_cat.setdefault(cmd["category"], []).append(cmd)

    lines = ["**Commandes disponibles :**\n"]
    for cat, cmds in sorted(by_cat.items()):
        lines.append(f"**{cat.title()}**")
        for c in cmds:
            aliases = f" (alias: {', '.join(c['aliases'])})" if c.get("aliases") else ""
            lines.append(f"  `{c['usage']}` — {c['description']}{aliases}")
        lines.append("")
    return SlashCommandResult(handled=True, response="\n".join(lines))


async def _clear_handler(args: str, context: dict) -> SlashCommandResult:
    """Efface l'historique de conversation."""
    db = context.get("db")
    user_id = context.get("user_id", "")
    if db and user_id:
        from api.routers.agent3_openclaw import _clear_agent3_messages
        _clear_agent3_messages(db, user_id)
    return SlashCommandResult(
        handled=True,
        response="Historique efface.",
        actions=[{"type": "CLEAR_MESSAGES"}],
    )


async def _memory_handler(args: str, context: dict) -> SlashCommandResult:
    """Gestion des memoires."""
    db = context.get("db")
    user_id = context.get("user_id", "")
    if not db or not user_id:
        return SlashCommandResult(handled=True, error="Non authentifie")

    from api.routers.agent3_openclaw import _load_memories, _search_memories

    args = args.strip()

    if args == "clear":
        db.conn.execute("DELETE FROM agent3_memory WHERE auth_user_id = ?", (user_id,))
        db.conn.commit()
        return SlashCommandResult(handled=True, response="Toutes les memoires ont ete effacees.")

    if args.startswith("search "):
        query = args[7:].strip()
        results = _search_memories(db, user_id, query, top_k=10)
        if not results:
            return SlashCommandResult(handled=True, response=f"Aucun resultat pour '{query}'")
        lines = [f"**Resultats pour '{query}' :**"]
        for r in results:
            lines.append(f"  - [{r.category}] **{r.key}** : {r.value} (score: {r.score:.2f})")
        return SlashCommandResult(handled=True, response="\n".join(lines))

    # Par defaut : lister les memoires
    memories = _load_memories(db, user_id, limit=30)
    if not memories:
        return SlashCommandResult(handled=True, response="Aucune memoire enregistree.")
    lines = [f"**{len(memories)} memoire(s) :**"]
    by_cat: dict[str, list] = {}
    for m in memories:
        by_cat.setdefault(m["category"], []).append(m)
    for cat, mems in sorted(by_cat.items()):
        lines.append(f"\n**{cat}** ({len(mems)})")
        for m in mems[:10]:
            lines.append(f"  - `{m['key']}` : {m['value'][:80]}")
    return SlashCommandResult(handled=True, response="\n".join(lines))


async def _undo_handler(args: str, context: dict) -> SlashCommandResult:
    """Annulation de la derniere action."""
    user_id = context.get("user_id", "")
    db = context.get("db")
    if not user_id:
        return SlashCommandResult(handled=True, error="Non authentifie")

    from api.agent3_undo import get_undo_manager
    mgr = get_undo_manager(user_id, db)

    if args.strip() == "history":
        history = mgr.get_all_history(limit=15)
        if not history:
            return SlashCommandResult(handled=True, response="Aucun historique d'actions.")
        lines = ["**Historique des actions :**"]
        for h in history:
            status = "annule" if h["rolled_back"] else "actif"
            lines.append(f"  - [{status}] {h['description']} ({h['age_seconds']}s)")
        lines.append(f"\n{mgr.undoable_count} action(s) annulable(s)")
        return SlashCommandResult(handled=True, response="\n".join(lines))

    # Par defaut : annuler la derniere action
    success, msg = await mgr.undo_last()
    return SlashCommandResult(
        handled=True,
        response=msg,
        data={"success": success},
    )


async def _status_handler(args: str, context: dict) -> SlashCommandResult:
    """Statut de l'agent."""
    user_id = context.get("user_id", "")

    from api.agent3_cost_tracker import get_cost_tracker
    tracker = get_cost_tracker(user_id or "default")
    cost = tracker.get()

    from api.agent3_skills import get_skill_registry
    reg = get_skill_registry()

    from api.agent3_hooks import get_hook_registry
    hooks = get_hook_registry()

    lines = [
        "**Statut Agent 3 :**",
        f"  - Tokens : {cost['input_tokens']} in / {cost['output_tokens']} out",
        f"  - Cout session : ${cost['estimated_usd']:.4f}",
        f"  - Appels API : {cost['calls']}",
        f"  - Skills : {reg.count} chargees",
        f"  - Hooks : {hooks.count} actifs",
    ]
    return SlashCommandResult(handled=True, response="\n".join(lines))


async def _cost_handler(args: str, context: dict) -> SlashCommandResult:
    """Affiche le cout de la session."""
    user_id = context.get("user_id", "")
    from api.agent3_cost_tracker import get_cost_tracker
    tracker = get_cost_tracker(user_id or "default")
    cost = tracker.get()
    lines = [
        "**Cout de la session :**",
        f"  Total : **${cost['estimated_usd']:.4f}**",
        f"  Input : {cost['input_tokens']:,} tokens",
        f"  Output : {cost['output_tokens']:,} tokens",
        f"  Cache : {cost['cache_read_tokens']:,} tokens",
        f"  Appels : {cost['calls']}",
        f"  Duree : {cost['session_duration_seconds']}s",
    ]
    if cost.get("model_breakdown"):
        lines.append("\n  **Par modele :**")
        for model, stats in cost["model_breakdown"].items():
            lines.append(f"    - {model}: ${stats['usd']:.4f} ({stats['calls']} appels)")
    return SlashCommandResult(handled=True, response="\n".join(lines))


def _skills_handler(args: str, context: dict) -> SlashCommandResult:
    """Liste les skills internes + Computer Use + outils OpenClaw."""
    from api.agent3_skills import get_skill_registry
    from api.openclaw_bridge import ALL_OPENCLAW_TOOLS

    reg = get_skill_registry()
    internal_skills = reg.to_dict_list()

    # Computer Use : moteur autonome (api/computer_use.py) — pas un Skill interne
    # ni un outil OpenClaw, mais une capacite majeure qu'il faut exposer ici.
    computer_use_entries = [
        {
            "name": "computer_use",
            "group": "computer_use",
            "description": "Controle autonome du navigateur Chrome (clic, saisie, screenshots) via Anthropic Computer Use API. Utilise pour taches complexes : navigation, formulaires, scraping visuel.",
        },
    ]

    total = len(internal_skills) + len(computer_use_entries) + len(ALL_OPENCLAW_TOOLS)
    lines = [
        f"**{total} skill(s) / outil(s) disponible(s) :**",
        f"  {len(internal_skills)} skills internes + {len(computer_use_entries)} Computer Use + {len(ALL_OPENCLAW_TOOLS)} outils OpenClaw\n",
    ]

    # Skills internes
    if internal_skills:
        lines.append("**Skills internes**")
        for s in internal_skills:
            triggers = ", ".join(s.get("triggers", [])[:3])
            lines.append(f"  - **{s['name']}** [{s['category']}] — {s['description']}")
            if triggers:
                lines.append(f"    Triggers: {triggers}")
        lines.append("")

    # Computer Use
    lines.append("**Computer Use** (moteur autonome Anthropic)")
    for t in computer_use_entries:
        lines.append(f"  - **{t['name']}** — {t['description']}")
    lines.append("")

    # Outils OpenClaw par groupe
    by_group: dict[str, list] = {}
    for t in ALL_OPENCLAW_TOOLS:
        by_group.setdefault(t["group"], []).append(t)
    for group, tools in sorted(by_group.items()):
        lines.append(f"**OpenClaw — {group}** ({len(tools)})")
        for t in tools:
            lines.append(f"  - **{t['name']}** — {t['description']}")
        lines.append("")

    return SlashCommandResult(handled=True, response="\n".join(lines))


def _hooks_handler(args: str, context: dict) -> SlashCommandResult:
    """Liste les hooks."""
    from api.agent3_hooks import get_hook_registry
    reg = get_hook_registry()
    hooks = reg.list_hooks()
    lines = [f"**{len(hooks)} hook(s) actif(s) :**"]
    for h in hooks:
        status = "actif" if h["enabled"] else "inactif"
        lines.append(f"  - [{h['phase']}] **{h['name']}** ({h['action_pattern']}) — {status}, priorite {h['priority']}")
    return SlashCommandResult(handled=True, response="\n".join(lines))


async def _extract_handler(args: str, context: dict) -> SlashCommandResult:
    """Force l'extraction de memoires."""
    db = context.get("db")
    user_id = context.get("user_id", "")
    if not db or not user_id:
        return SlashCommandResult(handled=True, error="Non authentifie")

    from api.routers.agent3_openclaw import _auto_extract_memories, _load_agent3_messages
    recent = _load_agent3_messages(db, user_id, limit=20)
    turns = [
        {"role": m["role"], "content": m["content"]}
        for m in recent if m.get("content", "").strip()
    ]
    facts = await _auto_extract_memories(db, user_id, turns, force=True)
    if facts:
        lines = [f"**{len(facts)} fait(s) extrait(s) :**"]
        for f in facts:
            lines.append(f"  - [{f.category}] `{f.key}` : {f.value}")
        return SlashCommandResult(handled=True, response="\n".join(lines))
    return SlashCommandResult(handled=True, response="Aucun nouveau fait extrait.")


async def _todo_handler(args: str, context: dict) -> SlashCommandResult:
    """Affiche les todos en cours."""
    user_id = context.get("user_id", "")
    from api.agent3_todo_tracker import get_todo_tracker
    tracker = get_todo_tracker(user_id, create=False)
    if not tracker:
        return SlashCommandResult(handled=True, response="Aucun todo en cours.")
    summary = tracker.get_summary()
    lines = [f"**Todos ({summary['progress']:.0f}% complete) :**"]
    for item in summary["items"]:
        icon = {"pending": "⬜", "running": "🔄", "done": "✅", "failed": "❌", "skipped": "⏭️"}.get(item["status"], "?")
        lines.append(f"  {icon} {item['title']} ({item['status']})")
        if item.get("result"):
            lines.append(f"      → {item['result'][:80]}")
    return SlashCommandResult(handled=True, response="\n".join(lines))


# ── Registry singleton ──

_parser: Optional[SlashCommandParser] = None


def get_slash_parser() -> SlashCommandParser:
    """Retourne le parseur singleton avec les commandes built-in."""
    global _parser
    if _parser is None:
        _parser = SlashCommandParser()

        commands = [
            SlashCommand("help", "Liste des commandes disponibles", "/help", _help_handler, aliases=["h", "?"], category="general"),
            SlashCommand("clear", "Efface l'historique de conversation", "/clear", _clear_handler, aliases=["cls", "reset"], category="general"),
            SlashCommand("memory", "Affiche / recherche les memoires", "/memory [search <query>|clear]", _memory_handler, aliases=["mem"], category="memoire"),
            SlashCommand("undo", "Annule la derniere action", "/undo [history]", _undo_handler, category="actions"),
            SlashCommand("status", "Statut de l'agent", "/status", _status_handler, aliases=["stat"], category="info"),
            SlashCommand("cost", "Cout de la session", "/cost", _cost_handler, aliases=["$"], category="info"),
            SlashCommand("skills", "Liste les skills disponibles", "/skills", _skills_handler, category="info"),
            SlashCommand("hooks", "Liste les hooks actifs", "/hooks", _hooks_handler, category="info"),
            SlashCommand("extract", "Force l'extraction de memoires", "/extract", _extract_handler, category="memoire"),
            SlashCommand("todo", "Affiche les todos en cours", "/todo", _todo_handler, aliases=["todos"], category="actions"),
        ]
        for cmd in commands:
            _parser.register(cmd)

        logger.info(f"Slash command parser initialized with {len(commands)} commands")

    return _parser
