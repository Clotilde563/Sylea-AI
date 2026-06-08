"""Tests pour api.llm_router (routing + caching + cost estimation)."""

from __future__ import annotations

import importlib

import pytest

import api.llm_router as llm


@pytest.fixture(autouse=True)
def reset_overrides(monkeypatch):
    monkeypatch.delenv("SYLEA_LLM_ROUTE_OVERRIDES", raising=False)
    monkeypatch.delenv("SYLEA_LLM_OPUS_ENABLED", raising=False)
    importlib.reload(llm)


def test_trivial_routes_to_haiku():
    assert llm.route_model("chat_companion") == llm.Model.HAIKU.value
    assert llm.route_model("intent_classification") == llm.Model.HAIKU.value


def test_standard_routes_to_sonnet():
    assert llm.route_model("dilemma_analysis") == llm.Model.SONNET.value
    assert llm.route_model("action_plan_generation") == llm.Model.SONNET.value


def test_critical_downgraded_to_sonnet_when_opus_disabled():
    assert llm.route_model("deep_reasoning") == llm.Model.SONNET.value


def test_critical_uses_opus_when_enabled(monkeypatch):
    monkeypatch.setenv("SYLEA_LLM_OPUS_ENABLED", "true")
    importlib.reload(llm)
    assert llm.route_model("deep_reasoning") == llm.Model.OPUS.value


def test_unknown_task_defaults_to_sonnet():
    assert llm.route_model("nonexistent_task") == llm.Model.SONNET.value


def test_overrides_via_env(monkeypatch):
    monkeypatch.setenv(
        "SYLEA_LLM_ROUTE_OVERRIDES",
        '{"dilemma_analysis": "trivial"}',
    )
    importlib.reload(llm)
    assert llm.route_model("dilemma_analysis") == llm.Model.HAIKU.value


def test_overrides_invalid_json_silently_ignored(monkeypatch):
    monkeypatch.setenv("SYLEA_LLM_ROUTE_OVERRIDES", "{not valid json")
    importlib.reload(llm)
    # Behavior par défaut conservé
    assert llm.route_model("dilemma_analysis") == llm.Model.SONNET.value


# ─── Cached system blocks ────────────────────────────────────────────────────

def test_build_cached_blocks_short_text_not_cached():
    blocks = llm.build_cached_system_blocks(
        static_instructions="short",
        model=llm.Model.SONNET.value,
    )
    assert len(blocks) == 1
    assert "cache_control" not in blocks[0]


def test_build_cached_blocks_long_text_is_cached():
    long_text = "x" * 5000
    blocks = llm.build_cached_system_blocks(
        static_instructions=long_text,
        model=llm.Model.SONNET.value,
    )
    assert len(blocks) == 1
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_haiku_higher_threshold():
    # 5000 chars : cacheable pour Sonnet, mais PAS pour Haiku (seuil 8000)
    mid_text = "x" * 5000
    sonnet_blocks = llm.build_cached_system_blocks(
        static_instructions=mid_text,
        model=llm.Model.SONNET.value,
    )
    haiku_blocks = llm.build_cached_system_blocks(
        static_instructions=mid_text,
        model=llm.Model.HAIKU.value,
    )
    assert sonnet_blocks[0].get("cache_control") is not None
    assert haiku_blocks[0].get("cache_control") is None


def test_dynamic_context_never_cached():
    blocks = llm.build_cached_system_blocks(
        static_instructions="x" * 5000,
        user_profile="y" * 5000,
        dynamic_context="z" * 5000,  # même long, ne devrait pas être caché
    )
    assert len(blocks) == 3
    assert blocks[0].get("cache_control") is not None  # static
    assert blocks[1].get("cache_control") is not None  # user_profile
    assert blocks[2].get("cache_control") is None      # dynamic


def test_empty_inputs_skipped():
    blocks = llm.build_cached_system_blocks(
        static_instructions="x" * 5000,
        user_profile=None,
        dynamic_context=None,
    )
    assert len(blocks) == 1


# ─── Cost estimation ─────────────────────────────────────────────────────────

def test_cost_estimate_haiku():
    est = llm.estimate_cost(
        llm.Model.HAIKU.value,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    # Haiku : 0.25 input + 1.25 output = 1.50 USD per Mtok
    assert abs(est.cost_usd - 1.50) < 0.01


def test_cost_estimate_sonnet():
    est = llm.estimate_cost(
        llm.Model.SONNET.value,
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    # Sonnet : 3 + 15 = 18 USD per Mtok
    assert abs(est.cost_usd - 18.0) < 0.01


def test_cost_estimate_with_cache():
    est = llm.estimate_cost(
        llm.Model.SONNET.value,
        cache_read_tokens=1_000_000,
    )
    # cache_read Sonnet : 0.30 USD per Mtok
    assert abs(est.cost_usd - 0.30) < 0.01


def test_unknown_model_falls_back_to_sonnet():
    est = llm.estimate_cost("unknown-model-x", input_tokens=1_000_000)
    # Doit utiliser Sonnet (3 USD/Mtok input)
    assert abs(est.cost_usd - 3.0) < 0.01


def test_savings_break_even():
    """Vérifie qu'avec 1 réutilisation seule, le cache COÛTE plus cher."""
    result = llm.estimate_savings_with_cache(
        llm.Model.SONNET.value,
        cached_input_tokens=5000,
        reuse_count=1,
    )
    # 1 utilisation : on paye le write sans bénéficier des reads
    assert result["cost_with_cache_usd"] > result["cost_without_cache_usd"]


def test_savings_at_high_reuse():
    """10 utilisations : économie substantielle."""
    result = llm.estimate_savings_with_cache(
        llm.Model.SONNET.value,
        cached_input_tokens=5000,
        reuse_count=10,
    )
    assert result["savings_pct"] > 70  # > 70% économisé


def test_get_router_config_returns_full_info():
    cfg = llm.get_router_config()
    assert "models" in cfg
    assert "opus_enabled" in cfg
    assert "pricing_usd_per_mtok" in cfg
    assert len(cfg["pricing_usd_per_mtok"]) == 3
