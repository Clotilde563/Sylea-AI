"""
Agent 3 — Rate limiting per-user global pour /chat/native.

Complement du rate-limiter par action deja en place (`api/agent3_security.py`).
Ici on cap le nombre de REQUETES /chat/native par user par minute pour empecher :
  - abuse deliberee (scripts de scraping de reponses)
  - bugs client qui bouclent sur /chat

Token bucket simple en memoire :
  - `max_rpm` tokens refill lineaire a `max_rpm/60` tokens/s
  - `acquire(user_id)` retourne (ok, retry_after_s)
  - Dict global thread-safe avec Lock

Config via env :
  SYLEA_CHAT_MAX_RPM=30 (defaut 30 req/min par user)
  SYLEA_CHAT_BURST=10 (burst size, defaut = rpm)

Desactive sous pytest ou via SYLEA_DISABLE_CHAT_RATELIMIT=1.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("sylea.chat_ratelimit")


DEFAULT_MAX_RPM = int(os.getenv("SYLEA_CHAT_MAX_RPM", "30"))
DEFAULT_BURST = int(os.getenv("SYLEA_CHAT_BURST", str(max(10, DEFAULT_MAX_RPM // 3))))


class _ChatRateLimiter:
    """Token bucket par user pour les requetes /chat/native."""

    def __init__(self, max_rpm: int = DEFAULT_MAX_RPM, burst: int | None = None):
        self.max_rpm = max(1, int(max_rpm))
        self.burst = max(1, int(burst if burst is not None else max(10, self.max_rpm // 3)))
        self.refill_per_s = self.max_rpm / 60.0
        # {user_id: (tokens_float, last_refill_ts)}
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()
        # Metrics
        self._allowed = 0
        self._blocked = 0

    def acquire(self, user_id: str | None) -> tuple[bool, float]:
        """Tente de consommer 1 token.

        Retourne (allowed, retry_after_s).
        Si allowed=False, l'appelant doit retourner HTTP 429 + Retry-After header.

        Note : pure logic, ne lit PAS l'env. Utilise `check_chat_rate_limit`
        pour le bypass pytest/dev.
        """
        if not user_id:
            # Anonyme : on laisse passer (plus laxiste mais limite par reverse proxy)
            return True, 0.0

        now = time.time()
        with self._lock:
            tokens, last = self._buckets.get(user_id, (float(self.burst), now))
            # Refill
            elapsed = now - last
            tokens = min(float(self.burst), tokens + elapsed * self.refill_per_s)
            if tokens >= 1.0:
                tokens -= 1.0
                self._buckets[user_id] = (tokens, now)
                self._allowed += 1
                return True, 0.0
            # Pas assez → calc retry_after
            deficit = 1.0 - tokens
            retry_after = deficit / self.refill_per_s if self.refill_per_s > 0 else 60.0
            self._buckets[user_id] = (tokens, now)
            self._blocked += 1
            return False, round(retry_after, 2)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._allowed + self._blocked
            block_pct = (self._blocked / total * 100.0) if total else 0.0
            return {
                "allowed": self._allowed,
                "blocked": self._blocked,
                "total": total,
                "block_pct": round(block_pct, 2),
                "active_users": len(self._buckets),
                "max_rpm": self.max_rpm,
                "burst": self.burst,
            }

    def reset_for_user(self, user_id: str) -> None:
        with self._lock:
            self._buckets.pop(user_id, None)

    def reset_all(self) -> None:
        """Pour tests."""
        with self._lock:
            self._buckets.clear()
            self._allowed = 0
            self._blocked = 0


_global_limiter: _ChatRateLimiter | None = None
_global_lock = threading.Lock()


def get_chat_limiter() -> _ChatRateLimiter:
    """Singleton limiter."""
    global _global_limiter
    if _global_limiter is None:
        with _global_lock:
            if _global_limiter is None:
                _global_limiter = _ChatRateLimiter()
    return _global_limiter


def check_chat_rate_limit(user_id: str | None) -> tuple[bool, float]:
    """Raccourci : (allowed, retry_after_s).

    Bypass auto sous pytest (PYTEST_CURRENT_TEST) ou via SYLEA_DISABLE_CHAT_RATELIMIT=1.

    Mode in-memory (sync) — pour contexte sync. Si vous etes dans un endpoint
    async, preferez `check_chat_rate_limit_async` qui utilise le rate limiter
    distribue (Redis Lua atomique).
    """
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("SYLEA_DISABLE_CHAT_RATELIMIT") == "1":
        return True, 0.0
    return get_chat_limiter().acquire(user_id)


async def check_chat_rate_limit_async(user_id: str | None) -> tuple[bool, float]:
    """Version async distribuée (Redis Lua atomique quand REDIS_URL defini).

    Migration 2026-05-17 : utilise `api.distributed_rate_limiter.chat_native_limiter`
    pour la coherence multi-worker. Fallback in-memory si Redis indisponible.
    """
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("SYLEA_DISABLE_CHAT_RATELIMIT") == "1":
        return True, 0.0
    try:
        from api.distributed_rate_limiter import chat_native_limiter
        return await chat_native_limiter.acquire(user_id)
    except Exception:
        # Fallback in-memory si distributed_rate_limiter cassé
        return get_chat_limiter().acquire(user_id)


def get_chat_rate_stats() -> dict[str, Any]:
    """Stats globales (pour endpoint metrics)."""
    return get_chat_limiter().stats()


def reset_chat_limiter() -> None:
    """Pour tests."""
    global _global_limiter
    with _global_lock:
        if _global_limiter:
            _global_limiter.reset_all()


__all__ = [
    "check_chat_rate_limit",
    "get_chat_rate_stats",
    "reset_chat_limiter",
]
