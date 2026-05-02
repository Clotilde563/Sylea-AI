"""
Tests Phase 9 — Tier 3 : GDPR + Retention + Feedback + Rate-limit.

Couvre :
  - api/agent3_gdpr.py : export complet + delete atomique
  - api/agent3_retention.py : cleanup par categorie + idempotence 6h
  - api/agent3_feedback.py : record/read/stats + contexte prompt
  - api/agent3_chat_ratelimit.py : token bucket + stats
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sylea.core.storage.database import DatabaseManager


@pytest.fixture
def db():
    d = DatabaseManager(db_path=Path(":memory:"))
    d.connect()
    return d


def _seed_user(db, user_id: str = "u1", email: str = "u1@test.com") -> None:
    """Cree le user parent requis par les FK."""
    db.conn.execute(
        "INSERT INTO users (id, email, hashed_password, created_at) VALUES (?,?,?,?)",
        (user_id, email, "pw", "2026-04-23T10:00:00"),
    )
    db.conn.commit()


# ═════════════════════════════════════════════════════════════════════════════
# GDPR — export + delete
# ═════════════════════════════════════════════════════════════════════════════

class TestGDPRExport:
    def test_empty_user_export(self, db):
        from api.agent3_gdpr import export_my_data
        bundle = export_my_data(db, "u_no_data")
        assert "manifest" in bundle
        assert bundle["manifest"]["user_id"] == "u_no_data"
        assert bundle["manifest"]["total_rows"] == 0

    def test_export_includes_messages(self, db):
        from api.agent3_gdpr import export_my_data
        _seed_user(db, "u_msg")
        db.conn.execute(
            "INSERT INTO agent3_messages (id, auth_user_id, role, content, type, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("m1", "u_msg", "user", "hello", "text", "2026-04-23T10:00:00"),
        )
        db.conn.commit()

        bundle = export_my_data(db, "u_msg")
        assert "agent3_messages" in bundle["data"]
        assert len(bundle["data"]["agent3_messages"]) == 1
        assert bundle["data"]["agent3_messages"][0]["content"] == "hello"
        assert bundle["manifest"]["total_rows"] >= 1

    def test_export_isolation(self, db):
        """Alice ne voit pas les donnees de Bob."""
        from api.agent3_gdpr import export_my_data
        _seed_user(db, "alice")
        _seed_user(db, "bob", email="bob@test.com")
        db.conn.execute(
            "INSERT INTO agent3_messages (id, auth_user_id, role, content, type, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("ma", "alice", "user", "secret_alice", "text", "2026-04-23"),
        )
        db.conn.execute(
            "INSERT INTO agent3_messages (id, auth_user_id, role, content, type, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("mb", "bob", "user", "secret_bob", "text", "2026-04-23"),
        )
        db.conn.commit()
        bundle_a = export_my_data(db, "alice")
        contents = [m["content"] for m in bundle_a["data"].get("agent3_messages", [])]
        assert "secret_alice" in contents
        assert "secret_bob" not in contents

    def test_export_no_user_id(self, db):
        from api.agent3_gdpr import export_my_data
        b = export_my_data(db, "")
        assert b["manifest"] == {}


class TestGDPRDelete:
    def test_delete_removes_messages(self, db):
        from api.agent3_gdpr import delete_my_data
        _seed_user(db, "u_del")
        db.conn.execute(
            "INSERT INTO agent3_messages (id, auth_user_id, role, content, type, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("m1", "u_del", "user", "hello", "text", "2026-04-23"),
        )
        db.conn.commit()

        result = delete_my_data(db, "u_del", delete_uploads=False)
        assert result["total_rows"] >= 1
        assert result["deleted_by_table"].get("agent3_messages", 0) == 1

        remaining = db.conn.execute(
            "SELECT COUNT(*) FROM agent3_messages WHERE auth_user_id = ?", ("u_del",),
        ).fetchone()[0]
        assert remaining == 0

    def test_delete_preserves_other_users(self, db):
        from api.agent3_gdpr import delete_my_data
        _seed_user(db, "alice")
        _seed_user(db, "bob", email="bob@test.com")
        db.conn.execute(
            "INSERT INTO agent3_messages (id, auth_user_id, role, content, type, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("ma", "alice", "user", "A", "text", "2026-04-23"),
        )
        db.conn.execute(
            "INSERT INTO agent3_messages (id, auth_user_id, role, content, type, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("mb", "bob", "user", "B", "text", "2026-04-23"),
        )
        db.conn.commit()

        delete_my_data(db, "alice", delete_uploads=False)
        bob_count = db.conn.execute(
            "SELECT COUNT(*) FROM agent3_messages WHERE auth_user_id = ?", ("bob",),
        ).fetchone()[0]
        assert bob_count == 1

    def test_delete_removes_uploaded_files(self, db, tmp_path):
        from api.agent3_gdpr import delete_my_data
        from api.routers.agent3_openclaw import _ensure_agent3_tables
        _ensure_agent3_tables(db)
        _seed_user(db, "u_files")
        f = tmp_path / "to_delete.txt"
        f.write_text("data", encoding="utf-8")
        db.conn.execute(
            "INSERT INTO agent3_files (id, auth_user_id, filename, filetype, filesize, filepath, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("f1", "u_files", "f.txt", "text/plain", 4, str(f), "2026-04-23"),
        )
        db.conn.commit()
        assert f.exists()
        result = delete_my_data(db, "u_files", delete_uploads=True)
        assert result["files_deleted"] >= 1
        assert not f.exists()

    def test_delete_no_user_id(self, db):
        from api.agent3_gdpr import delete_my_data
        r = delete_my_data(db, "")
        assert "error" in r


# ═════════════════════════════════════════════════════════════════════════════
# Retention policies
# ═════════════════════════════════════════════════════════════════════════════

class TestRetention:
    def setup_method(self):
        from api.agent3_retention import reset_retention_tracker
        reset_retention_tracker()

    def test_cleanup_messages_removes_old(self, db):
        from api.agent3_retention import cleanup_messages
        _seed_user(db, "u_ret")
        old_date = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        db.conn.execute(
            "INSERT INTO agent3_messages (id, auth_user_id, role, content, type, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("old", "u_ret", "user", "old msg", "text", old_date),
        )
        db.conn.execute(
            "INSERT INTO agent3_messages (id, auth_user_id, role, content, type, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("recent", "u_ret", "user", "recent msg", "text", recent),
        )
        db.conn.commit()
        n = cleanup_messages(db, days=180)
        assert n == 1
        remaining = db.conn.execute(
            "SELECT COUNT(*) FROM agent3_messages"
        ).fetchone()[0]
        assert remaining == 1

    def test_run_retention_pass_executes(self, db):
        from api.agent3_retention import run_retention_pass, reset_retention_tracker
        reset_retention_tracker()
        result = run_retention_pass(db, force=True)
        assert "deleted_by_category" in result
        assert result["skipped"] is False
        assert "messages" in result["deleted_by_category"]

    def test_run_retention_respects_interval(self, db):
        from api.agent3_retention import run_retention_pass, reset_retention_tracker
        reset_retention_tracker()
        # 1er run OK
        r1 = run_retention_pass(db)
        assert r1["skipped"] is False
        # 2eme run trop rapproche → skipped
        r2 = run_retention_pass(db)
        assert r2["skipped"] is True
        # Force bypass
        r3 = run_retention_pass(db, force=True)
        assert r3["skipped"] is False

    def test_cleanup_figures_disk(self, tmp_path):
        from api.agent3_retention import cleanup_figures
        # Cree un dossier avec mtime dans le passe
        old_dir = tmp_path / "old_run"
        old_dir.mkdir()
        (old_dir / "fig.png").write_bytes(b"x")
        # Set mtime 100j dans le passe
        past = datetime.now().timestamp() - 100 * 86400
        os.utime(old_dir, (past, past))
        os.utime(old_dir / "fig.png", (past, past))
        # Un dossier recent
        recent_dir = tmp_path / "recent_run"
        recent_dir.mkdir()
        (recent_dir / "fig.png").write_bytes(b"x")

        deleted = cleanup_figures(days=30, figures_dir=tmp_path)
        assert deleted >= 1
        assert not old_dir.exists()
        assert recent_dir.exists()

    def test_get_last_run_info(self, db):
        from api.agent3_retention import (
            run_retention_pass, get_last_run_info, reset_retention_tracker,
        )
        reset_retention_tracker()
        info = get_last_run_info()
        assert info["ever_ran"] is False
        run_retention_pass(db, force=True)
        info = get_last_run_info()
        assert info["ever_ran"] is True


# ═════════════════════════════════════════════════════════════════════════════
# Feedback
# ═════════════════════════════════════════════════════════════════════════════

class TestFeedback:
    def test_record_vote_up(self, db):
        from api.agent3_feedback import record_feedback, get_feedback_stats
        r = record_feedback(db, "u_fb", vote="up", comment="Tres bien !")
        assert r["ok"] is True
        assert "feedback_id" in r
        stats = get_feedback_stats(db, "u_fb")
        assert stats["thumbs_up"] == 1
        assert stats["thumbs_down"] == 0

    def test_record_vote_down(self, db):
        from api.agent3_feedback import record_feedback, get_feedback_stats
        record_feedback(db, "u_fb2", vote="down", comment="Mauvaise reponse")
        stats = get_feedback_stats(db, "u_fb2")
        assert stats["thumbs_down"] == 1

    def test_invalid_vote_rejected(self, db):
        from api.agent3_feedback import record_feedback
        r = record_feedback(db, "u_fb", vote="maybe")
        assert r["ok"] is False

    def test_no_user_id(self, db):
        from api.agent3_feedback import record_feedback
        r = record_feedback(db, "", vote="up")
        assert r["ok"] is False

    def test_ratio_calculation(self, db):
        from api.agent3_feedback import record_feedback, get_feedback_stats
        for _ in range(7):
            record_feedback(db, "u_r", vote="up")
        for _ in range(3):
            record_feedback(db, "u_r", vote="down")
        stats = get_feedback_stats(db, "u_r")
        assert stats["total"] == 10
        assert stats["ratio"] == 0.7

    def test_isolation(self, db):
        from api.agent3_feedback import record_feedback, get_feedback_stats
        record_feedback(db, "alice", vote="up")
        record_feedback(db, "bob", vote="down")
        record_feedback(db, "bob", vote="down")
        a_stats = get_feedback_stats(db, "alice")
        b_stats = get_feedback_stats(db, "bob")
        assert a_stats["thumbs_up"] == 1 and a_stats["thumbs_down"] == 0
        assert b_stats["thumbs_down"] == 2

    def test_recent_feedback(self, db):
        from api.agent3_feedback import record_feedback, get_recent_feedback
        for i in range(5):
            record_feedback(db, "u", vote="up" if i % 2 else "down", comment=f"c{i}")
        recent = get_recent_feedback(db, "u", limit=3)
        assert len(recent) == 3
        assert all("vote" in f for f in recent)

    def test_format_context_empty_when_low(self, db):
        from api.agent3_feedback import format_feedback_context, record_feedback
        # Pas assez de feedback → bloc vide
        ctx = format_feedback_context(db, "u_new")
        assert ctx == ""
        for _ in range(2):
            record_feedback(db, "u_new", vote="up")
        # 2 < 3 → toujours vide
        ctx = format_feedback_context(db, "u_new")
        assert ctx == ""

    def test_format_context_includes_negatives(self, db):
        from api.agent3_feedback import format_feedback_context, record_feedback
        record_feedback(db, "u_n", vote="up")
        record_feedback(db, "u_n", vote="up")
        record_feedback(
            db, "u_n", vote="down",
            comment="Tu as oublie de mentionner le prix au m2",
        )
        ctx = format_feedback_context(db, "u_n")
        assert "FEEDBACK" in ctx
        assert "prix" in ctx.lower()


# ═════════════════════════════════════════════════════════════════════════════
# Chat rate limiter
# ═════════════════════════════════════════════════════════════════════════════

class TestChatRateLimit:
    def setup_method(self):
        from api.agent3_chat_ratelimit import reset_chat_limiter
        reset_chat_limiter()
        # Override autour pytest autodisable
        os.environ.pop("PYTEST_CURRENT_TEST", None)
        os.environ.pop("SYLEA_DISABLE_CHAT_RATELIMIT", None)

    def teardown_method(self):
        from api.agent3_chat_ratelimit import reset_chat_limiter
        reset_chat_limiter()

    def test_pytest_env_disables(self):
        """Par defaut en test : tout passe."""
        os.environ["PYTEST_CURRENT_TEST"] = "active"
        from api.agent3_chat_ratelimit import check_chat_rate_limit
        # 1000 requetes passent
        for _ in range(100):
            ok, _ = check_chat_rate_limit("user_x")
            assert ok is True

    def test_disable_env(self):
        os.environ["SYLEA_DISABLE_CHAT_RATELIMIT"] = "1"
        try:
            from api.agent3_chat_ratelimit import check_chat_rate_limit
            for _ in range(50):
                ok, _ = check_chat_rate_limit("user_x")
                assert ok is True
        finally:
            os.environ.pop("SYLEA_DISABLE_CHAT_RATELIMIT", None)

    def test_anon_user_allowed(self):
        """Sans user_id : on laisse passer (limite par reverse proxy)."""
        from api.agent3_chat_ratelimit import (
            check_chat_rate_limit, _ChatRateLimiter,
        )
        limiter = _ChatRateLimiter(max_rpm=5, burst=3)
        for _ in range(10):
            ok, _ = limiter.acquire(None)
            assert ok is True

    def test_burst_then_block(self):
        from api.agent3_chat_ratelimit import _ChatRateLimiter
        limiter = _ChatRateLimiter(max_rpm=60, burst=3)
        # 3 requetes : OK
        for _ in range(3):
            ok, _ = limiter.acquire("user_a")
            assert ok is True
        # 4eme : bloquee (0 token, refill 1/s, burst = 3)
        ok, retry_after = limiter.acquire("user_a")
        assert ok is False
        assert retry_after > 0

    def test_isolation_per_user(self):
        from api.agent3_chat_ratelimit import _ChatRateLimiter
        limiter = _ChatRateLimiter(max_rpm=60, burst=2)
        # User A utilise ses 2 tokens
        for _ in range(2):
            ok, _ = limiter.acquire("A")
            assert ok is True
        ok_a, _ = limiter.acquire("A")
        assert ok_a is False
        # User B a encore ses tokens
        ok_b, _ = limiter.acquire("B")
        assert ok_b is True

    def test_stats(self):
        from api.agent3_chat_ratelimit import _ChatRateLimiter
        limiter = _ChatRateLimiter(max_rpm=60, burst=2)
        limiter.acquire("x")
        limiter.acquire("x")
        limiter.acquire("x")  # bloqued
        s = limiter.stats()
        assert s["allowed"] == 2
        assert s["blocked"] == 1
        assert s["total"] == 3
        assert s["active_users"] == 1
