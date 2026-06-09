"""
Garde-fous anti-fuite du planificateur de crons (api/scheduler.py).

Regression de l'incident 2026-06 : un cron Agent 3 oublie reutilisait la meme
session OpenClaw -> l'historique enflait a ~88k tokens et etait re-envoye toutes
les ~30 min, vidant la cle API (le cap $/jour ne couvrait que le fallback direct).

Ces tests verifient les 3 garde-fous, sans reseau ni vraie DB (openclaw_chat et
les writes DB sont mockes).
"""

from __future__ import annotations

import types

import pytest


def _fake_oc_response(text: str = "done"):
    return types.SimpleNamespace(content=text)


@pytest.fixture
def sched(monkeypatch):
    from api.scheduler import SyleaScheduler
    s = SyleaScheduler()
    # On ne touche pas la DB pour l'enregistrement du resultat.
    monkeypatch.setattr(s, "_update_cron_result", lambda cid, txt: None)
    return s


def _patch_openclaw(monkeypatch, calls: list):
    """Mock openclaw_chat : capture le session_key, renvoie une reponse OK."""
    import api.openclaw_bridge as ocb

    def _fake_chat(instruction, session_key=None, **kw):
        calls.append(session_key)
        return _fake_oc_response("ok")

    monkeypatch.setattr(ocb, "openclaw_chat", _fake_chat, raising=False)


def test_fresh_session_per_run(sched, monkeypatch):
    """Chaque execution utilise une session EPHEMERE distincte (anti-88k)."""
    calls: list = []
    _patch_openclaw(monkeypatch, calls)

    sched._execute_cron(None, "cronA", "u1", "fais X")
    sched._execute_cron(None, "cronA", "u1", "fais X")

    assert len(calls) == 2
    assert calls[0] != calls[1], "la session doit etre neuve a chaque run"
    assert all(c and c.startswith("sylea-cron-cronA-") for c in calls)


def test_max_calls_per_day_cap(sched, monkeypatch):
    """Plafond deterministe d'appels LLM/jour, TOUS chemins (openclaw inclus)."""
    monkeypatch.setenv("SYLEA_SCHEDULER_MAX_CALLS_PER_DAY", "3")
    calls: list = []
    _patch_openclaw(monkeypatch, calls)

    # 5 crons DISTINCTS -> seul le plafond global s'applique (pas le per-cron).
    for i in range(5):
        sched._execute_cron(None, f"cron{i}", "u1", "go")

    assert len(calls) == 3  # bloque au-dela de 3 appels/jour


def test_runaway_cron_auto_disabled(sched, monkeypatch):
    """Un cron qui s'emballe est AUTO-DESACTIVE en base apres N runs/jour."""
    monkeypatch.setenv("SYLEA_SCHEDULER_MAX_RUNS_PER_CRON_PER_DAY", "3")
    monkeypatch.setenv("SYLEA_SCHEDULER_MAX_CALLS_PER_DAY", "1000")
    calls: list = []
    _patch_openclaw(monkeypatch, calls)
    disabled: list = []
    monkeypatch.setattr(sched, "_disable_cron", lambda cid: disabled.append(cid))

    for _ in range(5):
        sched._execute_cron(None, "loopy", "u1", "go")

    assert len(calls) == 3                 # 3 executions puis stop
    assert "loopy" in disabled             # auto-desactive au-dela


def test_budget_cap_covers_openclaw_path(sched, monkeypatch):
    """Le cap $/jour est aussi alimente par le chemin OpenClaw (avant : 0 -> jamais)."""
    monkeypatch.setenv("SYLEA_SCHEDULER_MAX_CALLS_PER_DAY", "1000")
    monkeypatch.setenv("SYLEA_SCHEDULER_DAILY_CAP_USD", "0.05")
    monkeypatch.setenv("SYLEA_SCHEDULER_OPENCLAW_EST_USD", "0.02")
    calls: list = []
    _patch_openclaw(monkeypatch, calls)

    # 0.02 * 3 = 0.06 > 0.05 -> le 4e doit etre bloque par le cap budgetaire.
    for i in range(6):
        sched._execute_cron(None, f"c{i}", "u1", "go")

    assert len(calls) == 3
    assert sched._spent_today_usd >= 0.05


def test_daily_reset_reenables(sched, monkeypatch):
    """Les compteurs se reinitialisent a minuit (jour calendaire)."""
    monkeypatch.setenv("SYLEA_SCHEDULER_MAX_CALLS_PER_DAY", "2")
    calls: list = []
    _patch_openclaw(monkeypatch, calls)

    sched._execute_cron(None, "c1", "u1", "go")
    sched._execute_cron(None, "c2", "u1", "go")
    sched._execute_cron(None, "c3", "u1", "go")  # bloque (cap 2)
    assert len(calls) == 2

    # Force un nouveau jour -> reset au prochain execute
    sched._spent_day_key = "2000-01-01"
    sched._execute_cron(None, "c4", "u1", "go")
    assert len(calls) == 3
