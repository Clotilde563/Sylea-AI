"""
Agent 3 — Pool HTTP partage pour les appels sortants.

httpx.AsyncClient maintient un pool de connexions keep-alive. Creer un nouveau
client par appel (le pattern `async with httpx.AsyncClient() as c: ...`)
detruit le pool a chaque fois => nouvelle TCP handshake, nouvelle TLS
negociation, nouvelle resolution DNS. Gros impact sur la latence quand on
enchaine plusieurs appels Google/OpenClaw.

Ce module expose un singleton partage, lazy-init, avec limites raisonnables
pour un serveur FastAPI. Le client est ferme proprement au shutdown via
`close_http_client()` (appele depuis le lifespan de l'app).
"""

from __future__ import annotations

import httpx


# Limites du pool :
# - 100 connexions simultanees max (protege contre les fuites).
# - 20 keep-alive : suffisant pour rouler plusieurs agents en parallele
#   sans reouvrir TCP/TLS a chaque tour.
_LIMITS = httpx.Limits(
    max_connections=100,
    max_keepalive_connections=20,
    keepalive_expiry=30.0,
)

# Timeouts par defaut (overridables par appel via `timeout=...`).
# `connect` court (5s) pour detecter vite un service down, `read` long (30s)
# pour les appels Google un peu lents.
_DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=5.0)

_DEFAULT_HEADERS = {
    "User-Agent": "Sylea-Agent3/1.0",
}

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Retourne le singleton httpx.AsyncClient (lazy init).

    Thread-safe en mode single-process + asyncio (pas besoin de lock : les
    coroutines s'executent dans un seul thread). Pour un mode multi-process
    (gunicorn workers), chaque worker aura son propre pool — pas un probleme,
    c'est meme souhaitable pour isoler les pannes.
    """
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            limits=_LIMITS,
            headers=_DEFAULT_HEADERS,
            follow_redirects=False,  # laisser le caller gerer (anti-SSRF)
        )
    return _client


async def close_http_client() -> None:
    """Ferme proprement le pool au shutdown. Idempotent."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None


__all__ = ["get_http_client", "close_http_client"]
