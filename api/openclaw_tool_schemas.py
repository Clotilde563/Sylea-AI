"""
Agent 3 — Schemas Anthropic pour les 38 outils OpenClaw directs.

Expose chaque outil OpenClaw comme un tool Anthropic invocable directement par
le LLM d'Agent 3, au lieu de passer par skills ClawHub ou les handlers natifs.

Ces schemas sont injectes dans `build_tool_schemas()` quand la preference user
`openclaw_direct_tools_enabled` est True (opt-in). Le dispatcher route les
appels vers `openclaw_invoke_tool(name, action, args, session_key)`.

Design :
  - Input schema uniforme : `{action?: string, args?: object}`.
  - OpenClaw Gateway valide les `args` cote serveur (Pi framework), on ne
    duplique pas la validation ici.
  - La description LLM inclut des hints d'utilisation pour chaque tool —
    plus precis que le dict compact dans openclaw_bridge.py.

Prefixes :
  - `oc_` sur tous les tool names Anthropic pour eviter les collisions avec
    les actions natives (ex: `SEARCH`, `WEB_FETCH`, `MEMORY_SEARCH`...) qui
    partagent parfois un nom similaire.
"""

from __future__ import annotations

from typing import Any


# ─────────────────────────────────────────────────────────────────────────────
# Metadata des 38 outils : description riche + hints d'args pour le LLM.
# ─────────────────────────────────────────────────────────────────────────────

_OC_TOOL_META: list[dict[str, Any]] = [
    # ── group:web (9) ──────────────────────────────────────────────────────
    {
        "oc_name": "web_search",
        "group": "web",
        "description": (
            "OpenClaw web_search : recherche web via DuckDuckGo. "
            "Prefere SEARCH (native) sauf si tu veux controler `max_results` ou `locale`. "
            "args attendus : {query: string, max_results?: number, locale?: string}."
        ),
    },
    {
        "oc_name": "web_fetch",
        "group": "web",
        "description": (
            "OpenClaw web_fetch : recupere le contenu d'une URL (HTML/JSON/markdown). "
            "Prefere WEB_FETCH (native, SSRF-protege) sauf cas specifique. "
            "args : {url: string, headers?: object, timeout?: number}."
        ),
    },
    {
        "oc_name": "x_search",
        "group": "web",
        "description": (
            "OpenClaw x_search : recherche X/Twitter via xAI Grok. "
            "Prefere X_SEARCH (native). args : {query: string, limit?: number}."
        ),
    },
    {
        "oc_name": "firecrawl",
        "group": "web",
        "description": (
            "OpenClaw firecrawl : crawl multi-pages avec extraction structuree. "
            "Utilise pour scraper un site complet (docs, blog, e-commerce). "
            "args : {url: string, max_pages?: number, extraction_schema?: object}."
        ),
    },
    {
        "oc_name": "perplexity_search",
        "group": "web",
        "description": (
            "OpenClaw perplexity_search : recherche IA avec citations (Perplexity). "
            "Utilise pour questions factuelles complexes avec sources. "
            "args : {query: string, model?: 'sonar'|'sonar-pro', recency?: 'day'|'week'|'month'|'year'}."
        ),
    },
    {
        "oc_name": "brave_search",
        "group": "web",
        "description": (
            "OpenClaw brave_search : recherche privacy-first (Brave Search API). "
            "Alternative a google_search quand privacy ou rate-limits comptent. "
            "args : {query: string, count?: number, country?: string}."
        ),
    },
    {
        "oc_name": "google_search",
        "group": "web",
        "description": (
            "OpenClaw google_search : recherche Google (SerpAPI / Custom Search). "
            "Meilleure qualite pour requetes mainstream. "
            "args : {query: string, num?: number, site_filter?: string}."
        ),
    },
    {
        "oc_name": "tavily_search",
        "group": "web",
        "description": (
            "OpenClaw tavily_search : recherche agentic RAG optimisee (Tavily). "
            "Retourne des snippets longs pre-digeres pour les LLM. "
            "args : {query: string, search_depth?: 'basic'|'advanced', max_results?: number}."
        ),
    },
    {
        "oc_name": "exa_search",
        "group": "web",
        "description": (
            "OpenClaw exa_search : recherche neurale semantique (Exa / Metaphor). "
            "Meilleur pour requetes conceptuelles 'montre-moi des articles qui disent...'. "
            "args : {query: string, type?: 'neural'|'keyword', num_results?: number}."
        ),
    },

    # ── group:ui (2) ───────────────────────────────────────────────────────
    {
        "oc_name": "browser",
        "group": "ui",
        "description": (
            "OpenClaw browser : navigation web Chrome automatisee (Playwright). "
            "Screenshots, clics, formulaires, scraping dynamique. ACTION POTENTIELLEMENT "
            "DESTRUCTIVE. Prefere COMPUTER_USE (native) pour les workflows multi-etapes "
            "complexes necessitant du raisonnement visuel. "
            "args : {url: string, actions: [{type: 'click'|'fill'|'screenshot'|'extract', ...}]}."
        ),
    },
    {
        "oc_name": "canvas",
        "group": "ui",
        "description": (
            "OpenClaw canvas : generer une visualisation interactive (presentation, "
            "diagramme, graphique). Prefere CANVAS (native) pour un affichage simple dans le chat. "
            "args : {type: 'slides'|'diagram'|'chart', content: object}."
        ),
    },

    # ── group:runtime (3) — TOOLS SENSIBLES ────────────────────────────────
    {
        "oc_name": "exec",
        "group": "runtime",
        "description": (
            "[DERNIER RECOURS DESTRUCTIF] OpenClaw exec : executer une commande shell "
            "systeme one-shot. ACTION DESTRUCTIVE (acces complet OS, FS, reseau). "
            "Confirmation user obligatoire en mode permission=default. "
            "**NE PAS UTILISER pour du Python — utilise `python_exec` (sandbox Sylea safe).** "
            "**NE PAS UTILISER pour generer du code — utilise `code` (affichage).** "
            "Reserver a : pkg install, services systeme, scripts shell complexes, gestion "
            "fichiers OS, operations git/docker, etc. — quand AUCUN autre tool ne peut le faire. "
            "args : {command: string, cwd?: string, env?: object, timeout?: number}."
        ),
    },
    {
        "oc_name": "bash",
        "group": "runtime",
        "description": (
            "[DERNIER RECOURS DESTRUCTIF] OpenClaw bash : terminal bash interactif stateful "
            "(cwd, env, variables persistants entre commandes). ACTION DESTRUCTIVE. "
            "**NE PAS UTILISER pour Python (utilise `python_exec` safe sandbox).** "
            "Reserver a : workflows multi-commandes shell stateful, sequences de scripts. "
            "args : {commands: string[], session_id?: string}."
        ),
    },
    {
        "oc_name": "process",
        "group": "runtime",
        "description": (
            "OpenClaw process : lister / demarrer / arreter des processus systeme. "
            "ACTION DESTRUCTIVE en mode start/kill. "
            "args : {operation: 'list'|'start'|'kill'|'signal', pid?: number, command?: string}."
        ),
    },

    # ── group:fs (4) — FILESYSTEM LOCAL ────────────────────────────────────
    {
        "oc_name": "fs_read",
        "group": "fs",
        "description": (
            "OpenClaw fs.read : lire un fichier local. Prefere FILE_READ (native, "
            "confine au workspace user) sauf cas specifique hors workspace. "
            "args : {path: string, encoding?: string, offset?: number, limit?: number}."
        ),
    },
    {
        "oc_name": "fs_write",
        "group": "fs",
        "description": (
            "OpenClaw fs.write : ecrire un fichier local. ACTION DESTRUCTIVE (overwrite). "
            "Prefere FILE_CREATE (native, confine au workspace). "
            "args : {path: string, content: string, encoding?: string, append?: boolean}."
        ),
    },
    {
        "oc_name": "fs_edit",
        "group": "fs",
        "description": (
            "OpenClaw fs.edit : modifier un fichier existant par remplacement de chaine. "
            "ACTION DESTRUCTIVE. "
            "args : {path: string, old_string: string, new_string: string, replace_all?: boolean}."
        ),
    },
    {
        "oc_name": "fs_apply_patch",
        "group": "fs",
        "description": (
            "OpenClaw fs.apply_patch : appliquer un patch unified-diff. ACTION DESTRUCTIVE. "
            "args : {patch: string, base_path?: string}."
        ),
    },

    # ── group:sessions (4) — SUB-AGENTS AUTONOMES ──────────────────────────
    {
        "oc_name": "sessions_spawn",
        "group": "sessions",
        "description": (
            "OpenClaw sessions.spawn : lance un sous-agent autonome OpenClaw (budget + "
            "timeout). Alternative native : SPAWN_AGENT (AgenticLoop Anthropic enfant). "
            "args : {prompt: string, agent_type?: string, budget_usd?: number, timeout_s?: number}."
        ),
    },
    {
        "oc_name": "sessions_send",
        "group": "sessions",
        "description": (
            "OpenClaw sessions.send : envoie un message a une session existante (follow-up). "
            "args : {session_id: string, message: string}."
        ),
    },
    {
        "oc_name": "sessions_list",
        "group": "sessions",
        "description": (
            "OpenClaw sessions.list : liste les sessions OpenClaw actives. "
            "args : {} (aucun argument)."
        ),
    },
    {
        "oc_name": "sessions_history",
        "group": "sessions",
        "description": (
            "OpenClaw sessions.history : recupere l'historique complet d'une session. "
            "args : {session_id: string, limit?: number}."
        ),
    },

    # ── group:memory (2) ───────────────────────────────────────────────────
    {
        "oc_name": "oc_memory_search",
        "group": "memory",
        "description": (
            "OpenClaw memory_search : recherche dans la memoire long-terme OpenClaw. "
            "Complementaire a MEMORY_SEARCH (native, SQLite Sylea). "
            "args : {query: string, limit?: number, scope?: string}."
        ),
    },
    {
        "oc_name": "oc_memory_get",
        "group": "memory",
        "description": (
            "OpenClaw memory_get : recupere un souvenir OpenClaw par cle. "
            "args : {key: string, scope?: string}."
        ),
    },

    # ── group:automation (2) ───────────────────────────────────────────────
    {
        "oc_name": "oc_cron",
        "group": "automation",
        "description": (
            "OpenClaw cron : tache planifiee cote OpenClaw Gateway. Alternative native : "
            "CRON (stockage SQLite Sylea, reveil via scheduler local). "
            "args : {schedule: string, action: object, name?: string}."
        ),
    },
    {
        "oc_name": "gateway",
        "group": "automation",
        "description": (
            "OpenClaw gateway : controle du Gateway (reload config, status). "
            "args : {operation: 'status'|'reload'|'shutdown'}."
        ),
    },

    # ── group:messaging (1) ────────────────────────────────────────────────
    {
        "oc_name": "message",
        "group": "messaging",
        "description": (
            "OpenClaw message : envoyer un message multi-canal (WhatsApp/Slack/Discord/"
            "Telegram/iMessage/...) via les integrations du Gateway OpenClaw. "
            "ACTION DESTRUCTIVE visible par l'interlocuteur. "
            "args : {channel: string, recipient: string, content: string}."
        ),
    },

    # ── group:media (5) ────────────────────────────────────────────────────
    {
        "oc_name": "image",
        "group": "media",
        "description": (
            "OpenClaw image : analyse d'images (vision). Extraction de texte, description, "
            "detection d'objets. args : {image_url?: string, image_base64?: string, prompt: string}."
        ),
    },
    {
        "oc_name": "image_generate",
        "group": "media",
        "description": (
            "OpenClaw image_generate : genere ou edite une image (DALL-E 3 / SDXL). "
            "args : {prompt: string, size?: '1024x1024'|'1792x1024'|'1024x1792', style?: string}."
        ),
    },
    {
        "oc_name": "music_generate",
        "group": "media",
        "description": (
            "OpenClaw music_generate : genere une piste audio (Suno / MusicGen). "
            "args : {prompt: string, duration_s?: number, style?: string}."
        ),
    },
    {
        "oc_name": "video_generate",
        "group": "media",
        "description": (
            "OpenClaw video_generate : genere un clip video (Runway / Pika). "
            "args : {prompt: string, duration_s?: number, aspect_ratio?: '16:9'|'9:16'|'1:1'}."
        ),
    },
    {
        "oc_name": "voice_generate",
        "group": "media",
        "description": (
            "OpenClaw voice_generate : synthese vocale TTS (ElevenLabs / OpenAI TTS). "
            "args : {text: string, voice?: string, model?: string}."
        ),
    },

    # ── group:safety (3) ───────────────────────────────────────────────────
    {
        "oc_name": "content_moderation",
        "group": "safety",
        "description": (
            "OpenClaw content_moderation : detection toxicite/harm/violence (OpenAI Moderation). "
            "args : {content: string}."
        ),
    },
    {
        "oc_name": "url_safety_check",
        "group": "safety",
        "description": (
            "OpenClaw url_safety_check : verification phishing/malware (Google Safe Browsing). "
            "args : {url: string}."
        ),
    },
    {
        "oc_name": "pii_scrub",
        "group": "safety",
        "description": (
            "OpenClaw pii_scrub : detection + redaction PII (email, telephone, IBAN, etc.). "
            "args : {content: string, redact?: boolean}."
        ),
    },

    # ── special (3) ────────────────────────────────────────────────────────
    {
        "oc_name": "llm_task",
        "group": "special",
        "description": (
            "OpenClaw llm_task : delegue une sous-tache a un LLM (routing cout/capacite). "
            "args : {prompt: string, model?: string, max_tokens?: number}."
        ),
    },
    {
        "oc_name": "lobster",
        "group": "special",
        "description": (
            "OpenClaw lobster : moteur de workflows multi-etapes avec validations. "
            "args : {workflow: object}."
        ),
    },
    {
        "oc_name": "subagents",
        "group": "special",
        "description": (
            "OpenClaw subagents : orchestration multi-agents coordonnes. "
            "args : {task: string, agents: string[]}."
        ),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Derive mappings utilitaires.
# ─────────────────────────────────────────────────────────────────────────────

# Mapping nom_Anthropic (expose au LLM) -> nom_OpenClaw (envoye au Gateway).
# Certains outils ont un prefixe `oc_` pour eviter collision (ex: `oc_memory_search`
# vs `MEMORY_SEARCH` native) ou `fs_` (ex: `fs_read` vs le tool OpenClaw `read`).
_ANTHROPIC_TO_OPENCLAW: dict[str, str] = {
    "fs_read": "read",
    "fs_write": "write",
    "fs_edit": "edit",
    "fs_apply_patch": "apply_patch",
    "oc_memory_search": "memory_search",
    "oc_memory_get": "memory_get",
    "oc_cron": "cron",
    # Les autres ont le meme nom des deux cotes.
}


def openclaw_name_from_anthropic(anthropic_name: str) -> str:
    """Retourne le nom OpenClaw (Gateway) correspondant a un nom Anthropic."""
    return _ANTHROPIC_TO_OPENCLAW.get(anthropic_name, anthropic_name)


def all_anthropic_tool_names() -> set[str]:
    """Set des noms Anthropic exposes (le LLM reconnait ces tool_use)."""
    return {m["oc_name"] for m in _OC_TOOL_META}


def build_openclaw_tool_schemas(
    enabled_tools: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Construit les schemas Anthropic pour les 38 outils OpenClaw.

    Args:
        enabled_tools : si fourni, filtre pour ne garder que ces noms.
            Format : set de noms Anthropic (ex: {"browser", "fs_read"}).
            None = tous (38).

    Retourne : liste de tool schemas au format Anthropic.
    """
    schemas: list[dict[str, Any]] = []
    for meta in _OC_TOOL_META:
        name = meta["oc_name"]
        if enabled_tools is not None and name not in enabled_tools:
            continue
        schemas.append({
            "name": name,
            "description": meta["description"],
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "Sous-action OpenClaw. Defaut : 'default'. "
                            "Certains tools ont plusieurs actions (ex: browser 'click', 'screenshot')."
                        ),
                        "default": "default",
                    },
                    "args": {
                        "type": "object",
                        "description": (
                            "Arguments specifiques a ce tool. Voir la description pour les "
                            "champs attendus. OpenClaw validera le schema cote serveur."
                        ),
                        "additionalProperties": True,
                    },
                },
                "required": [],
            },
        })
    return schemas


# ─────────────────────────────────────────────────────────────────────────────
# Actions destructives (subset des 38).
# Utilise par AgenticLoop.DESTRUCTIVE_ACTIONS pour declencher la confirmation.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Pricing estime par outil OpenClaw (USD par invocation reussie).
#
# Valeurs indicatives basees sur les tarifs 2026 des APIs sous-jacentes :
#   - perplexity_search : $5 / 1000 queries = $0.005
#   - firecrawl         : $1 / 1000 pages    = $0.001 (page unique)
#   - image_generate    : DALL-E 3 standard  = $0.040
#   - music_generate    : Suno/MusicGen      = $0.100
#   - video_generate    : Runway/Pika        = $0.500
#   - voice_generate    : ElevenLabs short   = $0.010
#   - google_search     : SerpAPI            = $0.005
#   - brave_search      : Brave Search API   = $0.003
#   - exa_search        : Exa                = $0.005
#   - tavily_search     : Tavily             = $0.004
#   - web_search (DDG)  : gratuit            = $0.000
#   - web_fetch         : gratuit            = $0.000
#   - browser           : CPU Playwright     = $0.001 (estimation amortie)
#   - exec/bash/process : ressources locales = $0.000
#   - fs_*              : 0 (local)
#   - sessions_*        : dependant des tokens, pas ici
#   - memory_*, cron    : 0
#   - message           : dependant du canal (WhatsApp Business API est payant)
#   - safety tools      : generalement gratuit a ce volume
#   - special (llm_task, lobster, subagents) : variable
#
# Pour des tools a cout variable (selon taille output, duree, etc.), on met une
# estimation basse. Le vrai cout sera connu quand le Gateway retourne
# `cost_usd` dans le `result` (le shaper le captera) — ces prix sont un
# fallback si le Gateway ne remonte rien.
# ─────────────────────────────────────────────────────────────────────────────

OPENCLAW_TOOL_ESTIMATED_COST_USD: dict[str, float] = {
    # web (search APIs payantes)
    "perplexity_search": 0.005,
    "brave_search": 0.003,
    "google_search": 0.005,
    "tavily_search": 0.004,
    "exa_search": 0.005,
    "firecrawl": 0.001,
    # web gratuits
    "web_search": 0.0,
    "web_fetch": 0.0,
    "x_search": 0.0,
    # ui
    "browser": 0.001,
    "canvas": 0.0,
    # runtime (local)
    "exec": 0.0, "bash": 0.0, "process": 0.0,
    # fs (local)
    "fs_read": 0.0, "fs_write": 0.0, "fs_edit": 0.0, "fs_apply_patch": 0.0,
    # sessions (cout via tokens, pas ici)
    "sessions_spawn": 0.0, "sessions_send": 0.0,
    "sessions_list": 0.0, "sessions_history": 0.0,
    # memory / automation
    "oc_memory_search": 0.0, "oc_memory_get": 0.0,
    "oc_cron": 0.0, "gateway": 0.0,
    # messaging (variable selon canal — estimation moyenne faible)
    "message": 0.002,
    # media (generatifs — les vrais couts)
    "image": 0.0,               # vision = tokens input seulement
    "image_generate": 0.040,
    "music_generate": 0.100,
    "video_generate": 0.500,
    "voice_generate": 0.010,
    # safety
    "content_moderation": 0.0,
    "url_safety_check": 0.0,
    "pii_scrub": 0.0,
    # special
    "llm_task": 0.005, "lobster": 0.0, "subagents": 0.0,
}


def estimate_tool_cost_usd(anthropic_tool_name: str, result: Any = None) -> float:
    """Estime le cout en USD d'un appel reussi a un tool OpenClaw.

    Si le Gateway a retourne un `cost_usd` dans son result, on l'utilise
    (valeur reelle). Sinon, on fallback sur l'estimation statique du dict.
    """
    # 1) Priorite : valeur reelle retournee par le Gateway (via shaper).
    if isinstance(result, dict):
        real = result.get("cost_usd")
        if isinstance(real, (int, float)) and real >= 0:
            return float(real)
    # 2) Fallback : estimation statique.
    return OPENCLAW_TOOL_ESTIMATED_COST_USD.get(anthropic_tool_name, 0.0)


DESTRUCTIVE_OPENCLAW_TOOLS: set[str] = {
    # Runtime (execution code)
    "exec", "bash", "process",
    # Filesystem (writes)
    "fs_write", "fs_edit", "fs_apply_patch",
    # Browser (peut soumettre des formulaires)
    "browser",
    # Messaging (visible par tiers)
    "message",
    # Media (generation coute, parfois irreversible)
    "image_generate", "music_generate", "video_generate",
    # Automation (programmation)
    "oc_cron", "gateway",
    # Sub-agents (spawn = budget)
    "sessions_spawn",
}


__all__ = [
    "build_openclaw_tool_schemas",
    "openclaw_name_from_anthropic",
    "all_anthropic_tool_names",
    "DESTRUCTIVE_OPENCLAW_TOOLS",
    "OPENCLAW_TOOL_ESTIMATED_COST_USD",
    "estimate_tool_cost_usd",
]
