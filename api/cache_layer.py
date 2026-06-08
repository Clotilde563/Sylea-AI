"""
Couche d'abstraction caches distribués — Sylea.AI.

Migration 2026-05-17 : in-memory → Redis pour résoudre l'incohérence en mode
multi-worker (gunicorn workers, Kubernetes pods). Chaque worker avait son
propre état → rate limits contournables, circuit breakers non cohérents.

Architecture :
- `CacheBackend` interface abstraite (Protocol).
- `RedisBackend` : si `REDIS_URL` env défini, utilise redis-py async.
- `InMemoryBackend` : fallback dev/single-worker (dict + threading.Lock).
- `get_cache()` : factory singleton qui choisit le backend.

Caches migrés (voir api/openclaw_bridge.py) :
- _per_tool_breakers       → Redis HASH per tool
- _daily_cost_by_user      → Redis INCR atomique key per (user, date)
- _retry_metrics           → Redis HASH (tool_event → count)
- _tool_latencies          → Redis LIST (LPUSH + LTRIM maxlen=50)
- _gateway_health_cache    → Redis key avec TTL (SETEX)
- _chat_ratelimit_buckets  → Lua script atomique (token bucket)

PAS migré :
- _shared_http_client (agent3_http.py) : pool TCP local, OK par-worker.

Usage :
    from api.cache_layer import get_cache
    cache = get_cache()
    await cache.incr("counter:user:abc:2026-05-17", amount=1.5)
    await cache.set_with_ttl("health:gateway", "up", ttl_s=30)
    val = await cache.get("health:gateway")
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Any, Protocol

logger = logging.getLogger("sylea.cache")


# ─────────────────────────────────────────────────────────────────────────────
# Interface abstraite
# ─────────────────────────────────────────────────────────────────────────────

class CacheBackend(Protocol):
    """Interface unifiée Redis ↔ InMemory."""

    async def get(self, key: str) -> str | None: ...
    async def set_with_ttl(self, key: str, value: str, ttl_s: int) -> None: ...
    async def set(self, key: str, value: str) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def incr(self, key: str, amount: float = 1.0) -> float: ...
    async def hget(self, key: str, field: str) -> str | None: ...
    async def hset(self, key: str, field: str, value: str) -> None: ...
    async def hincrby(self, key: str, field: str, amount: int = 1) -> int: ...
    async def hgetall(self, key: str) -> dict[str, str]: ...
    async def hdel(self, key: str, field: str) -> None: ...
    async def lpush_trim(self, key: str, value: str, maxlen: int) -> None: ...
    async def lrange(self, key: str, start: int = 0, end: int = -1) -> list[str]: ...
    async def eval_lua(self, script: str, keys: list[str], args: list[str]) -> Any: ...
    async def keys(self, pattern: str) -> list[str]: ...
    async def close(self) -> None: ...


# ─────────────────────────────────────────────────────────────────────────────
# Backend Redis
# ─────────────────────────────────────────────────────────────────────────────

class RedisBackend:
    """Backend Redis pour caches distribués multi-worker."""

    def __init__(self, url: str):
        try:
            from redis.asyncio import Redis  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "redis-py non installe. `pip install redis>=5.0`",
            ) from e

        # decode_responses=True : retourne str au lieu de bytes
        self._client = Redis.from_url(url, decode_responses=True)
        self._url = url
        logger.info(f"RedisBackend init : {url[:30]}...")

    async def get(self, key: str) -> str | None:
        return await self._client.get(key)

    async def set(self, key: str, value: str) -> None:
        await self._client.set(key, value)

    async def set_with_ttl(self, key: str, value: str, ttl_s: int) -> None:
        await self._client.setex(key, ttl_s, value)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def incr(self, key: str, amount: float = 1.0) -> float:
        if isinstance(amount, int):
            return float(await self._client.incrby(key, amount))
        # Pour float : INCRBYFLOAT
        return float(await self._client.incrbyfloat(key, amount))

    async def hget(self, key: str, field: str) -> str | None:
        return await self._client.hget(key, field)

    async def hset(self, key: str, field: str, value: str) -> None:
        await self._client.hset(key, field, value)

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        return int(await self._client.hincrby(key, field, amount))

    async def hgetall(self, key: str) -> dict[str, str]:
        return await self._client.hgetall(key) or {}

    async def hdel(self, key: str, field: str) -> None:
        await self._client.hdel(key, field)

    async def lpush_trim(self, key: str, value: str, maxlen: int) -> None:
        """Push à gauche + tronque (deque maxlen-like).

        Utilise un pipeline pour atomiser les 2 commandes.
        """
        async with self._client.pipeline(transaction=False) as pipe:
            await pipe.lpush(key, value)
            await pipe.ltrim(key, 0, maxlen - 1)
            await pipe.execute()

    async def lrange(self, key: str, start: int = 0, end: int = -1) -> list[str]:
        return await self._client.lrange(key, start, end)

    async def eval_lua(self, script: str, keys: list[str], args: list[str]) -> Any:
        return await self._client.eval(script, len(keys), *keys, *args)

    async def keys(self, pattern: str) -> list[str]:
        return await self._client.keys(pattern)

    async def close(self) -> None:
        try:
            await self._client.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Backend InMemory (fallback)
# ─────────────────────────────────────────────────────────────────────────────

class InMemoryBackend:
    """Backend in-memory pour dev / single-worker.

    Thread-safe via RLock. Pas distribué : chaque process a son état.
    Acceptable en dev SQLite + uvicorn 1 worker, à éviter en prod multi-worker.
    """

    def __init__(self):
        self._data: dict[str, Any] = {}
        self._expirations: dict[str, float] = {}  # key → unix ts
        self._lock = threading.RLock()
        logger.warning(
            "InMemoryBackend init — pas distribue. Pour la prod multi-worker, "
            "definir REDIS_URL=redis://..."
        )

    def _expired(self, key: str) -> bool:
        exp = self._expirations.get(key)
        return exp is not None and time.time() >= exp

    def _purge_if_expired(self, key: str) -> None:
        if self._expired(key):
            self._data.pop(key, None)
            self._expirations.pop(key, None)

    async def get(self, key: str) -> str | None:
        with self._lock:
            self._purge_if_expired(key)
            v = self._data.get(key)
            return str(v) if v is not None else None

    async def set(self, key: str, value: str) -> None:
        with self._lock:
            self._data[key] = value
            self._expirations.pop(key, None)

    async def set_with_ttl(self, key: str, value: str, ttl_s: int) -> None:
        with self._lock:
            self._data[key] = value
            self._expirations[key] = time.time() + ttl_s

    async def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)
            self._expirations.pop(key, None)

    async def incr(self, key: str, amount: float = 1.0) -> float:
        with self._lock:
            self._purge_if_expired(key)
            current = float(self._data.get(key, 0) or 0)
            new = current + float(amount)
            self._data[key] = new
            return new

    async def hget(self, key: str, field: str) -> str | None:
        with self._lock:
            h = self._data.get(key)
            if not isinstance(h, dict):
                return None
            v = h.get(field)
            return str(v) if v is not None else None

    async def hset(self, key: str, field: str, value: str) -> None:
        with self._lock:
            h = self._data.setdefault(key, {})
            if not isinstance(h, dict):
                h = {}
                self._data[key] = h
            h[field] = value

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        with self._lock:
            h = self._data.setdefault(key, {})
            if not isinstance(h, dict):
                h = {}
                self._data[key] = h
            current = int(h.get(field, 0) or 0)
            new = current + int(amount)
            h[field] = new
            return new

    async def hgetall(self, key: str) -> dict[str, str]:
        with self._lock:
            h = self._data.get(key)
            if not isinstance(h, dict):
                return {}
            return {k: str(v) for k, v in h.items()}

    async def hdel(self, key: str, field: str) -> None:
        with self._lock:
            h = self._data.get(key)
            if isinstance(h, dict):
                h.pop(field, None)

    async def lpush_trim(self, key: str, value: str, maxlen: int) -> None:
        with self._lock:
            lst = self._data.setdefault(key, deque(maxlen=maxlen))
            if not isinstance(lst, deque) or lst.maxlen != maxlen:
                lst = deque(lst if isinstance(lst, (list, deque)) else [], maxlen=maxlen)
                self._data[key] = lst
            lst.appendleft(value)

    async def lrange(self, key: str, start: int = 0, end: int = -1) -> list[str]:
        with self._lock:
            lst = self._data.get(key)
            if not isinstance(lst, (list, deque)):
                return []
            items = list(lst)
            if end == -1:
                return [str(v) for v in items[start:]]
            return [str(v) for v in items[start:end + 1]]

    async def eval_lua(self, script: str, keys: list[str], args: list[str]) -> Any:
        """Pas de Lua en in-memory : on retourne None.

        Les callers doivent avoir un fallback Python (cf. distributed_rate_limiter).
        """
        return None

    async def keys(self, pattern: str) -> list[str]:
        with self._lock:
            # Pattern matching simple : juste le wildcard '*'
            import fnmatch
            return [k for k in list(self._data.keys()) if fnmatch.fnmatch(k, pattern)]

    async def close(self) -> None:
        with self._lock:
            self._data.clear()
            self._expirations.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Factory singleton
# ─────────────────────────────────────────────────────────────────────────────

_cache_instance: CacheBackend | None = None
_cache_lock = threading.Lock()


def get_cache() -> CacheBackend:
    """Retourne le backend cache (singleton lazy).

    Détection :
    - REDIS_URL défini + redis-py installé → RedisBackend
    - Sinon → InMemoryBackend (warning log)
    """
    global _cache_instance
    if _cache_instance is not None:
        return _cache_instance

    with _cache_lock:
        if _cache_instance is not None:
            return _cache_instance

        redis_url = os.environ.get("REDIS_URL", "").strip()
        if redis_url:
            try:
                _cache_instance = RedisBackend(redis_url)
                return _cache_instance
            except Exception as e:
                logger.error(
                    f"Redis init failed ({e}) — fallback InMemory. "
                    "VERIFIER REDIS_URL en prod pour eviter incoherences multi-worker."
                )

        _cache_instance = InMemoryBackend()
        return _cache_instance


def reset_cache_for_tests() -> None:
    """Reset le singleton (utilisé dans les tests pour basculer entre backends)."""
    global _cache_instance
    with _cache_lock:
        _cache_instance = None


def is_redis_enabled() -> bool:
    """Indique si le backend actuel est Redis."""
    cache = get_cache()
    return isinstance(cache, RedisBackend)


__all__ = [
    "CacheBackend",
    "RedisBackend",
    "InMemoryBackend",
    "get_cache",
    "reset_cache_for_tests",
    "is_redis_enabled",
]
