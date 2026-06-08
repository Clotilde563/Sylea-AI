"""Tests pour secrets_manager (backend env + cache)."""

from __future__ import annotations

import os
import time

import pytest

import api.secrets_manager as sm


@pytest.fixture(autouse=True)
def reset_module_state(monkeypatch):
    """Reset le cache + le backend singleton entre les tests."""
    sm._backend = None
    sm._secret_cache.clear()
    yield
    sm._backend = None
    sm._secret_cache.clear()


def test_env_backend_reads_environ(monkeypatch):
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "env")
    monkeypatch.setenv("MY_SECRET", "value-123")
    assert sm.get_secret("MY_SECRET") == "value-123"


def test_default_returned_when_missing(monkeypatch):
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "env")
    monkeypatch.delenv("MISSING_KEY", raising=False)
    assert sm.get_secret("MISSING_KEY", default="fallback") == "fallback"


def test_required_raises_when_missing(monkeypatch):
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "env")
    monkeypatch.delenv("REQUIRED_KEY", raising=False)
    with pytest.raises(RuntimeError, match="obligatoire"):
        sm.get_secret_required("REQUIRED_KEY")


def test_required_returns_when_present(monkeypatch):
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "env")
    monkeypatch.setenv("REQUIRED_KEY", "yes")
    assert sm.get_secret_required("REQUIRED_KEY") == "yes"


def test_cache_hits_avoid_backend(monkeypatch):
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "env")
    monkeypatch.setenv("KEY_X", "first-value")
    assert sm.get_secret("KEY_X") == "first-value"
    # Modifier l'env : le cache doit servir l'ancienne valeur
    monkeypatch.setenv("KEY_X", "second-value")
    assert sm.get_secret("KEY_X") == "first-value"


def test_clear_cache_forces_re_read(monkeypatch):
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "env")
    monkeypatch.setenv("KEY_Y", "a")
    assert sm.get_secret("KEY_Y") == "a"
    monkeypatch.setenv("KEY_Y", "b")
    sm.clear_secret_cache("KEY_Y")
    assert sm.get_secret("KEY_Y") == "b"


def test_clear_all_cache(monkeypatch):
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "env")
    monkeypatch.setenv("K1", "v1")
    monkeypatch.setenv("K2", "v2")
    sm.get_secret("K1")
    sm.get_secret("K2")
    assert len(sm._secret_cache) == 2
    sm.clear_secret_cache()
    assert len(sm._secret_cache) == 0


def test_env_override_wins_over_backend(monkeypatch):
    """get_secret_with_env_override : env var locale gagne toujours."""
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "env")
    monkeypatch.setenv("OVERRIDE_KEY", "from-env")
    # Cache une valeur différente pour simuler un backend distant
    sm._secret_cache["OVERRIDE_KEY"] = ("from-backend", time.time() + 3600)
    # env_override doit prioriser l'env
    assert sm.get_secret_with_env_override("OVERRIDE_KEY") == "from-env"


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "azurevault")
    with pytest.raises(RuntimeError, match="inconnu"):
        sm.get_secrets_backend()


def test_require_remote_blocks_env(monkeypatch):
    """SYLEA_REQUIRE_REMOTE_SECRETS=true doit refuser le backend env."""
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "env")
    monkeypatch.setenv("SYLEA_REQUIRE_REMOTE_SECRETS", "true")
    with pytest.raises(RuntimeError, match="REQUIRE_REMOTE"):
        sm.get_secrets_backend()


def test_diagnostic_info(monkeypatch):
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "env")
    monkeypatch.delenv("SYLEA_REQUIRE_REMOTE_SECRETS", raising=False)
    info = sm.list_active_backend_info()
    assert info["backend"] == "env"
    assert "cache_size" in info


def test_cache_caches_misses_too(monkeypatch):
    """Même les misses (None) sont cachés pour ne pas spammer le backend."""
    monkeypatch.setenv("SYLEA_SECRETS_BACKEND", "env")
    monkeypatch.delenv("ABSENT_KEY", raising=False)
    sm.get_secret("ABSENT_KEY")
    assert "ABSENT_KEY" in sm._secret_cache
    val, exp = sm._secret_cache["ABSENT_KEY"]
    assert val is None
    assert exp > time.time()
