"""
Tests Phase 10+11 — Tier 4 (Quotas/Workspaces/Admin/API publique)
                  + Tier 5 partial (Self-reflection/Long-term/Voice).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sylea.core.storage.database import DatabaseManager


@pytest.fixture
def db():
    d = DatabaseManager(db_path=Path(":memory:"))
    d.connect()
    return d


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
        from api.agent3_quotas import get_user_plan
        plan = get_user_plan(db, "u_new")
        assert plan["name"] == "free"
        assert plan["limits"]["tokens_per_month"] == 100_000

    def test_set_plan_pro(self, db):
        from api.agent3_quotas import set_user_plan, get_user_plan
        r = set_user_plan(db, "u_pro", "pro")
        assert r["ok"] is True
        plan = get_user_plan(db, "u_pro")
        assert plan["name"] == "pro"
        assert plan["limits"]["tokens_per_month"] == 1_000_000

    def test_set_unknown_plan_rejected(self, db):
        from api.agent3_quotas import set_user_plan
        r = set_user_plan(db, "u", "premium")
        assert r["ok"] is False

    def test_custom_limits_override(self, db):
        from api.agent3_quotas import set_user_plan, get_user_plan
        set_user_plan(db, "u", "free", custom_limits={"tokens_per_month": 500_000})
        plan = get_user_plan(db, "u")
        assert plan["limits"]["tokens_per_month"] == 500_000


class TestQuotas:
    def test_record_and_get_usage(self, db):
        from api.agent3_quotas import record_usage, get_usage
        record_usage(db, "u1", "tokens", 5000)
        record_usage(db, "u1", "tokens", 3000)
        usage = get_usage(db, "u1")
        assert usage["tokens"] == 8000

    def test_check_quota_under_limit(self, db):
        from api.agent3_quotas import check_quota, record_usage
        record_usage(db, "u1", "tokens", 50_000)
        ok, _, rem = check_quota(db, "u1", "tokens", 1000)
        assert ok is True
        assert rem > 0

    def test_check_quota_over_limit(self, db):
        from api.agent3_quotas import check_quota, record_usage
        # Free = 100k tokens
        record_usage(db, "u1", "tokens", 99_000)
        ok, reason, rem = check_quota(db, "u1", "tokens", 5000)
        assert ok is False
        assert "depasse" in reason.lower() or "quota" in reason.lower()

    def test_unlimited_team_plan(self, db):
        from api.agent3_quotas import set_user_plan, check_quota, record_usage
        set_user_plan(db, "u_team", "team")
        # Team : skills_installed -1 = unlimited
        ok, reason, _ = check_quota(db, "u_team", "skills_installed", 999_999)
        assert ok is True

    def test_isolation_per_user(self, db):
        from api.agent3_quotas import record_usage, get_usage
        record_usage(db, "alice", "tokens", 10_000)
        record_usage(db, "bob", "tokens", 20_000)
        assert get_usage(db, "alice")["tokens"] == 10_000
        assert get_usage(db, "bob")["tokens"] == 20_000

    def test_reset_usage(self, db):
        from api.agent3_quotas import record_usage, reset_usage, get_usage
        record_usage(db, "u", "tokens", 5000)
        reset_usage(db, "u")
        assert get_usage(db, "u")["tokens"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# Phase 10B — Workspaces
# ═════════════════════════════════════════════════════════════════════════════

class TestWorkspaces:
    def test_create_workspace_and_owner_role(self, db):
        from api.agent3_workspaces import create_workspace, get_user_role
        r = create_workspace(db, "alice", "My Team")
        assert r["ok"] is True
        assert get_user_role(db, r["workspace_id"], "alice") == "owner"

    def test_add_member_by_owner(self, db):
        from api.agent3_workspaces import create_workspace, add_member, list_members
        r = create_workspace(db, "alice", "T1")
        wid = r["workspace_id"]
        m = add_member(db, wid, "bob", "member", requester_id="alice")
        assert m["ok"] is True
        members = list_members(db, wid)
        assert len(members) == 2

    def test_add_member_non_admin_forbidden(self, db):
        from api.agent3_workspaces import create_workspace, add_member
        r = create_workspace(db, "alice", "T")
        add_member(db, r["workspace_id"], "bob", "member", requester_id="alice")
        # Bob (member) essaie d'inviter Charlie
        m = add_member(db, r["workspace_id"], "charlie", "member", requester_id="bob")
        assert m["ok"] is False

    def test_remove_owner_forbidden(self, db):
        from api.agent3_workspaces import create_workspace, remove_member
        r = create_workspace(db, "alice", "T")
        m = remove_member(db, r["workspace_id"], "alice", requester_id="alice")
        assert m["ok"] is False

    def test_list_user_workspaces(self, db):
        from api.agent3_workspaces import create_workspace, list_user_workspaces
        create_workspace(db, "u", "A")
        create_workspace(db, "u", "B")
        ws = list_user_workspaces(db, "u")
        assert len(ws) == 2

    def test_share_memory_requires_member(self, db):
        from api.agent3_workspaces import create_workspace, share_memory
        r = create_workspace(db, "alice", "T")
        # Alice membre (owner) OK
        ok = share_memory(db, r["workspace_id"], "alice", key="k", value="v")
        assert ok["ok"] is True
        # Bob pas membre → forbidden
        ko = share_memory(db, r["workspace_id"], "bob", key="k2", value="v2")
        assert ko["ok"] is False

    def test_delete_workspace_by_owner(self, db):
        from api.agent3_workspaces import create_workspace, delete_workspace, get_workspace
        r = create_workspace(db, "alice", "T")
        wid = r["workspace_id"]
        d = delete_workspace(db, wid, "alice")
        assert d["ok"] is True
        assert get_workspace(db, wid) is None


# ═════════════════════════════════════════════════════════════════════════════
# Phase 10C — Admin
# ═════════════════════════════════════════════════════════════════════════════

class TestAdmin:
    def test_is_admin_false_by_default(self, db):
        from api.agent3_admin import is_admin
        _seed_user(db, "u_normal", "u@x.com")
        assert is_admin(db, "u_normal") is False

    def test_promote_and_demote(self, db):
        from api.agent3_admin import is_admin, promote_user_to_admin, demote_user
        _seed_user(db, "u_admin", "a@x.com")
        promote_user_to_admin(db, "u_admin")
        assert is_admin(db, "u_admin") is True
        demote_user(db, "u_admin")
        assert is_admin(db, "u_admin") is False

    def test_env_whitelist_auto_promote(self, db, monkeypatch):
        from api.agent3_admin import is_admin
        _seed_user(db, "u_env", "envadmin@sylea.ai")
        monkeypatch.setenv("SYLEA_ADMIN_EMAILS", "envadmin@sylea.ai")
        assert is_admin(db, "u_env") is True

    def test_disable_user(self, db):
        from api.agent3_admin import disable_user, ensure_admin_columns
        _seed_user(db, "u_dis", "dis@x.com")
        r = disable_user(db, "u_dis")
        assert r["ok"] is True
        row = db.conn.execute(
            "SELECT disabled_at FROM users WHERE id = ?", ("u_dis",),
        ).fetchone()
        assert row[0] is not None

    def test_global_stats(self, db):
        from api.agent3_admin import get_global_stats
        _seed_user(db, "u_a", "a@x.com")
        _seed_user(db, "u_b", "b@x.com")
        stats = get_global_stats(db)
        assert stats["users_total"] >= 2
        assert "plans_distribution" in stats


# ═════════════════════════════════════════════════════════════════════════════
# Phase 10D — API keys + Webhooks
# ═════════════════════════════════════════════════════════════════════════════

class TestAPIKeys:
    def test_create_returns_plaintext_once(self, db):
        from api.agent3_api_keys import create_api_key
        r = create_api_key(db, "u", "My App")
        assert r["ok"] is True
        assert r["token"].startswith("sk-sylea-")
        assert "warning" in r

    def test_validate_valid_token(self, db):
        from api.agent3_api_keys import create_api_key, validate_api_key
        r = create_api_key(db, "u", "k1")
        res = validate_api_key(db, r["token"])
        assert res is not None
        assert res["user_id"] == "u"

    def test_validate_invalid_token(self, db):
        from api.agent3_api_keys import validate_api_key
        assert validate_api_key(db, "sk-sylea-invalid") is None
        assert validate_api_key(db, "not-a-key") is None

    def test_revoke_disables_token(self, db):
        from api.agent3_api_keys import create_api_key, revoke_api_key, validate_api_key
        r = create_api_key(db, "u", "k")
        revoke_api_key(db, r["key_id"], "u")
        assert validate_api_key(db, r["token"]) is None

    def test_revoke_wrong_owner_forbidden(self, db):
        from api.agent3_api_keys import create_api_key, revoke_api_key
        r = create_api_key(db, "alice", "k")
        res = revoke_api_key(db, r["key_id"], "bob")
        assert res["ok"] is False

    def test_list_keys_no_plaintext(self, db):
        from api.agent3_api_keys import create_api_key, list_api_keys
        create_api_key(db, "u", "k1")
        keys = list_api_keys(db, "u")
        assert len(keys) == 1
        assert "prefix" in keys[0]
        assert "token" not in keys[0]  # jamais reexpose


class TestWebhooks:
    def test_create_subscription_https_required(self, db):
        from api.agent3_webhooks import create_subscription
        # http:// public refuse
        r = create_subscription(db, "u", "http://evil.example.com/hook", ["message.completed"])
        assert r["ok"] is False

    def test_create_subscription_valid(self, db):
        from api.agent3_webhooks import create_subscription
        r = create_subscription(
            db, "u", "https://api.example.com/webhook", ["message.completed"],
        )
        assert r["ok"] is True
        assert "secret" in r

    def test_invalid_event_rejected(self, db):
        from api.agent3_webhooks import create_subscription
        r = create_subscription(
            db, "u", "https://api.example.com/h", ["unknown.event"],
        )
        assert r["ok"] is False

    def test_list_and_delete(self, db):
        from api.agent3_webhooks import (
            create_subscription, list_subscriptions, delete_subscription,
        )
        r = create_subscription(
            db, "u", "https://api.example.com/h", ["*"],
        )
        subs = list_subscriptions(db, "u")
        assert len(subs) == 1
        delete_subscription(db, r["subscription_id"], "u")
        assert list_subscriptions(db, "u") == []

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
# Phase 11B — Long-term planner
# ═════════════════════════════════════════════════════════════════════════════

class TestLongTerm:
    def test_create_and_get_plan(self, db):
        from api.agent3_longterm import create_plan, get_plan
        r = create_plan(db, "u", title="Livre IA", goal="Ecrire un livre de 10 chapitres")
        assert r["ok"] is True
        p = get_plan(db, r["plan_id"])
        assert p["title"] == "Livre IA"
        assert p["status"] == "active"
        assert p["progress_pct"] == 0

    def test_list_user_plans_with_filter(self, db):
        from api.agent3_longterm import create_plan, update_plan, list_user_plans
        r = create_plan(db, "u", title="A", goal="aa")
        create_plan(db, "u", title="B", goal="bb")
        update_plan(db, r["plan_id"], "u", status="completed")
        active = list_user_plans(db, "u", status="active")
        assert len(active) == 1
        assert active[0]["title"] == "B"

    def test_record_check_in_updates_progress(self, db):
        from api.agent3_longterm import create_plan, record_check_in, get_plan
        r = create_plan(db, "u", title="P", goal="g")
        record_check_in(db, r["plan_id"], progress_delta=30, summary="Phase 1 done")
        p = get_plan(db, r["plan_id"])
        assert p["progress_pct"] == 30
        assert len(p["check_ins"]) == 1

    def test_check_in_100pct_completes(self, db):
        from api.agent3_longterm import create_plan, record_check_in, get_plan
        r = create_plan(db, "u", title="P", goal="g")
        record_check_in(db, r["plan_id"], progress_delta=100)
        p = get_plan(db, r["plan_id"])
        assert p["status"] == "completed"

    def test_update_plan_ownership(self, db):
        from api.agent3_longterm import create_plan, update_plan
        r = create_plan(db, "alice", title="P", goal="g")
        res = update_plan(db, r["plan_id"], "bob", title="Hacked")
        assert res["ok"] is False

    def test_format_plans_for_prompt(self, db):
        from api.agent3_longterm import create_plan, format_plans_for_prompt
        create_plan(db, "u", title="Mon Livre", goal="Ecrire 10 chapitres")
        ctx = format_plans_for_prompt(db, "u")
        assert "OBJECTIFS LONG-TERME" in ctx
        assert "Mon Livre" in ctx

    def test_format_empty_when_no_plans(self, db):
        from api.agent3_longterm import format_plans_for_prompt
        assert format_plans_for_prompt(db, "u_nothing") == ""

    def test_delete_plan(self, db):
        from api.agent3_longterm import create_plan, delete_plan, get_plan
        r = create_plan(db, "u", title="P", goal="g")
        delete_plan(db, r["plan_id"], "u")
        assert get_plan(db, r["plan_id"]) is None


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
