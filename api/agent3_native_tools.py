"""
Agent 3 — Native Tool Calling + Agentic Loop.

Ce module remplace progressivement le parsing regex `[ACTION:X]{json}[/ACTION]`
par l'API tool calling native d'Anthropic, et enveloppe l'appel LLM dans une
boucle agentique multi-tours (tool_use -> executer -> tool_result -> LLM).

Objectifs :
  1. Supprimer les hallucinations d'actions (le LLM ne peut plus inventer d'actions,
     il doit passer par l'API structuree).
  2. Permettre l'iteration : le LLM observe le resultat de chaque outil et
     ajuste sa strategie, appelle d'autres outils, ou conclut.
  3. Remonter les erreurs au LLM (is_error=True) pour qu'il puisse reessayer
     ou changer d'approche.

Architecture :
  - `build_tool_schemas()` -> [tool_definition] pour `client.messages.create(tools=...)`
  - `AgenticLoop` -> classe qui orchestre la boucle LLM <-> tools
  - `ActionDispatcher` -> protocole que doit implementer tout executeur d'actions
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Protocol

logger = logging.getLogger("agent3.native_tools")


# ══════════════════════════════════════════════════════════════════════════════
# 1. Tool Schemas — mapping action_type -> Anthropic tool definition
# ══════════════════════════════════════════════════════════════════════════════

# Descriptions riches pour chaque outil. Le LLM choisit un outil en lisant ces
# descriptions, donc il faut etre precis sur quand chaque outil s'applique.
_TOOL_DESCRIPTIONS: dict[str, str] = {
    "SEARCH": "Recherche web generale via DuckDuckGo. Utilise pour actualites, "
              "informations factuelles, recherches rapides. Retourne une liste de resultats.",
    "X_SEARCH": "Recherche sur X/Twitter via xAI Grok. Utilise pour opinions, "
                "tendances, actualites en temps reel sur les reseaux sociaux.",
    "WEB_FETCH": "Recupere le contenu d'une URL specifique (HTML, markdown, JSON). "
                 "Utilise quand tu connais deja l'URL exacte a lire.",
    "MEMORY": "Sauvegarde une information importante pour s'en souvenir dans les "
              "sessions futures. Prend une cle semantique et une valeur.",
    "MEMORY_SEARCH": "Cherche dans la memoire long-terme de l'utilisateur par mot-cle.",
    "PDF": "Genere un rapport PDF structure avec titre et sections. Utilise pour "
           "rapports formels, documents a partager.",
    "IMAGE": "Genere une image via un modele de diffusion a partir d'un prompt textuel. "
             "Utilise pour illustrations, visualisations.",
    "EMAIL": "Envoie un email via SMTP ou Gmail API. ACTION DESTRUCTIVE. "
             "Utilise uniquement si l'utilisateur a explicitement demande d'envoyer un mail.",
    "GMAIL_SEND": "Envoie un email via l'API Gmail (OAuth). ACTION DESTRUCTIVE. "
                  "Preferable a EMAIL quand l'utilisateur est connecte a Gmail.",
    "GMAIL_READ": "Lit les emails recents de la boite Gmail de l'utilisateur.",
    "CALENDAR_EVENT": "Cree un evenement dans le calendrier Google. ACTION DESTRUCTIVE.",
    "CALENDAR_LIST": "Liste les prochains evenements du calendrier Google.",
    "FILE_CREATE": "Cree un fichier dans le workspace de l'utilisateur. ACTION DESTRUCTIVE "
                   "(ecrit sur disque). Le champ 'path' est relatif au workspace.",
    "FILE_READ": "Lit le contenu d'un fichier du workspace de l'utilisateur.",
    "DRIVE_SAVE": "Sauvegarde un fichier dans Google Drive. ACTION DESTRUCTIVE.",
    "CRON": "Cree une tache recurrente programmee. ACTION DESTRUCTIVE. "
            "Utilise uniquement pour automatiser une action future.",
    "CODE": "Genere et affiche un bloc de code avec coloration syntaxique. "
            "Pas d'execution — juste rendu pour l'utilisateur.",
    "COMPUTER_USE": "Controle autonome du navigateur via l'API Anthropic Computer Use. "
                    "ACTION DESTRUCTIVE ET COUTEUSE. Utilise UNIQUEMENT pour des taches "
                    "qui necessitent vraiment une navigation visuelle (formulaires "
                    "complexes, apps sans API, scraping avec interaction). Prompt descriptif "
                    "de l'objectif attendu.",
    "SCREENSHOT": "Prend une capture d'ecran d'une URL donnee. Utile pour apercu visuel "
                  "d'un site, extraction de mise en page.",
    "CANVAS": "Affiche un element interactif (graphique, diagramme, visualisation) dans "
              "le chat. Pas d'execution externe.",
    "SPAWN_AGENT": "Delegue une sous-tache a un agent enfant qui tourne en boucle "
                   "autonome avec ses propres outils (lecture seule). Utile pour "
                   "explorer un sujet sans polluer le contexte principal, ou paralleliser "
                   "plusieurs recherches. L'enfant retourne un resume textuel. Ne peut "
                   "pas utiliser d'actions destructives ni se re-spawn lui-meme.",
    "TODO_WRITE": "Cree ou met a jour une liste de taches (todos) partagee avec "
                  "l'utilisateur. A utiliser pour planifier et suivre l'execution "
                  "d'une demande multi-etapes (3+ etapes). Modes : "
                  "'create' (cree une liste), 'start' (passe un todo en running), "
                  "'complete' (marque un todo comme fait), 'fail' (marque comme echoue), "
                  "'skip' (marque comme saute), 'list' (retourne l'etat courant).",
}

# Mapping input schema par action_type. Base sur REQUIRED_FIELDS de ActionValidator
# mais enrichi (types precis, enums, champs optionnels utiles).
_INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "SEARCH": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Requete de recherche en langage naturel."},
            "max_results": {"type": "integer", "description": "Nombre max de resultats (1-10).", "default": 5},
        },
        "required": ["query"],
    },
    "X_SEARCH": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Requete X/Twitter. Ex: 'AI agents trends 2025'."},
        },
        "required": ["query"],
    },
    "WEB_FETCH": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL HTTP(S) complete a recuperer."},
        },
        "required": ["url"],
    },
    "MEMORY": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "Cle semantique courte, ex: 'preference_langue'."},
            "value": {"type": "string", "description": "Valeur a memoriser."},
        },
        "required": ["key", "value"],
    },
    "MEMORY_SEARCH": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Mot-cle ou phrase a chercher dans la memoire."},
        },
        "required": ["query"],
    },
    "PDF": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "sections": {
                "type": "array",
                "description": "Liste de sections {heading, content}.",
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["heading", "content"],
                },
            },
            "color": {"type": "string", "description": "Couleur primaire hex, ex: '#2563eb'.", "default": "#2563eb"},
        },
        "required": ["title", "sections"],
    },
    "IMAGE": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Description textuelle de l'image a generer."},
        },
        "required": ["prompt"],
    },
    "EMAIL": {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "Adresse email du destinataire."},
            "subject": {"type": "string"},
            "body": {"type": "string", "description": "Corps du message en texte brut."},
        },
        "required": ["to", "subject", "body"],
    },
    "GMAIL_SEND": {
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["to", "subject", "body"],
    },
    "GMAIL_READ": {
        "type": "object",
        "properties": {
            "mailbox": {"type": "string", "description": "Boite a lire.", "default": "INBOX"},
            "limit": {"type": "integer", "default": 10},
        },
        "required": [],
    },
    "CALENDAR_EVENT": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start": {"type": "string", "description": "ISO 8601 debut, ex: '2026-04-20T14:00:00'."},
            "end": {"type": "string", "description": "ISO 8601 fin (optionnel)."},
            "description": {"type": "string"},
        },
        "required": ["title", "start"],
    },
    "CALENDAR_LIST": {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "default": 7},
        },
        "required": [],
    },
    "FILE_CREATE": {
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "Nom de fichier avec extension, ex: 'rapport.md'."},
            "content": {"type": "string"},
            "path": {"type": "string", "description": "Chemin relatif optionnel dans le workspace."},
        },
        "required": ["filename", "content"],
    },
    "FILE_READ": {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
        },
        "required": ["filename"],
    },
    "DRIVE_SAVE": {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["filename", "content"],
    },
    "CRON": {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "instruction": {"type": "string", "description": "Instruction a executer lors du declenchement."},
            "cron_expr": {"type": "string", "description": "Expression cron standard a 5 champs."},
        },
        "required": ["label", "instruction", "cron_expr"],
    },
    "CODE": {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "language": {"type": "string", "default": "python"},
        },
        "required": ["content"],
    },
    "COMPUTER_USE": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Objectif en langage naturel pour le Computer Use agent."},
        },
        "required": ["prompt"],
    },
    "SCREENSHOT": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
        },
        "required": ["url"],
    },
    "CANVAS": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string", "description": "Markdown ou HTML du canvas."},
        },
        "required": ["title", "content"],
    },
    "SPAWN_AGENT": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Description courte de l'agent enfant (3-5 mots). Ex: 'Recherche concurrents IA'.",
            },
            "task": {
                "type": "string",
                "description": "Instruction detaillee que l'agent enfant doit accomplir. "
                               "Doit etre auto-suffisante : l'enfant n'a pas acces a la "
                               "conversation parente.",
            },
            "max_turns": {
                "type": "integer",
                "description": "Plafond de tours pour l'enfant (1-10).",
                "default": 5,
            },
            "tasks": {
                "type": "array",
                "description": "OPTIONNEL — liste de taches a executer EN PARALLELE via "
                               "plusieurs sous-agents independants. Chaque item: "
                               "{description, task, max_turns?}. Si fourni, les champs "
                               "description/task top-level sont ignores. Les resultats "
                               "sont agreges dans un seul tool_result.",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "task": {"type": "string"},
                        "max_turns": {"type": "integer", "default": 5},
                    },
                    "required": ["description", "task"],
                },
            },
        },
        "required": ["description", "task"],
    },
    "TODO_WRITE": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["create", "start", "complete", "fail", "skip", "list"],
                "description": "Operation a effectuer sur le tracker de todos.",
            },
            "items": {
                "type": "array",
                "description": "Pour 'create' : liste de {title, active_form, group}.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "active_form": {"type": "string"},
                        "group": {"type": "string"},
                    },
                    "required": ["title"],
                },
            },
            "item_id": {
                "type": "string",
                "description": "Id du todo cible pour start/complete/fail/skip.",
            },
            "result": {
                "type": "string",
                "description": "Resultat/commentaire pour complete/skip.",
            },
            "error": {
                "type": "string",
                "description": "Raison d'echec pour fail.",
            },
        },
        "required": ["mode"],
    },
}


def build_tool_schemas(enabled_actions: set[str] | None = None) -> list[dict[str, Any]]:
    """Construit la liste des tool definitions pour client.messages.create(tools=...).

    Args:
      enabled_actions: si fourni, filtre pour ne garder que ces action types.

    Returns:
      Liste de dicts {"name": str, "description": str, "input_schema": dict}
    """
    tools: list[dict[str, Any]] = []
    for action_type, schema in _INPUT_SCHEMAS.items():
        if enabled_actions is not None and action_type not in enabled_actions:
            continue
        description = _TOOL_DESCRIPTIONS.get(action_type, f"Action {action_type}.")
        # Les noms de tool Anthropic : [a-zA-Z0-9_-], max 64 chars.
        tool_name = action_type.lower()
        tools.append({
            "name": tool_name,
            "description": description,
            "input_schema": schema,
        })
    return tools


def tool_name_to_action_type(tool_name: str) -> str:
    """Convertit un tool_name (snake_case) en action_type (UPPER_SNAKE)."""
    return tool_name.upper()


# ══════════════════════════════════════════════════════════════════════════════
# Smart model routing — reduit les couts en choisissant Haiku pour les taches
# simples (lecture, recherche, classification) et Sonnet pour le raisonnement
# complexe (dilemmes, plans multi-etapes, generation de code).
# ══════════════════════════════════════════════════════════════════════════════

# Tarifs Anthropic (USD par million de tokens, maj avril 2026).
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # (input_usd_per_mtok, output_usd_per_mtok)
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-haiku-4-5-20250929": (1.0, 5.0),
    # Fallback par defaut : Sonnet 4.5 pricing
}

# Mots-cles qui SIGNALENT un besoin de raisonnement profond (=> Sonnet).
_COMPLEX_KEYWORDS = (
    "dilemm", "analyse", "analys", "raisonn", "plan ", "planifi",
    "strateg", "decision", "decid", "compar", "evalu", "reflechis",
    "pourquoi", "explique pourquoi", "code", "programme", "script",
    "algorithm", "pseudocode", "refactor", "architecture", "conception",
    "debug", "resoud", "demonstre", "prouve", "theoreme",
)

# Tool simples qui peuvent tourner sur Haiku sans perte de qualite notable.
_HAIKU_FRIENDLY_TOOLS = frozenset({
    "SEARCH", "WEB_FETCH", "FILE_READ", "MEMORY_SEARCH",
    "CALENDAR_LIST", "GMAIL_READ", "TODO_WRITE",
})


def pick_model_for_request(
    user_message: str,
    *,
    has_long_history: bool = False,
    thinking_enabled: bool = False,
    force_model: str | None = None,
) -> str:
    """Choisit le modele le moins cher capable de traiter la requete.

    Regles :
      - force_model != None -> retourne tel quel (override utilisateur).
      - thinking_enabled -> Sonnet (Haiku n'a pas extended thinking).
      - historique long (> N messages) -> Sonnet (contexte a tenir).
      - keyword complexe (dilemme/analyse/code/...) -> Sonnet.
      - message court sans keyword complexe -> Haiku 4.5.
      - defaut -> Haiku 4.5 (66% moins cher).

    Returns: model id Anthropic.
    """
    if force_model:
        return force_model

    sonnet = "claude-sonnet-4-5-20250929"
    haiku = "claude-haiku-4-5-20250929"

    if thinking_enabled:
        return sonnet
    if has_long_history:
        return sonnet

    msg_low = (user_message or "").lower()
    # Message long -> probablement complexe
    if len(msg_low) > 500:
        return sonnet
    # Keywords complexes
    if any(kw in msg_low for kw in _COMPLEX_KEYWORDS):
        return sonnet
    # Par defaut : Haiku (moins cher, rapide, suffit pour la majorite des tours)
    return haiku


def pricing_for_model(model: str) -> tuple[float, float]:
    """Retourne (input_usd_per_mtok, output_usd_per_mtok) pour un modele."""
    return MODEL_PRICING.get(model, (3.0, 15.0))


# ══════════════════════════════════════════════════════════════════════════════
# 2. Protocol pour l'executeur d'actions
# ══════════════════════════════════════════════════════════════════════════════


class ActionExecutor(Protocol):
    """Interface que doit implementer tout executeur d'actions.

    L'AgenticLoop appelle `execute(action_type, action_input)` pour chaque
    tool_use recu du LLM, et attend un dict resultat.

    Le resultat doit contenir :
      - `content`: str (ce que le LLM verra comme tool_result)
      - `is_error`: bool (True si l'action a echoue)
      - `raw`: Any (donnees arbitraires pour le frontend, pas vues par le LLM)
    """

    async def execute(self, action_type: str, action_input: dict) -> dict:
        ...


# ══════════════════════════════════════════════════════════════════════════════
# 3. Compaction automatique du contexte
# ══════════════════════════════════════════════════════════════════════════════


def compact_messages(
    messages: list[dict[str, Any]],
    keep_last_n: int = 4,
    max_tool_result_chars: int = 300,
) -> tuple[list[dict[str, Any]], int]:
    """Compresse les anciens tool_results volumineux pour reduire les tokens.

    Strategie sans casser la validite Anthropic :
      - Garde intactes les `keep_last_n` derniers messages de l'historique.
      - Pour les messages plus anciens, tronque le `content` de chaque bloc
        `tool_result` a `max_tool_result_chars` caracteres avec un marqueur
        "[...tronque par compaction...]".
      - Ne touche JAMAIS aux blocs `tool_use` (IDs et inputs preserves pour
        l'appairage tool_use ↔ tool_result).
      - Ne touche pas au texte assistant/user (souvent peu volumineux).

    Returns:
      (nouveaux_messages, chars_economises)
    """
    if len(messages) <= keep_last_n:
        return messages, 0

    cutoff = len(messages) - keep_last_n
    new_messages: list[dict[str, Any]] = []
    chars_saved = 0
    marker = "\n\n[...tronque par compaction...]"

    for idx, msg in enumerate(messages):
        if idx >= cutoff:
            new_messages.append(msg)
            continue

        content = msg.get("content")
        # content peut etre str (user messages simples) ou list (tool results, etc.)
        if isinstance(content, list):
            new_content: list[dict[str, Any]] = []
            for block in content:
                if (isinstance(block, dict)
                        and block.get("type") == "tool_result"):
                    raw_c = block.get("content", "")
                    if isinstance(raw_c, str) and len(raw_c) > max_tool_result_chars:
                        truncated = raw_c[:max_tool_result_chars] + marker
                        chars_saved += len(raw_c) - len(truncated)
                        new_block = dict(block)
                        new_block["content"] = truncated
                        new_content.append(new_block)
                    else:
                        new_content.append(block)
                else:
                    new_content.append(block)
            new_messages.append({"role": msg["role"], "content": new_content})
        else:
            new_messages.append(msg)

    return new_messages, chars_saved


# ══════════════════════════════════════════════════════════════════════════════
# 4. Boucle agentique
# ══════════════════════════════════════════════════════════════════════════════


@dataclass
class LoopEvent:
    """Event emis pendant la boucle agentique (pour SSE)."""
    type: str  # "turn_start" | "tool_use" | "tool_result" | "thinking" | "done" | "error"
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoopResult:
    """Resultat final d'une boucle agentique."""
    final_text: str
    turns: int
    actions_executed: list[dict[str, Any]]
    stop_reason: str
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    error: str | None = None


class AgenticLoop:
    """Boucle LLM <-> Tools a la Claude Code.

    Usage :
        loop = AgenticLoop(
            client=anthropic.AsyncAnthropic(...),
            system_prompt="...",
            tools=build_tool_schemas(),
            executor=my_executor,
            max_turns=15,
        )
        async for event in loop.run(user_message="...", history=[]):
            # forward en SSE
            ...
        final = loop.result
    """

    # Claude 4.5 family. Sonnet pour la qualite de raisonnement, Haiku pour
    # les petites taches. La facturation agentique peut etre elevee — on cap
    # a max_turns pour limiter l'explosion de cout.
    DEFAULT_MODEL = "claude-sonnet-4-5-20250929"
    DEFAULT_MAX_TOKENS = 4096
    DEFAULT_MAX_TURNS = 15

    # Actions qui modifient l'etat externe (envoi, ecriture, programmation) et
    # necessitent une confirmation explicite de l'utilisateur avant execution.
    DESTRUCTIVE_ACTIONS: set[str] = {
        "EMAIL", "GMAIL_SEND",
        "CALENDAR_EVENT",
        "FILE_CREATE",
        "DRIVE_SAVE",
        "CRON",
        "COMPUTER_USE",
    }

    def __init__(
        self,
        client: Any,  # anthropic.AsyncAnthropic
        system_prompt: str,
        tools: list[dict[str, Any]],
        executor: ActionExecutor,
        model: str | None = None,
        max_turns: int = DEFAULT_MAX_TURNS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        pre_approved_tool_ids: set[str] | None = None,
        auto_compact_threshold: int = 120_000,
        tool_timeout_s: float = 120.0,
        max_llm_retries: int = 3,
        retry_backoff_base_s: float = 1.5,
        stream: bool = False,
        thinking_enabled: bool = False,
        thinking_budget_tokens: int = 4000,
        cancel_event: Any = None,  # asyncio.Event | None
        hook_registry: Any = None,  # api.agent3_hooks.HookRegistry | None
        hook_user_id: str = "",
        hook_user_msg: str = "",
        hook_session_key: str = "",
        cache_tools: bool = True,
        interleaved_thinking: bool = False,
        cost_hard_cap_usd: float | None = None,
        input_usd_per_mtok: float = 3.0,     # Sonnet 4.5 pricing (avril 2026)
        output_usd_per_mtok: float = 15.0,
        event_logger: Any = None,  # Callable[[dict], None] | None — persist loop events
    ):
        self.client = client
        self.system_prompt = system_prompt
        self.tools = tools
        self.executor = executor
        self.model = model or self.DEFAULT_MODEL
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        # IDs de tool_use deja approuves par l'utilisateur (pour le resume apres
        # confirmation). Vide au premier appel ; rempli dans les reprises.
        self.pre_approved_tool_ids: set[str] = set(pre_approved_tool_ids or [])
        self.result: LoopResult | None = None
        # Etat de confirmation en attente (pour que le router puisse stocker la
        # session et la reprendre apres validation).
        self.pending_confirmation: dict[str, Any] | None = None
        # Seuil de tokens d'entree cumules au-dessus duquel la boucle compresse
        # les anciens tool_results volumineux pour eviter de saturer la fenetre
        # de contexte du modele (200k chez Claude Sonnet). 120k laisse ~80k de
        # marge pour la suite de la conversation.
        self.auto_compact_threshold = auto_compact_threshold
        self._compacted_once: bool = False
        # Plafond de temps pour un tool_use : au-dela, on injecte une erreur
        # artificielle ("tool timeout") pour que le LLM puisse pivoter sans
        # bloquer toute la boucle.
        self.tool_timeout_s = tool_timeout_s
        # Retry avec backoff exponentiel sur erreurs LLM transitoires (429, 500,
        # network). Evite d'abandonner la boucle sur un simple rate-limit.
        self.max_llm_retries = max_llm_retries
        self.retry_backoff_base_s = retry_backoff_base_s
        # Streaming : si True, la boucle emet des events `token_delta` (texte
        # partiel) et `thinking_delta` (raisonnement partiel) au fur et a mesure
        # que le LLM genere, au lieu d'attendre la reponse complete. L'UX s'en
        # trouve radicalement transformee (feedback immediat).
        self.stream = stream
        # Extended thinking : si True, le modele raisonne ~`thinking_budget_tokens`
        # tokens avant de repondre (blocs `thinking` serializes). Ideal pour les
        # dilemmes de vie ou la qualite du raisonnement compte plus que la
        # vitesse. Requis pour preserver les blocs thinking dans l'historique
        # assistant pour maintenir la continuite.
        self.thinking_enabled = thinking_enabled
        self.thinking_budget_tokens = thinking_budget_tokens
        # Interrupt : un asyncio.Event que l'appelant peut set() pour demander
        # l'arret immediat de la boucle. Verifie entre chaque tour et apres
        # chaque event de streaming.
        self.cancel_event = cancel_event
        # Hooks pre/post tool_use. Si fourni, chaque tool_use passe par
        # run_pre (peut MODIFY input ou BLOCK) et run_post (audit, enrichissement).
        self.hook_registry = hook_registry
        self.hook_user_id = hook_user_id
        self.hook_user_msg = hook_user_msg
        self.hook_session_key = hook_session_key
        # Cache prompt tools : ajoute cache_control: ephemeral sur la liste d'outils
        # pour eviter de les re-tokeniser a chaque tour. Gain : -30 a -50% sur
        # les sessions longues.
        self.cache_tools = cache_tools
        # Interleaved thinking : permet au modele de re-raisonner ENTRE les
        # tool_use au sein d'un meme tour. Necessite le beta header.
        self.interleaved_thinking = interleaved_thinking
        # Budget hard-cap : arret immediat de la boucle si le cout cumule
        # depasse ce seuil. Protege contre les runs cher qui tournent en
        # rond.
        self.cost_hard_cap_usd = cost_hard_cap_usd
        self.input_usd_per_mtok = input_usd_per_mtok
        self.output_usd_per_mtok = output_usd_per_mtok
        # Logger optionnel : callable invoque pour chaque LoopEvent emis.
        # Permet de persister les logs d'execution en DB pour replay / audit.
        self.event_logger = event_logger

    def _build_create_kwargs(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Construit les kwargs communs pour messages.create / messages.stream.

        Optimisations de coût/qualité :
          - cache_control ephemeral sur system_prompt (toujours)
          - cache_control ephemeral sur le dernier tool (caching de TOUTE la liste)
          - extra_headers: anthropic-beta pour interleaved-thinking si active
        """
        # Cache prompt tools : on met cache_control sur le DERNIER tool de la
        # liste. Anthropic met automatiquement en cache tout ce qui est AVANT
        # ce marqueur dans la sequence system + tools. Donc un seul marker
        # couvre la liste entiere.
        tools_list = self.tools
        if self.cache_tools and tools_list:
            # Shallow-copy pour ne pas muter l'objet partage (plusieurs AgenticLoop
            # peuvent reutiliser le meme self.tools).
            tools_list = [dict(t) for t in tools_list]
            tools_list[-1] = {**tools_list[-1], "cache_control": {"type": "ephemeral"}}

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            "messages": messages,
            "tools": tools_list,
        }
        if self.thinking_enabled:
            kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget_tokens,
            }
        # Interleaved thinking beta : permet des blocs `thinking` entre
        # plusieurs tool_use du meme tour, et entre tool_result et suite
        # de la generation. Qualite accrue sur les dilemmes multi-etapes.
        if self.thinking_enabled and self.interleaved_thinking:
            kwargs["extra_headers"] = {
                "anthropic-beta": "interleaved-thinking-2025-05-14",
            }
        return kwargs

    def _estimate_cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        """Coût estimé en USD pour (input, output) tokens. Base : tarifs Sonnet 4.5."""
        return (
            input_tokens * self.input_usd_per_mtok / 1_000_000.0
            + output_tokens * self.output_usd_per_mtok / 1_000_000.0
        )

    def _is_cost_exceeded(self, input_tokens: int, output_tokens: int) -> bool:
        """True si le cout cumule depasse le hard-cap (si defini)."""
        if self.cost_hard_cap_usd is None:
            return False
        return self._estimate_cost_usd(input_tokens, output_tokens) >= self.cost_hard_cap_usd

    def _log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Forward vers event_logger si configure (best-effort, swallow errors)."""
        if self.event_logger is None:
            return
        try:
            self.event_logger({"type": event_type, "data": data})
        except Exception as e:
            logger.debug(f"event_logger failed: {e}")

    async def _call_llm_with_retry(
        self,
        messages: list[dict[str, Any]],
        turn: int,
    ) -> Any:
        """Appelle messages.create avec retry exponentiel sur erreurs transitoires.

        Retry sur :
          - RateLimitError (HTTP 429)
          - APIError avec status 5xx
          - Timeout, connection errors (via classname heuristique)
        Propage immediatement les autres erreurs (authentication, bad request…).
        """
        import random
        last_exc: Exception | None = None
        for attempt in range(self.max_llm_retries + 1):
            try:
                return await self.client.messages.create(**self._build_create_kwargs(messages))
            except Exception as e:
                last_exc = e
                # Determine si l'erreur est transitoire
                cls_name = type(e).__name__.lower()
                status = getattr(e, "status_code", None) or getattr(e, "status", None)
                is_rate_limit = ("ratelimit" in cls_name) or status == 429
                is_server_err = isinstance(status, int) and 500 <= status < 600
                is_network = any(tok in cls_name for tok in (
                    "timeout", "connection", "network", "apiconnection",
                ))
                transient = is_rate_limit or is_server_err or is_network

                if not transient or attempt >= self.max_llm_retries:
                    raise

                # Backoff exponentiel avec jitter
                delay = self.retry_backoff_base_s * (2 ** attempt)
                delay += random.uniform(0, 0.5)
                logger.warning(
                    f"LLM transient error at turn {turn} attempt {attempt + 1}: "
                    f"{type(e).__name__} — retry in {delay:.1f}s"
                )
                await asyncio.sleep(delay)
        # Inatteignable mais rassurer le type checker
        raise last_exc  # type: ignore[misc]

    def _is_cancelled(self) -> bool:
        """Retourne True si l'appelant a demande l'arret de la boucle."""
        return bool(self.cancel_event is not None and self.cancel_event.is_set())

    async def _stream_llm_turn(
        self,
        messages: list[dict[str, Any]],
        turns: int,
    ) -> AsyncIterator[LoopEvent]:
        """Streame un tour LLM : yield `token_delta` pour chaque morceau de
        texte, `thinking_delta` pour chaque morceau de raisonnement. A la fin
        du stream, stocke le Message final dans `self._last_stream_response`
        (a consommer par run()).
        """
        self._last_stream_response = None
        try:
            stream_cm = self.client.messages.stream(**self._build_create_kwargs(messages))
        except Exception as e:
            # Propagation propre : run() le transformera en event 'error'.
            raise
        async with stream_cm as stream:
            async for event in stream:
                if self._is_cancelled():
                    yield LoopEvent("cancelled", {"turn": turns, "phase": "stream"})
                    return
                etype = getattr(event, "type", None)
                if etype != "content_block_delta":
                    continue
                delta = getattr(event, "delta", None)
                dtype = getattr(delta, "type", None) if delta is not None else None
                if dtype == "text_delta":
                    txt = getattr(delta, "text", "") or ""
                    if txt:
                        yield LoopEvent("token_delta", {"turn": turns, "text": txt})
                elif dtype == "thinking_delta":
                    tk = getattr(delta, "thinking", "") or ""
                    if tk:
                        yield LoopEvent("thinking_delta", {"turn": turns, "text": tk})
                elif dtype == "input_json_delta":
                    # Stream partiel des inputs de tool_use : l'UI peut afficher
                    # les parametres JSON se construire en live (meilleur UX,
                    # aucun impact cout). Le message final contient toujours
                    # l'input assemble valide.
                    partial = getattr(delta, "partial_json", "") or ""
                    idx = getattr(event, "index", None)
                    if partial:
                        yield LoopEvent("tool_input_delta", {
                            "turn": turns,
                            "block_index": idx,
                            "partial_json": partial,
                        })
            self._last_stream_response = await stream.get_final_message()

    async def _run_pre_hooks(
        self,
        action_type: str,
        action_input: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Applique la chaine pre-hook. Retourne (input_final, block_info_or_None).

        Si block_info est non None, la tool call doit etre court-circuitee avec
        un tool_result is_error=True dont le contenu est block_info["content"].
        """
        if self.hook_registry is None:
            return action_input, None
        try:
            pre_result = await self.hook_registry.run_pre(
                action_type=action_type,
                action_data=action_input,
                user_id=self.hook_user_id,
                user_msg=self.hook_user_msg,
                session_key=self.hook_session_key,
            )
        except Exception as e:
            logger.warning(f"Pre-hook chain failed for {action_type}: {e}")
            return action_input, None
        if pre_result is None:
            return action_input, None
        if getattr(pre_result, "blocked", False):
            reason = getattr(pre_result, "block_reason", "") or "politique interne"
            return action_input, {
                "content": f"Action bloquee par un hook : {reason}",
                "is_error": True,
                "raw": {
                    "hook_block": True,
                    "hook_name": getattr(pre_result, "hook_name", ""),
                },
                "_hook_name": getattr(pre_result, "hook_name", ""),
                "_reason": reason,
            }
        if getattr(pre_result, "modified", False) and getattr(pre_result, "modified_data", None):
            return pre_result.modified_data, None
        return action_input, None

    async def _run_post_hooks(
        self,
        action_type: str,
        action_input: dict[str, Any],
        exec_result: dict[str, Any],
    ) -> None:
        """Applique la chaine post-hook. N'altere pas exec_result (log/audit only)."""
        if self.hook_registry is None:
            return
        try:
            await self.hook_registry.run_post(
                action_type=action_type,
                action_data=action_input,
                execution_result=exec_result,
                user_id=self.hook_user_id,
                user_msg=self.hook_user_msg,
                session_key=self.hook_session_key,
            )
        except Exception as e:
            logger.warning(f"Post-hook chain failed for {action_type}: {e}")

    async def run(
        self,
        user_message: str,
        history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LoopEvent]:
        """Execute la boucle agentique. Yield des LoopEvent au fur et a mesure.

        history: liste de messages {role, content} au format Anthropic.
                 Sera completee avec user_message puis les echanges de la boucle.
        """
        messages: list[dict[str, Any]] = list(history or [])
        messages.append({"role": "user", "content": user_message})

        turns = 0
        actions_executed: list[dict[str, Any]] = []
        total_input = 0
        total_output = 0
        final_text = ""
        stop_reason = "unknown"
        error_msg: str | None = None

        try:
            while turns < self.max_turns:
                if self._is_cancelled():
                    stop_reason = "cancelled"
                    yield LoopEvent("cancelled", {"turn": turns, "phase": "between_turns"})
                    break
                turns += 1
                yield LoopEvent("turn_start", {"turn": turns})

                # Auto-compaction : si on approche du plafond de tokens du
                # modele, on compresse les anciens tool_results volumineux.
                # On ne le fait qu'une fois par run pour eviter de boucler.
                if (not self._compacted_once
                        and total_input >= self.auto_compact_threshold
                        and len(messages) > 6):
                    messages, chars_saved = compact_messages(
                        messages, keep_last_n=4, max_tool_result_chars=300,
                    )
                    self._compacted_once = True
                    yield LoopEvent("context_compacted", {
                        "turn": turns,
                        "chars_saved": chars_saved,
                        "threshold_tokens": self.auto_compact_threshold,
                        "total_input_tokens_at_trigger": total_input,
                    })

                t0 = time.perf_counter()
                cancelled_mid_stream = False
                try:
                    if self.stream:
                        async for sev in self._stream_llm_turn(messages, turns):
                            if sev.type == "cancelled":
                                cancelled_mid_stream = True
                            yield sev
                        response = self._last_stream_response
                        if cancelled_mid_stream or response is None:
                            stop_reason = "cancelled"
                            break
                    else:
                        response = await self._call_llm_with_retry(messages, turns)
                except Exception as e:
                    error_msg = f"LLM call failed at turn {turns}: {e}"
                    logger.exception(error_msg)
                    yield LoopEvent("error", {"message": error_msg, "turn": turns})
                    break

                dt = time.perf_counter() - t0
                total_input += getattr(response.usage, "input_tokens", 0)
                total_output += getattr(response.usage, "output_tokens", 0)
                stop_reason = response.stop_reason or "unknown"

                turn_done_data = {
                    "turn": turns,
                    "stop_reason": stop_reason,
                    "latency_ms": int(dt * 1000),
                    "input_tokens": getattr(response.usage, "input_tokens", 0),
                    "output_tokens": getattr(response.usage, "output_tokens", 0),
                    "cum_cost_usd": round(self._estimate_cost_usd(total_input, total_output), 4),
                }
                yield LoopEvent("turn_llm_done", turn_done_data)
                self._log_event("turn_llm_done", turn_done_data)

                # Hard cap de cout : si le cumule depasse le seuil, on arrete
                # immediatement. Emet un event explicite pour l'UI.
                if self._is_cost_exceeded(total_input, total_output):
                    cost = self._estimate_cost_usd(total_input, total_output)
                    cap_data = {
                        "turn": turns,
                        "cost_usd": round(cost, 4),
                        "cap_usd": self.cost_hard_cap_usd,
                        "total_input_tokens": total_input,
                        "total_output_tokens": total_output,
                    }
                    yield LoopEvent("cost_exceeded", cap_data)
                    self._log_event("cost_exceeded", cap_data)
                    stop_reason = "cost_exceeded"
                    error_msg = (
                        f"Budget cost hard-cap atteint: ${cost:.4f} >= "
                        f"${self.cost_hard_cap_usd:.4f}. Boucle arretee."
                    )
                    logger.warning(error_msg)
                    break

                # Collecter le texte et les tool_use du message assistant.
                assistant_content: list[dict[str, Any]] = []
                tool_uses: list[dict[str, Any]] = []
                turn_text_parts: list[str] = []

                for block in response.content:
                    btype = getattr(block, "type", None)
                    if btype == "thinking":
                        # Bloc de raisonnement (extended thinking). Doit etre
                        # preserve AVEC sa signature dans l'historique assistant
                        # pour que l'API Anthropic accepte les tours suivants.
                        thinking_text = getattr(block, "thinking", "") or ""
                        signature = getattr(block, "signature", "")
                        assistant_content.append({
                            "type": "thinking",
                            "thinking": thinking_text,
                            "signature": signature,
                        })
                        yield LoopEvent("thinking_block", {
                            "turn": turns,
                            "text": thinking_text,
                            "length": len(thinking_text),
                        })
                    elif btype == "text":
                        text = getattr(block, "text", "")
                        turn_text_parts.append(text)
                        assistant_content.append({"type": "text", "text": text})
                        if text.strip():
                            yield LoopEvent("thinking", {"text": text, "turn": turns})
                    elif btype == "tool_use":
                        tool_use_block = {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                        assistant_content.append(tool_use_block)
                        tool_uses.append(tool_use_block)

                # Ajouter le message assistant complet a l'historique.
                messages.append({"role": "assistant", "content": assistant_content})

                # Si pas de tool_use -> fin de boucle.
                if stop_reason != "tool_use" or not tool_uses:
                    final_text = "\n".join(p for p in turn_text_parts if p.strip())
                    break

                # Sinon, executer chaque tool_use et batcher les results.
                tool_results: list[dict[str, Any]] = []
                needs_confirmation_for: list[dict[str, Any]] = []
                for tu in tool_uses:
                    action_type = tool_name_to_action_type(tu["name"])
                    action_input = tu["input"] if isinstance(tu["input"], dict) else {}

                    yield LoopEvent("tool_use", {
                        "turn": turns,
                        "tool_use_id": tu["id"],
                        "name": tu["name"],
                        "action_type": action_type,
                        "input": action_input,
                    })

                    # Gate confirmation : action destructive non pre-approuvee -> on pause.
                    if (action_type in self.DESTRUCTIVE_ACTIONS
                            and tu["id"] not in self.pre_approved_tool_ids):
                        needs_confirmation_for.append({
                            "tool_use_id": tu["id"],
                            "name": tu["name"],
                            "action_type": action_type,
                            "input": action_input,
                        })
                        yield LoopEvent("confirmation_needed", {
                            "turn": turns,
                            "tool_use_id": tu["id"],
                            "name": tu["name"],
                            "action_type": action_type,
                            "input": action_input,
                            "reason": f"Action destructive ({action_type}) — confirmation utilisateur requise avant execution.",
                        })
                        continue  # on passe aux autres tool_uses, mais on stoppera la boucle apres

                    # Pre-hooks : possibilite de MODIFY ou BLOCK avant execution.
                    action_input, blocked = await self._run_pre_hooks(action_type, action_input)
                    if blocked is not None:
                        yield LoopEvent("hook_blocked", {
                            "turn": turns,
                            "tool_use_id": tu["id"],
                            "action_type": action_type,
                            "hook_name": blocked.get("_hook_name", ""),
                            "reason": blocked.get("_reason", ""),
                        })
                        exec_result = {
                            "content": blocked["content"],
                            "is_error": True,
                            "raw": blocked.get("raw", {}),
                        }
                        actions_executed.append({
                            "tool_use_id": tu["id"],
                            "action_type": action_type,
                            "input": action_input,
                            "result": exec_result,
                        })
                        yield LoopEvent("tool_result", {
                            "turn": turns,
                            "tool_use_id": tu["id"],
                            "action_type": action_type,
                            "is_error": True,
                            "content_preview": str(exec_result["content"])[:200],
                            "raw": exec_result.get("raw"),
                        })
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tu["id"],
                            "content": str(exec_result["content"]),
                            "is_error": True,
                        })
                        continue

                    try:
                        exec_result = await asyncio.wait_for(
                            self.executor.execute(action_type, action_input),
                            timeout=self.tool_timeout_s,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Tool {action_type} hit timeout after {self.tool_timeout_s}s"
                        )
                        exec_result = {
                            "content": (
                                f"L'outil '{action_type}' a depasse le delai de "
                                f"{int(self.tool_timeout_s)}s et a ete interrompu. "
                                "Propose une alternative ou un perimetre plus restreint."
                            ),
                            "is_error": True,
                            "raw": {"timeout_s": self.tool_timeout_s},
                        }
                    except Exception as e:
                        logger.exception(f"Executor crashed on {action_type}: {e}")
                        exec_result = {
                            "content": f"Erreur technique: {str(e)[:500]}",
                            "is_error": True,
                            "raw": {"exception": str(e)},
                        }

                    # Post-hooks : audit/log uniquement (ne modifie pas le resultat).
                    await self._run_post_hooks(action_type, action_input, exec_result)

                    actions_executed.append({
                        "tool_use_id": tu["id"],
                        "action_type": action_type,
                        "input": action_input,
                        "result": exec_result,
                    })

                    yield LoopEvent("tool_result", {
                        "turn": turns,
                        "tool_use_id": tu["id"],
                        "action_type": action_type,
                        "is_error": bool(exec_result.get("is_error")),
                        "content_preview": str(exec_result.get("content", ""))[:200],
                        "raw": exec_result.get("raw"),
                    })

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tu["id"],
                        "content": str(exec_result.get("content", "")),
                        "is_error": bool(exec_result.get("is_error", False)),
                    })

                # Si des tool_uses destructifs attendent confirmation, on arrete
                # la boucle ici. Le router va serialiser l'etat et attendre la
                # reponse de l'utilisateur avant de reprendre via /chat/native/resume.
                if needs_confirmation_for:
                    self.pending_confirmation = {
                        "messages": messages,  # inclut le assistant turn avec tool_use
                        "pending_tool_uses": needs_confirmation_for,
                        "already_executed_results": tool_results,  # tool_results des tool_uses non-destructifs deja faits ce tour
                        "turn": turns,
                        "actions_executed": actions_executed,
                        "total_input_tokens": total_input,
                        "total_output_tokens": total_output,
                    }
                    stop_reason = "awaiting_confirmation"
                    final_text = "\n".join(p for p in turn_text_parts if p.strip())
                    break

                # Feed tous les tool_results en un seul message user.
                messages.append({"role": "user", "content": tool_results})
            else:
                # max_turns atteint sans end_turn naturel.
                error_msg = f"Max turns ({self.max_turns}) atteint — boucle interrompue."
                logger.warning(error_msg)
                yield LoopEvent("error", {"message": error_msg})

        except Exception as e:
            error_msg = f"AgenticLoop crashed: {e}"
            logger.exception(error_msg)
            yield LoopEvent("error", {"message": error_msg})

        self.result = LoopResult(
            final_text=final_text,
            turns=turns,
            actions_executed=actions_executed,
            stop_reason=stop_reason,
            total_input_tokens=total_input,
            total_output_tokens=total_output,
            error=error_msg,
        )
        done_data = {
            "turns": turns,
            "actions_count": len(actions_executed),
            "input_tokens": total_input,
            "output_tokens": total_output,
            "final_text_preview": final_text[:200],
            "total_cost_usd": round(self._estimate_cost_usd(total_input, total_output), 4),
            "model": self.model,
            "error": error_msg,
        }
        yield LoopEvent("done", done_data)
        self._log_event("done", done_data)

    async def resume_from_confirmation(
        self,
        pending_state: dict[str, Any],
        approvals: dict[str, bool],
    ) -> AsyncIterator[LoopEvent]:
        """Reprend une boucle apres qu'un event `confirmation_needed` a ete leve.

        pending_state : le dict stocke dans self.pending_confirmation au pause.
        approvals : {tool_use_id: bool} — True approuve, False refuse.

        Pour chaque tool_use en attente :
          - approved=True  -> on execute l'action via l'executor
          - approved=False -> on emet un tool_result is_error=True expliquant le refus
        Puis on continue la boucle LLM<->tools normalement.
        """
        messages = [dict(m) for m in pending_state["messages"]]
        pending_uses = pending_state["pending_tool_uses"]
        already_executed = pending_state.get("already_executed_results", [])
        start_turn = pending_state["turn"]
        actions_executed: list[dict[str, Any]] = list(pending_state.get("actions_executed", []))
        total_input = pending_state.get("total_input_tokens", 0)
        total_output = pending_state.get("total_output_tokens", 0)

        # 1) Construire les tool_results pour chaque tool_use en attente.
        tool_results: list[dict[str, Any]] = list(already_executed)
        for tu in pending_uses:
            tu_id = tu["tool_use_id"]
            action_type = tu["action_type"]
            action_input = tu["input"]
            approved = bool(approvals.get(tu_id, False))

            if approved:
                try:
                    exec_result = await asyncio.wait_for(
                        self.executor.execute(action_type, action_input),
                        timeout=self.tool_timeout_s,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"Confirmed tool {action_type} hit timeout after {self.tool_timeout_s}s"
                    )
                    exec_result = {
                        "content": (
                            f"L'outil '{action_type}' a depasse le delai de "
                            f"{int(self.tool_timeout_s)}s et a ete interrompu."
                        ),
                        "is_error": True,
                        "raw": {"timeout_s": self.tool_timeout_s},
                    }
                except Exception as e:
                    logger.exception(f"Executor crashed on confirmed {action_type}: {e}")
                    exec_result = {
                        "content": f"Erreur technique: {str(e)[:500]}",
                        "is_error": True,
                        "raw": {"exception": str(e)},
                    }
                # Post-hooks (audit/log) apres execution destructive approuvee.
                await self._run_post_hooks(action_type, action_input, exec_result)
            else:
                exec_result = {
                    "content": f"L'utilisateur a refuse l'execution de {action_type}. "
                               f"Explique pourquoi tu voulais le faire et propose une alternative non destructive.",
                    "is_error": True,
                    "raw": {"user_denied": True},
                }

            actions_executed.append({
                "tool_use_id": tu_id,
                "action_type": action_type,
                "input": action_input,
                "result": exec_result,
                "user_approved": approved,
            })

            yield LoopEvent("tool_result", {
                "turn": start_turn,
                "tool_use_id": tu_id,
                "action_type": action_type,
                "is_error": bool(exec_result.get("is_error")),
                "content_preview": str(exec_result.get("content", ""))[:200],
                "raw": exec_result.get("raw"),
                "user_approved": approved,
            })

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu_id,
                "content": str(exec_result.get("content", "")),
                "is_error": bool(exec_result.get("is_error", False)),
            })

        # 2) Injecter tous les tool_results comme un seul message user.
        messages.append({"role": "user", "content": tool_results})

        # 3) Reset pending state — la confirmation est traitee.
        self.pending_confirmation = None

        # 4) Relancer la boucle principale a partir du tour suivant.
        turns = start_turn
        final_text = ""
        stop_reason = "unknown"
        error_msg: str | None = None

        try:
            while turns < self.max_turns:
                if self._is_cancelled():
                    stop_reason = "cancelled"
                    yield LoopEvent("cancelled", {"turn": turns, "phase": "between_turns"})
                    break
                turns += 1
                yield LoopEvent("turn_start", {"turn": turns})

                # Auto-compaction : si on approche du plafond de tokens du
                # modele, on compresse les anciens tool_results volumineux.
                # On ne le fait qu'une fois par run pour eviter de boucler.
                if (not self._compacted_once
                        and total_input >= self.auto_compact_threshold
                        and len(messages) > 6):
                    messages, chars_saved = compact_messages(
                        messages, keep_last_n=4, max_tool_result_chars=300,
                    )
                    self._compacted_once = True
                    yield LoopEvent("context_compacted", {
                        "turn": turns,
                        "chars_saved": chars_saved,
                        "threshold_tokens": self.auto_compact_threshold,
                        "total_input_tokens_at_trigger": total_input,
                    })

                t0 = time.perf_counter()
                cancelled_mid_stream = False
                try:
                    if self.stream:
                        async for sev in self._stream_llm_turn(messages, turns):
                            if sev.type == "cancelled":
                                cancelled_mid_stream = True
                            yield sev
                        response = self._last_stream_response
                        if cancelled_mid_stream or response is None:
                            stop_reason = "cancelled"
                            break
                    else:
                        response = await self._call_llm_with_retry(messages, turns)
                except Exception as e:
                    error_msg = f"LLM call failed at turn {turns}: {e}"
                    logger.exception(error_msg)
                    yield LoopEvent("error", {"message": error_msg, "turn": turns})
                    break

                dt = time.perf_counter() - t0
                total_input += getattr(response.usage, "input_tokens", 0)
                total_output += getattr(response.usage, "output_tokens", 0)
                stop_reason = response.stop_reason or "unknown"

                turn_done_data = {
                    "turn": turns,
                    "stop_reason": stop_reason,
                    "latency_ms": int(dt * 1000),
                    "input_tokens": getattr(response.usage, "input_tokens", 0),
                    "output_tokens": getattr(response.usage, "output_tokens", 0),
                    "cum_cost_usd": round(self._estimate_cost_usd(total_input, total_output), 4),
                }
                yield LoopEvent("turn_llm_done", turn_done_data)
                self._log_event("turn_llm_done", turn_done_data)

                if self._is_cost_exceeded(total_input, total_output):
                    cost = self._estimate_cost_usd(total_input, total_output)
                    cap_data = {
                        "turn": turns,
                        "cost_usd": round(cost, 4),
                        "cap_usd": self.cost_hard_cap_usd,
                        "total_input_tokens": total_input,
                        "total_output_tokens": total_output,
                    }
                    yield LoopEvent("cost_exceeded", cap_data)
                    self._log_event("cost_exceeded", cap_data)
                    stop_reason = "cost_exceeded"
                    error_msg = (
                        f"Budget cost hard-cap atteint: ${cost:.4f} >= "
                        f"${self.cost_hard_cap_usd:.4f}. Reprise interrompue."
                    )
                    logger.warning(error_msg)
                    break

                assistant_content: list[dict[str, Any]] = []
                tool_uses: list[dict[str, Any]] = []
                turn_text_parts: list[str] = []

                for block in response.content:
                    btype = getattr(block, "type", None)
                    if btype == "thinking":
                        # Bloc de raisonnement (extended thinking). Doit etre
                        # preserve AVEC sa signature dans l'historique assistant
                        # pour que l'API Anthropic accepte les tours suivants.
                        thinking_text = getattr(block, "thinking", "") or ""
                        signature = getattr(block, "signature", "")
                        assistant_content.append({
                            "type": "thinking",
                            "thinking": thinking_text,
                            "signature": signature,
                        })
                        yield LoopEvent("thinking_block", {
                            "turn": turns,
                            "text": thinking_text,
                            "length": len(thinking_text),
                        })
                    elif btype == "text":
                        text = getattr(block, "text", "")
                        turn_text_parts.append(text)
                        assistant_content.append({"type": "text", "text": text})
                        if text.strip():
                            yield LoopEvent("thinking", {"text": text, "turn": turns})
                    elif btype == "tool_use":
                        tool_use_block = {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                        assistant_content.append(tool_use_block)
                        tool_uses.append(tool_use_block)

                messages.append({"role": "assistant", "content": assistant_content})

                if stop_reason != "tool_use" or not tool_uses:
                    final_text = "\n".join(p for p in turn_text_parts if p.strip())
                    break

                # Nouveau batch de tool_uses -> on applique le meme gate que dans run().
                new_results: list[dict[str, Any]] = []
                needs_confirmation_for: list[dict[str, Any]] = []
                for tu in tool_uses:
                    action_type = tool_name_to_action_type(tu["name"])
                    action_input = tu["input"] if isinstance(tu["input"], dict) else {}

                    yield LoopEvent("tool_use", {
                        "turn": turns, "tool_use_id": tu["id"], "name": tu["name"],
                        "action_type": action_type, "input": action_input,
                    })

                    if (action_type in self.DESTRUCTIVE_ACTIONS
                            and tu["id"] not in self.pre_approved_tool_ids):
                        needs_confirmation_for.append({
                            "tool_use_id": tu["id"], "name": tu["name"],
                            "action_type": action_type, "input": action_input,
                        })
                        yield LoopEvent("confirmation_needed", {
                            "turn": turns, "tool_use_id": tu["id"], "name": tu["name"],
                            "action_type": action_type, "input": action_input,
                            "reason": f"Action destructive ({action_type}) — confirmation utilisateur requise.",
                        })
                        continue

                    # Pre-hooks (MODIFY / BLOCK) aussi cote resume.
                    action_input, blocked = await self._run_pre_hooks(action_type, action_input)
                    if blocked is not None:
                        yield LoopEvent("hook_blocked", {
                            "turn": turns, "tool_use_id": tu["id"],
                            "action_type": action_type,
                            "hook_name": blocked.get("_hook_name", ""),
                            "reason": blocked.get("_reason", ""),
                        })
                        exec_result = {
                            "content": blocked["content"], "is_error": True,
                            "raw": blocked.get("raw", {}),
                        }
                        actions_executed.append({
                            "tool_use_id": tu["id"], "action_type": action_type,
                            "input": action_input, "result": exec_result,
                        })
                        yield LoopEvent("tool_result", {
                            "turn": turns, "tool_use_id": tu["id"], "action_type": action_type,
                            "is_error": True,
                            "content_preview": str(exec_result["content"])[:200],
                            "raw": exec_result.get("raw"),
                        })
                        new_results.append({
                            "type": "tool_result", "tool_use_id": tu["id"],
                            "content": str(exec_result["content"]), "is_error": True,
                        })
                        continue

                    try:
                        exec_result = await asyncio.wait_for(
                            self.executor.execute(action_type, action_input),
                            timeout=self.tool_timeout_s,
                        )
                    except asyncio.TimeoutError:
                        logger.warning(
                            f"Tool {action_type} hit timeout after {self.tool_timeout_s}s (resume)"
                        )
                        exec_result = {
                            "content": f"L'outil '{action_type}' a depasse le delai de {int(self.tool_timeout_s)}s.",
                            "is_error": True,
                            "raw": {"timeout_s": self.tool_timeout_s},
                        }
                    except Exception as e:
                        logger.exception(f"Executor crashed on {action_type}: {e}")
                        exec_result = {"content": f"Erreur technique: {str(e)[:500]}", "is_error": True, "raw": {"exception": str(e)}}

                    await self._run_post_hooks(action_type, action_input, exec_result)

                    actions_executed.append({
                        "tool_use_id": tu["id"], "action_type": action_type,
                        "input": action_input, "result": exec_result,
                    })
                    yield LoopEvent("tool_result", {
                        "turn": turns, "tool_use_id": tu["id"], "action_type": action_type,
                        "is_error": bool(exec_result.get("is_error")),
                        "content_preview": str(exec_result.get("content", ""))[:200],
                        "raw": exec_result.get("raw"),
                    })
                    new_results.append({
                        "type": "tool_result", "tool_use_id": tu["id"],
                        "content": str(exec_result.get("content", "")),
                        "is_error": bool(exec_result.get("is_error", False)),
                    })

                if needs_confirmation_for:
                    self.pending_confirmation = {
                        "messages": messages, "pending_tool_uses": needs_confirmation_for,
                        "already_executed_results": new_results, "turn": turns,
                        "actions_executed": actions_executed,
                        "total_input_tokens": total_input, "total_output_tokens": total_output,
                    }
                    stop_reason = "awaiting_confirmation"
                    final_text = "\n".join(p for p in turn_text_parts if p.strip())
                    break

                messages.append({"role": "user", "content": new_results})
            else:
                error_msg = f"Max turns ({self.max_turns}) atteint — boucle interrompue."
                logger.warning(error_msg)
                yield LoopEvent("error", {"message": error_msg})

        except Exception as e:
            error_msg = f"AgenticLoop.resume crashed: {e}"
            logger.exception(error_msg)
            yield LoopEvent("error", {"message": error_msg})

        self.result = LoopResult(
            final_text=final_text, turns=turns, actions_executed=actions_executed,
            stop_reason=stop_reason, total_input_tokens=total_input,
            total_output_tokens=total_output, error=error_msg,
        )
        yield LoopEvent("done", {
            "turns": turns, "actions_count": len(actions_executed),
            "input_tokens": total_input, "output_tokens": total_output,
            "final_text_preview": final_text[:200], "error": error_msg,
        })


# ══════════════════════════════════════════════════════════════════════════════
# 4. Utilitaires de test
# ══════════════════════════════════════════════════════════════════════════════


class MockExecutor:
    """Executeur fake pour les tests — retourne ce qu'on lui dit."""

    def __init__(self, responses: dict[str, dict] | None = None):
        self.responses = responses or {}
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, action_type: str, action_input: dict) -> dict:
        self.calls.append((action_type, action_input))
        return self.responses.get(action_type, {
            "content": f"[mock] {action_type} executed",
            "is_error": False,
            "raw": {},
        })


__all__ = [
    "build_tool_schemas",
    "tool_name_to_action_type",
    "compact_messages",
    "ActionExecutor",
    "AgenticLoop",
    "LoopEvent",
    "LoopResult",
    "MockExecutor",
]
