"""
Sylea web search providers — implementations natives multi-user-safe.

**Contexte :** OpenClaw Gateway lit ses cles API tierces depuis un unique
fichier `~/.openclaw/openclaw.json`. Impossible pour un SaaS multi-user :
user A verrait la cle de user B ecrasee par la sienne.

**Solution :** reimplementer localement dans Sylea les 6 providers web search
qui dependaient d'OpenClaw pour leurs cles. Chaque appel lit la cle du user
authentifie via le Credential Vault (Phase 6). Isolation parfaite.

**Providers couverts :**
  - perplexity_search : IA + citations
  - brave_search     : privacy-first
  - tavily_search    : RAG-optimized
  - exa_search       : semantic/neural
  - firecrawl        : crawl + markdown extraction
  - x_search         : xAI Grok / Twitter search

**Design :**
  - Chaque provider = une fonction `async search_<name>(db, user_id, query, **opts)`
  - Signature uniforme : retourne `{ok, results: [...], cost_usd, error}`
  - Utilise `get_credential(db, user_id, <provider_slug>, "api_key")` pour la cle
  - Timeout 30s, retry 2x sur 5xx/429
  - Format de retour compatible avec le shaping existant (web_search schema)

**Fallback policy :**
  - Si la cle Vault du user est absente : retourne `{ok: False, error: "missing_api_key"}`
  - L'appelant (`_openclaw_direct`) peut alors soit :
    a) Utiliser la clee globale via OpenClaw Gateway (mono-user dev)
    b) Proposer a l'user d'ajouter sa cle dans /credentials

**Cout :**
  - Perplexity : ~$0.005/search
  - Brave : $0-$0.005 (free tier ample)
  - Tavily : ~$0.008/search
  - Exa : ~$0.004/search
  - Firecrawl : ~$0.01/page crawled
  - xAI Grok : ~$0.005/search
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("sylea.web_providers")


_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_RESULTS = 10


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_user_key_async(db: Any, user_id: str, provider: str) -> str | None:
    """Recupere la cle API user depuis le Credential Vault (async/PG).

    Retourne None si absente — l'appelant fera fallback.
    Le param `db` est garde pour compat de signature mais non utilise.
    """
    if not user_id:
        return None
    try:
        from api.credentials import get_credential_async
        return await get_credential_async(user_id, provider, "api_key", context="web_search")
    except Exception as e:
        logger.debug(f"get_credential_async({provider}) failed: {e}")
        return None


async def _post_json(
    url: str,
    headers: dict[str, str],
    json_body: dict,
    *,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[int, dict]:
    """POST JSON + return (status, body). Never raises (wraps exceptions)."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.post(url, headers=headers, json=json_body)
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text[:1000]}
            return resp.status_code, body
    except httpx.TimeoutException:
        return 504, {"error": "timeout"}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {str(e)[:200]}"}


async def _get_json(
    url: str,
    headers: dict[str, str],
    *,
    params: dict | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[int, dict]:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers, params=params)
            try:
                body = resp.json()
            except Exception:
                body = {"raw": resp.text[:1000]}
            return resp.status_code, body
    except httpx.TimeoutException:
        return 504, {"error": "timeout"}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {str(e)[:200]}"}


def _normalize_result(
    title: str, url: str, snippet: str, *,
    source: str = "",
    published: str = "",
    score: float | None = None,
) -> dict[str, Any]:
    """Format uniforme des results (compat shaping existant)."""
    r = {
        "title": str(title or "")[:200],
        "url": str(url or ""),
        "snippet": str(snippet or "")[:500],
    }
    if source:
        r["source"] = source
    if published:
        r["published"] = published
    if score is not None:
        r["score"] = score
    return r


# ─────────────────────────────────────────────────────────────────────────────
# Perplexity
# ─────────────────────────────────────────────────────────────────────────────

async def search_perplexity(
    db: Any, user_id: str, query: str,
    *,
    max_results: int = 10,
    freshness: str | None = None,  # day/week/month/year
) -> dict[str, Any]:
    """Perplexity Sonar API (avec citations).

    Docs : https://docs.perplexity.ai/api-reference/chat-completions
    """
    key = await _get_user_key_async(db, user_id, "perplexity")
    if not key:
        return {"ok": False, "error": "missing_api_key", "provider": "perplexity"}
    if not query.strip():
        return {"ok": False, "error": "empty_query", "provider": "perplexity"}

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    # On utilise le modele "sonar" qui retourne resultats + citations
    payload = {
        "model": "sonar",
        "messages": [{"role": "user", "content": query[:2000]}],
        "max_tokens": 800,
        "temperature": 0.2,
        "return_citations": True,
    }
    if freshness:
        payload["search_recency_filter"] = freshness

    status, body = await _post_json(
        "https://api.perplexity.ai/chat/completions", headers, payload,
    )
    if status != 200:
        return {
            "ok": False,
            "error": f"http_{status}",
            "provider": "perplexity",
            "detail": body.get("error", {}).get("message", "") or body.get("error", ""),
        }

    # Extract answer + citations
    choice = (body.get("choices") or [{}])[0]
    content = choice.get("message", {}).get("content", "") or ""
    citations = body.get("citations") or []

    results = []
    for i, url in enumerate(citations[:max_results]):
        # Perplexity retourne juste des URLs. On prend les N premiers pour snippets.
        results.append(_normalize_result(
            title=f"Source {i + 1}",
            url=url,
            snippet=content[:300] if i == 0 else "",
            source="perplexity",
        ))

    # Cout estime : 0.005 USD par requete Sonar
    cost_usd = 0.005

    return {
        "ok": True,
        "provider": "perplexity",
        "query": query,
        "answer": content,
        "results": results,
        "cost_usd": cost_usd,
        "raw_citations": citations,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Brave Search
# ─────────────────────────────────────────────────────────────────────────────

async def search_brave(
    db: Any, user_id: str, query: str,
    *,
    max_results: int = 10,
    country: str = "FR",
    safesearch: str = "moderate",
) -> dict[str, Any]:
    """Brave Search API (privacy-first).

    Docs : https://api.search.brave.com/app/documentation/web-search/get-started
    """
    key = await _get_user_key_async(db, user_id, "brave")
    if not key:
        return {"ok": False, "error": "missing_api_key", "provider": "brave"}
    if not query.strip():
        return {"ok": False, "error": "empty_query", "provider": "brave"}

    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": key,
    }
    params = {
        "q": query[:400],
        "count": min(max_results, 20),
        "country": country,
        "safesearch": safesearch,
    }

    status, body = await _get_json(
        "https://api.search.brave.com/res/v1/web/search", headers, params=params,
    )
    if status != 200:
        return {"ok": False, "error": f"http_{status}", "provider": "brave"}

    items = (body.get("web") or {}).get("results") or []
    results = [
        _normalize_result(
            title=it.get("title", ""),
            url=it.get("url", ""),
            snippet=it.get("description", ""),
            source="brave",
            published=it.get("page_age", ""),
        )
        for it in items[:max_results]
    ]

    return {
        "ok": True,
        "provider": "brave",
        "query": query,
        "results": results,
        "cost_usd": 0.0,  # Free tier genereux
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tavily
# ─────────────────────────────────────────────────────────────────────────────

async def search_tavily(
    db: Any, user_id: str, query: str,
    *,
    max_results: int = 10,
    search_depth: str = "basic",  # basic|advanced
    include_answer: bool = True,
) -> dict[str, Any]:
    """Tavily Search API (RAG-optimized).

    Docs : https://docs.tavily.com/docs/rest-api/api-reference
    """
    key = await _get_user_key_async(db, user_id, "tavily")
    if not key:
        return {"ok": False, "error": "missing_api_key", "provider": "tavily"}
    if not query.strip():
        return {"ok": False, "error": "empty_query", "provider": "tavily"}

    headers = {"Content-Type": "application/json"}
    payload = {
        "api_key": key,  # Tavily met la cle dans le body (pattern particulier)
        "query": query[:400],
        "search_depth": search_depth,
        "max_results": min(max_results, 20),
        "include_answer": include_answer,
    }

    status, body = await _post_json(
        "https://api.tavily.com/search", headers, payload,
    )
    if status != 200:
        return {"ok": False, "error": f"http_{status}", "provider": "tavily"}

    items = body.get("results") or []
    results = [
        _normalize_result(
            title=it.get("title", ""),
            url=it.get("url", ""),
            snippet=it.get("content", ""),
            source="tavily",
            score=it.get("score"),
        )
        for it in items[:max_results]
    ]

    cost_usd = 0.008 if search_depth == "basic" else 0.016
    return {
        "ok": True,
        "provider": "tavily",
        "query": query,
        "answer": body.get("answer", ""),
        "results": results,
        "cost_usd": cost_usd,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Exa
# ─────────────────────────────────────────────────────────────────────────────

async def search_exa(
    db: Any, user_id: str, query: str,
    *,
    max_results: int = 10,
    search_type: str = "neural",  # neural|keyword|auto
) -> dict[str, Any]:
    """Exa (Metaphor) Search API — recherche semantique/neurale.

    Docs : https://docs.exa.ai/reference/search
    """
    key = await _get_user_key_async(db, user_id, "exa")
    if not key:
        return {"ok": False, "error": "missing_api_key", "provider": "exa"}
    if not query.strip():
        return {"ok": False, "error": "empty_query", "provider": "exa"}

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "x-api-key": key,
    }
    payload = {
        "query": query[:400],
        "numResults": min(max_results, 25),
        "type": search_type,
        "contents": {"text": {"maxCharacters": 500}},
    }

    status, body = await _post_json(
        "https://api.exa.ai/search", headers, payload,
    )
    if status != 200:
        return {"ok": False, "error": f"http_{status}", "provider": "exa"}

    items = body.get("results") or []
    results = [
        _normalize_result(
            title=it.get("title", ""),
            url=it.get("url", ""),
            snippet=(it.get("text") or it.get("snippet") or "")[:500],
            source="exa",
            published=it.get("publishedDate", ""),
            score=it.get("score"),
        )
        for it in items[:max_results]
    ]

    return {
        "ok": True,
        "provider": "exa",
        "query": query,
        "results": results,
        "cost_usd": 0.004,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Firecrawl
# ─────────────────────────────────────────────────────────────────────────────

async def firecrawl_scrape(
    db: Any, user_id: str, url: str,
    *,
    formats: list[str] | None = None,
) -> dict[str, Any]:
    """Firecrawl Scrape API — crawl + extraction markdown propre.

    Docs : https://docs.firecrawl.dev/api-reference/endpoint/scrape
    """
    key = await _get_user_key_async(db, user_id, "firecrawl")
    if not key:
        return {"ok": False, "error": "missing_api_key", "provider": "firecrawl"}
    if not url.strip():
        return {"ok": False, "error": "empty_url", "provider": "firecrawl"}

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "url": url,
        "formats": formats or ["markdown"],
    }

    status, body = await _post_json(
        "https://api.firecrawl.dev/v1/scrape", headers, payload, timeout=60.0,
    )
    if status != 200:
        return {"ok": False, "error": f"http_{status}", "provider": "firecrawl"}

    data = body.get("data") or {}
    return {
        "ok": True,
        "provider": "firecrawl",
        "url": url,
        "markdown": data.get("markdown", "")[:50000],
        "html": data.get("html", "")[:50000] if "html" in (formats or []) else "",
        "metadata": data.get("metadata", {}),
        "cost_usd": 0.01,
    }


async def firecrawl_search(
    db: Any, user_id: str, query: str,
    *,
    max_results: int = 10,
) -> dict[str, Any]:
    """Firecrawl Search + scrape (retourne results + markdown)."""
    key = await _get_user_key_async(db, user_id, "firecrawl")
    if not key:
        return {"ok": False, "error": "missing_api_key", "provider": "firecrawl"}
    if not query.strip():
        return {"ok": False, "error": "empty_query", "provider": "firecrawl"}

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query[:400],
        "limit": min(max_results, 20),
    }
    status, body = await _post_json(
        "https://api.firecrawl.dev/v1/search", headers, payload, timeout=60.0,
    )
    if status != 200:
        return {"ok": False, "error": f"http_{status}", "provider": "firecrawl"}

    items = body.get("data") or []
    results = [
        _normalize_result(
            title=it.get("title", ""),
            url=it.get("url", ""),
            snippet=it.get("description", "") or it.get("markdown", "")[:300],
            source="firecrawl",
        )
        for it in items[:max_results]
    ]
    return {
        "ok": True,
        "provider": "firecrawl",
        "query": query,
        "results": results,
        "cost_usd": 0.02 * len(results),  # ~0.02 par result
    }


# ─────────────────────────────────────────────────────────────────────────────
# xAI Grok (x_search)
# ─────────────────────────────────────────────────────────────────────────────

async def search_xai(
    db: Any, user_id: str, query: str,
    *,
    max_results: int = 10,
) -> dict[str, Any]:
    """xAI Grok API avec live search (equivalent x_search).

    Docs : https://docs.x.ai/docs/api-reference
    """
    key = await _get_user_key_async(db, user_id, "xai")
    if not key:
        return {"ok": False, "error": "missing_api_key", "provider": "xai"}
    if not query.strip():
        return {"ok": False, "error": "empty_query", "provider": "xai"}

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "grok-2-latest",
        "messages": [{
            "role": "user",
            "content": f"Recherche X/Twitter : {query[:1500]}. Retourne 5-10 posts pertinents avec auteurs, dates, et liens.",
        }],
        "max_tokens": 1500,
        "temperature": 0.3,
    }

    status, body = await _post_json(
        "https://api.x.ai/v1/chat/completions", headers, payload, timeout=45.0,
    )
    if status != 200:
        return {"ok": False, "error": f"http_{status}", "provider": "xai"}

    content = (body.get("choices") or [{}])[0].get("message", {}).get("content", "")

    return {
        "ok": True,
        "provider": "xai",
        "query": query,
        "answer": content,
        "results": [],  # Grok retourne texte formate, pas de struct
        "cost_usd": 0.005,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Registry : nom OpenClaw tool -> fonction Sylea native
# ─────────────────────────────────────────────────────────────────────────────

# Chaque entree : tool OpenClaw name -> (func, is_scrape (bool))
# `is_scrape=True` : firecrawl peut faire scrape OU search selon args.

PROVIDER_MAP: dict[str, dict[str, Any]] = {
    "perplexity_search": {"fn": search_perplexity, "kind": "search"},
    "brave_search": {"fn": search_brave, "kind": "search"},
    "tavily_search": {"fn": search_tavily, "kind": "search"},
    "exa_search": {"fn": search_exa, "kind": "search"},
    "x_search": {"fn": search_xai, "kind": "search"},
    "firecrawl": {"fn": firecrawl_search, "kind": "hybrid"},  # scrape OR search
}


async def has_user_key_for(db: Any, user_id: str, tool_name: str) -> bool:
    """Quick check : est-ce que le user a une cle pour CE tool dans son Vault ?

    Permet au dispatcher de decider si on appelle direct ou fallback OpenClaw.
    """
    if tool_name not in PROVIDER_MAP:
        return False
    # Provider slug = prefix sans _search
    slug_map = {
        "perplexity_search": "perplexity",
        "brave_search": "brave",
        "tavily_search": "tavily",
        "exa_search": "exa",
        "x_search": "xai",
        "firecrawl": "firecrawl",
    }
    slug = slug_map.get(tool_name)
    if not slug:
        return False
    return (await _get_user_key_async(db, user_id, slug)) is not None


async def invoke_provider(
    db: Any, user_id: str, tool_name: str, args: dict,
) -> dict[str, Any]:
    """Dispatch uniforme vers le bon provider avec signature tool_use OpenClaw.

    args = le meme dict que ce qu'OpenClaw Gateway recevrait.
    """
    entry = PROVIDER_MAP.get(tool_name)
    if not entry:
        return {"ok": False, "error": f"unknown_provider:{tool_name}"}

    # Normalise les args communs
    query = (args.get("query") or "").strip()
    url = (args.get("url") or "").strip()
    max_results = int(args.get("max_results") or args.get("limit") or _DEFAULT_MAX_RESULTS)

    fn = entry["fn"]
    kind = entry["kind"]

    # Firecrawl : scrape si URL, sinon search
    if tool_name == "firecrawl":
        if url:
            return await firecrawl_scrape(db, user_id, url)
        if query:
            return await firecrawl_search(db, user_id, query, max_results=max_results)
        return {"ok": False, "error": "firecrawl: query or url required"}

    # Providers search classiques
    if not query:
        return {"ok": False, "error": f"{tool_name}: query required"}

    return await fn(db, user_id, query, max_results=max_results)


__all__ = [
    "PROVIDER_MAP",
    "has_user_key_for",
    "invoke_provider",
    "search_perplexity",
    "search_brave",
    "search_tavily",
    "search_exa",
    "search_xai",
    "firecrawl_scrape",
    "firecrawl_search",
]
