"""
Rate limiting global par IP — Syléa.AI (sécurité niveau pro).

Couche ajoutée AU-DESSUS du rate-limiting per-user existant. Bloque les
attaques par IP avant même que l'authentification utilisateur soit faite,
ce qui :
  - protège la route /api/auth/login contre le credential stuffing
  - protège les routes publiques (/api/health, /api/auth/signup) contre
    le scraping et le DoS
  - limite les attaques distribuées simples sans WAF (le WAF Cloudflare
    reste la première ligne ; ici, défense en profondeur applicative)

Algorithme : token bucket distribué via Redis Lua atomique (réutilise la
même infra que `api/distributed_rate_limiter.py`). Fallback in-memory si
Redis indisponible (cohérence dégradée par-worker, mais ne bloque pas).

Stratégie de clé : on hash l'IP (sha256, premier 16 hex) pour éviter de
stocker des IP en clair dans Redis (RGPD : minimisation des données).

Configuration via env :
    SYLEA_IP_RATELIMIT_CAPACITY  : burst max (défaut 60)
    SYLEA_IP_RATELIMIT_REFILL    : tokens/seconde (défaut 1.0)
    SYLEA_IP_RATELIMIT_BURST_LOGIN : burst pour /login (défaut 10)
    SYLEA_IP_RATELIMIT_REFILL_LOGIN : refill /login (défaut 0.1, soit 6/min)
    SYLEA_DISABLE_IP_RATELIMIT   : true pour désactiver (tests/dev)
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from api.distributed_rate_limiter import DistributedRateLimiter

logger = logging.getLogger("sylea.ip_rate_limiter")


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


# Endpoints sensibles : rate limit plus strict (anti credential stuffing).
# FIX P0 2026-06 : les anciens prefixes /signup, /forgot-password,
# /reset-password, /verify-code ne correspondaient a AUCUN endpoint reel
# (les vrais sont /register et /verify) → l'OTP brute-force et la creation
# de compte tombaient dans le bucket global laxiste (60/min). On aligne sur
# les routes reellement exposees par api/auth/router.py + les echanges OAuth.
_STRICT_ENDPOINTS_PREFIX = (
    "/api/auth/login",
    "/api/auth/register",   # creation de compte (anti-spam)
    "/api/auth/verify",     # validation OTP (anti-bruteforce code) — CRITIQUE
    "/api/auth/oauth",      # echanges OAuth google/github/apple (POST token)
)

# Endpoints exclus (health checks, websocket handshake — limités ailleurs)
_EXCLUDED_PREFIX = (
    "/api/health",
    "/ws/",
    "/static/",
    "/favicon.ico",
)


# ─────────────────────────────────────────────────────────────────────────────
# Extraction IP client
# ─────────────────────────────────────────────────────────────────────────────

# Préférer X-Forwarded-For si on est derrière un proxy (Cloudflare, nginx).
# Ordre : Cloudflare CF-Connecting-IP > X-Real-IP > X-Forwarded-For (1er) > client direct.
# Configurer SYLEA_TRUSTED_PROXIES=true pour activer (sinon on prend l'IP TCP directe,
# ce qui empêche un attaquant de spoofer son IP via un header).
_TRUST_PROXY_HEADERS = os.environ.get("SYLEA_TRUSTED_PROXIES", "").strip().lower() in (
    "1", "true", "yes", "on"
)


def _extract_client_ip(request: Request) -> str:
    """Retourne l'IP client (avec ou sans proxy chain selon config)."""
    if _TRUST_PROXY_HEADERS:
        # Cloudflare envoie CF-Connecting-IP qui est garanti par leur infra
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip:
            return cf_ip.strip()
        # nginx proxy_pass courant
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()
        # X-Forwarded-For : first hop = client réel
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()

    # Fallback : IP TCP directe (non spoofable)
    return request.client.host if request.client else "unknown"


def _hash_ip(ip: str) -> str:
    """Hash sha256 tronqué — évite de stocker l'IP en clair (RGPD)."""
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────────
# Limiters singletons
# ─────────────────────────────────────────────────────────────────────────────

_GLOBAL_CAPACITY = _int_env("SYLEA_IP_RATELIMIT_CAPACITY", 60)
_GLOBAL_REFILL = _float_env("SYLEA_IP_RATELIMIT_REFILL", 1.0)
_LOGIN_CAPACITY = _int_env("SYLEA_IP_RATELIMIT_BURST_LOGIN", 10)
_LOGIN_REFILL = _float_env("SYLEA_IP_RATELIMIT_REFILL_LOGIN", 0.1)

# Bucket global : 60 req en rafale + 1 req/s soutenu (soit ~60/min sustained)
_global_ip_limiter = DistributedRateLimiter(
    name="ip_global",
    capacity=_GLOBAL_CAPACITY,
    refill_rate=_GLOBAL_REFILL,
    bucket_ttl_s=300,
)

# Bucket /auth/* : 10 req en rafale + 1 req / 10s sustained = anti credential stuffing
_login_ip_limiter = DistributedRateLimiter(
    name="ip_auth",
    capacity=_LOGIN_CAPACITY,
    refill_rate=_LOGIN_REFILL,
    bucket_ttl_s=900,  # 15 min — on garde le bucket d'auth plus longtemps
)


# ─────────────────────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────────────────────

class IPRateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limit toutes les requêtes HTTP par IP, avant l'authentification.

    Bypass automatique :
      - /api/health (probes Kubernetes / Render / Railway)
      - /ws/* (websocket : géré par le rate-limiter chat)
      - /static/* (assets servis par le frontend)

    Mode strict appliqué aux endpoints d'auth (login/signup/reset).
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self._disabled = os.environ.get(
            "SYLEA_DISABLE_IP_RATELIMIT", ""
        ).strip().lower() in ("1", "true", "yes", "on")

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Bypass si désactivé via env (utile en tests)
        if self._disabled:
            return await call_next(request)

        path = request.url.path

        # Bypass endpoints autorisés
        if path.startswith(_EXCLUDED_PREFIX):
            return await call_next(request)

        # Calcul de l'IP (hashed pour RGPD)
        ip = _extract_client_ip(request)
        ip_hash = _hash_ip(ip)

        # Sélection du bucket : strict pour auth, normal sinon
        if path.startswith(_STRICT_ENDPOINTS_PREFIX):
            limiter = _login_ip_limiter
        else:
            limiter = _global_ip_limiter

        try:
            allowed, retry_after = await limiter.acquire(ip_hash, n=1)
        except Exception as e:
            # Si Redis crash et fallback in-memory crash aussi : on laisse passer
            # plutôt que de bloquer toute l'API. Loggué pour alerting.
            logger.error("[ip_rate_limit] limiter crashed for ip=%s: %s",
                         ip_hash, e)
            return await call_next(request)

        if not allowed:
            # 429 Too Many Requests avec Retry-After header standard RFC 7231
            return JSONResponse(
                status_code=429,
                headers={
                    "Retry-After": str(int(retry_after) + 1),
                    "X-RateLimit-Bucket": (
                        "auth" if path.startswith(_STRICT_ENDPOINTS_PREFIX)
                        else "global"
                    ),
                },
                content={
                    "detail": "Trop de requêtes depuis cette adresse IP. "
                              f"Réessayez dans {int(retry_after) + 1}s.",
                    "code": "rate_limit_exceeded",
                },
            )

        return await call_next(request)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de diagnostic (exposés via /api/health/security si on veut)
# ─────────────────────────────────────────────────────────────────────────────

def get_ip_rate_limit_config() -> dict[str, Any]:
    """Retourne la config active (lecture seule, jamais d'IP)."""
    return {
        "global_capacity": _GLOBAL_CAPACITY,
        "global_refill_per_s": _GLOBAL_REFILL,
        "login_capacity": _LOGIN_CAPACITY,
        "login_refill_per_s": _LOGIN_REFILL,
        "trust_proxy_headers": _TRUST_PROXY_HEADERS,
        "disabled": os.environ.get(
            "SYLEA_DISABLE_IP_RATELIMIT", ""
        ).strip().lower() in ("1", "true", "yes", "on"),
    }
