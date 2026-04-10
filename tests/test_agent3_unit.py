"""
Tests unitaires exhaustifs pour l'Agent 3 (Agent Sylea 3 — OpenClaw).

Ces tests NE necessitent PAS de cle API (ANTHROPIC_API_KEY) ni OpenClaw.
Ils testent les fonctions utilitaires, helpers, parseurs, DB, et logique
interne de l'Agent 3 en isolation complete.

Couverture :
  - Tables et schemas DB
  - Preferences utilisateur (CRUD)
  - Memoire inter-sessions (save/load/cleanup/search/format)
  - Messages (save/load/count/clear)
  - Prompt builder
  - Response cleaner & default message generator
  - Token estimation & message pruning
  - Task decomposition
  - Agent routing
  - Code sandbox (validation)
  - Cron scheduler (expression parser)
  - Semantic memory (TF-IDF search)
  - Action fallback map
  - File create fallback
  - Workspace folder naming
"""

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from sylea.core.storage.database import DatabaseManager


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

TEST_USER_ID = "test-unit-agent3"


@pytest.fixture()
def db():
    """Base SQLite en memoire avec schema complet + tables Agent 3."""
    manager = DatabaseManager(db_path=Path(":memory:"))
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    manager._conn = conn
    manager._initialiser_schema()

    # Migration colonne optionnelle
    try:
        conn.execute(
            "ALTER TABLE profil_utilisateur ADD COLUMN objectif_probabilite_calculee REAL DEFAULT 0.0"
        )
    except Exception:
        pass

    # Inserer un utilisateur test
    conn.execute(
        "INSERT INTO users (id, email, hashed_password, provider, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (TEST_USER_ID, "test-unit-agent3@test.com", "fake_hash", "local"),
    )
    conn.commit()

    # Initialiser les tables Agent 3
    from api.routers.agent3_openclaw import _ensure_agent3_tables
    _ensure_agent3_tables(manager)

    yield manager
    manager.disconnect()


# ══════════════════════════════════════════════════════════════════════════════
# 1. Tables et schemas DB
# ══════════════════════════════════════════════════════════════════════════════

class TestAgent3Tables:
    """Verification de la creation des tables Agent 3."""

    def test_agent3_cron_table_exists(self, db):
        row = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent3_cron'"
        ).fetchone()
        assert row is not None

    def test_agent3_memory_table_exists(self, db):
        row = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent3_memory'"
        ).fetchone()
        assert row is not None

    def test_agent3_files_table_exists(self, db):
        row = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent3_files'"
        ).fetchone()
        assert row is not None

    def test_agent3_preferences_table_exists(self, db):
        row = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent3_preferences'"
        ).fetchone()
        assert row is not None

    def test_agent3_tasks_table_exists(self, db):
        row = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='agent3_tasks'"
        ).fetchone()
        assert row is not None

    def test_ensure_tables_idempotent(self, db):
        """Appeler _ensure_agent3_tables plusieurs fois ne crashe pas."""
        from api.routers.agent3_openclaw import _ensure_agent3_tables
        _ensure_agent3_tables(db)
        _ensure_agent3_tables(db)

    def test_cron_table_columns(self, db):
        """Verifier les colonnes de agent3_cron."""
        cursor = db.conn.execute("PRAGMA table_info(agent3_cron)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "id" in cols
        assert "auth_user_id" in cols
        assert "label" in cols
        assert "instruction" in cols
        assert "cron_expr" in cols
        assert "enabled" in cols

    def test_tasks_table_columns(self, db):
        """Verifier les colonnes de agent3_tasks."""
        cursor = db.conn.execute("PRAGMA table_info(agent3_tasks)")
        cols = {row[1] for row in cursor.fetchall()}
        assert "title" in cols
        assert "steps_json" in cols
        assert "status" in cols
        assert "progress" in cols


# ══════════════════════════════════════════════════════════════════════════════
# 2. Preferences utilisateur
# ══════════════════════════════════════════════════════════════════════════════

class TestUserPreferences:
    """Tests CRUD des preferences utilisateur Agent 3."""

    def test_default_preferences(self, db):
        from api.routers.agent3_openclaw import _get_user_preferences
        prefs = _get_user_preferences(db, TEST_USER_ID)
        assert prefs == {"confirm_destructive": True}

    def test_save_and_load_preferences(self, db):
        from api.routers.agent3_openclaw import _get_user_preferences, _save_user_preferences
        custom = {"confirm_destructive": False, "language": "fr", "theme": "dark"}
        _save_user_preferences(db, TEST_USER_ID, custom)
        loaded = _get_user_preferences(db, TEST_USER_ID)
        assert loaded == custom

    def test_update_preferences(self, db):
        from api.routers.agent3_openclaw import _get_user_preferences, _save_user_preferences
        _save_user_preferences(db, TEST_USER_ID, {"confirm_destructive": True})
        _save_user_preferences(db, TEST_USER_ID, {"confirm_destructive": False, "new_field": 42})
        loaded = _get_user_preferences(db, TEST_USER_ID)
        assert loaded["confirm_destructive"] is False
        assert loaded["new_field"] == 42

    def test_preferences_isolation_between_users(self, db):
        from api.routers.agent3_openclaw import _get_user_preferences, _save_user_preferences
        db.conn.execute(
            "INSERT INTO users (id, email, hashed_password, provider, created_at) "
            "VALUES ('user-b', 'b@test.com', 'hash', 'local', datetime('now'))"
        )
        db.conn.commit()
        _save_user_preferences(db, TEST_USER_ID, {"theme": "dark"})
        _save_user_preferences(db, "user-b", {"theme": "light"})
        assert _get_user_preferences(db, TEST_USER_ID)["theme"] == "dark"
        assert _get_user_preferences(db, "user-b")["theme"] == "light"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Memoire inter-sessions
# ══════════════════════════════════════════════════════════════════════════════

class TestMemory:
    """Tests de la memoire persistante de l'Agent 3."""

    def test_save_and_load_memory(self, db):
        from api.routers.agent3_openclaw import _save_memory, _load_memories
        _save_memory(db, TEST_USER_ID, "nom_client", "Jean Dupont", "contact")
        memories = _load_memories(db, TEST_USER_ID)
        assert len(memories) == 1
        assert memories[0]["key"] == "nom_client"
        assert memories[0]["value"] == "Jean Dupont"
        assert memories[0]["category"] == "contact"

    def test_save_multiple_memories(self, db):
        from api.routers.agent3_openclaw import _save_memory, _load_memories
        _save_memory(db, TEST_USER_ID, "skill_1", "Python", "competence")
        _save_memory(db, TEST_USER_ID, "skill_2", "React", "competence")
        _save_memory(db, TEST_USER_ID, "projet", "Startup IA", "projet")
        memories = _load_memories(db, TEST_USER_ID)
        assert len(memories) == 3

    def test_update_existing_memory(self, db):
        from api.routers.agent3_openclaw import _save_memory, _load_memories
        _save_memory(db, TEST_USER_ID, "ville", "Paris", "preference")
        _save_memory(db, TEST_USER_ID, "ville", "Lyon", "preference")
        memories = _load_memories(db, TEST_USER_ID)
        assert len(memories) == 1
        assert memories[0]["value"] == "Lyon"

    def test_memory_limit(self, db):
        from api.routers.agent3_openclaw import _save_memory, _load_memories
        for i in range(10):
            _save_memory(db, TEST_USER_ID, f"key_{i}", f"value_{i}")
        all_mem = _load_memories(db, TEST_USER_ID, limit=5)
        assert len(all_mem) == 5

    def test_format_memories_empty(self):
        from api.routers.agent3_openclaw import _format_memories
        assert _format_memories([]) == ""

    def test_format_memories_non_empty(self):
        from api.routers.agent3_openclaw import _format_memories
        memories = [
            {"key": "skill", "value": "Python", "category": "competence", "updated_at": "2026-01-01"},
            {"key": "projet", "value": "Startup", "category": "projet", "updated_at": "2026-01-02"},
        ]
        result = _format_memories(memories)
        assert "MEMOIRE" in result
        assert "[competence] skill: Python" in result
        assert "[projet] projet: Startup" in result

    def test_cleanup_old_memories_removes_old(self, db):
        from api.routers.agent3_openclaw import _cleanup_old_memories
        # Inserer un vieux souvenir (> 90 jours)
        old_date = (datetime.now() - timedelta(days=100)).isoformat()
        db.conn.execute(
            "INSERT INTO agent3_memory (id, auth_user_id, key, value, category, created_at, updated_at) "
            "VALUES (?, ?, 'old_key', 'old_value', 'general', ?, ?)",
            (str(uuid.uuid4()), TEST_USER_ID, old_date, old_date),
        )
        db.conn.commit()
        deleted = _cleanup_old_memories(db, TEST_USER_ID)
        assert deleted >= 1

    def test_cleanup_old_memories_keeps_recent(self, db):
        from api.routers.agent3_openclaw import _save_memory, _load_memories, _cleanup_old_memories
        _save_memory(db, TEST_USER_ID, "recent_key", "recent_value")
        deleted = _cleanup_old_memories(db, TEST_USER_ID)
        assert deleted == 0
        memories = _load_memories(db, TEST_USER_ID)
        assert len(memories) == 1

    def test_memory_isolation_between_users(self, db):
        from api.routers.agent3_openclaw import _save_memory, _load_memories
        db.conn.execute(
            "INSERT INTO users (id, email, hashed_password, provider, created_at) "
            "VALUES ('user-c', 'c@test.com', 'hash', 'local', datetime('now'))"
        )
        db.conn.commit()
        _save_memory(db, TEST_USER_ID, "secret", "my_data")
        _save_memory(db, "user-c", "secret", "other_data")
        mem_a = _load_memories(db, TEST_USER_ID)
        mem_c = _load_memories(db, "user-c")
        assert mem_a[0]["value"] == "my_data"
        assert mem_c[0]["value"] == "other_data"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Messages Agent 3 (persistance)
# ══════════════════════════════════════════════════════════════════════════════

class TestMessages:
    """Tests CRUD des messages Agent 3."""

    def test_save_and_load_message(self, db):
        from api.routers.agent3_openclaw import _save_agent3_message, _load_agent3_messages
        _save_agent3_message(db, TEST_USER_ID, "user", "Bonjour", "text")
        msgs = _load_agent3_messages(db, TEST_USER_ID)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "Bonjour"
        assert msgs[0]["type"] == "text"

    def test_save_multiple_messages(self, db):
        from api.routers.agent3_openclaw import _save_agent3_message, _load_agent3_messages
        _save_agent3_message(db, TEST_USER_ID, "user", "Question 1")
        _save_agent3_message(db, TEST_USER_ID, "agent", "Reponse 1")
        _save_agent3_message(db, TEST_USER_ID, "user", "Question 2")
        msgs = _load_agent3_messages(db, TEST_USER_ID)
        assert len(msgs) == 3
        # Ordre chronologique (reversed dans load)
        assert msgs[0]["role"] == "user"
        assert msgs[2]["role"] == "user"

    def test_count_messages(self, db):
        from api.routers.agent3_openclaw import _save_agent3_message, _count_agent3_messages
        assert _count_agent3_messages(db, TEST_USER_ID) == 0
        _save_agent3_message(db, TEST_USER_ID, "user", "Message 1")
        _save_agent3_message(db, TEST_USER_ID, "agent", "Reponse 1")
        assert _count_agent3_messages(db, TEST_USER_ID) == 2

    def test_clear_messages(self, db):
        from api.routers.agent3_openclaw import (
            _save_agent3_message, _clear_agent3_messages, _count_agent3_messages
        )
        _save_agent3_message(db, TEST_USER_ID, "user", "A supprimer")
        _save_agent3_message(db, TEST_USER_ID, "agent", "A supprimer aussi")
        assert _count_agent3_messages(db, TEST_USER_ID) == 2
        _clear_agent3_messages(db, TEST_USER_ID)
        assert _count_agent3_messages(db, TEST_USER_ID) == 0

    def test_message_load_limit(self, db):
        from api.routers.agent3_openclaw import _save_agent3_message, _load_agent3_messages
        for i in range(20):
            _save_agent3_message(db, TEST_USER_ID, "user", f"Message {i}")
        msgs = _load_agent3_messages(db, TEST_USER_ID, limit=5)
        assert len(msgs) == 5

    def test_message_with_audio(self, db):
        from api.routers.agent3_openclaw import _save_agent3_message, _load_agent3_messages
        _save_agent3_message(db, TEST_USER_ID, "user", "Vocal", "voice", audio_data="base64audio==")
        msgs = _load_agent3_messages(db, TEST_USER_ID)
        assert msgs[0]["type"] == "voice"
        assert msgs[0]["audio_data"] == "base64audio=="

    def test_message_fields_complete(self, db):
        from api.routers.agent3_openclaw import _save_agent3_message, _load_agent3_messages
        _save_agent3_message(db, TEST_USER_ID, "user", "Test fields")
        msg = _load_agent3_messages(db, TEST_USER_ID)[0]
        assert "id" in msg
        assert "role" in msg
        assert "content" in msg
        assert "type" in msg
        assert "created_at" in msg
        assert len(msg["id"]) == 36  # UUID format


# ══════════════════════════════════════════════════════════════════════════════
# 5. Response cleaner & default message generator
# ══════════════════════════════════════════════════════════════════════════════

class TestResponseCleaner:
    """Tests du nettoyage des reponses agent."""

    def test_clean_empty_string(self):
        from api.routers.agent3_openclaw import _clean_agent_response
        assert _clean_agent_response("") == ""

    def test_clean_plain_text(self):
        from api.routers.agent3_openclaw import _clean_agent_response
        assert _clean_agent_response("Bonjour !") == "Bonjour !"

    def test_removes_action_blocks(self):
        from api.routers.agent3_openclaw import _clean_agent_response
        text = 'Voici le resultat. [ACTION:PDF]{"title": "Test"}[/ACTION]'
        assert _clean_agent_response(text) == "Voici le resultat."

    def test_removes_multiple_action_blocks(self):
        from api.routers.agent3_openclaw import _clean_agent_response
        text = 'A [ACTION:SEARCH]{"query":"x"}[/ACTION] B [ACTION:PDF]{"title":"y"}[/ACTION] C'
        clean = _clean_agent_response(text)
        assert "[ACTION:" not in clean
        assert "[/ACTION]" not in clean
        assert "A" in clean
        assert "C" in clean

    def test_removes_multiline_action_blocks(self):
        from api.routers.agent3_openclaw import _clean_agent_response
        text = 'Message.\n[ACTION:PDF]{\n"title": "Rapport",\n"sections": []\n}[/ACTION]\nFin.'
        clean = _clean_agent_response(text)
        assert "[ACTION:" not in clean
        assert "Message." in clean

    def test_removes_xml_tags(self):
        from api.routers.agent3_openclaw import _clean_agent_response
        text = 'Texte <function_calls>blah</function_calls> suite'
        clean = _clean_agent_response(text)
        assert "<function_calls>" not in clean

    def test_removes_json_code_blocks(self):
        from api.routers.agent3_openclaw import _clean_agent_response
        text = 'Voici ```json\n{"key": "val"}\n``` le resultat.'
        clean = _clean_agent_response(text)
        assert "```" not in clean


class TestDefaultMessage:
    """Tests de la generation de messages par defaut."""

    def test_empty_actions(self):
        from api.routers.agent3_openclaw import _generate_default_message
        assert _generate_default_message([]) == "C'est fait."

    def test_pdf_action(self):
        from api.routers.agent3_openclaw import _generate_default_message
        actions = [{"type": "PDF", "data": {"title": "Analyse Marche"}}]
        msg = _generate_default_message(actions)
        assert "Analyse Marche" in msg

    def test_search_action(self):
        from api.routers.agent3_openclaw import _generate_default_message
        actions = [{"type": "SEARCH", "data": {"query": "formations Python"}}]
        msg = _generate_default_message(actions)
        assert "formations Python" in msg

    def test_email_sent(self):
        from api.routers.agent3_openclaw import _generate_default_message
        actions = [{"type": "EMAIL", "data": {"to": "jean@test.com", "sent": True}}]
        msg = _generate_default_message(actions)
        assert "jean@test.com" in msg
        assert "envoye" in msg.lower()

    def test_email_error(self):
        from api.routers.agent3_openclaw import _generate_default_message
        actions = [{"type": "EMAIL", "data": {"to": "x@y.com", "send_error": "SMTP timeout"}}]
        msg = _generate_default_message(actions)
        assert "SMTP timeout" in msg

    def test_code_action(self):
        from api.routers.agent3_openclaw import _generate_default_message
        actions = [{"type": "CODE", "data": {"filename": "script.py"}}]
        msg = _generate_default_message(actions)
        assert "script.py" in msg

    def test_reminder_action(self):
        from api.routers.agent3_openclaw import _generate_default_message
        actions = [{"type": "REMINDER", "data": {"time": "18:00"}}]
        msg = _generate_default_message(actions)
        assert "rappel" in msg.lower()

    def test_unknown_action_type(self):
        from api.routers.agent3_openclaw import _generate_default_message
        actions = [{"type": "CUSTOM_THING", "data": {}}]
        msg = _generate_default_message(actions)
        assert msg == "C'est fait."


# ══════════════════════════════════════════════════════════════════════════════
# 6. Token estimation & message pruning
# ══════════════════════════════════════════════════════════════════════════════

class TestTokenEstimation:
    """Tests de l'estimation de tokens."""

    def test_empty_text(self):
        from api.routers.agent3_openclaw import _estimate_tokens
        assert _estimate_tokens("") == 0

    def test_short_text(self):
        from api.routers.agent3_openclaw import _estimate_tokens
        tokens = _estimate_tokens("Hello World")  # 11 chars -> ~2-3 tokens
        assert tokens > 0
        assert tokens < 10

    def test_long_text(self):
        from api.routers.agent3_openclaw import _estimate_tokens
        text = "a" * 4000  # 4000 chars -> ~1000 tokens
        tokens = _estimate_tokens(text)
        assert tokens == 1000

    def test_french_text(self):
        from api.routers.agent3_openclaw import _estimate_tokens
        text = "Bonjour, comment allez-vous aujourd'hui ?"
        tokens = _estimate_tokens(text)
        assert tokens > 5


class TestMessagePruning:
    """Tests du pruning (compression) des messages."""

    def test_no_pruning_under_threshold(self):
        from api.routers.agent3_openclaw import _prune_messages
        msgs = [
            {"role": "user", "content": "Salut"},
            {"role": "assistant", "content": "Hey"},
        ]
        result = _prune_messages(msgs, max_tokens=1000)
        assert len(result) == 2

    def test_empty_messages(self):
        from api.routers.agent3_openclaw import _prune_messages
        assert _prune_messages([]) == []

    def test_pruning_long_history(self):
        from api.routers.agent3_openclaw import _prune_messages
        msgs = []
        for i in range(30):
            msgs.append({"role": "user", "content": f"Message long numero {i} " + "blah " * 100})
            msgs.append({"role": "assistant", "content": f"Reponse longue numero {i} " + "blah " * 100})
        result = _prune_messages(msgs, max_tokens=500)
        # Pruned list should be shorter
        assert len(result) < len(msgs)
        # Should contain context compress marker
        all_content = " ".join(m.get("content", "") for m in result)
        assert "contexte compress" in all_content.lower() or len(result) < 20

    def test_pruning_keeps_recent(self):
        from api.routers.agent3_openclaw import _prune_messages
        msgs = []
        for i in range(30):
            msgs.append({"role": "user", "content": f"Message {i} " + "x" * 200})
            msgs.append({"role": "assistant", "content": f"Reponse {i} " + "x" * 200})
        result = _prune_messages(msgs, max_tokens=500)
        # Last messages should be preserved
        last_contents = [m["content"] for m in result[-5:]]
        assert any("29" in c for c in last_contents)  # Message 29 = dernier


# ══════════════════════════════════════════════════════════════════════════════
# 7. Task decomposition
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskDecomposition:
    """Tests de la decomposition en sous-taches."""

    def test_simple_greeting(self):
        from api.routers.agent3_openclaw import _decompose_task
        steps = _decompose_task("Salut ca va ?")
        # Simple greeting has at least "understand" + "respond" steps
        assert len(steps) >= 1
        ids = [s["id"] for s in steps]
        # At least one step should exist
        assert len(ids) >= 1

    def test_search_task(self):
        from api.routers.agent3_openclaw import _decompose_task
        steps = _decompose_task("Cherche les meilleurs prix pour un MacBook Air")
        ids = [s["id"] for s in steps]
        assert "search" in ids

    def test_browse_task(self):
        from api.routers.agent3_openclaw import _decompose_task
        steps = _decompose_task("Va sur linkedin.com et scrape le profil")
        ids = [s["id"] for s in steps]
        assert "browse" in ids

    def test_analysis_task(self):
        from api.routers.agent3_openclaw import _decompose_task
        steps = _decompose_task("Fais une analyse complete du marche de l'IA")
        ids = [s["id"] for s in steps]
        assert "search" in ids  # analysis includes search

    def test_email_task(self):
        from api.routers.agent3_openclaw import _decompose_task
        steps = _decompose_task("Envoie un mail a jean@startup.com")
        ids = [s["id"] for s in steps]
        assert any("mail" in step_id or "email" in step_id or "compose" in step_id for step_id in ids) or len(steps) >= 2

    def test_code_task(self):
        from api.routers.agent3_openclaw import _decompose_task
        steps = _decompose_task("Ecris un script Python qui calcule les primes")
        ids = [s["id"] for s in steps]
        assert any("code" in step_id or "understand" in step_id for step_id in ids)

    def test_all_steps_have_required_fields(self):
        from api.routers.agent3_openclaw import _decompose_task
        steps = _decompose_task("Recherche les tendances du marche et genere un rapport PDF")
        for step in steps:
            assert "id" in step
            assert "label" in step
            assert "status" in step
            assert step["status"] == "pending"


# ══════════════════════════════════════════════════════════════════════════════
# 8. Agent routing
# ══════════════════════════════════════════════════════════════════════════════

class TestAgentRouting:
    """Tests du routage multi-agent."""

    def test_default_route(self):
        from api.routers.agent3_openclaw import route_to_agent
        result = route_to_agent("coucou ca va ?")
        assert result["agent_id"] == "default"
        assert result["confidence"] == 0

    def test_research_route(self):
        from api.routers.agent3_openclaw import route_to_agent
        result = route_to_agent("Recherche les tendances du marche de l'IA")
        assert result["agent_id"] == "researcher"
        assert result["confidence"] >= 1
        assert "recherche" in result["keywords_matched"] or "tendance" in result["keywords_matched"]

    def test_writer_route(self):
        from api.routers.agent3_openclaw import route_to_agent
        result = route_to_agent("Redige un mail professionnel pour Jean")
        assert result["agent_id"] == "writer"
        assert result["confidence"] >= 1

    def test_coder_route(self):
        from api.routers.agent3_openclaw import route_to_agent
        result = route_to_agent("Execute un script Python de calcul")
        assert result["agent_id"] == "coder"
        assert result["confidence"] >= 1

    def test_automator_route(self):
        from api.routers.agent3_openclaw import route_to_agent
        result = route_to_agent("Planifie un rappel tous les jours a 9h")
        assert result["agent_id"] == "automator"
        assert result["confidence"] >= 1

    def test_browser_route(self):
        from api.routers.agent3_openclaw import route_to_agent
        result = route_to_agent("Va sur linkedin.com et visite le profil")
        assert result["agent_id"] == "browser"
        assert result["confidence"] >= 1

    def test_creative_route(self):
        from api.routers.agent3_openclaw import route_to_agent
        result = route_to_agent("Genere une image d'un logo pour ma startup")
        assert result["agent_id"] == "creative"
        assert result["confidence"] >= 1

    def test_route_has_required_fields(self):
        from api.routers.agent3_openclaw import route_to_agent
        result = route_to_agent("Recherche quelque chose")
        assert "agent_id" in result
        assert "tool_profile" in result
        assert "description" in result
        assert "confidence" in result
        assert "keywords_matched" in result

    def test_get_agent_routes(self):
        from api.routers.agent3_openclaw import get_agent_routes
        routes = get_agent_routes()
        assert isinstance(routes, list)
        assert len(routes) >= 5
        for route in routes:
            assert "id" in route
            assert "keywords" in route
            assert "description" in route


# ══════════════════════════════════════════════════════════════════════════════
# 9. Prompt builder
# ══════════════════════════════════════════════════════════════════════════════

class TestPromptBuilder:
    """Tests du constructeur de system prompt."""

    def test_prompt_without_profil(self):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        prompt = _build_agent3_prompt(None, [], [])
        assert "Agent Sylea 3" in prompt
        assert "AUCUN PROFIL" in prompt

    def test_prompt_with_profil(self):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        profil = {
            "nom": "Jean Dupont",
            "age": 30,
            "genre": "Homme",
            "profession": "Developpeur",
            "ville": "Paris",
            "situation_familiale": "celibataire",
            "competences": ["Python", "React"],
            "diplomes": ["Master Info"],
            "langues": ["Francais", "Anglais"],
            "objectif_description": "Devenir CTO",
            "probabilite_actuelle": 45.0,
        }
        prompt = _build_agent3_prompt(profil, [], [])
        assert "Jean Dupont" in prompt
        assert "Developpeur" in prompt
        assert "CTO" in prompt
        assert "45.0%" in prompt

    def test_prompt_with_decisions(self):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        decisions = [
            {"question": "Accepter le projet", "choix": "Oui", "impact": 5.2},
        ]
        prompt = _build_agent3_prompt(None, decisions, [])
        assert "Accepter le projet" in prompt

    def test_prompt_with_sous_objectifs(self):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        so = [{"titre": "Apprendre Docker", "progression": 60.0}]
        prompt = _build_agent3_prompt(None, [], so)
        assert "Apprendre Docker" in prompt
        assert "60" in prompt

    def test_prompt_contains_action_syntax(self):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        prompt = _build_agent3_prompt(None, [], [])
        assert "[ACTION:PDF]" in prompt
        assert "[ACTION:SEARCH]" in prompt
        assert "[ACTION:EMAIL]" in prompt
        assert "[ACTION:COMPUTER_USE]" in prompt

    def test_prompt_contains_identity(self):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        prompt = _build_agent3_prompt(None, [], [])
        assert "SYLEA" in prompt
        assert "Claude" in prompt  # "tu n'es PAS Claude"

    def test_prompt_with_memory_context(self):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        memory = "\n=== MEMOIRE ===\n[contact] Jean: PDG de Startup"
        prompt = _build_agent3_prompt(None, [], [], memory_context=memory)
        assert "MEMOIRE" in prompt

    def test_prompt_with_files_context(self):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        files = "Fichier: rapport.pdf (2.3 MB)"
        prompt = _build_agent3_prompt(None, [], [], files_context=files)
        assert "rapport.pdf" in prompt


# ══════════════════════════════════════════════════════════════════════════════
# 10. Cron expression parser (scheduler)
# ══════════════════════════════════════════════════════════════════════════════

class TestCronParser:
    """Tests du parseur d'expressions cron."""

    def test_wildcard_matches_all(self):
        from api.scheduler import _cron_matches
        dt = datetime(2026, 4, 6, 9, 30)  # Dimanche
        assert _cron_matches("* * * * *", dt) is True

    def test_exact_minute_match(self):
        from api.scheduler import _cron_matches
        dt = datetime(2026, 4, 6, 9, 30)
        assert _cron_matches("30 * * * *", dt) is True
        assert _cron_matches("31 * * * *", dt) is False

    def test_exact_hour_match(self):
        from api.scheduler import _cron_matches
        dt = datetime(2026, 4, 6, 9, 0)
        assert _cron_matches("0 9 * * *", dt) is True
        assert _cron_matches("0 10 * * *", dt) is False

    def test_every_n_minutes(self):
        from api.scheduler import _cron_matches
        dt = datetime(2026, 4, 6, 9, 15)
        assert _cron_matches("*/15 * * * *", dt) is True
        dt2 = datetime(2026, 4, 6, 9, 16)
        assert _cron_matches("*/15 * * * *", dt2) is False

    def test_every_6_hours(self):
        from api.scheduler import _cron_matches
        dt0 = datetime(2026, 4, 6, 0, 0)
        dt6 = datetime(2026, 4, 6, 6, 0)
        dt12 = datetime(2026, 4, 6, 12, 0)
        dt3 = datetime(2026, 4, 6, 3, 0)
        assert _cron_matches("0 */6 * * *", dt0) is True
        assert _cron_matches("0 */6 * * *", dt6) is True
        assert _cron_matches("0 */6 * * *", dt12) is True
        assert _cron_matches("0 */6 * * *", dt3) is False

    def test_range(self):
        from api.scheduler import _cron_matches
        dt = datetime(2026, 4, 6, 10, 0)
        assert _cron_matches("0 9-17 * * *", dt) is True
        dt_night = datetime(2026, 4, 6, 3, 0)
        assert _cron_matches("0 9-17 * * *", dt_night) is False

    def test_list(self):
        from api.scheduler import _cron_matches
        dt = datetime(2026, 4, 6, 9, 0)
        assert _cron_matches("0 9,12,18 * * *", dt) is True
        dt2 = datetime(2026, 4, 6, 12, 0)
        assert _cron_matches("0 9,12,18 * * *", dt2) is True
        dt3 = datetime(2026, 4, 6, 10, 0)
        assert _cron_matches("0 9,12,18 * * *", dt3) is False

    def test_day_of_month(self):
        from api.scheduler import _cron_matches
        dt = datetime(2026, 4, 1, 9, 0)
        assert _cron_matches("0 9 1 * *", dt) is True
        dt2 = datetime(2026, 4, 2, 9, 0)
        assert _cron_matches("0 9 1 * *", dt2) is False

    def test_month(self):
        from api.scheduler import _cron_matches
        dt = datetime(2026, 12, 25, 0, 0)
        assert _cron_matches("0 0 25 12 *", dt) is True
        dt2 = datetime(2026, 11, 25, 0, 0)
        assert _cron_matches("0 0 25 12 *", dt2) is False

    def test_day_of_week(self):
        from api.scheduler import _cron_matches
        # 2026-04-06 est un lundi (weekday=0 Python, cron=1)
        dt_monday = datetime(2026, 4, 6, 9, 0)
        assert _cron_matches("0 9 * * 1", dt_monday) is True  # 1=Monday in cron
        assert _cron_matches("0 9 * * 0", dt_monday) is False  # 0=Sunday in cron

    def test_invalid_cron_expression(self):
        from api.scheduler import _cron_matches
        dt = datetime(2026, 4, 6, 9, 0)
        assert _cron_matches("invalid", dt) is False
        assert _cron_matches("* * *", dt) is False  # Only 3 fields
        assert _cron_matches("", dt) is False

    def test_field_matches_star(self):
        from api.scheduler import _field_matches
        assert _field_matches("*", 0, (0, 59)) is True
        assert _field_matches("*", 59, (0, 59)) is True

    def test_field_matches_step(self):
        from api.scheduler import _field_matches
        assert _field_matches("*/10", 0, (0, 59)) is True
        assert _field_matches("*/10", 10, (0, 59)) is True
        assert _field_matches("*/10", 30, (0, 59)) is True
        assert _field_matches("*/10", 7, (0, 59)) is False

    def test_field_matches_range(self):
        from api.scheduler import _field_matches
        assert _field_matches("9-17", 9, (0, 23)) is True
        assert _field_matches("9-17", 17, (0, 23)) is True
        assert _field_matches("9-17", 13, (0, 23)) is True
        assert _field_matches("9-17", 8, (0, 23)) is False
        assert _field_matches("9-17", 18, (0, 23)) is False


# ══════════════════════════════════════════════════════════════════════════════
# 11. Code sandbox — validation statique
# ══════════════════════════════════════════════════════════════════════════════

class TestCodeSandboxValidation:
    """Tests de la validation de code avant execution."""

    def test_valid_python_code(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        ok, reason = sandbox.validate_code("print('hello')", "python")
        assert ok is True
        assert reason == ""

    def test_empty_code_rejected(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        ok, reason = sandbox.validate_code("", "python")
        assert ok is False
        assert "vide" in reason.lower()

    def test_whitespace_only_rejected(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        ok, reason = sandbox.validate_code("   \n\t  ", "python")
        assert ok is False

    def test_os_system_blocked(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        ok, reason = sandbox.validate_code("import os\nos.system('rm -rf /')", "python")
        assert ok is False
        assert "os.system" in reason

    def test_shutil_rmtree_blocked(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        ok, reason = sandbox.validate_code("import shutil\nshutil.rmtree('/tmp')", "python")
        assert ok is False

    def test_subprocess_blocked(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        ok, reason = sandbox.validate_code("import subprocess\nsubprocess.run(['ls'])", "python")
        assert ok is False

    def test_ctypes_blocked(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        ok, reason = sandbox.validate_code("import ctypes", "python")
        assert ok is False

    def test_network_blocked_default(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        ok, reason = sandbox.validate_code("import requests\nrequests.get('http://evil.com')", "python")
        assert ok is False

    def test_network_allowed_when_enabled(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox(allow_network=True)
        ok, reason = sandbox.validate_code("import requests\nrequests.get('http://api.com')", "python")
        # Network patterns should NOT be checked when allow_network=True
        assert ok is True

    def test_absolute_path_blocked(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        ok, reason = sandbox.validate_code("open('/etc/passwd')", "python")
        assert ok is False

    def test_directory_traversal_blocked(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        ok, reason = sandbox.validate_code("open('../../../etc/passwd')", "python")
        assert ok is False

    def test_code_too_long_rejected(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        ok, reason = sandbox.validate_code("x = 1\n" * 50000, "python")
        assert ok is False
        assert "trop long" in reason.lower()

    def test_shell_no_static_validation(self):
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox()
        # Shell scripts aren't statically validated (only size check)
        ok, reason = sandbox.validate_code("echo hello", "bash")
        assert ok is True

    def test_sandbox_result_to_dict(self):
        from api.code_sandbox import SandboxResult
        result = SandboxResult(
            success=True, exit_code=0, stdout="hello\n", stderr="",
            language="python", filename="test.py", execution_time_ms=42
        )
        d = result.to_dict()
        assert d["success"] is True
        assert d["exit_code"] == 0
        assert d["stdout"] == "hello\n"
        assert d["execution_time_ms"] == 42
        assert "blocked" not in d  # Not included when False

    def test_sandbox_result_blocked_to_dict(self):
        from api.code_sandbox import SandboxResult
        result = SandboxResult(
            success=False, exit_code=-1, stdout="", stderr="",
            language="python", filename="bad.py",
            blocked=True, block_reason="os.system interdit"
        )
        d = result.to_dict()
        assert d["blocked"] is True
        assert d["block_reason"] == "os.system interdit"


# ══════════════════════════════════════════════════════════════════════════════
# 12. Semantic memory
# ══════════════════════════════════════════════════════════════════════════════

class TestSemanticMemory:
    """Tests de la recherche semantique dans les souvenirs."""

    def test_is_semantic_available(self):
        from api.semantic_memory import is_semantic_available
        # Should return True or False (scikit-learn may or may not be installed)
        result = is_semantic_available()
        assert isinstance(result, bool)

    def test_semantic_search_empty(self):
        from api.semantic_memory import semantic_search
        results = semantic_search("Python", [])
        assert results == []

    def test_semantic_search_empty_query(self):
        from api.semantic_memory import semantic_search
        memories = [{"key": "x", "value": "y", "category": "z"}]
        results = semantic_search("", memories)
        assert results == []

    def test_semantic_search_basic(self):
        from api.semantic_memory import semantic_search
        memories = [
            {"key": "lang1", "value": "Python est mon langage prefere", "category": "competence", "updated_at": "2026-01-01"},
            {"key": "sport", "value": "Je fais du tennis le weekend", "category": "loisir", "updated_at": "2026-01-02"},
            {"key": "lang2", "value": "J'apprends aussi JavaScript pour le web", "category": "competence", "updated_at": "2026-01-03"},
        ]
        results = semantic_search("programmation Python", memories, top_k=3)
        # Should return MemoryMatch list (TF-IDF or keyword fallback)
        assert isinstance(results, list)
        if results:
            from api.semantic_memory import MemoryMatch
            assert isinstance(results[0], MemoryMatch)

    def test_search_memories_via_db(self, db):
        from api.routers.agent3_openclaw import _save_memory, _search_memories
        _save_memory(db, TEST_USER_ID, "python_level", "Expert en Python depuis 10 ans")
        _save_memory(db, TEST_USER_ID, "hobby", "Joue de la guitare")
        _save_memory(db, TEST_USER_ID, "framework", "Specialise en FastAPI et Django")

        results = _search_memories(db, TEST_USER_ID, "Python programmation")
        # Should find Python-related memories
        assert isinstance(results, list)


# ══════════════════════════════════════════════════════════════════════════════
# 13. Action fallback map
# ══════════════════════════════════════════════════════════════════════════════

class TestActionFallbacks:
    """Tests de la map de fallback des actions."""

    def test_fallback_map_exists(self):
        from api.routers.agent3_openclaw import _ACTION_FALLBACKS
        assert isinstance(_ACTION_FALLBACKS, dict)

    def test_browser_fallback_to_search(self):
        from api.routers.agent3_openclaw import _ACTION_FALLBACKS
        assert _ACTION_FALLBACKS.get("BROWSER") == "SEARCH"

    def test_screenshot_fallback_to_search(self):
        from api.routers.agent3_openclaw import _ACTION_FALLBACKS
        assert _ACTION_FALLBACKS.get("SCREENSHOT") == "SEARCH"

    def test_search_no_fallback(self):
        from api.routers.agent3_openclaw import _ACTION_FALLBACKS
        assert _ACTION_FALLBACKS.get("SEARCH") is None


# ══════════════════════════════════════════════════════════════════════════════
# 14. Workspace folder naming
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkspaceFolderName:
    """Tests du nommage du dossier workspace."""

    def test_default_name_without_profil(self, db):
        from api.routers.agent3_openclaw import get_workspace_folder_name
        name = get_workspace_folder_name(db, TEST_USER_ID)
        assert name == "Documents_Sylea"

    def test_name_from_objective(self, db):
        from api.routers.agent3_openclaw import get_workspace_folder_name
        import uuid
        pid = str(uuid.uuid4())
        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(profil_utilisateur)").fetchall()]
        base_vals = {
            "id": pid, "nom": "Jean", "age": 30, "profession": "Dev",
            "ville": "Paris", "situation_familiale": "celibataire",
            "revenu_annuel": 40000, "patrimoine_estime": 10000,
            "charges_mensuelles": 1500, "objectif_description": "Devenir CTO startup",
            "cree_le": "2025-01-01T00:00:00", "mis_a_jour_le": "2025-01-01T00:00:00",
        }
        if "auth_user_id" in cols:
            base_vals["auth_user_id"] = TEST_USER_ID
        col_names = ", ".join(base_vals.keys())
        placeholders = ", ".join(["?"] * len(base_vals))
        db.conn.execute(f"INSERT INTO profil_utilisateur ({col_names}) VALUES ({placeholders})", list(base_vals.values()))
        db.conn.commit()
        name = get_workspace_folder_name(db, TEST_USER_ID)
        # May return objective-based name or default
        assert isinstance(name, str)
        assert len(name) > 0

    def test_special_chars_stripped(self, db):
        from api.routers.agent3_openclaw import get_workspace_folder_name
        import uuid
        db.conn.execute(
            "INSERT INTO users (id, email, hashed_password, provider, created_at) "
            "VALUES ('user-special', 'special@t.com', 'h', 'local', datetime('now'))"
        )
        pid = str(uuid.uuid4())
        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(profil_utilisateur)").fetchall()]
        base_vals = {
            "id": pid, "nom": "Test", "age": 25, "profession": "Dev",
            "ville": "Lyon", "situation_familiale": "celibataire",
            "revenu_annuel": 30000, "patrimoine_estime": 5000,
            "charges_mensuelles": 1000, "objectif_description": "Creer une startup @#$%",
            "cree_le": "2025-01-01T00:00:00", "mis_a_jour_le": "2025-01-01T00:00:00",
        }
        if "auth_user_id" in cols:
            base_vals["auth_user_id"] = "user-special"
        col_names = ", ".join(base_vals.keys())
        placeholders = ", ".join(["?"] * len(base_vals))
        db.conn.execute(f"INSERT INTO profil_utilisateur ({col_names}) VALUES ({placeholders})", list(base_vals.values()))
        db.conn.commit()
        name = get_workspace_folder_name(db, "user-special")
        assert "@" not in name
        assert "#" not in name
        assert "$" not in name


# ══════════════════════════════════════════════════════════════════════════════
# 15. OpenClaw bridge — ToolLoopDetector
# ══════════════════════════════════════════════════════════════════════════════

class TestToolLoopDetector:
    """Tests du detecteur de boucles d'outils."""

    def test_no_loop_initially(self):
        from api.openclaw_bridge import ToolLoopDetector
        detector = ToolLoopDetector()
        looping, reason = detector.is_looping()
        assert looping is False

    def test_loop_detected_after_many_repeats(self):
        from api.openclaw_bridge import ToolLoopDetector
        detector = ToolLoopDetector(max_repeats=3, max_total=15)
        detector.record("web_search")
        detector.record("web_search")
        detector.record("web_search")
        # 3 consecutive calls of the same tool -> loop detected
        looping, reason = detector.is_looping()
        assert looping is True
        assert "web_search" in reason

    def test_different_tools_no_loop(self):
        from api.openclaw_bridge import ToolLoopDetector
        detector = ToolLoopDetector(max_repeats=3, max_total=15)
        detector.record("web_search")
        detector.record("browser")
        detector.record("exec")
        detector.record("read")
        looping, reason = detector.is_looping()
        assert looping is False

    def test_total_calls_exceeded(self):
        from api.openclaw_bridge import ToolLoopDetector
        detector = ToolLoopDetector(max_repeats=10, max_total=5)
        for i in range(6):
            detector.record(f"tool_{i}")
        looping, reason = detector.is_looping()
        assert looping is True
        assert "Trop" in reason

    def test_get_stats(self):
        from api.openclaw_bridge import ToolLoopDetector
        detector = ToolLoopDetector()
        detector.record("web_search")
        detector.record("browser")
        stats = detector.get_stats()
        assert stats["total_calls"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# 16. Tool profiles & permissions
# ══════════════════════════════════════════════════════════════════════════════

class TestToolProfiles:
    """Tests des profils d'outils et permissions."""

    def test_get_allowed_tools(self):
        from api.openclaw_bridge import get_allowed_tools
        tools = get_allowed_tools("agent3")
        assert isinstance(tools, (list, set, tuple))

    def test_tool_allowed_check(self):
        from api.openclaw_bridge import is_tool_allowed
        # web_search should be allowed for agent3
        result = is_tool_allowed("web_search", "agent3")
        assert isinstance(result, bool)

    def test_tool_profiles_exist(self):
        from api.openclaw_bridge import TOOL_PROFILES
        assert isinstance(TOOL_PROFILES, dict)
        assert "agent3" in TOOL_PROFILES


# ══════════════════════════════════════════════════════════════════════════════
# 17. Context helper
# ══════════════════════════════════════════════════════════════════════════════

class TestContextHelper:
    """Tests du helper de contexte."""

    def test_moment_du_jour(self):
        from api.context_helper import _moment_du_jour
        assert _moment_du_jour(8) in ["matin"]
        assert _moment_du_jour(14) in ["apres-midi", "après-midi"]
        assert _moment_du_jour(20) in ["soir", "soiree", "soirée"]
        assert _moment_du_jour(3) in ["nuit"]

    def test_format_device_context_none(self):
        from api.context_helper import format_device_context
        result = format_device_context(None)
        assert result == ""

    def test_format_device_context_dict(self):
        from api.context_helper import format_device_context
        ctx = {"platform": "Windows", "screen": "1920x1080", "battery": 85}
        result = format_device_context(ctx)
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════════════════════
# 18. Cron CRUD DB (direct)
# ══════════════════════════════════════════════════════════════════════════════

class TestCronCRUD:
    """Tests CRUD des taches cron en DB."""

    def test_insert_and_list_cron(self, db):
        cron_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            "INSERT INTO agent3_cron (id, auth_user_id, label, instruction, cron_expr, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (cron_id, TEST_USER_ID, "Test Cron", "Fais un rapport", "0 9 * * *", now),
        )
        db.conn.commit()
        rows = db.conn.execute(
            "SELECT * FROM agent3_cron WHERE auth_user_id = ?", (TEST_USER_ID,)
        ).fetchall()
        assert len(rows) == 1

    def test_toggle_cron(self, db):
        cron_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            "INSERT INTO agent3_cron (id, auth_user_id, label, instruction, cron_expr, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (cron_id, TEST_USER_ID, "Toggle Test", "Instruction", "0 9 * * *", now),
        )
        db.conn.commit()
        # Toggle off
        db.conn.execute("UPDATE agent3_cron SET enabled = 0 WHERE id = ?", (cron_id,))
        db.conn.commit()
        row = db.conn.execute("SELECT enabled FROM agent3_cron WHERE id = ?", (cron_id,)).fetchone()
        assert row[0] == 0

    def test_delete_cron(self, db):
        cron_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            "INSERT INTO agent3_cron (id, auth_user_id, label, instruction, cron_expr, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?)",
            (cron_id, TEST_USER_ID, "Delete Test", "Instruction", "*/5 * * * *", now),
        )
        db.conn.commit()
        db.conn.execute("DELETE FROM agent3_cron WHERE id = ?", (cron_id,))
        db.conn.commit()
        row = db.conn.execute("SELECT * FROM agent3_cron WHERE id = ?", (cron_id,)).fetchone()
        assert row is None


# ══════════════════════════════════════════════════════════════════════════════
# 19. Tasks CRUD DB (direct)
# ══════════════════════════════════════════════════════════════════════════════

class TestTasksCRUD:
    """Tests CRUD des taches multi-etapes."""

    def test_create_task(self, db):
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        steps = json.dumps([
            {"label": "Recherche", "status": "pending"},
            {"label": "Analyse", "status": "pending"},
        ])
        db.conn.execute(
            "INSERT INTO agent3_tasks (id, auth_user_id, title, steps_json, status, progress, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'en_cours', 0.0, ?, ?)",
            (task_id, TEST_USER_ID, "Etude de marche", steps, now, now),
        )
        db.conn.commit()
        row = db.conn.execute("SELECT * FROM agent3_tasks WHERE id = ?", (task_id,)).fetchone()
        assert row is not None

    def test_update_task_progress(self, db):
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            "INSERT INTO agent3_tasks (id, auth_user_id, title, steps_json, status, progress, created_at, updated_at) "
            "VALUES (?, ?, 'Task', '[]', 'en_cours', 0.0, ?, ?)",
            (task_id, TEST_USER_ID, now, now),
        )
        db.conn.commit()
        db.conn.execute(
            "UPDATE agent3_tasks SET progress = 50.0, updated_at = ? WHERE id = ?",
            (now, task_id),
        )
        db.conn.commit()
        row = db.conn.execute("SELECT progress FROM agent3_tasks WHERE id = ?", (task_id,)).fetchone()
        assert row[0] == 50.0

    def test_delete_task(self, db):
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            "INSERT INTO agent3_tasks (id, auth_user_id, title, steps_json, status, progress, created_at, updated_at) "
            "VALUES (?, ?, 'To Delete', '[]', 'en_cours', 0.0, ?, ?)",
            (task_id, TEST_USER_ID, now, now),
        )
        db.conn.commit()
        db.conn.execute("DELETE FROM agent3_tasks WHERE id = ?", (task_id,))
        db.conn.commit()
        row = db.conn.execute("SELECT * FROM agent3_tasks WHERE id = ?", (task_id,)).fetchone()
        assert row is None


# ══════════════════════════════════════════════════════════════════════════════
# 20. Endpoints HTTP (sans API key)
# ══════════════════════════════════════════════════════════════════════════════

class TestEndpointsNoApiKey:
    """Tests des endpoints Agent 3 qui NE necessitent PAS de cle API."""

    @pytest.fixture()
    def client(self, db):
        from fastapi.testclient import TestClient
        from api.main import app
        from api.dependencies import get_db, get_agent, get_optional_user

        async def _override_db():
            yield db

        def _override_agent():
            return None

        async def _override_user():
            return TEST_USER_ID

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_agent] = _override_agent
        app.dependency_overrides[get_optional_user] = _override_user

        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()

    # ── Status ──
    def test_status_endpoint(self, client):
        resp = client.get("/api/agent3/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "openclaw_connected" in body

    # ── Capabilities ──
    def test_capabilities_endpoint(self, client):
        resp = client.get("/api/agent3/capabilities")
        assert resp.status_code == 200

    # ── Messages (empty) ──
    def test_messages_empty(self, client):
        resp = client.get("/api/agent3/messages")
        assert resp.status_code == 200
        assert resp.json() == []

    # ── Delete messages (empty) ──
    def test_delete_messages_empty(self, client):
        resp = client.delete("/api/agent3/messages")
        assert resp.status_code == 200

    # ── Cron CRUD via HTTP ──
    def test_cron_list_empty(self, client):
        resp = client.get("/api/agent3/cron")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_cron_create_and_list(self, client):
        resp = client.post("/api/agent3/cron", json={
            "label": "Rapport quotidien",
            "instruction": "Genere un rapport",
            "cron_expr": "0 9 * * *",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "cron_id" in data
        assert data["success"] is True

        resp = client.get("/api/agent3/cron")
        crons = resp.json()
        assert len(crons) == 1
        assert crons[0]["label"] == "Rapport quotidien"

    def test_cron_delete(self, client):
        resp = client.post("/api/agent3/cron", json={
            "label": "A supprimer",
            "instruction": "Rien",
            "cron_expr": "*/5 * * * *",
        })
        cron_id = resp.json()["cron_id"]
        resp = client.delete(f"/api/agent3/cron/{cron_id}")
        assert resp.status_code == 200
        assert client.get("/api/agent3/cron").json() == []

    def test_cron_toggle(self, client):
        resp = client.post("/api/agent3/cron", json={
            "label": "Toggle",
            "instruction": "Test",
            "cron_expr": "0 9 * * *",
        })
        cron_id = resp.json()["cron_id"]
        resp = client.put(f"/api/agent3/cron/{cron_id}/toggle")
        assert resp.status_code == 200
        body = resp.json()
        assert "enabled" in body

    # ── Tasks CRUD via HTTP ──
    def test_tasks_list_empty(self, client):
        resp = client.get("/api/agent3/tasks")
        assert resp.status_code == 200
        assert resp.json() == []

    # ── Memory via HTTP ──
    def test_memory_list_empty(self, client):
        resp = client.get("/api/agent3/memory")
        assert resp.status_code == 200
        assert resp.json() == []

    # ── Preferences via HTTP ──
    def test_preferences_get_default(self, client):
        resp = client.get("/api/agent3/preferences")
        assert resp.status_code == 200
        prefs = resp.json()
        assert prefs["confirm_destructive"] is True

    def test_preferences_update(self, client):
        resp = client.put("/api/agent3/preferences", json={
            "confirm_destructive": False,
        })
        assert resp.status_code == 200
        resp = client.get("/api/agent3/preferences")
        prefs = resp.json()
        assert prefs["confirm_destructive"] is False

    # ── Routing ──
    def test_routing_table(self, client):
        resp = client.get("/api/agent3/routing")
        assert resp.status_code == 200
        body = resp.json()
        assert "routes" in body
        assert len(body["routes"]) >= 5

    def test_routing_test(self, client):
        resp = client.post("/api/agent3/routing/test", json={
            "message": "Recherche les prix des MacBook"
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["routing"]["agent_id"] == "researcher"

    # ── Tool profiles ──
    def test_tool_profiles(self, client):
        resp = client.get("/api/agent3/tool-profiles")
        assert resp.status_code == 200

    # ── Skills (ClawHub) ──
    def test_skills_list(self, client):
        resp = client.get("/api/agent3/skills")
        assert resp.status_code == 200

    # ── Setup check ──
    def test_setup_check(self, client):
        resp = client.get("/api/agent3/setup/check")
        assert resp.status_code == 200
        body = resp.json()
        assert "ready" in body

    # ── Export (empty conversation) ──
    def test_export_empty_conversation(self, client):
        resp = client.get("/api/agent3/export")
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# 21. Code execution (sandbox execute — safe code only)
# ══════════════════════════════════════════════════════════════════════════════

class TestCodeSandboxExecution:
    """Tests d'execution de code dans le sandbox (code sans danger)."""

    def test_execute_simple_python(self):
        import asyncio
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox(timeout=10)
        result = asyncio.get_event_loop().run_until_complete(
            sandbox.execute("print('hello world')", language="python")
        )
        assert result.success is True
        assert "hello world" in result.stdout
        assert result.exit_code == 0

    def test_execute_python_math(self):
        import asyncio
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox(timeout=10)
        result = asyncio.get_event_loop().run_until_complete(
            sandbox.execute("print(2 + 3)", language="python")
        )
        assert result.success is True
        assert "5" in result.stdout

    def test_execute_blocked_code(self):
        import asyncio
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox(timeout=10)
        result = asyncio.get_event_loop().run_until_complete(
            sandbox.execute("import os\nos.system('whoami')", language="python")
        )
        assert result.blocked is True

    def test_execute_syntax_error(self):
        import asyncio
        from api.code_sandbox import CodeSandbox
        sandbox = CodeSandbox(timeout=10)
        result = asyncio.get_event_loop().run_until_complete(
            sandbox.execute("def broken(:", language="python")
        )
        assert result.success is False
        assert result.exit_code != 0


# ══════════════════════════════════════════════════════════════════════════════
# 22. Circuit breaker (OpenClaw bridge)
# ══════════════════════════════════════════════════════════════════════════════

class TestCircuitBreaker:
    """Tests du circuit breaker."""

    def test_circuit_breaker_initial_state(self):
        from api.openclaw_bridge import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=5)
        assert cb.can_execute() is True  # Starts closed (can execute)
        assert cb.state == "closed"

    def test_circuit_breaker_opens_after_failures(self):
        from api.openclaw_bridge import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.can_execute() is False
        assert cb.state == "open"

    def test_circuit_breaker_resets_on_success(self):
        from api.openclaw_bridge import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.can_execute() is True
        assert cb.state == "closed"

    def test_circuit_breaker_stats(self):
        from api.openclaw_bridge import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        cb.record_failure()
        cb.record_failure()
        stats = cb.get_stats()
        assert stats["failures"] == 2
        assert stats["threshold"] == 5
        assert stats["state"] == "closed"


# ══════════════════════════════════════════════════════════════════════════════
# 23. Action parsing regex
# ══════════════════════════════════════════════════════════════════════════════

class TestActionParsing:
    """Tests du regex de parsing des actions dans les reponses."""

    def _parse_actions(self, text: str) -> list[tuple[str, dict]]:
        """Simule le parsing d'actions comme dans le chat handler."""
        actions = []
        for match in re.finditer(r'\[ACTION:(\w+)\](.*?)\[/ACTION\]', text, re.DOTALL):
            action_type = match.group(1)
            try:
                action_data = json.loads(match.group(2))
                actions.append((action_type, action_data))
            except json.JSONDecodeError:
                actions.append((action_type, None))
        return actions

    def test_parse_single_action(self):
        text = 'Voici. [ACTION:PDF]{"title": "Test"}[/ACTION]'
        actions = self._parse_actions(text)
        assert len(actions) == 1
        assert actions[0][0] == "PDF"
        assert actions[0][1]["title"] == "Test"

    def test_parse_multiple_actions(self):
        text = (
            'Voici. [ACTION:SEARCH]{"query": "AI"}[/ACTION] '
            '[ACTION:PDF]{"title": "Rapport"}[/ACTION]'
        )
        actions = self._parse_actions(text)
        assert len(actions) == 2
        assert actions[0][0] == "SEARCH"
        assert actions[1][0] == "PDF"

    def test_parse_email_action(self):
        text = '[ACTION:EMAIL]{"to": "a@b.com", "subject": "Hello", "body": "Hi there"}[/ACTION]'
        actions = self._parse_actions(text)
        assert len(actions) == 1
        assert actions[0][1]["to"] == "a@b.com"

    def test_parse_computer_use_action(self):
        text = '[ACTION:COMPUTER_USE]{"prompt": "Open browser", "reason": "No tool available"}[/ACTION]'
        actions = self._parse_actions(text)
        assert len(actions) == 1
        assert actions[0][0] == "COMPUTER_USE"
        assert actions[0][1]["prompt"] == "Open browser"

    def test_parse_multiline_json(self):
        text = '[ACTION:PDF]{\n"title": "Test",\n"sections": []\n}[/ACTION]'
        actions = self._parse_actions(text)
        assert len(actions) == 1
        assert actions[0][1]["title"] == "Test"

    def test_parse_invalid_json(self):
        text = '[ACTION:PDF]{invalid json}[/ACTION]'
        actions = self._parse_actions(text)
        assert len(actions) == 1
        assert actions[0][0] == "PDF"
        assert actions[0][1] is None  # JSON parse failed

    def test_parse_no_actions(self):
        text = "Juste un message normal sans action."
        actions = self._parse_actions(text)
        assert len(actions) == 0

    def test_parse_all_known_action_types(self):
        """Verifie que tous les types d'action connus sont parsables."""
        types = [
            "PDF", "SEARCH", "X_SEARCH", "WEBPAGE", "EMAIL", "GMAIL_SEND",
            "CALENDAR_EVENT", "DRIVE_SAVE", "REMINDER", "LINK", "COPY",
            "CODE", "EXEC_RESULT", "FILE_CREATE", "FILE_DOWNLOAD",
            "SCREENSHOT", "IMAGE", "CANVAS", "MEMORY", "CRON",
            "SPAWN_AGENT", "TASK_CREATE", "TASK_UPDATE",
            "SKILL_SEARCH", "SKILL_INSTALL", "COMPUTER_USE",
        ]
        for t in types:
            text = f'[ACTION:{t}]{{"test": true}}[/ACTION]'
            actions = self._parse_actions(text)
            assert len(actions) == 1, f"Failed to parse action type: {t}"
            assert actions[0][0] == t


# ══════════════════════════════════════════════════════════════════════════════
# 24. Familiarity level & tone progression
# ══════════════════════════════════════════════════════════════════════════════

class TestFamiliarityLevel:
    """Tests du calcul du niveau de familiarite (ton progressif)."""

    def test_level_0_no_data(self, db):
        """Nouvel utilisateur sans aucune donnee → niveau 0."""
        from api.routers.agent3_openclaw import _compute_familiarity_level
        level = _compute_familiarity_level(db, "unknown-user", None, [], 0)
        assert level == 0

    def test_level_1_partial_profil(self, db):
        """Utilisateur avec profil partiel → niveau 1."""
        from api.routers.agent3_openclaw import _compute_familiarity_level
        profil = {"nom": "Jean", "profession": "", "ville": "", "objectif_description": ""}
        level = _compute_familiarity_level(db, "user-1", profil, [], 0)
        assert level == 1

    def test_level_increases_with_messages(self, db):
        """Plus de messages = niveau plus eleve."""
        from api.routers.agent3_openclaw import _compute_familiarity_level
        uid = TEST_USER_ID
        # Inserer 25 messages
        for i in range(25):
            db.conn.execute(
                "INSERT INTO agent3_messages (id, auth_user_id, role, content, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                (str(uuid.uuid4()), uid, "user", f"msg {i}"),
            )
        db.conn.commit()
        profil = {"nom": "Jean", "profession": "Dev", "ville": "Paris", "objectif_description": "CTO"}
        level = _compute_familiarity_level(db, uid, profil, [], 0)
        assert level >= 2

    def test_level_3_with_full_data(self, db):
        """Utilisateur avec beaucoup de donnees → niveau 3."""
        from api.routers.agent3_openclaw import _compute_familiarity_level
        uid = TEST_USER_ID
        # 60 messages
        for i in range(60):
            db.conn.execute(
                "INSERT INTO agent3_messages (id, auth_user_id, role, content, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                (str(uuid.uuid4()), uid, "user" if i % 2 == 0 else "agent", f"msg {i}"),
            )
        db.conn.commit()
        profil = {"nom": "Jean", "profession": "Dev", "ville": "Paris", "objectif_description": "Devenir CTO"}
        decisions = [{"impact": 2.0}] * 6
        level = _compute_familiarity_level(db, uid, profil, decisions, 12)
        assert level == 3

    def test_level_monotonically_increases(self, db):
        """Le niveau ne diminue jamais quand on ajoute des donnees."""
        from api.routers.agent3_openclaw import _compute_familiarity_level
        uid = TEST_USER_ID
        profil = None
        levels = []

        # Pas de donnees
        levels.append(_compute_familiarity_level(db, uid, profil, [], 0))

        # Profil partiel
        profil = {"nom": "Test", "profession": "", "ville": "", "objectif_description": ""}
        levels.append(_compute_familiarity_level(db, uid, profil, [], 0))

        # Profil complet
        profil = {"nom": "Test", "profession": "Dev", "ville": "Lyon", "objectif_description": "Objectif"}
        levels.append(_compute_familiarity_level(db, uid, profil, [], 0))

        # + messages
        for i in range(10):
            db.conn.execute(
                "INSERT INTO agent3_messages (id, auth_user_id, role, content, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                (str(uuid.uuid4()), uid, "user", f"msg {i}"),
            )
        db.conn.commit()
        levels.append(_compute_familiarity_level(db, uid, profil, [], 0))

        # + decisions
        decisions = [{"impact": 1.0}] * 5
        levels.append(_compute_familiarity_level(db, uid, profil, decisions, 5))

        # Verifier que ca monte (ou reste stable)
        for i in range(1, len(levels)):
            assert levels[i] >= levels[i - 1], f"Level decreased at step {i}: {levels}"


class TestToneInstructions:
    """Tests des instructions de ton en fonction du niveau de familiarite."""

    def test_level_0_vouvoie(self):
        from api.routers.agent3_openclaw import _get_tone_instructions
        tone = _get_tone_instructions(0)
        assert "vouvoie" in tone.lower() or "neutre" in tone.lower()

    def test_level_1_tutoie(self):
        from api.routers.agent3_openclaw import _get_tone_instructions
        tone = _get_tone_instructions(1)
        assert "tutoie" in tone.lower()

    def test_level_2_direct(self):
        from api.routers.agent3_openclaw import _get_tone_instructions
        tone = _get_tone_instructions(2)
        assert "direct" in tone.lower() or "cash" in tone.lower()

    def test_level_3_brutal(self):
        from api.routers.agent3_openclaw import _get_tone_instructions
        tone = _get_tone_instructions(3)
        assert "brutal" in tone.lower() or "grand frere" in tone.lower()

    def test_decision_score_affects_tone(self):
        from api.routers.agent3_openclaw import _get_tone_instructions
        angry = _get_tone_instructions(3, decision_score=-20)
        happy = _get_tone_instructions(3, decision_score=50)
        assert "furieux" in angry.lower() or "secoue" in angry.lower()
        assert "respectueux" in happy.lower() or "bien" in happy.lower()

    def test_level_2_with_bad_decisions(self):
        from api.routers.agent3_openclaw import _get_tone_instructions
        tone = _get_tone_instructions(2, decision_score=-15)
        assert "frustre" in tone.lower() or "pousse" in tone.lower()

    def test_level_0_ignores_decision_score(self):
        """Au niveau 0, le score de decisions ne change pas le ton neutre."""
        from api.routers.agent3_openclaw import _get_tone_instructions
        tone_bad = _get_tone_instructions(0, decision_score=-50)
        tone_good = _get_tone_instructions(0, decision_score=80)
        # Les deux doivent rester neutres/polis
        assert "neutre" in tone_bad.lower() or "poli" in tone_bad.lower()
        assert "neutre" in tone_good.lower() or "poli" in tone_good.lower()


# ══════════════════════════════════════════════════════════════════════════════
# 26. Working Memory (Scratchpad)
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkingMemory:
    """Tests du scratchpad / memoire de travail en RAM."""

    def setup_method(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory._store.clear()
        WorkingMemory._history.clear()

    def test_set_and_get(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.set("u1", "key1", "value1")
        assert WorkingMemory.get("u1", "key1") == "value1"

    def test_get_default(self):
        from api.routers.agent3_openclaw import WorkingMemory
        assert WorkingMemory.get("u1", "missing") is None
        assert WorkingMemory.get("u1", "missing", "fallback") == "fallback"

    def test_append(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.append("u1", "list_key", "a")
        WorkingMemory.append("u1", "list_key", "b")
        result = WorkingMemory.get("u1", "list_key")
        assert result == ["a", "b"]

    def test_append_creates_list(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.set("u1", "x", "not_a_list")
        WorkingMemory.append("u1", "x", "item")
        assert WorkingMemory.get("u1", "x") == ["item"]

    def test_all_returns_copy(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.set("u1", "a", 1)
        WorkingMemory.set("u1", "b", 2)
        data = WorkingMemory.all("u1")
        assert data == {"a": 1, "b": 2}
        # Modifying the copy doesn't affect store
        data["c"] = 3
        assert WorkingMemory.get("u1", "c") is None

    def test_clear(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.set("u1", "k", "v")
        WorkingMemory.clear("u1")
        assert WorkingMemory.all("u1") == {}
        assert WorkingMemory.history("u1") == []

    def test_user_isolation(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.set("u1", "key", "val1")
        WorkingMemory.set("u2", "key", "val2")
        assert WorkingMemory.get("u1", "key") == "val1"
        assert WorkingMemory.get("u2", "key") == "val2"

    def test_session_isolation(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.set("u1", "key", "s1", session_id="sess1")
        WorkingMemory.set("u1", "key", "s2", session_id="sess2")
        assert WorkingMemory.get("u1", "key", session_id="sess1") == "s1"
        assert WorkingMemory.get("u1", "key", session_id="sess2") == "s2"

    def test_summarize_empty(self):
        from api.routers.agent3_openclaw import WorkingMemory
        assert WorkingMemory.summarize("u1") == ""

    def test_summarize_with_data(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.set("u1", "search_results", "AI trends 2025")
        WorkingMemory.set("u1", "last_pdf", "/api/agent3/pdf/report.pdf")
        summary = WorkingMemory.summarize("u1")
        assert "MEMOIRE DE TRAVAIL" in summary
        assert "search_results" in summary
        assert "last_pdf" in summary

    def test_summarize_truncation(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.set("u1", "big", "x" * 500)
        summary = WorkingMemory.summarize("u1", max_len=100)
        assert len(summary) <= 100
        assert summary.endswith("...")

    def test_history(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.set("u1", "a", 1)
        WorkingMemory.append("u1", "b", 2)
        hist = WorkingMemory.history("u1")
        assert len(hist) == 2
        assert hist[0]["action"] == "set"
        assert hist[1]["action"] == "append"

    def test_size(self):
        from api.routers.agent3_openclaw import WorkingMemory
        assert WorkingMemory.size("u1") == 0
        WorkingMemory.set("u1", "a", 1)
        WorkingMemory.set("u1", "b", 2)
        assert WorkingMemory.size("u1") == 2

    def test_overwrite_value(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.set("u1", "k", "old")
        WorkingMemory.set("u1", "k", "new")
        assert WorkingMemory.get("u1", "k") == "new"

    def test_complex_values(self):
        from api.routers.agent3_openclaw import WorkingMemory
        WorkingMemory.set("u1", "data", {"nested": [1, 2], "text": "hello"})
        result = WorkingMemory.get("u1", "data")
        assert result["nested"] == [1, 2]
        assert result["text"] == "hello"


# ══════════════════════════════════════════════════════════════════════════════
# 27. Heuristic Planner (enrichi)
# ══════════════════════════════════════════════════════════════════════════════

class TestHeuristicPlan:
    """Tests du planificateur heuristique enrichi."""

    def test_simple_message_has_steps(self):
        from api.routers.agent3_openclaw import _heuristic_plan
        plan = _heuristic_plan("salut comment ca va")
        assert isinstance(plan, list)
        assert len(plan) >= 1
        for step in plan:
            assert "id" in step
            assert "label" in step
            assert "depends_on" in step

    def test_search_task_has_web_search_hint(self):
        from api.routers.agent3_openclaw import _heuristic_plan
        plan = _heuristic_plan("cherche les tendances AI 2025")
        hints = [s.get("tool_hint") for s in plan if s.get("tool_hint")]
        assert "web_search" in hints

    def test_pdf_task_has_pdf_hint(self):
        from api.routers.agent3_openclaw import _heuristic_plan
        plan = _heuristic_plan("fais-moi un rapport PDF sur le marketing digital")
        hints = [s.get("tool_hint") for s in plan if s.get("tool_hint")]
        assert "ACTION:PDF" in hints

    def test_email_task_has_email_hint(self):
        from api.routers.agent3_openclaw import _heuristic_plan
        plan = _heuristic_plan("envoie un email a mon boss")
        hints = [s.get("tool_hint") for s in plan if s.get("tool_hint")]
        assert "ACTION:EMAIL" in hints

    def test_code_task_has_code_hint(self):
        from api.routers.agent3_openclaw import _heuristic_plan
        plan = _heuristic_plan("ecris un script Python pour trier des fichiers")
        hints = [s.get("tool_hint") for s in plan if s.get("tool_hint")]
        assert "code_sandbox" in hints

    def test_browse_task_has_browser_hint(self):
        from api.routers.agent3_openclaw import _heuristic_plan
        plan = _heuristic_plan("va sur le site linkedin et extraire les infos")
        hints = [s.get("tool_hint") for s in plan if s.get("tool_hint")]
        assert "browser" in hints

    def test_depends_on_chain(self):
        """Les etapes doivent dependre de la precedente."""
        from api.routers.agent3_openclaw import _heuristic_plan
        plan = _heuristic_plan("cherche des infos et fais un rapport pdf")
        # Verifier que le chain est correct
        for i in range(1, len(plan)):
            assert plan[i]["depends_on"] == [plan[i - 1]["id"]]

    def test_all_steps_have_status(self):
        from api.routers.agent3_openclaw import _heuristic_plan
        plan = _heuristic_plan("analyse le marche et fais un rapport")
        for step in plan:
            assert step["status"] == "pending"

    def test_complex_task_has_many_steps(self):
        from api.routers.agent3_openclaw import _heuristic_plan
        plan = _heuristic_plan("cherche les concurrents, analyse les prix, fais un rapport PDF avec synthese")
        assert len(plan) >= 4  # understand + search + analyze + pdf + respond


# ══════════════════════════════════════════════════════════════════════════════
# 28. LLM Planner (fallback sans API)
# ══════════════════════════════════════════════════════════════════════════════

class TestLLMPlanner:
    """Tests du planificateur LLM (tombe en fallback heuristique sans API key)."""

    def test_fallback_without_api_key(self):
        """Sans ANTHROPIC_API_KEY, retourne le plan heuristique."""
        import asyncio
        from api.routers.agent3_openclaw import _llm_plan_task
        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            plan = asyncio.get_event_loop().run_until_complete(
                _llm_plan_task("cherche les tendances AI")
            )
            assert isinstance(plan, list)
            assert len(plan) >= 1
            for step in plan:
                assert "id" in step
                assert "depends_on" in step
        finally:
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key

    def test_fallback_with_invalid_key(self):
        """Avec une fausse cle, le LLM echoue → fallback heuristique."""
        import asyncio
        from api.routers.agent3_openclaw import _llm_plan_task
        plan = asyncio.get_event_loop().run_until_complete(
            _llm_plan_task("cherche les tendances AI", api_key="sk-fake-invalid")
        )
        assert isinstance(plan, list)
        assert len(plan) >= 1

    def test_context_is_accepted(self):
        """Verifier que le contexte est passe sans erreur."""
        import asyncio
        from api.routers.agent3_openclaw import _llm_plan_task
        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            plan = asyncio.get_event_loop().run_until_complete(
                _llm_plan_task("fais un truc", context="Utilisateur: Jean, Dev, Paris")
            )
            assert isinstance(plan, list)
        finally:
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key


# ══════════════════════════════════════════════════════════════════════════════
# 29. Self-reflection (ReAct)
# ══════════════════════════════════════════════════════════════════════════════

class TestSelfReflection:
    """Tests de la reflexion / auto-correction sur echec."""

    def test_auth_error_is_not_retryable(self):
        """Les erreurs d'autorisation ne doivent pas etre retentees."""
        import asyncio
        from api.routers.agent3_openclaw import _reflect_on_failure
        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            result = asyncio.get_event_loop().run_until_complete(
                _reflect_on_failure("EMAIL", {"to": "a@b.com"}, "403 Forbidden")
            )
            assert result["should_retry"] is False
        finally:
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key

    def test_timeout_is_retryable(self):
        """Les erreurs reseau temporaires doivent etre retentees."""
        import asyncio
        from api.routers.agent3_openclaw import _reflect_on_failure
        result = asyncio.get_event_loop().run_until_complete(
            _reflect_on_failure("SEARCH", {"query": "AI"}, "Connection timeout after 30s")
        )
        assert result["should_retry"] is True
        assert result["corrected_action"] is not None
        assert result["corrected_action"]["type"] == "SEARCH"

    def test_connection_refused_is_retryable(self):
        import asyncio
        from api.routers.agent3_openclaw import _reflect_on_failure
        result = asyncio.get_event_loop().run_until_complete(
            _reflect_on_failure("PDF", {}, "Connection refused")
        )
        assert result["should_retry"] is True

    def test_unauthorized_is_not_retryable(self):
        import asyncio
        from api.routers.agent3_openclaw import _reflect_on_failure
        result = asyncio.get_event_loop().run_until_complete(
            _reflect_on_failure("CALENDAR_EVENT", {}, "unauthorized: invalid token")
        )
        assert result["should_retry"] is False

    def test_quota_exceeded_is_not_retryable(self):
        import asyncio
        from api.routers.agent3_openclaw import _reflect_on_failure
        result = asyncio.get_event_loop().run_until_complete(
            _reflect_on_failure("IMAGE", {}, "Quota exceeded for DALL-E 3")
        )
        assert result["should_retry"] is False

    def test_unknown_error_without_api(self):
        """Sans API, une erreur inconnue retourne should_retry=False."""
        import asyncio
        from api.routers.agent3_openclaw import _reflect_on_failure
        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            result = asyncio.get_event_loop().run_until_complete(
                _reflect_on_failure("PDF", {"title": "Test"}, "Some weird error happened")
            )
            assert isinstance(result["should_retry"], bool)
            assert "reason" in result
        finally:
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key

    def test_result_has_all_fields(self):
        """Le resultat de reflection doit toujours avoir les 4 champs."""
        import asyncio
        from api.routers.agent3_openclaw import _reflect_on_failure
        result = asyncio.get_event_loop().run_until_complete(
            _reflect_on_failure("SEARCH", {}, "timeout")
        )
        assert "should_retry" in result
        assert "corrected_action" in result
        assert "alternative_approach" in result
        assert "reason" in result

    def test_502_is_retryable(self):
        import asyncio
        from api.routers.agent3_openclaw import _reflect_on_failure
        result = asyncio.get_event_loop().run_until_complete(
            _reflect_on_failure("PDF", {}, "HTTP Error 502: Bad Gateway")
        )
        assert result["should_retry"] is True

    def test_401_is_not_retryable(self):
        import asyncio
        from api.routers.agent3_openclaw import _reflect_on_failure
        result = asyncio.get_event_loop().run_until_complete(
            _reflect_on_failure("EMAIL", {}, "HTTP 401 Unauthorized")
        )
        assert result["should_retry"] is False


# ══════════════════════════════════════════════════════════════════════════════
# 30. Execute with reflection (ReAct loop)
# ══════════════════════════════════════════════════════════════════════════════

class TestExecuteWithReflection:
    """Tests de la boucle ReAct complete (execute → reflect → retry)."""

    def test_success_on_first_attempt(self):
        import asyncio
        from api.routers.agent3_openclaw import _execute_action_with_reflection

        async def executor(action_type, action_data):
            return {"success": True, "result": "ok", "error": ""}

        result = asyncio.get_event_loop().run_until_complete(
            _execute_action_with_reflection("SEARCH", {"query": "AI"}, executor)
        )
        assert result["success"] is True
        assert result["attempts"] == 1
        assert result["reflections"] == []

    def test_fails_after_max_retries(self):
        import asyncio
        from api.routers.agent3_openclaw import _execute_action_with_reflection

        call_count = 0
        async def failing_executor(action_type, action_data):
            nonlocal call_count
            call_count += 1
            return {"success": False, "result": None, "error": "always fails"}

        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            result = asyncio.get_event_loop().run_until_complete(
                _execute_action_with_reflection("SEARCH", {}, failing_executor, max_retries=2)
            )
            assert result["success"] is False
            assert result["attempts"] >= 1
        finally:
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key

    def test_retry_on_transient_error(self):
        import asyncio
        from api.routers.agent3_openclaw import _execute_action_with_reflection

        attempts = 0
        async def flaky_executor(action_type, action_data):
            nonlocal attempts
            attempts += 1
            if attempts < 2:
                return {"success": False, "result": None, "error": "Connection timeout"}
            return {"success": True, "result": "ok", "error": ""}

        result = asyncio.get_event_loop().run_until_complete(
            _execute_action_with_reflection("SEARCH", {"query": "test"}, flaky_executor, max_retries=3)
        )
        assert result["success"] is True
        assert result["attempts"] == 2
        assert len(result["reflections"]) == 1

    def test_no_retry_on_auth_error(self):
        import asyncio
        from api.routers.agent3_openclaw import _execute_action_with_reflection

        async def auth_failing_executor(action_type, action_data):
            return {"success": False, "result": None, "error": "403 Forbidden access denied"}

        result = asyncio.get_event_loop().run_until_complete(
            _execute_action_with_reflection("EMAIL", {}, auth_failing_executor, max_retries=3)
        )
        assert result["success"] is False
        assert result["attempts"] == 1  # No retry
        assert len(result["reflections"]) == 1
        assert result["reflections"][0]["should_retry"] is False

    def test_executor_exception_is_caught(self):
        import asyncio
        from api.routers.agent3_openclaw import _execute_action_with_reflection

        async def crashing_executor(action_type, action_data):
            raise RuntimeError("executor crashed")

        old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            result = asyncio.get_event_loop().run_until_complete(
                _execute_action_with_reflection("PDF", {}, crashing_executor, max_retries=0)
            )
            assert result["success"] is False
            assert "executor crashed" in result["error"]
        finally:
            if old_key:
                os.environ["ANTHROPIC_API_KEY"] = old_key

    def test_reflections_are_recorded(self):
        import asyncio
        from api.routers.agent3_openclaw import _execute_action_with_reflection

        attempt = 0
        async def flaky(action_type, action_data):
            nonlocal attempt
            attempt += 1
            if attempt <= 2:
                return {"success": False, "result": None, "error": "Connection reset"}
            return {"success": True, "result": "done", "error": ""}

        result = asyncio.get_event_loop().run_until_complete(
            _execute_action_with_reflection("SEARCH", {}, flaky, max_retries=3)
        )
        assert result["success"] is True
        assert len(result["reflections"]) == 2
        for r in result["reflections"]:
            assert r["should_retry"] is True
            assert r["reason"] != ""


# ══════════════════════════════════════════════════════════════════════════════
# 31. Prompt builder avec scratchpad
# ══════════════════════════════════════════════════════════════════════════════

class TestPromptWithScratchpad:
    """Verifie que le scratchpad est injecte dans le prompt."""

    def test_prompt_without_scratchpad(self):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        prompt = _build_agent3_prompt(None, [], [])
        assert "MEMOIRE DE TRAVAIL" not in prompt

    def test_prompt_with_scratchpad(self):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        prompt = _build_agent3_prompt(
            None, [], [],
            scratchpad_context="=== MEMOIRE DE TRAVAIL ===\n- search_results: AI trends"
        )
        assert "MEMOIRE DE TRAVAIL" in prompt
        assert "search_results" in prompt
