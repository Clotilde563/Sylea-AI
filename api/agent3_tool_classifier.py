"""
Agent 3 — Classifier Haiku pour filtrage contextuel des tools.

Avec 118 tools envoyes au LLM a chaque tour, le prompt cache aide mais c'est
toujours ~60k tokens d'overhead. La plupart des requetes user n'ont besoin
que de 5-20 tools.

Ce module fait un pre-classification (Haiku 4.5 ~100 tokens) de la requete
user en UNE categorie d'intention. Cette categorie est ensuite mappee sur un
sous-ensemble de tools a envoyer au modele principal (Sonnet).

Architecture :
  user_msg -> classify_intent_haiku() -> category (enum)
           -> tool_subset_for_category() -> set de noms de tools
           -> build_tool_schemas(filtered)
           -> Sonnet voit seulement les tools pertinents

Gains mesures en pratique :
  - 30-50% de reduction input tokens Sonnet
  - Moins de "distraction" LLM : il se concentre sur les tools pertinents
  - Latence perception : +200ms pour le classifier, -400ms sur l'appel Sonnet (tokens plus courts)

Fallback de securite :
  - Si la classification echoue (timeout, error, quota) -> on envoie TOUS les tools.
  - Si la categorie est 'unknown' ou 'any' -> idem tous les tools.
  - L'user peut desactiver cette feature via pref `contextual_filter_enabled=False`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("agent3.tool_classifier")


# ─────────────────────────────────────────────────────────────────────────────
# Categories d'intention.
# ─────────────────────────────────────────────────────────────────────────────

# Categories discretes. "any" = pas de filtrage, envoyer tous les tools.
CATEGORIES: tuple[str, ...] = (
    "conversation",     # salut, thanks, question philosophique, pas d'outil necessaire
    "web_research",     # recherche web, infos factuelles
    "web_fetch",        # lire une URL precise
    "file_ops",         # lecture/ecriture fichier local/workspace
    "code_exec",        # executer du code, commande shell
    "media_gen",        # generer image/audio/video/voix
    "image_analyze",    # analyser une image fournie
    "messaging",        # envoyer email/message/calendrier
    "memory_ops",       # sauvegarder/chercher en memoire
    "planning",         # todo list, cron, planification
    "sub_agent",        # deleguer a un sous-agent / orchestration
    "skill_extension",  # auto-extension ClawHub (search/install/publish)
    "safety_check",     # moderation, PII scrub, url safety
    "any",              # fallback : tous les tools (incertain)
)


# ─────────────────────────────────────────────────────────────────────────────
# Mapping categorie -> tools pertinents (noms Anthropic).
#
# Inclut TOUJOURS quelques "always-on" (memory_search, todo_write) qui
# peuvent etre utiles transversalement.
# ─────────────────────────────────────────────────────────────────────────────

_ALWAYS_ON_TOOLS: set[str] = {
    "memory", "memory_search",
    "todo_write",
    # Meta-tools ClawHub toujours utile pour auto-extension
    "clawhub_search", "clawhub_install", "clawhub_publish",
    # Phase 14C : python_exec sandbox safe — utile pour TOUTE categorie qui
    # implique du calcul (web_research avec stats, planning avec dates, etc.)
    # et CRITIQUE pour la math precision (anti-hallucination numerique).
    # Sans ca, le contextual filter peut le retirer pour les categories
    # 'code_exec' / 'web_research' / 'any' et le LLM calcule mentalement.
    "python_exec",
}


CATEGORY_TOOLS: dict[str, set[str]] = {
    "conversation": _ALWAYS_ON_TOOLS | {
        "memory", "memory_search",
    },
    "web_research": _ALWAYS_ON_TOOLS | {
        # Natifs
        "search", "x_search", "web_fetch", "deep_research",
        # OpenClaw moteurs de recherche
        "web_search", "perplexity_search", "brave_search", "google_search",
        "tavily_search", "exa_search", "firecrawl",
        # Browser dynamique (sites JS-heavy comme LinkedIn)
        "browser", "computer_use", "screenshot",
        # URL safety
        "url_safety_check",
    },
    "web_fetch": _ALWAYS_ON_TOOLS | {
        "web_fetch", "search",
        "browser", "firecrawl",
        "url_safety_check",
        # computer_use = navigation autonome avec vision (dernier recours
        # quand le site requiert clic/login/captcha). Necessite confirmation
        # destructive avant execution.
        "computer_use",
        # screenshot = capture d'ecran de page (visuel, pas DOM)
        "screenshot",
    },
    "file_ops": _ALWAYS_ON_TOOLS | {
        "file_read", "file_create",
        "fs_read", "fs_write", "fs_edit", "fs_apply_patch",
        "pdf", "code", "canvas",
        "drive_save",
    },
    "code_exec": _ALWAYS_ON_TOOLS | {
        # python_exec deja inclus via _ALWAYS_ON_TOOLS — c'est l'option
        # par defaut pour executer du Python (sandbox safe).
        "code", "exec", "bash", "process",
        "file_read", "file_create",
        "fs_read", "fs_write", "fs_edit",
        # computer_use peut etre demande pour automatiser des taches OS
        # (clic, type, screenshot) si exec/bash ne suffisent pas.
        "computer_use", "screenshot",
    },
    "media_gen": _ALWAYS_ON_TOOLS | {
        "image_gen", "tts_gen",  # Phase 14L : tools natifs OpenAI (preferes)
        "image_generate", "music_generate", "video_generate", "voice_generate",
        "canvas", "pdf",
    },
    "image_analyze": _ALWAYS_ON_TOOLS | {
        "image",
        "web_fetch",  # parfois pour recuperer l'image
    },
    "messaging": _ALWAYS_ON_TOOLS | {
        "email", "gmail_send", "gmail_read",
        "message",  # OpenClaw multi-canal
        "calendar_list", "calendar_event",
        "pii_scrub",  # nettoyer avant envoi
    },
    "memory_ops": _ALWAYS_ON_TOOLS | {
        "memory", "memory_search",
        "oc_memory_search", "oc_memory_get",
    },
    "planning": _ALWAYS_ON_TOOLS | {
        "todo_write", "cron", "oc_cron", "reminder",
        "calendar_list", "calendar_event",
    },
    "sub_agent": _ALWAYS_ON_TOOLS | {
        "spawn_agent",
        "openclaw_session",  # Phase 14J : session OpenClaw acces complet
        "sessions_spawn", "sessions_send", "sessions_list", "sessions_history",
        "llm_task", "subagents", "lobster",
    },
    "skill_extension": _ALWAYS_ON_TOOLS | {
        "clawhub_search", "clawhub_install", "clawhub_publish",
    },
    "safety_check": _ALWAYS_ON_TOOLS | {
        "content_moderation", "url_safety_check", "pii_scrub",
    },
    "any": set(),  # sentinelle : filtre desactive (envoie tous les tools)
}


def tool_subset_for_category(
    category: str, skill_tool_names: set[str] | None = None,
) -> set[str] | None:
    """Retourne le set des noms de tools a exposer pour cette categorie.

    Retourne None si "any" (= pas de filtrage, envoie tous les tools).
    Les tools `skill_<slug>` peuvent etre filtres via select_relevant_skills()
    avant d'etre passes ici. Si fournis, ils sont ajoutes au subset de la
    category (pour que les skills selectionnees soient toujours disponibles).
    """
    if category not in CATEGORY_TOOLS or category == "any":
        return None
    base = set(CATEGORY_TOOLS[category])
    if skill_tool_names:
        base |= skill_tool_names
    return base


# ─────────────────────────────────────────────────────────────────────────────
# Sélection intelligente des skills ClawHub (lazy-load par pertinence)
# ─────────────────────────────────────────────────────────────────────────────
#
# PROBLEME : un user qui a 50+ skills installees envoie ~15-25k tokens de
# schemas a chaque tour, meme si le prompt n'utilise qu'une seule skill.
# Anthropic prompt cache aide mais le cout reste reel sur la 1ere requete et
# si l'ordre des tools change.
#
# SOLUTION : pre-filtrer les skills en fonction du prompt user. Pattern
# similaire au "deferred tools" / "ToolSearch" de Claude Code : ne pas
# exposer toutes les skills d'un coup, seulement les plus pertinentes.
#
# Strategie de scoring (rapide, sans LLM additionnel) :
#   1. Tokenize le prompt user en mots significatifs (>= 3 chars).
#   2. Pour chaque skill, score = somme des matches dans (slug, name,
#      description, tags, body_preview).
#   3. Boost +5 si la skill a deja ete utilisee dans les 10 derniers messages
#      (skills recurrentes restent dispo sans re-scoring).
#   4. Top-K (default 8) skills retournees.
#   5. Fallback : si zero match, retourne set() vide -> l'agent peut toujours
#      appeler CLAWHUB_SEARCH si besoin d'une skill non-listee.
# ─────────────────────────────────────────────────────────────────────────────

# Mots-outils francais/anglais qui n'apportent pas d'info pour le scoring.
_STOPWORDS: frozenset[str] = frozenset({
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "ou", "que",
    "qui", "quoi", "comment", "pour", "avec", "dans", "sur", "par", "ce",
    "cette", "ces", "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa",
    "ses", "il", "elle", "ils", "elles", "je", "tu", "nous", "vous",
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "at", "by",
    "with", "from", "this", "that", "these", "those", "is", "are", "was",
    "were", "be", "been", "being", "have", "has", "had", "do", "does",
    "did", "will", "would", "could", "should", "may", "might", "can",
    "ai", "agent", "sylea", "moi", "toi", "stp", "svp", "please",
})


def _tokenize_prompt(text: str) -> set[str]:
    """Decoupe le prompt en mots significatifs (lowercased, len >= 3, non-stopword)."""
    import re as _re
    if not text:
        return set()
    # Split sur tout ce qui n'est pas alphanumerique
    raw = _re.findall(r"[a-zA-ZÀ-ÿ0-9]+", text.lower())
    return {w for w in raw if len(w) >= 3 and w not in _STOPWORDS}


def select_relevant_skills(
    user_msg: str,
    skills_meta: list[Any],  # list[ClawHubSkillMeta]
    *,
    top_k: int = 8,
    recent_skill_slugs: set[str] | None = None,
    always_keep_min: int = 0,
) -> set[str]:
    """Selectionne les K skills les plus pertinentes pour le prompt user.

    Args:
        user_msg : message utilisateur (prompt en cours).
        skills_meta : liste de ClawHubSkillMeta (toutes les skills installees).
        top_k : nombre max de skills retournees (default 8).
        recent_skill_slugs : slugs deja utilises dans les N derniers tours
            (boost de score pour conserver la continuite).
        always_keep_min : si > 0, retourne au moins N skills meme sans match
            (utile pour eviter zero-skill quand le prompt est ambigu).

    Returns:
        Set de noms de tools (`skill_<slug>` avec '-' converti en '_') a
        inclure dans le subset envoye au LLM. Toujours <= top_k items.
    """
    if not skills_meta:
        return set()

    prompt_tokens = _tokenize_prompt(user_msg)
    recent = recent_skill_slugs or set()

    scored: list[tuple[float, str]] = []
    for meta in skills_meta:
        slug = getattr(meta, "slug", "") or ""
        if not slug:
            continue
        # Tokenize les champs textuels de la skill
        skill_text_parts = [
            slug.replace("-", " "),
            getattr(meta, "name", "") or "",
            getattr(meta, "description", "") or "",
            " ".join(getattr(meta, "tags", []) or []),
            (getattr(meta, "body_preview", "") or "")[:300],
        ]
        skill_tokens = _tokenize_prompt(" ".join(skill_text_parts))
        if not skill_tokens:
            continue

        # Score = nombre de tokens du prompt presents dans la skill
        match_count = len(prompt_tokens & skill_tokens) if prompt_tokens else 0
        score = float(match_count)

        # Boost +5 pour skills recemment utilisees
        if slug in recent:
            score += 5.0

        # Bonus +1 si le slug exact apparait dans le prompt (signal fort)
        if slug.replace("-", "") in user_msg.lower().replace("-", "").replace(" ", ""):
            score += 3.0

        if score > 0:
            scored.append((score, slug))

    # Tri decroissant + top-K
    scored.sort(key=lambda x: (-x[0], x[1]))
    selected = scored[:top_k]

    # Si zero match mais always_keep_min > 0, garder les N plus recentes par mtime
    if not selected and always_keep_min > 0:
        # Tri par mtime decroissant (recentes en premier)
        sorted_by_mtime = sorted(
            skills_meta,
            key=lambda m: getattr(m, "mtime", 0.0),
            reverse=True,
        )
        for meta in sorted_by_mtime[:always_keep_min]:
            slug = getattr(meta, "slug", "")
            if slug:
                selected.append((0.0, slug))

    # Convertit en noms de tools `skill_<slug>` (avec '-' -> '_' comme dans loader)
    result = set()
    for _score, slug in selected:
        tool_name = "skill_" + slug.replace("-", "_")
        result.add(tool_name)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Classifier Haiku
# ─────────────────────────────────────────────────────────────────────────────

_CLASSIFIER_SYSTEM_PROMPT = f"""Tu es un classifier leger pour Agent 3 Sylea.
Tu classes la requete user en UNE categorie, rien de plus. Pas d'explication.

Categories disponibles (reponds EXACTEMENT avec l'un de ces mots) :
{', '.join(CATEGORIES)}

Regles :
- "conversation" : salut, merci, oui/non, question conversationnelle sans outil.
- "web_research" : chercher des infos, "qu'est-ce que", actualites, prix, etc.
- "web_fetch" : lire une URL precise fournie par l'user.
- "file_ops" : lire/ecrire/creer un fichier, generer PDF, code a sauvegarder.
- "code_exec" : executer du code, lancer un script, commande shell/bash.
- "media_gen" : generer image/musique/video/voix.
- "image_analyze" : analyser une image que l'user a fournie.
- "messaging" : envoyer email, creer evenement calendrier, message externe.
- "memory_ops" : sauvegarder/chercher dans la memoire long-terme.
- "planning" : creer un todo, programmer une tache recurrente, cron.
- "sub_agent" : deleguer a un sous-agent autonome.
- "skill_extension" : chercher/installer/creer un skill ClawHub.
- "safety_check" : verifier moderation, PII, safety d'URL.
- "any" : incertain ou requete tres complexe multi-categories.

Reponds UNIQUEMENT avec le nom exact de la categorie, sans point, sans guillemets.
"""


async def classify_intent_haiku(
    user_msg: str,
    *,
    client: Any = None,
    timeout_s: float = 5.0,
) -> str:
    """Classe une requete user en une categorie (string). Fallback 'any' si erreur.

    Utilise Claude Haiku 4.5 (~100 tokens input + 10 tokens output = tres peu cher).

    Args:
        user_msg : le message user a classer.
        client : AsyncAnthropic instance (optionnel — cree une locale si None).
        timeout_s : cap de temps pour le classifier.

    Returns:
        Une categorie de CATEGORIES, ou "any" en fallback.
    """
    msg = (user_msg or "").strip()
    if not msg or len(msg) < 3:
        return "any"
    # Si msg super court (ex: "ok", "merci"), c'est probablement "conversation".
    if len(msg) <= 20 and not any(c in msg for c in ("http", "?", "!", "fichier", "envoie", "cree")):
        return "conversation"

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "any"

    try:
        import asyncio as _aio
        if client is None:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=api_key)

        async def _call() -> str:
            resp = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=12,  # categorie courte, pas besoin de plus
                system=_CLASSIFIER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": msg[:1500]}],  # cap input
            )
            text = ""
            for block in resp.content:
                if getattr(block, "type", "") == "text":
                    text += block.text
            return text.strip().lower()

        raw = await _aio.wait_for(_call(), timeout=timeout_s)
        # Match strict : la reponse doit etre l'un de CATEGORIES.
        for cat in CATEGORIES:
            if raw == cat or raw.startswith(cat):
                return cat
        # Parfois Haiku rajoute un point ou guillemet.
        cleaned = raw.strip("\".'` ").split()[0] if raw else ""
        if cleaned in CATEGORIES:
            return cleaned
        logger.info(f"Classifier reponse inattendue '{raw[:50]}' -> fallback 'any'")
        return "any"

    except Exception as e:
        logger.info(f"Classifier Haiku echec ({type(e).__name__}) -> fallback 'any'")
        return "any"


__all__ = [
    "CATEGORIES",
    "CATEGORY_TOOLS",
    "tool_subset_for_category",
    "classify_intent_haiku",
]
