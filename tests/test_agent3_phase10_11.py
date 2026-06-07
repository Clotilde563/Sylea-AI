"""
Tests Phase 10+11 — Tier 4 (Quotas/Workspaces/Admin/API publique)
                  + Tier 5 partial (Self-reflection/Long-term/Voice).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sylea.core.storage.database import DatabaseManager
from tests.conftest import make_shared_db, dispose_shared_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB SQLite partagee (sync + async) via fichier temp.
    Migration shared-DB : remplace `:memory:` pour permettre a l'async
    session_factory de pointer sur la meme DB."""
    d = make_shared_db(tmp_path, monkeypatch)
    # Bootstrap tables Agent 3 utilisees par les helpers async (qui ne creent
    # pas leurs tables a la volee, contrairement aux variantes sync).
    try:
        from api.agent3_quotas import ensure_quota_tables
        ensure_quota_tables(d)
    except Exception:
        pass
    try:
        import asyncio as _asyncio
        from api.agent3_workspaces import ensure_workspace_tables_async
        _asyncio.run(ensure_workspace_tables_async())
    except Exception:
        pass
    try:
        import asyncio as _asyncio
        from api.agent3_admin import ensure_admin_columns_async
        _asyncio.run(ensure_admin_columns_async())
    except Exception:
        pass
    try:
        from api.agent3_api_keys import ensure_api_keys_table
        ensure_api_keys_table(d)
    except Exception:
        pass
    try:
        from api.agent3_webhooks import ensure_webhook_tables
        ensure_webhook_tables(d)
    except Exception:
        pass
    yield d
    dispose_shared_db(d)


def _seed_user(db, user_id: str, email: str) -> None:
    try:
        db.conn.execute(
            "INSERT INTO users (id, email, hashed_password, created_at) VALUES (?,?,?,?)",
            (user_id, email, "pw", "2026-04-24"),
        )
        db.conn.commit()
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# Phase 10A — Plans & Quotas
# ═════════════════════════════════════════════════════════════════════════════

class TestPlans:
    def test_default_plan_is_free(self, db):
        from api.agent3_quotas import get_user_plan_async
        plan = asyncio.run(get_user_plan_async("u_new"))
        assert plan["name"] == "free"
        assert plan["limits"]["tokens_per_month"] == 100_000

    def test_set_plan_advanced(self, db):
        from api.agent3_quotas import set_user_plan_async, get_user_plan_async
        # NB (audit 2026-06) : plan "pro" renomme en "advanced".
        r = asyncio.run(set_user_plan_async("u_pro", "advanced"))
        assert r["ok"] is True
        plan = asyncio.run(get_user_plan_async("u_pro"))
        assert plan["name"] == "advanced"
        assert plan["limits"]["tokens_per_month"] == 1_000_000

    def test_set_unknown_plan_rejected(self, db):
        from api.agent3_quotas import set_user_plan_async
        r = asyncio.run(set_user_plan_async("u", "premium"))
        assert r["ok"] is False

    def test_custom_limits_override(self, db):
        from api.agent3_quotas import set_user_plan_async, get_user_plan_async
        asyncio.run(set_user_plan_async("u", "free", custom_limits={"tokens_per_month": 500_000}))
        plan = asyncio.run(get_user_plan_async("u"))
        assert plan["limits"]["tokens_per_month"] == 500_000


class TestQuotas:
    def test_record_and_get_usage(self, db):
        from api.agent3_quotas import record_usage_async, get_usage_async
        asyncio.run(record_usage_async("u1", "tokens", 5000))
        asyncio.run(record_usage_async("u1", "tokens", 3000))
        usage = asyncio.run(get_usage_async("u1"))
        assert usage["tokens"] == 8000

    def test_check_quota_under_limit(self, db):
        from api.agent3_quotas import check_quota_async, record_usage_async
        asyncio.run(record_usage_async("u1", "tokens", 50_000))
        ok, _, rem = asyncio.run(check_quota_async("u1", "tokens", 1000))
        assert ok is True
        assert rem > 0

    def test_check_quota_over_limit(self, db):
        from api.agent3_quotas import check_quota_async, record_usage_async
        # Free = 100k tokens
        asyncio.run(record_usage_async("u1", "tokens", 99_000))
        ok, reason, rem = asyncio.run(check_quota_async("u1", "tokens", 5000))
        assert ok is False
        assert "depasse" in reason.lower() or "quota" in reason.lower()

    def test_unlimited_team_plan(self, db):
        from api.agent3_quotas import set_user_plan_async, check_quota_async, record_usage_async
        asyncio.run(set_user_plan_async("u_team", "team"))
        # Team : skills_installed -1 = unlimited
        ok, reason, _ = asyncio.run(check_quota_async("u_team", "skills_installed", 999_999))
        assert ok is True

    def test_isolation_per_user(self, db):
        from api.agent3_quotas import record_usage_async, get_usage_async
        asyncio.run(record_usage_async("alice", "tokens", 10_000))
        asyncio.run(record_usage_async("bob", "tokens", 20_000))
        assert asyncio.run(get_usage_async("alice"))["tokens"] == 10_000
        assert asyncio.run(get_usage_async("bob"))["tokens"] == 20_000

    def test_reset_usage(self, db):
        from api.agent3_quotas import record_usage_async, reset_usage_async, get_usage_async
        asyncio.run(record_usage_async("u", "tokens", 5000))
        asyncio.run(reset_usage_async("u"))
        assert asyncio.run(get_usage_async("u"))["tokens"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Phase 10B — Workspaces
# ═════════════════════════════════════════════════════════════════════════════

class TestWorkspaces:
    def test_create_workspace_and_owner_role(self, db):
        from api.agent3_workspaces import create_workspace_async, get_user_role_async
        r = asyncio.run(create_workspace_async("alice", "My Team"))
        assert r["ok"] is True
        assert asyncio.run(get_user_role_async(r["workspace_id"], "alice")) == "owner"

    def test_add_member_by_owner(self, db):
        from api.agent3_workspaces import create_workspace_async, add_member_async, list_members_async
        r = asyncio.run(create_workspace_async("alice", "T1"))
        wid = r["workspace_id"]
        m = asyncio.run(add_member_async(wid, "bob", "member", requester_id="alice"))
        assert m["ok"] is True
        members = asyncio.run(list_members_async(wid))
        assert len(members) == 2

    def test_add_member_non_admin_forbidden(self, db):
        from api.agent3_workspaces import create_workspace_async, add_member_async
        r = asyncio.run(create_workspace_async("alice", "T"))
        asyncio.run(add_member_async(r["workspace_id"], "bob", "member", requester_id="alice"))
        # Bob (member) essaie d'inviter Charlie
        m = asyncio.run(add_member_async(r["workspace_id"], "charlie", "member", requester_id="bob"))
        assert m["ok"] is False

    def test_remove_owner_forbidden(self, db):
        from api.agent3_workspaces import create_workspace_async, remove_member_async
        r = asyncio.run(create_workspace_async("alice", "T"))
        m = asyncio.run(remove_member_async(r["workspace_id"], "alice", requester_id="alice"))
        assert m["ok"] is False

    def test_list_user_workspaces(self, db):
        from api.agent3_workspaces import create_workspace_async, list_user_workspaces_async
        asyncio.run(create_workspace_async("u", "A"))
        asyncio.run(create_workspace_async("u", "B"))
        ws = asyncio.run(list_user_workspaces_async("u"))
        assert len(ws) == 2

    def test_share_memory_requires_member(self, db):
        from api.agent3_workspaces import create_workspace_async, share_memory_async
        r = asyncio.run(create_workspace_async("alice", "T"))
        # Alice membre (owner) OK
        ok = asyncio.run(share_memory_async(r["workspace_id"], "alice", key="k", value="v"))
        assert ok["ok"] is True
        # Bob pas membre → forbidden
        ko = asyncio.run(share_memory_async(r["workspace_id"], "bob", key="k2", value="v2"))
        assert ko["ok"] is False

    def test_delete_workspace_by_owner(self, db):
        from api.agent3_workspaces import create_workspace_async, delete_workspace_async, get_workspace_async
        r = asyncio.run(create_workspace_async("alice", "T"))
        wid = r["workspace_id"]
        d = asyncio.run(delete_workspace_async(wid, "alice"))
        assert d["ok"] is True
        assert asyncio.run(get_workspace_async(wid)) is None


# ═════════════════════════════════════════════════════════════════════════════
# Phase 10C — Admin
# ═════════════════════════════════════════════════════════════════════════════

class TestAdmin:
    def test_is_admin_false_by_default(self, db):
        from api.agent3_admin import is_admin_async
        _seed_user(db, "u_normal", "u@x.com")
        assert asyncio.run(is_admin_async("u_normal")) is False

    def test_promote_and_demote(self, db):
        from api.agent3_admin import is_admin_async, promote_user_to_admin_async, demote_user_async
        _seed_user(db, "u_admin", "a@x.com")
        asyncio.run(promote_user_to_admin_async("u_admin"))
        assert asyncio.run(is_admin_async("u_admin")) is True
        asyncio.run(demote_user_async("u_admin"))
        assert asyncio.run(is_admin_async("u_admin")) is False

    def test_env_whitelist_auto_promote(self, db, monkeypatch):
        from api.agent3_admin import is_admin_async
        _seed_user(db, "u_env", "envadmin@sylea.ai")
        monkeypatch.setenv("SYLEA_ADMIN_EMAILS", "envadmin@sylea.ai")
        assert asyncio.run(is_admin_async("u_env")) is True

    def test_disable_user(self, db):
        from api.agent3_admin import disable_user_async, ensure_admin_columns_async
        _seed_user(db, "u_dis", "dis@x.com")
        r = asyncio.run(disable_user_async("u_dis"))
        assert r["ok"] is True
        row = db.conn.execute(
            "SELECT disabled_at FROM users WHERE id = ?", ("u_dis",),
        ).fetchone()
        assert row[0] is not None

    def test_global_stats(self, db):
        from api.agent3_admin import get_global_stats_async
        _seed_user(db, "u_a", "a@x.com")
        _seed_user(db, "u_b", "b@x.com")
        stats = asyncio.run(get_global_stats_async())
        assert stats["users_total"] >= 2
        assert "plans_distribution" in stats


# ═════════════════════════════════════════════════════════════════════════════
# Phase 10D — API keys + Webhooks
# ═════════════════════════════════════════════════════════════════════════════

class TestAPIKeys:
    def test_create_returns_plaintext_once(self, db):
        from api.agent3_api_keys import create_api_key_async
        r = asyncio.run(create_api_key_async("u", "My App"))
        assert r["ok"] is True
        assert r["token"].startswith("sk-sylea-")
        assert "warning" in r

    def test_validate_valid_token(self, db):
        from api.agent3_api_keys import create_api_key_async, validate_api_key_async
        r = asyncio.run(create_api_key_async("u", "k1"))
        res = asyncio.run(validate_api_key_async(r["token"]))
        assert res is not None
        assert res["user_id"] == "u"

    def test_validate_invalid_token(self, db):
        from api.agent3_api_keys import validate_api_key_async
        assert asyncio.run(validate_api_key_async("sk-sylea-invalid")) is None
        assert asyncio.run(validate_api_key_async("not-a-key")) is None

    def test_revoke_disables_token(self, db):
        from api.agent3_api_keys import create_api_key_async, revoke_api_key_async, validate_api_key_async
        r = asyncio.run(create_api_key_async("u", "k"))
        asyncio.run(revoke_api_key_async(r["key_id"], "u"))
        assert asyncio.run(validate_api_key_async(r["token"])) is None

    def test_revoke_wrong_owner_forbidden(self, db):
        from api.agent3_api_keys import create_api_key_async, revoke_api_key_async
        r = asyncio.run(create_api_key_async("alice", "k"))
        res = asyncio.run(revoke_api_key_async(r["key_id"], "bob"))
        assert res["ok"] is False

    def test_list_keys_no_plaintext(self, db):
        from api.agent3_api_keys import create_api_key_async, list_api_keys_async
        asyncio.run(create_api_key_async("u", "k1"))
        keys = asyncio.run(list_api_keys_async("u"))
        assert len(keys) == 1
        assert "prefix" in keys[0]
        assert "token" not in keys[0]  # jamais reexpose


class TestWebhooks:
    def test_create_subscription_https_required(self, db):
        from api.agent3_webhooks import create_subscription_async
        # http:// public refuse
        r = asyncio.run(create_subscription_async("u", "http://evil.example.com/hook", ["message.completed"]))
        assert r["ok"] is False

    def test_create_subscription_valid(self, db):
        from api.agent3_webhooks import create_subscription_async
        r = asyncio.run(create_subscription_async(
            "u", "https://api.example.com/webhook", ["message.completed"],
        ))
        assert r["ok"] is True
        assert "secret" in r

    def test_invalid_event_rejected(self, db):
        from api.agent3_webhooks import create_subscription_async
        r = asyncio.run(create_subscription_async(
            "u", "https://api.example.com/h", ["unknown.event"],
        ))
        assert r["ok"] is False

    def test_list_and_delete(self, db):
        from api.agent3_webhooks import (
            create_subscription_async, list_subscriptions_async, delete_subscription_async,
        )
        r = asyncio.run(create_subscription_async(
            "u", "https://api.example.com/h", ["*"],
        ))
        subs = asyncio.run(list_subscriptions_async("u"))
        assert len(subs) == 1
        asyncio.run(delete_subscription_async(r["subscription_id"], "u"))
        assert asyncio.run(list_subscriptions_async("u")) == []

    @pytest.mark.asyncio
    async def test_fire_event_no_subs_returns_zero(self, db):
        from api.agent3_webhooks import fire_event
        r = await fire_event(db, "message.completed", {"x": 1}, user_id="u_nosub")
        assert r["delivered"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Phase 11A — Self-reflection
# ═════════════════════════════════════════════════════════════════════════════

class TestSelfReflection:
    def test_short_response_no_reflection(self):
        from api.agent3_self_reflection import should_reflect
        ok, _ = should_reflect("Bonjour !", tool_uses_count=0)
        assert ok is False

    def test_long_response_triggers(self, monkeypatch):
        from api.agent3_self_reflection import should_reflect
        monkeypatch.setenv("SYLEA_REFLECTION_ENABLED", "1")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        draft = "A" * 600
        ok, _ = should_reflect(draft, tool_uses_count=0)
        assert ok is True

    def test_many_tools_triggers(self, monkeypatch):
        from api.agent3_self_reflection import should_reflect
        monkeypatch.setenv("SYLEA_REFLECTION_ENABLED", "1")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        ok, _ = should_reflect("short", tool_uses_count=5)
        assert ok is True

    def test_opt_out(self, monkeypatch):
        from api.agent3_self_reflection import should_reflect
        monkeypatch.setenv("SYLEA_REFLECTION_ENABLED", "1")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        ok, reason = should_reflect("x" * 600, user_opted_in=False)
        assert ok is False
        assert "opt_out" in reason

    @pytest.mark.asyncio
    async def test_review_response_ok(self):
        from api.agent3_self_reflection import review_response
        client = MagicMock()
        block = MagicMock()
        block.text = "OK"
        resp = MagicMock()
        resp.content = [block]
        client.messages.create = AsyncMock(return_value=resp)
        result = await review_response("Some draft response", client)
        assert result["has_issues"] is False

    @pytest.mark.asyncio
    async def test_review_response_with_issues(self):
        from api.agent3_self_reflection import review_response
        client = MagicMock()
        block = MagicMock()
        block.text = "- [FACTUEL] La date est fausse\n- [OUBLI] Manque la conclusion"
        resp = MagicMock()
        resp.content = [block]
        client.messages.create = AsyncMock(return_value=resp)
        result = await review_response("draft", client)
        assert result["has_issues"] is True
        assert len(result["issues"]) == 2

    @pytest.mark.asyncio
    async def test_reflect_pipeline_no_issues(self, monkeypatch):
        from api.agent3_self_reflection import reflect_and_refine
        monkeypatch.setenv("SYLEA_REFLECTION_ENABLED", "1")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        client = MagicMock()
        block = MagicMock()
        block.text = "OK"
        resp = MagicMock()
        resp.content = [block]
        client.messages.create = AsyncMock(return_value=resp)
        draft = "A" * 600
        r = await reflect_and_refine(draft, client)
        assert r["reflected"] is True
        assert r["changed"] is False
        assert r["final_text"] == draft


# ═════════════════════════════════════════════════════════════════════════════
# Phase 11B — Long-term planner (SUPPRIME)
# Le module api/agent3_longterm a ete retire dans une session precedente
# (l'utilisateur a juge la fonctionnalite redondante avec memory + sous-objectifs
# auto-generes a l'onboarding). Les 8 tests de TestLongTerm ont ete supprimes
# en consequence.
# ═════════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════════
# Phase 11C — Voice
# ═════════════════════════════════════════════════════════════════════════════

class TestVoice:
    def test_chunk_for_tts_single_short(self):
        from api.agent3_voice import chunk_for_tts_stream
        chunks = chunk_for_tts_stream("Coucou.")
        # 40 chars min, phrase trop courte → reste dans buffer final
        assert len(chunks) == 1

    def test_chunk_for_tts_multiple_sentences(self):
        from api.agent3_voice import chunk_for_tts_stream
        text = (
            "Voici la premiere phrase complete assez longue pour etre emise. "
            "Ensuite arrive la deuxieme phrase qui est aussi assez longue. "
            "Et enfin la troisieme phrase qui termine le message correctement."
        )
        chunks = chunk_for_tts_stream(text)
        assert len(chunks) >= 2

    @pytest.mark.asyncio
    async def test_transcribe_empty_audio(self):
        from api.agent3_voice import transcribe_audio
        r = await transcribe_audio(b"")
        assert "error" in r

    @pytest.mark.asyncio
    async def test_transcribe_no_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from api.agent3_voice import transcribe_audio
        r = await transcribe_audio(b"fake-mp3-bytes", filename="audio.mp3")
        assert "OPENAI_API_KEY" in (r.get("error") or "")

    @pytest.mark.asyncio
    async def test_synthesize_empty(self):
        from api.agent3_voice import synthesize_speech
        r = await synthesize_speech("")
        assert "error" in r

    @pytest.mark.asyncio
    async def test_synthesize_no_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from api.agent3_voice import synthesize_speech
        r = await synthesize_speech("Bonjour")
        assert "error" in r

    @pytest.mark.asyncio
    async def test_transcribe_unsupported_format(self):
        from api.agent3_voice import transcribe_audio
        r = await transcribe_audio(b"data", filename="doc.pdf")
        assert "format" in (r.get("error") or "").lower()
