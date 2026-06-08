"""Garde d'auth des endpoints Agent 3 sensibles (audit securite 2026-06).

Regression : avant le fix, `_require_agent3_plan` faisait `return` quand
user_id etait None (anonyme) -> les endpoints sensibles (POST /code/execute,
computer-use, acces fichiers) s'executaient SANS authentification = RCE non
authentifiee. On verifie :
  - anonyme (user_id None)        -> 401 (bloque, fail-closed)
  - authentifie sans plan team    -> 403 (reserve team/enterprise)
  - authentifie plan team         -> passe (pas d'exception)
"""

import pytest
from fastapi import HTTPException

from api.routers.agent3_openclaw import _require_agent3_plan


@pytest.mark.asyncio
async def test_anonymous_blocked_401():
    """Un appel NON authentifie ne doit jamais franchir la garde."""
    with pytest.raises(HTTPException) as exc:
        await _require_agent3_plan(db=None, user_id=None)
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_free_user_blocked_403(monkeypatch):
    async def _fake_plan(uid, *a, **k):
        return {"name": "free"}
    monkeypatch.setattr("api.agent3_quotas.get_user_plan_async", _fake_plan)
    with pytest.raises(HTTPException) as exc:
        await _require_agent3_plan(db=None, user_id="u-free")
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_team_user_allowed(monkeypatch):
    async def _fake_plan(uid, *a, **k):
        return {"name": "team"}
    monkeypatch.setattr("api.agent3_quotas.get_user_plan_async", _fake_plan)
    # Ne doit PAS lever d'exception
    await _require_agent3_plan(db=None, user_id="u-team")
