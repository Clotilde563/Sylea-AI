"""
Tests Phase 9 — Tier 3 : GDPR + Retention + Feedback + Rate-limit.

Couvre :
  - api/agent3_gdpr.py : export complet + delete atomique
  - api/agent3_retention.py : cleanup par categorie + idempotence 6h
  - api/agent3_feedback.py : record/read/stats + contexte prompt
  - api/agent3_chat_ratelimit.py : token bucket + stats
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sylea.core.storage.database import DatabaseManager
from tests.conftest import make_shared_db, dispose_shared_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB SQLite partagee (sync + async) via fichier temp.
    Migration shared-DB : remplace `:memory:` pour permettre a l'async
    session_factory de pointer sur la meme DB."""
    d = make_shared_db(tmp_path, monkeypatch)
    # Bootstrap tables Agent 3 (feedback) utilisees par les helpers async.
    try:
        from api.agent3_feedback import ensure_feedback_table_async
        asyncio.run(ensure_feedback_table_async())
    except Exception:
        pass
    yield d
    dispose_shared_db(d)


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
        from api.agent3_gdpr import export_my_data_async
        bundle = asyncio.run(export_my_data_async("u_no_data"))
        assert "manifest" in bundle
        assert bundle["manifest"]["user_id"] == "u_no_data"
        assert bundle["manifest"]["total_rows"] == 0

    def test_export_includes_messages(self, db):
        from api.agent3_gdpr import export_my_data_async
        _seed_user(db, "u_msg")
        db.conn.execute(
            "INSERT INTO agent3_messages (id, auth_user_id, role, content, type, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("m1", "u_msg", "user", "hello", "text", "2026-04-23T10:00:00"),
        )
        db.conn.commit()

        bundle = asyncio.run(export_my_data_async("u_msg"))
        assert "agent3_messages" in bundle["data"]
        assert len(bundle["data"]["agent3_messages"]) == 1
        assert bundle["data"]["agent3_messages"][0]["content"] == "hello"
        assert bundle["manifest"]["total_rows"] >= 1

    def test_export_isolation(self, db):
        """Alice ne voit pas les donnees de Bob."""
        from api.agent3_gdpr import export_my_data_async
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
        bundle_a = asyncio.run(export_my_data_async("alice"))
        contents = [m["content"] for m in bundle_a["data"].get("agent3_messages", [])]
        assert "secret_alice" in contents
        assert "secret_bob" not in contents

    def test_export_no_user_id(self, db):
        from api.agent3_gdpr import export_my_data_async
        b = asyncio.run(export_my_data_async(""))
        assert b["manifest"] == {}


class TestGDPRDelete:
    def test_delete_removes_messages(self, db):
        from api.agent3_gdpr import delete_my_data_async
        _seed_user(db, "u_del")
        db.conn.execute(
            "INSERT INTO agent3_messages (id, auth_user_id, role, content, type, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("m1", "u_del", "user", "hello", "text", "2026-04-23"),
        )
        db.conn.commit()

        result = asyncio.run(delete_my_data_async("u_del", delete_uploads=False))
        assert result["total_rows"] >= 1
        assert result["deleted_by_table"].get("agent3_messages", 0) == 1

        remaining = db.conn.execute(
            "SELECT COUNT(*) FROM agent3_messages WHERE auth_user_id = ?", ("u_del",),
        ).fetchone()[0]
        assert remaining == 0

    def test_delete_preserves_other_users(self, db):
        from api.agent3_gdpr import delete_my_data_async
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

        asyncio.run(delete_my_data_async("alice", delete_uploads=False))
        bob_count = db.conn.execute(
            "SELECT COUNT(*) FROM agent3_messages WHERE auth_user_id = ?", ("bob",),
        ).fetchone()[0]
        assert bob_count == 1

    def test_delete_removes_uploaded_files(self, db, tmp_path):
        from api.agent3_gdpr import delete_my_data_async
        from api.routers.agent3_openclaw import _ensure_agent3_tables_async
        asyncio.run(_ensure_agent3_tables_async())
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
        result = asyncio.run(delete_my_data_async("u_files", delete_uploads=True))
        assert result["files_deleted"] >= 1
        assert not f.exists()

    def test_delete_no_user_id(self, db):
        from api.agent3_gdpr import delete_my_data_async
        r = asyncio.run(delete_my_data_async(""))
        assert "error" in r


class TestGDPRCompleteErasure:
    """Verifie que la suppression RGPD (decouverte dynamique) purge VRAIMENT
    toutes les tables user-scoped — y compris les plus sensibles qui etaient
    auparavant oubliees (journaux sante, chats Agent 1/2, profil) — ET la ligne
    `users` (le compte). Garde-fou anti-regression de la violation Art. 17."""

    def _seed_sensitive(self, db, uid: str) -> None:
        c = db.conn
        # Profil EN PREMIER (id = uid) : les tables user_id (bilans, sous_obj)
        # ont une FK -> profil_utilisateur(id). auth_user_id -> users(id).
        c.execute(
            "INSERT INTO profil_utilisateur (id, auth_user_id, nom, age, profession, ville, "
            "situation_familiale, revenu_annuel, patrimoine_estime, charges_mensuelles, "
            "cree_le, mis_a_jour_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (uid, uid, "Nom", 30, "Job", "Paris", "Celibataire",
             50000.0, 10000.0, 1500.0, "2026-06-01", "2026-06-01"),
        )
        # Journal sante quotidien (donnee sensible) — user_id -> profil(id)
        c.execute(
            "INSERT INTO bilans_quotidiens (id, user_id, date, cree_le) VALUES (?,?,?,?)",
            (f"bil_{uid}", uid, "2026-06-01", "2026-06-01T08:00:00"),
        )
        # Chat Agent 1 (Compagnon)
        c.execute(
            "INSERT INTO agent_messages (id, auth_user_id, role, content, created_at) VALUES (?,?,?,?,?)",
            (f"a1_{uid}", uid, "user", f"secret_sante_{uid}", "2026-06-01T09:00:00"),
        )
        # Chat Agent 2 (Assistant)
        c.execute(
            "INSERT INTO agent2_messages (id, auth_user_id, role, content, type, created_at) VALUES (?,?,?,?,?,?)",
            (f"a2_{uid}", uid, "user", f"secret_finance_{uid}", "text", "2026-06-01T09:30:00"),
        )
        c.commit()

    def _count_user_rows(self, db, uid: str) -> dict[str, int]:
        """Compte les lignes referencant `uid` dans CHAQUE table user-scoped
        (meme logique de decouverte que le module GDPR)."""
        from api.agent3_gdpr import _OWNER_COLUMNS, _DISCOVERY_DENYLIST
        c = db.conn
        tables = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()]
        counts: dict[str, int] = {}
        for t in tables:
            if t in _DISCOVERY_DENYLIST:
                continue
            cols = [x[1] for x in c.execute(f"PRAGMA table_info({t})").fetchall()]
            owner = [x for x in _OWNER_COLUMNS if x in cols]
            if not owner:
                continue
            where = " OR ".join(f"{x} = ?" for x in owner)
            n = c.execute(f"SELECT COUNT(*) FROM {t} WHERE {where}", tuple([uid] * len(owner))).fetchone()[0]
            if n:
                counts[t] = n
        return counts

    def test_delete_purges_sensitive_tables_and_account(self, db):
        from api.agent3_gdpr import delete_my_data_async
        _seed_user(db, "u_rgpd", "u_rgpd@test.com")
        _seed_user(db, "bob_keep", "bob_keep@test.com")
        self._seed_sensitive(db, "u_rgpd")
        self._seed_sensitive(db, "bob_keep")

        # Avant : u_rgpd a des lignes dans plusieurs tables sensibles
        before = self._count_user_rows(db, "u_rgpd")
        assert "bilans_quotidiens" in before
        assert "agent_messages" in before
        assert "agent2_messages" in before
        assert "profil_utilisateur" in before

        result = asyncio.run(delete_my_data_async("u_rgpd", delete_uploads=False))
        assert "error" not in result
        # Les tables sensibles + le compte sont bien dans le rapport de suppression
        for t in ("bilans_quotidiens", "agent_messages", "agent2_messages",
                  "profil_utilisateur", "users"):
            assert result["deleted_by_table"].get(t, 0) >= 1, f"{t} non supprimee"

        # Apres : AUCUNE ligne referencant u_rgpd ne subsiste, nulle part
        after = self._count_user_rows(db, "u_rgpd")
        assert after == {}, f"residu apres suppression: {after}"
        # La ligne `users` (le compte) est supprimee
        assert db.conn.execute(
            "SELECT COUNT(*) FROM users WHERE id = ?", ("u_rgpd",)
        ).fetchone()[0] == 0

        # Isolation : bob_keep est intact
        bob = self._count_user_rows(db, "bob_keep")
        assert "agent_messages" in bob and "profil_utilisateur" in bob
        assert db.conn.execute(
            "SELECT COUNT(*) FROM users WHERE id = ?", ("bob_keep",)
        ).fetchone()[0] == 1

    def test_export_includes_sensitive_and_redacts_secrets(self, db):
        from api.agent3_gdpr import export_my_data_async
        _seed_user(db, "u_exp", "u_exp@test.com")
        self._seed_sensitive(db, "u_exp")

        bundle = asyncio.run(export_my_data_async("u_exp"))
        data = bundle["data"]
        # Les donnees sensibles sont bien exportees (Art. 15/20)
        assert "bilans_quotidiens" in data
        assert "agent_messages" in data
        assert "agent2_messages" in data
        assert "users" in data
        # Le hash du mot de passe n'est JAMAIS exporte en clair
        users_row = data["users"][0]
        assert users_row.get("hashed_password") == "[REDACTED — secret/hash non exporte en clair]"


# ═════════════════════════════════════════════════════════════════════════════
# Retention policies
# ═════════════════════════════════════════════════════════════════════════════

class TestRetention:
    def setup_method(self):
        from api.agent3_retention import reset_retention_tracker
        reset_retention_tracker()

    def test_cleanup_messages_removes_old(self, db):
        from api.agent3_retention import cleanup_messages_async
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
        n = asyncio.run(cleanup_messages_async(days=180))
        assert n == 1
        remaining = db.conn.execute(
            "SELECT COUNT(*) FROM agent3_messages"
        ).fetchone()[0]
        assert remaining == 1

    def test_run_retention_pass_executes(self, db):
        from api.agent3_retention import run_retention_pass_async, reset_retention_tracker
        reset_retention_tracker()
        result = asyncio.run(run_retention_pass_async(force=True))
        assert "deleted_by_category" in result
        assert result["skipped"] is False
        assert "messages" in result["deleted_by_category"]

    def test_run_retention_respects_interval(self, db):
        from api.agent3_retention import run_retention_pass_async, reset_retention_tracker
        reset_retention_tracker()
        # 1er run OK
        r1 = asyncio.run(run_retention_pass_async())
        assert r1["skipped"] is False
        # 2eme run trop rapproche → skipped
        r2 = asyncio.run(run_retention_pass_async())
        assert r2["skipped"] is True
        # Force bypass
        r3 = asyncio.run(run_retention_pass_async(force=True))
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
            run_retention_pass_async, get_last_run_info, reset_retention_tracker,
        )
        reset_retention_tracker()
        info = get_last_run_info()
        assert info["ever_ran"] is False
        asyncio.run(run_retention_pass_async(force=True))
        info = get_last_run_info()
        assert info["ever_ran"] is True


# ═════════════════════════════════════════════════════════════════════════════
# Feedback
# ═════════════════════════════════════════════════════════════════════════════

class TestFeedback:
    def test_record_vote_up(self, db):
        from api.agent3_feedback import record_feedback_async, get_feedback_stats_async
        r = asyncio.run(record_feedback_async("u_fb", vote="up", comment="Tres bien !"))
        assert r["ok"] is True
        assert "feedback_id" in r
        stats = asyncio.run(get_feedback_stats_async("u_fb"))
        assert stats["thumbs_up"] == 1
        assert stats["thumbs_down"] == 0

    def test_record_vote_down(self, db):
        from api.agent3_feedback import record_feedback_async, get_feedback_stats_async
        asyncio.run(record_feedback_async("u_fb2", vote="down", comment="Mauvaise reponse"))
        stats = asyncio.run(get_feedback_stats_async("u_fb2"))
        assert stats["thumbs_down"] == 1

    def test_invalid_vote_rejected(self, db):
        from api.agent3_feedback import record_feedback_async
        r = asyncio.run(record_feedback_async("u_fb", vote="maybe"))
        assert r["ok"] is False

    def test_no_user_id(self, db):
        from api.agent3_feedback import record_feedback_async
        r = asyncio.run(record_feedback_async("", vote="up"))
        assert r["ok"] is False

    def test_ratio_calculation(self, db):
        from api.agent3_feedback import record_feedback_async, get_feedback_stats_async
        for _ in range(7):
            asyncio.run(record_feedback_async("u_r", vote="up"))
        for _ in range(3):
            asyncio.run(record_feedback_async("u_r", vote="down"))
        stats = asyncio.run(get_feedback_stats_async("u_r"))
        assert stats["total"] == 10
        assert stats["ratio"] == 0.7

    def test_isolation(self, db):
        from api.agent3_feedback import record_feedback_async, get_feedback_stats_async
        asyncio.run(record_feedback_async("alice", vote="up"))
        asyncio.run(record_feedback_async("bob", vote="down"))
        asyncio.run(record_feedback_async("bob", vote="down"))
        a_stats = asyncio.run(get_feedback_stats_async("alice"))
        b_stats = asyncio.run(get_feedback_stats_async("bob"))
        assert a_stats["thumbs_up"] == 1 and a_stats["thumbs_down"] == 0
        assert b_stats["thumbs_down"] == 2

    def test_recent_feedback(self, db):
        from api.agent3_feedback import record_feedback_async, get_recent_feedback_async
        for i in range(5):
            asyncio.run(record_feedback_async("u", vote="up" if i % 2 else "down", comment=f"c{i}"))
        recent = asyncio.run(get_recent_feedback_async("u", limit=3))
        assert len(recent) == 3
        assert all("vote" in f for f in recent)

    def test_format_context_empty_when_low(self, db):
        from api.agent3_feedback import format_feedback_context_async, record_feedback_async
        # Pas assez de feedback → bloc vide
        ctx = asyncio.run(format_feedback_context_async("u_new"))
        assert ctx == ""
        for _ in range(2):
            asyncio.run(record_feedback_async("u_new", vote="up"))
        # 2 < 3 → toujours vide
        ctx = asyncio.run(format_feedback_context_async("u_new"))
        assert ctx == ""

    def test_format_context_includes_negatives(self, db):
        from api.agent3_feedback import format_feedback_context_async, record_feedback_async
        asyncio.run(record_feedback_async("u_n", vote="up"))
        asyncio.run(record_feedback_async("u_n", vote="up"))
        asyncio.run(record_feedback_async(
            "u_n", vote="down",
            comment="Tu as oublie de mentionner le prix au m2",
        ))
        ctx = asyncio.run(format_feedback_context_async("u_n"))
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
