"""
Rate limiter distribué (token bucket atomique) — Sylea.AI.

Migration 2026-05-17 : remplace le rate-limiter in-memory de
`api/agent3_chat_ratelimit.py` quand Redis est disponible.

Pourquoi Lua atomique :
- Le pattern "GET bucket → calculer refill → SET nouveau bucket" en 2 RTT
  Redis n'est PAS atomique : 2 requêtes simultanées peuvent dépasser la
  capacité (race condition classique). Avec Lua, tout s'exécute côté serveur
  Redis dans une seule transaction atomique.

Algorithme : Token bucket avec refill linéaire
- `capacity` : burst max (combien de requêtes en rafale)
- `refill_rate` : tokens ajoutés / seconde
- `acquire(user_id, n=1)` : tente de consommer N tokens. Retourne (ok, retry_after_s).

Fallback :
- Si Redis indisponible → utilise `_ChatRateLimiter` in-memory existant
  (pas distribué, mais évite de bloquer en dev/single-worker).
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from typing import Any

from api.cache_layer import get_cache, is_redis_enabled

logger = logging.getLogger("sylea.distributed_rate_limiter")


# ─────────────────────────────────────────────────────────────────────────────
# Lua script : token bucket atomique
# ─────────────────────────────────────────────────────────────────────────────
#
# KEYS[1] = clé du bucket (ex "ratelimit:chat:user_abc")
# ARGV[1] = capacity (max tokens en rafale)
# ARGV[2] = refill_rate (tokens/s)
# ARGV[3] = now (unix timestamp float)
# ARGV[4] = requested (combien on veut consommer)
# ARGV[5] = ttl (seconds : delete bucket si inactif)
#
# Retourne : { allowed: 0|1, retry_after: float, remaining: float }

_LUA_TOKEN_BUCKET = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

-- Charge l'etat actuel
local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
end

-- Refill lineaire depuis last_refill
local elapsed = now - last_refill
if elapsed > 0 then
    tokens = math.min(capacity, tokens + (elapsed * refill_rate))
    last_refill = now
end

-- Tentative de consommation
local allowed = 0
local retry_after = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
else
    -- Pas assez : calculer combien de temps pour avoir assez
    local needed = requested - tokens
    retry_after = needed / refill_rate
end

-- Sauvegarder l'etat + TTL
redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
redis.call('EXPIRE', key, ttl)

return {allowed, tostring(retry_after), tostring(tokens)}
"""


# ─────────────────────────────────────────────────────────────────────────────
# DistributedRateLimiter
# ─────────────────────────────────────────────────────────────────────────────

class DistributedRateLimiter:
    """Token bucket distribué via Redis Lua atomique.

    Args:
        name: nom du limiter (utilisé dans la clé Redis : "ratelimit:{name}:{user_id}")
        capacity: tokens max en rafale (burst)
        refill_rate: tokens ajoutés par seconde (= rpm/60 pour limite/min)
        bucket_ttl_s: durée de vie inactivité du bucket (défaut 3600s = 1h)
    """

    def __init__(
        self,
        name: str,
        capacity: int,
        refill_rate: float,
        bucket_ttl_s: int = 3600,
    ):
        self.name = name
        self.capacity = max(1, int(capacity))
        self.refill_rate = max(0.001, float(refill_rate))
        self.bucket_ttl_s = bucket_ttl_s

        # Fallback in-memory (utilisé si Redis indisponible ou en cas d'erreur)
        self._fallback_buckets: dict[str, tuple[float, float]] = {}
        self._fallback_lock = threading.Lock()

        # Metrics
        self._allowed_count = 0
        self._blocked_count = 0
        self._metrics_lock = threading.Lock()

    def _bucket_key(self, user_id: str) -> str:
        safe_uid = user_id.replace(":", "_").replace(" ", "_")[:80]
        return f"ratelimit:{self.name}:{safe_uid}"

    async def acquire(self, user_id: str | None, n: int = 1) -> tuple[bool, float]:
        """Tente de consommer N tokens du bucket du user.

        Returns:
            (allowed, retry_after_s) :
            - allowed=True : OK pour traiter la requête
            - allowed=False : trop de requêtes, attendre retry_after_s secondes
        """
        if not user_id:
            user_id = "_anonymous"

        cache = get_cache()
        now = time.time()
        key = self._bucket_key(user_id)

        # Try Lua atomic via Redis
        if is_redis_enabled():
            try:
                result = await cache.eval_lua(
                    _LUA_TOKEN_BUCKET,
                    keys=[key],
                    args=[
                        str(self.capacity),
                        str(self.refill_rate),
                        str(now),
                        str(n),
                        str(self.bucket_ttl_s),
                    ],
                )
                if result is not None:
                    allowed = bool(int(result[0]))
                    retry_after = float(result[1])
                    self._record_metric(allowed)
                    return allowed, retry_after
            except Exception as e:
                logger.warning(
                    f"Redis Lua acquire failed ({e}), fallback in-memory pour {key}"
                )

        # Fallback in-memory (pas distribué — used en dev ou si Redis down)
        return self._acquire_local(user_id, n)

    def _acquire_local(self, user_id: str, n: int) -> tuple[bool, float]:
        """Fallback in-memory : même algo, mais non distribué."""
        with self._fallback_lock:
            now = time.time()
            tokens, last_refill = self._fallback_buckets.get(
                user_id, (float(self.capacity), now),
            )
            elapsed = now - last_refill
            if elapsed > 0:
                tokens = min(self.capacity, tokens + elapsed * self.refill_rate)
                last_refill = now

            if tokens >= n:
                tokens -= n
                self._fallback_buckets[user_id] = (tokens, last_refill)
                self._record_metric(True)
                return True, 0.0
            else:
                needed = n - tokens
                retry_after = needed / self.refill_rate if self.refill_rate > 0 else 60.0
                self._fallback_buckets[user_id] = (tokens, last_refill)
                self._record_metric(False)
                return False, retry_after

    def _record_metric(self, allowed: bool) -> None:
        with self._metrics_lock:
            if allowed:
                self._allowed_count += 1
            else:
                self._blocked_count += 1

    def get_metrics(self) -> dict[str, Any]:
        """Retourne les métriques du limiter."""
        with self._metrics_lock:
            total = self._allowed_count + self._blocked_count
            return {
                "name": self.name,
                "capacity": self.capacity,
                "refill_rate_per_s": self.refill_rate,
                "allowed": self._allowed_count,
                "blocked": self._blocked_count,
                "total": total,
                "block_rate_pct": (
                    round(100 * self._blocked_count / total, 2) if total > 0 else 0.0
                ),
                "backend": "redis" if is_redis_enabled() else "in_memory_fallback",
            }

    def reset_metrics(self) -> None:
        with self._metrics_lock:
            self._allowed_count = 0
            self._blocked_count = 0


# ─────────────────────────────────────────────────────────────────────────────
# Instances pré-configurées (singletons)
# ─────────────────────────────────────────────────────────────────────────────

_CHAT_MAX_RPM = int(os.getenv("SYLEA_CHAT_MAX_RPM", "30"))
_CHAT_BURST = int(os.getenv("SYLEA_CHAT_BURST", str(max(10, _CHAT_MAX_RPM // 3))))

# Rate limiter pour /api/agent3/chat/native
chat_native_limiter = DistributedRateLimiter(
    name="chat_native",
    capacity=_CHAT_BURST,
    refill_rate=_CHAT_MAX_RPM / 60.0,
)

# Rate limiter pour /api/agent3/chat (legacy deprecated)
chat_legacy_limiter = DistributedRateLimiter(
    name="chat_legacy",
    capacity=_CHAT_BURST,
    refill_rate=_CHAT_MAX_RPM / 60.0,
)


__all__ = [
    "DistributedRateLimiter",
    "chat_native_limiter",
    "chat_legacy_limiter",
]
