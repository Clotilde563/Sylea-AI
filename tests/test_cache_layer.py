"""
Tests de la couche d'abstraction cache (Redis + InMemory backends).

Migration 2026-05-17 : caches in-memory → Redis pour coherence multi-worker.
"""

import os
import time

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_cache_singleton():
    """Reset le singleton entre tests pour isolation."""
    from api.cache_layer import reset_cache_for_tests
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()


@pytest.fixture
def in_memory_cache(monkeypatch):
    """Force le backend InMemory."""
    monkeypatch.delenv("REDIS_URL", raising=False)
    from api.cache_layer import get_cache, reset_cache_for_tests
    reset_cache_for_tests()
    return get_cache()


# ─────────────────────────────────────────────────────────────────────────────
# Tests InMemory backend (toujours dispo)
# ─────────────────────────────────────────────────────────────────────────────

class TestInMemoryBackend:
    async def test_get_set(self, in_memory_cache):
        await in_memory_cache.set("foo", "bar")
        assert await in_memory_cache.get("foo") == "bar"

    async def test_get_unknown(self, in_memory_cache):
        assert await in_memory_cache.get("unknown_key_xyz") is None

    async def test_set_with_ttl(self, in_memory_cache):
        await in_memory_cache.set_with_ttl("foo", "bar", ttl_s=1)
        assert await in_memory_cache.get("foo") == "bar"

    async def test_ttl_expiration(self, in_memory_cache):
        """Test que la valeur expire après le TTL."""
        await in_memory_cache.set_with_ttl("ephemeral", "value", ttl_s=1)
        # Simule le passage du temps en patchant time.time
        import api.cache_layer as cl
        orig_time = time.time
        try:
            # 2 secondes apres
            cl.time.time = lambda: orig_time() + 2.0
            assert await in_memory_cache.get("ephemeral") is None
        finally:
            cl.time.time = orig_time

    async def test_delete(self, in_memory_cache):
        await in_memory_cache.set("k", "v")
        await in_memory_cache.delete("k")
        assert await in_memory_cache.get("k") is None

    async def test_incr_int(self, in_memory_cache):
        v1 = await in_memory_cache.incr("counter", amount=1)
        assert v1 == 1.0
        v2 = await in_memory_cache.incr("counter", amount=5)
        assert v2 == 6.0

    async def test_incr_float(self, in_memory_cache):
        await in_memory_cache.incr("cost", amount=1.5)
        v = await in_memory_cache.incr("cost", amount=2.3)
        assert abs(v - 3.8) < 0.001

    async def test_hash_operations(self, in_memory_cache):
        await in_memory_cache.hset("breakers:tool_a", "state", "closed")
        await in_memory_cache.hset("breakers:tool_a", "failure_count", "0")
        assert await in_memory_cache.hget("breakers:tool_a", "state") == "closed"
        all_fields = await in_memory_cache.hgetall("breakers:tool_a")
        assert all_fields == {"state": "closed", "failure_count": "0"}

    async def test_hincrby(self, in_memory_cache):
        v1 = await in_memory_cache.hincrby("metrics", "calls", amount=1)
        assert v1 == 1
        v2 = await in_memory_cache.hincrby("metrics", "calls", amount=3)
        assert v2 == 4

    async def test_list_lpush_trim(self, in_memory_cache):
        for i in range(5):
            await in_memory_cache.lpush_trim("latencies:tool", f"val_{i}", maxlen=3)
        items = await in_memory_cache.lrange("latencies:tool", 0, -1)
        # On a pushé 5 items mais maxlen=3, donc les 3 derniers (LIFO)
        assert len(items) == 3
        assert items[0] == "val_4"  # le plus récent en tête

    async def test_keys_pattern(self, in_memory_cache):
        await in_memory_cache.set("user:abc:cost", "1.5")
        await in_memory_cache.set("user:def:cost", "2.0")
        await in_memory_cache.set("breaker:tool", "open")
        user_keys = await in_memory_cache.keys("user:*:cost")
        assert sorted(user_keys) == ["user:abc:cost", "user:def:cost"]

    async def test_eval_lua_returns_none_in_memory(self, in_memory_cache):
        """In-memory n'execute pas Lua (le caller doit avoir un fallback Python)."""
        result = await in_memory_cache.eval_lua("return 1", [], [])
        assert result is None


pytestmark = pytest.mark.asyncio


# ─────────────────────────────────────────────────────────────────────────────
# Tests détection backend
# ─────────────────────────────────────────────────────────────────────────────

class TestBackendDetection:
    def test_no_redis_url_uses_in_memory(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        from api.cache_layer import (
            get_cache, reset_cache_for_tests, InMemoryBackend, is_redis_enabled,
        )
        reset_cache_for_tests()
        cache = get_cache()
        assert isinstance(cache, InMemoryBackend)
        assert is_redis_enabled() is False

    def test_invalid_redis_url_falls_back(self, monkeypatch):
        """URL Redis invalide → fallback InMemory (pas de crash)."""
        # On ne peut pas vraiment tester sans fakeredis : si redis-py
        # est installe, l'URL invalide echouera silencieusement au premier
        # call. On verifie juste que get_cache() ne crash pas.
        monkeypatch.setenv("REDIS_URL", "redis://localhost:99999/0")
        from api.cache_layer import (
            get_cache, reset_cache_for_tests, is_redis_enabled,
        )
        reset_cache_for_tests()
        cache = get_cache()
        # Soit Redis instance (la connexion échouera plus tard), soit InMemory fallback.
        assert cache is not None


# ─────────────────────────────────────────────────────────────────────────────
# Tests Redis backend (skippés si fakeredis pas installé)
# ─────────────────────────────────────────────────────────────────────────────

fakeredis = pytest.importorskip("fakeredis", reason="fakeredis pas installe")


@pytest.fixture
def redis_cache(monkeypatch):
    """Force backend Redis via fakeredis (mock in-process)."""
    import fakeredis.aioredis
    from api.cache_layer import RedisBackend, reset_cache_for_tests
    reset_cache_for_tests()
    # On instancie directement le backend avec un fake client
    backend = RedisBackend.__new__(RedisBackend)
    backend._client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    backend._url = "fakeredis://test"
    return backend


class TestRedisBackend:
    async def test_set_get_redis(self, redis_cache):
        await redis_cache.set("k", "v")
        assert await redis_cache.get("k") == "v"

    async def test_incr_atomic_redis(self, redis_cache):
        await redis_cache.incr("counter", amount=1.5)
        v = await redis_cache.incr("counter", amount=2.5)
        assert float(v) == 4.0

    async def test_hash_redis(self, redis_cache):
        await redis_cache.hset("h", "f1", "v1")
        await redis_cache.hset("h", "f2", "v2")
        assert await redis_cache.hgetall("h") == {"f1": "v1", "f2": "v2"}
        assert await redis_cache.hget("h", "f1") == "v1"

    async def test_ttl_redis(self, redis_cache):
        await redis_cache.set_with_ttl("eph", "x", ttl_s=10)
        assert await redis_cache.get("eph") == "x"


# ─────────────────────────────────────────────────────────────────────────────
# Tests Rate Limiter distribué
# ─────────────────────────────────────────────────────────────────────────────

class TestDistributedRateLimiter:
    async def test_acquire_first_request_allowed(self, in_memory_cache):
        from api.distributed_rate_limiter import DistributedRateLimiter
        rl = DistributedRateLimiter("test", capacity=5, refill_rate=1.0)
        allowed, retry = await rl.acquire("user_1")
        assert allowed is True
        assert retry == 0.0

    async def test_acquire_exhausts_burst(self, in_memory_cache):
        from api.distributed_rate_limiter import DistributedRateLimiter
        rl = DistributedRateLimiter("burst_test", capacity=3, refill_rate=0.01)
        # On consomme la capacité totale
        for i in range(3):
            allowed, _ = await rl.acquire("user_1")
            assert allowed is True, f"Request {i+1} should be allowed"
        # La 4ème requête doit être bloquée
        allowed, retry = await rl.acquire("user_1")
        assert allowed is False
        assert retry > 0

    async def test_acquire_isolates_users(self, in_memory_cache):
        from api.distributed_rate_limiter import DistributedRateLimiter
        rl = DistributedRateLimiter("isolation_test", capacity=2, refill_rate=0.01)
        # User A consomme tout
        for _ in range(2):
            ok, _ = await rl.acquire("user_a")
            assert ok is True
        ok, _ = await rl.acquire("user_a")
        assert ok is False
        # User B doit avoir son propre bucket
        ok, _ = await rl.acquire("user_b")
        assert ok is True

    async def test_metrics(self, in_memory_cache):
        from api.distributed_rate_limiter import DistributedRateLimiter
        rl = DistributedRateLimiter("metrics_test", capacity=2, refill_rate=0.01)
        await rl.acquire("u1")  # allowed
        await rl.acquire("u1")  # allowed
        await rl.acquire("u1")  # blocked
        m = rl.get_metrics()
        assert m["allowed"] == 2
        assert m["blocked"] == 1
        assert m["total"] == 3
        assert 30 < m["block_rate_pct"] < 40
