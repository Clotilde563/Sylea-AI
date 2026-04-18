"""
Tests automatises pour les fonctionnalites Agent 3 inspirees de Claude Code.

Ces tests NE necessitent PAS de cle API (ANTHROPIC_API_KEY).
Ils testent en isolation complete :
  - Slash commands (parseur, toutes les commandes built-in)
  - Prompt caching (verification des flags cache_control)
  - Computer Use (retry, pruning, compaction, cost tracking, config)
  - Context compaction (seuils, logique de compaction)
  - Cost tracker (comptage, seuils, model breakdown)
  - Slash command interception dans les routes /chat et /chat/stream
"""

import asyncio
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sylea.core.storage.database import DatabaseManager


# ══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════════════

TEST_USER_ID = "test-features-agent3"


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

    try:
        conn.execute(
            "ALTER TABLE profil_utilisateur ADD COLUMN objectif_probabilite_calculee REAL DEFAULT 0.0"
        )
    except Exception:
        pass

    conn.execute(
        "INSERT INTO users (id, email, hashed_password, provider, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (TEST_USER_ID, "test-features@test.com", "fake_hash", "local"),
    )
    conn.commit()

    from api.routers.agent3_openclaw import _ensure_agent3_tables
    _ensure_agent3_tables(manager)

    yield manager
    manager.disconnect()


@pytest.fixture()
def slash_ctx(db):
    """Contexte standard pour les slash commands."""
    return {"db": db, "user_id": TEST_USER_ID, "session_key": f"agent3_{TEST_USER_ID}"}


# ══════════════════════════════════════════════════════════════════════════════
# 1. Slash Command Parser
# ══════════════════════════════════════════════════════════════════════════════

class TestSlashCommandParser:
    """Tests du parseur de slash commands."""

    def test_parser_singleton(self):
        """get_slash_parser retourne toujours la meme instance."""
        from api.agent3_slash_commands import get_slash_parser
        p1 = get_slash_parser()
        p2 = get_slash_parser()
        assert p1 is p2

    def test_is_command_valid(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        assert parser.is_command("/help")
        assert parser.is_command("/status")
        assert parser.is_command("/skills")
        assert parser.is_command("/cost")
        assert parser.is_command("/clear")
        assert parser.is_command("/memory")
        assert parser.is_command("/undo")
        assert parser.is_command("/hooks")
        assert parser.is_command("/extract")
        assert parser.is_command("/todo")

    def test_is_command_invalid(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        assert not parser.is_command("hello")
        assert not parser.is_command("bonjour")
        assert not parser.is_command("/nonexistent")
        assert not parser.is_command("")

    def test_is_command_aliases(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        assert parser.is_command("/h")      # alias for /help
        assert parser.is_command("/?")      # alias for /help
        assert parser.is_command("/cls")    # alias for /clear
        assert parser.is_command("/reset")  # alias for /clear
        assert parser.is_command("/mem")    # alias for /memory
        assert parser.is_command("/stat")   # alias for /status
        assert parser.is_command("/$")      # alias for /cost
        assert parser.is_command("/todos")  # alias for /todo

    def test_parse_command_with_args(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        cmd, args = parser.parse("/memory search test")
        assert cmd is not None
        assert cmd.name == "memory"
        assert args == "search test"

    def test_parse_command_no_args(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        cmd, args = parser.parse("/help")
        assert cmd is not None
        assert cmd.name == "help"
        assert args == ""

    def test_parse_not_command(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        cmd, text = parser.parse("bonjour")
        assert cmd is None
        assert text == "bonjour"

    def test_parse_alias_resolves(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        cmd, args = parser.parse("/cls")
        assert cmd is not None
        assert cmd.name == "clear"

    def test_list_commands_no_hidden(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        commands = parser.list_commands(include_hidden=False)
        assert len(commands) >= 10
        names = [c["name"] for c in commands]
        assert "help" in names
        assert "clear" in names
        assert "memory" in names

    def test_list_commands_has_categories(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        commands = parser.list_commands()
        cats = {c["category"] for c in commands}
        assert "general" in cats
        assert "info" in cats
        assert "memoire" in cats
        assert "actions" in cats


# ══════════════════════════════════════════════════════════════════════════════
# 2. Slash Command Handlers (execution)
# ══════════════════════════════════════════════════════════════════════════════

class TestSlashCommandHelp:
    """/help retourne la liste des commandes."""

    def test_help_returns_commands(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/help", {})
        )
        assert result.handled is True
        assert "Commandes disponibles" in result.response
        assert "/help" in result.response
        assert "/status" in result.response
        assert "/skills" in result.response

    def test_help_alias_h(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/h", {})
        )
        assert result.handled is True
        assert "Commandes disponibles" in result.response


class TestSlashCommandClear:
    """/clear efface les messages."""

    def test_clear_with_user(self, db, slash_ctx):
        from api.agent3_slash_commands import get_slash_parser
        from api.routers.agent3_openclaw import _save_agent3_message

        # Inserer des messages
        _save_agent3_message(db, TEST_USER_ID, "user", "test message 1", "text")
        _save_agent3_message(db, TEST_USER_ID, "agent", "reponse 1", "text")

        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/clear", slash_ctx)
        )
        assert result.handled is True
        assert "efface" in result.response.lower()

    def test_clear_returns_action(self, db, slash_ctx):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/clear", slash_ctx)
        )
        assert any(a.get("type") == "CLEAR_MESSAGES" for a in result.actions)


class TestSlashCommandMemory:
    """/memory affiche / recherche / efface les memoires."""

    def test_memory_empty(self, db, slash_ctx):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/memory", slash_ctx)
        )
        assert result.handled is True
        assert "Aucune memoire" in result.response

    def test_memory_list_after_save(self, db, slash_ctx):
        from api.agent3_slash_commands import get_slash_parser
        from api.routers.agent3_openclaw import _save_memory

        _save_memory(db, TEST_USER_ID, "ville", "Lyon", "perso")
        _save_memory(db, TEST_USER_ID, "job", "Developpeur", "pro")

        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/memory", slash_ctx)
        )
        assert "2 memoire(s)" in result.response
        assert "ville" in result.response
        assert "Lyon" in result.response

    def test_memory_clear(self, db, slash_ctx):
        from api.agent3_slash_commands import get_slash_parser
        from api.routers.agent3_openclaw import _save_memory, _load_memories

        _save_memory(db, TEST_USER_ID, "test_key", "test_val", "test")

        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/memory clear", slash_ctx)
        )
        assert "effacees" in result.response

        memories = _load_memories(db, TEST_USER_ID)
        assert len(memories) == 0

    def test_memory_search_no_results(self, db, slash_ctx):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/memory search zzzznotfound", slash_ctx)
        )
        assert "Aucun resultat" in result.response

    def test_memory_no_auth(self, db):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/memory", {"db": db})
        )
        assert "Non authentifie" in (result.error or "")


class TestSlashCommandStatus:
    """/status affiche le statut de l'agent."""

    def test_status_basic(self, slash_ctx):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/status", slash_ctx)
        )
        assert result.handled is True
        assert "Statut Agent 3" in result.response
        assert "Tokens" in result.response
        assert "Cout session" in result.response
        assert "Skills" in result.response
        assert "Hooks" in result.response


class TestSlashCommandCost:
    """/cost affiche le cout detaille."""

    def test_cost_basic(self, slash_ctx):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/cost", slash_ctx)
        )
        assert result.handled is True
        assert "Cout de la session" in result.response
        assert "Input" in result.response
        assert "Output" in result.response
        assert "Cache" in result.response
        assert "Duree" in result.response


class TestSlashCommandSkills:
    """/skills affiche les skills internes + outils OpenClaw."""

    def test_skills_lists_all(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/skills", {})
        )
        assert result.handled is True
        assert "disponible(s)" in result.response
        # Skills internes
        assert "web_search" in result.response
        assert "document" in result.response
        # Outils OpenClaw
        assert "OpenClaw" in result.response
        assert "browser" in result.response
        assert "bash" in result.response

    def test_skills_count_includes_openclaw(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/skills", {})
        )
        # Should show 30 total (4 internal + 26 OpenClaw)
        assert "30 skill" in result.response or "skills internes" in result.response
        assert "26 outils OpenClaw" in result.response


class TestSlashCommandHooks:
    """/hooks affiche les hooks actifs."""

    def test_hooks_lists(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/hooks", {})
        )
        assert result.handled is True
        assert "hook(s) actif(s)" in result.response


class TestSlashCommandUndo:
    """/undo annule la derniere action."""

    def test_undo_no_history(self, slash_ctx):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/undo history", slash_ctx)
        )
        assert result.handled is True
        assert "Aucun historique" in result.response


class TestSlashCommandTodo:
    """/todo affiche les todos."""

    def test_todo_empty(self, slash_ctx):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/todo", slash_ctx)
        )
        assert result.handled is True
        assert "Aucun todo" in result.response


class TestSlashCommandError:
    """Gestion des erreurs et cas limites."""

    def test_unknown_command_not_handled(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        result = asyncio.get_event_loop().run_until_complete(
            parser.execute("/nonexistent", {})
        )
        assert result.handled is False

    def test_empty_string_not_command(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        assert not parser.is_command("")

    def test_just_slash_not_command(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        assert not parser.is_command("/")

    def test_command_case_insensitive(self):
        from api.agent3_slash_commands import get_slash_parser
        parser = get_slash_parser()
        assert parser.is_command("/HELP")
        assert parser.is_command("/Help")
        assert parser.is_command("/STATUS")


# ══════════════════════════════════════════════════════════════════════════════
# 3. SlashCommandResult dataclass
# ══════════════════════════════════════════════════════════════════════════════

class TestSlashCommandResult:
    """Tests de la structure SlashCommandResult."""

    def test_default_values(self):
        from api.agent3_slash_commands import SlashCommandResult
        r = SlashCommandResult()
        assert r.handled is True
        assert r.response == ""
        assert r.error == ""
        assert r.actions == []
        assert r.data == {}
        assert r.silent is False

    def test_to_dict(self):
        from api.agent3_slash_commands import SlashCommandResult
        r = SlashCommandResult(
            handled=True,
            response="test",
            data={"key": "val"},
            actions=[{"type": "TEST"}],
        )
        d = r.to_dict()
        assert d["handled"] is True
        assert d["response"] == "test"
        assert d["data"]["key"] == "val"
        assert d["actions"][0]["type"] == "TEST"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Prompt Caching Verification
# ══════════════════════════════════════════════════════════════════════════════

class TestPromptCaching:
    """Verifie que le prompt caching est active sur tous les fichiers."""

    def test_computer_use_has_cache_control(self):
        """computer_use.py utilise cache_control ephemeral."""
        import ast
        with open("api/computer_use.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert '"cache_control"' in source or "'cache_control'" in source
        assert '"ephemeral"' in source or "'ephemeral'" in source

    def test_agent3_openclaw_has_cache_control(self):
        """agent3_openclaw.py utilise cache_control ephemeral."""
        with open("api/routers/agent3_openclaw.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert source.count("cache_control") >= 4, \
            f"Expected >=4 cache_control occurrences, found {source.count('cache_control')}"

    def test_browser_agent_has_cache_control(self):
        """browser_agent.py utilise cache_control ephemeral."""
        with open("api/browser_agent.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_self_review_has_cache_control(self):
        """agent3_self_review.py utilise cache_control ephemeral."""
        with open("api/agent3_self_review.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_memory_extractor_has_cache_control(self):
        """agent3_memory_extractor.py utilise cache_control ephemeral."""
        with open("api/agent3_memory_extractor.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_orchestrator_has_cache_control(self):
        """agent3_orchestrator.py utilise cache_control ephemeral."""
        with open("api/agent3_orchestrator.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_context_compaction_has_cache_control(self):
        """agent3_context_compaction.py utilise cache_control ephemeral."""
        with open("api/agent3_context_compaction.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_plan_mode_has_cache_control(self):
        """agent3_plan_mode.py utilise cache_control ephemeral."""
        with open("api/agent3_plan_mode.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_skill_web_search_has_cache_control(self):
        """skill_web_search.py utilise cache_control ephemeral."""
        with open("api/agent3_skills/skill_web_search.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_skill_trading_has_cache_control(self):
        """skill_trading.py utilise cache_control ephemeral."""
        with open("api/agent3_skills/skill_trading.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_skill_document_has_cache_control(self):
        """skill_document.py utilise cache_control ephemeral."""
        with open("api/agent3_skills/skill_document.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_skill_pine_script_has_cache_control(self):
        """skill_pine_script.py utilise cache_control ephemeral."""
        with open("api/agent3_skills/skill_pine_script.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_coaching_has_cache_control(self):
        """coaching.py utilise cache_control ephemeral."""
        with open("api/routers/coaching.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_agent_assistant_has_cache_control(self):
        """agent_assistant.py utilise cache_control ephemeral."""
        with open("api/routers/agent_assistant.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_agent_companion_has_cache_control(self):
        """agent_companion.py utilise cache_control ephemeral."""
        with open("api/routers/agent_companion.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_scenarios_has_cache_control(self):
        """scenarios.py utilise cache_control ephemeral."""
        with open("api/routers/scenarios.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_service_client_has_cache_control(self):
        """service_client.py utilise cache_control ephemeral."""
        with open("api/routers/service_client.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "cache_control" in source

    def test_cache_control_format_correct(self):
        """Verifie le format correct : {"type": "ephemeral"}."""
        with open("api/computer_use.py", "r", encoding="utf-8") as f:
            source = f.read()
        # Verify the pattern: "cache_control": {"type": "ephemeral"}
        pattern = r'"cache_control":\s*\{["\']type["\']:\s*["\']ephemeral["\']\}'
        assert re.search(pattern, source), \
            "cache_control format should be {\"type\": \"ephemeral\"}"


# ══════════════════════════════════════════════════════════════════════════════
# 5. Computer Use Configuration
# ══════════════════════════════════════════════════════════════════════════════

class TestComputerUseConfig:
    """Tests des constantes et configuration Computer Use."""

    def test_retry_constants(self):
        from api.computer_use import MAX_API_RETRIES, RETRY_BASE_DELAY, RETRY_JITTER
        assert MAX_API_RETRIES == 3
        assert RETRY_BASE_DELAY == 2.0
        assert RETRY_JITTER == 0.5

    def test_failure_tracking_constants(self):
        from api.computer_use import MAX_CONSECUTIVE_FAILURES, MAX_TOTAL_ERRORS
        assert MAX_CONSECUTIVE_FAILURES == 3
        assert MAX_TOTAL_ERRORS == 10

    def test_context_management_constants(self):
        from api.computer_use import (
            MAX_SCREENSHOTS_IN_CONTEXT,
            MAX_MESSAGES_BEFORE_COMPACT,
            COMPACT_TARGET_MESSAGES,
            IMAGE_TOKENS_ESTIMATE,
        )
        assert MAX_SCREENSHOTS_IN_CONTEXT == 4
        assert MAX_MESSAGES_BEFORE_COMPACT == 20
        assert COMPACT_TARGET_MESSAGES == 10
        assert IMAGE_TOKENS_ESTIMATE == 1600

    def test_cost_thresholds(self):
        from api.computer_use import COST_THRESHOLDS
        assert COST_THRESHOLDS == [0.10, 0.50, 1.00, 5.00]
        assert COST_THRESHOLDS == sorted(COST_THRESHOLDS)

    def test_model_config(self):
        from api.computer_use import ANTHROPIC_MODEL, HAIKU_MODEL, BETA_FLAG, TOOL_TYPE
        assert "sonnet" in ANTHROPIC_MODEL or "claude" in ANTHROPIC_MODEL
        assert "haiku" in HAIKU_MODEL
        assert "computer-use" in BETA_FLAG
        assert "computer" in TOOL_TYPE

    def test_sensitive_patterns_exist(self):
        from api.computer_use import SENSITIVE_TEXT_PATTERNS, DESTRUCTIVE_KEY_COMBOS
        assert len(SENSITIVE_TEXT_PATTERNS) >= 10
        assert "password" in SENSITIVE_TEXT_PATTERNS
        assert "credit card" in SENSITIVE_TEXT_PATTERNS
        assert len(DESTRUCTIVE_KEY_COMBOS) >= 3
        assert "ctrl+w" in DESTRUCTIVE_KEY_COMBOS

    def test_compute_scale(self):
        from api.computer_use import _compute_scale
        # 1920x1080 should scale down
        scale = _compute_scale(1920, 1080)
        assert 0 < scale <= 1.0
        assert scale * 1920 <= 1568  # longest edge constraint

    def test_compute_scale_small_screen(self):
        from api.computer_use import _compute_scale
        # 800x600 should not need scaling
        scale = _compute_scale(800, 600)
        assert scale == 1.0

    def test_system_prompt_exists(self):
        from api.computer_use import SYSTEM_PROMPT
        assert len(SYSTEM_PROMPT) > 500
        assert "Windows" in SYSTEM_PROMPT or "ecran" in SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════════════════════════
# 6. Cost Tracker
# ══════════════════════════════════════════════════════════════════════════════

class TestCostTracker:
    """Tests du suivi des couts API."""

    def test_get_cost_tracker_singleton(self):
        from api.agent3_cost_tracker import get_cost_tracker
        t1 = get_cost_tracker("test-user-1")
        t2 = get_cost_tracker("test-user-1")
        assert t1 is t2

    def test_cost_tracker_initial_state(self):
        from api.agent3_cost_tracker import get_cost_tracker
        tracker = get_cost_tracker(f"test-{uuid.uuid4()}")
        cost = tracker.get()
        assert cost["input_tokens"] == 0
        assert cost["output_tokens"] == 0
        assert cost["calls"] == 0
        assert cost["estimated_usd"] == 0.0

    def test_cost_tracker_record_usage(self):
        from api.agent3_cost_tracker import get_cost_tracker
        tracker = get_cost_tracker(f"test-{uuid.uuid4()}")
        tracker.record(model="claude-sonnet-4-20250514", input_tokens=1000, output_tokens=500)
        cost = tracker.get()
        assert cost["input_tokens"] == 1000
        assert cost["output_tokens"] == 500
        assert cost["calls"] == 1
        assert cost["estimated_usd"] > 0

    def test_cost_tracker_session_duration(self):
        from api.agent3_cost_tracker import get_cost_tracker
        tracker = get_cost_tracker(f"test-{uuid.uuid4()}")
        cost = tracker.get()
        assert "session_duration_seconds" in cost
        assert cost["session_duration_seconds"] >= 0

    def test_cost_tracker_cache_tokens(self):
        from api.agent3_cost_tracker import get_cost_tracker
        tracker = get_cost_tracker(f"test-{uuid.uuid4()}")
        tracker.record(
            model="claude-sonnet-4-20250514",
            input_tokens=1000,
            output_tokens=200,
            cache_read_tokens=800,
        )
        cost = tracker.get()
        assert cost["cache_read_tokens"] == 800


# ══════════════════════════════════════════════════════════════════════════════
# 7. Context Compaction
# ══════════════════════════════════════════════════════════════════════════════

class TestContextCompaction:
    """Tests de la compaction de contexte."""

    def test_compactor_class_exists(self):
        from api.agent3_context_compaction import ContextCompactor
        assert ContextCompactor is not None

    def test_compactor_init_defaults(self):
        from api.agent3_context_compaction import ContextCompactor
        mock_client = MagicMock()
        compactor = ContextCompactor(mock_client)
        assert compactor.max_messages == 18
        assert compactor.target_messages == 8
        assert compactor.keep_last == 6

    def test_compactor_no_compaction_under_threshold(self):
        from api.agent3_context_compaction import ContextCompactor
        mock_client = MagicMock()
        compactor = ContextCompactor(mock_client, max_messages=18)

        # 5 messages — under threshold
        messages = [
            {"role": "user", "content": f"msg {i}"}
            for i in range(5)
        ]
        result = asyncio.get_event_loop().run_until_complete(
            compactor.maybe_compact(messages)
        )
        # Under threshold: returns unchanged
        assert len(result) == 5
        assert result == messages

    def test_summarization_system_prompt_exists(self):
        from api.agent3_context_compaction import SUMMARIZATION_SYSTEM
        assert len(SUMMARIZATION_SYSTEM) > 50
        assert "resume" in SUMMARIZATION_SYSTEM.lower() or "contexte" in SUMMARIZATION_SYSTEM.lower()


# ══════════════════════════════════════════════════════════════════════════════
# 8. Slash Command Interception in Routes
# ══════════════════════════════════════════════════════════════════════════════

class TestSlashCommandInterception:
    """Tests que les slash commands sont interceptees dans les routes."""

    def test_chat_route_has_slash_interception(self):
        """La route /chat intercepte les slash commands."""
        with open("api/routers/agent3_openclaw.py", "r", encoding="utf-8") as f:
            source = f.read()
        # Verify slash command interception exists in the /chat route
        assert "Slash command interception" in source
        # Should appear at least twice (once for /chat, once for /chat/stream)
        assert source.count("_slash_parser.is_command") >= 2

    def test_stream_route_has_slash_interception(self):
        """La route /chat/stream intercepte les slash commands."""
        with open("api/routers/agent3_openclaw.py", "r", encoding="utf-8") as f:
            source = f.read()
        assert "Slash commands : interception AVANT tout traitement" in source

    def test_session_key_not_undefined_in_stream(self):
        """session_key ne doit PAS etre reference avant sa definition dans /chat/stream."""
        with open("api/routers/agent3_openclaw.py", "r", encoding="utf-8") as f:
            lines = f.readlines()

        in_slash_block = False
        for i, line in enumerate(lines, 1):
            if "Slash commands : interception AVANT" in line:
                in_slash_block = True
            if in_slash_block and "session_key" in line and "session_key =" not in line:
                # Verify it uses f-string, not bare session_key reference
                stripped = line.strip()
                assert "f\"agent3_" in stripped or "f'agent3_" in stripped, \
                    f"Line {i} references session_key unsafely: {stripped}"
                break


# ══════════════════════════════════════════════════════════════════════════════
# 9. Computer Use Session Stats
# ══════════════════════════════════════════════════════════════════════════════

class TestComputerUseSession:
    """Tests de la session Computer Use (sans API reelle)."""

    @pytest.mark.skipif(
        not os.environ.get("ANTHROPIC_API_KEY"),
        reason="Requires API key to instantiate session",
    )
    def test_session_stats(self):
        from api.computer_use import ComputerUseSession
        session = ComputerUseSession(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            user_id="test-stats",
        )
        stats = session.get_stats()
        assert stats["iteration"] == 0
        assert stats["total_actions"] == 0
        assert stats["total_errors"] == 0
        assert stats["is_running"] is False
        assert stats["is_aborted"] is False
        assert "screen" in stats
        assert "cost" in stats


# ══════════════════════════════════════════════════════════════════════════════
# 10. Mode Selector (UI)
# ══════════════════════════════════════════════════════════════════════════════

class TestModeSelector:
    """Verifie que seuls les modes Defaut et Bypass sont exposes."""

    def test_only_default_and_bypass_in_ui(self):
        """Le composant PermissionModeSwitcher ne doit montrer que 2 modes."""
        with open("frontend/src/components/Agent3PlanMode.tsx", "r", encoding="utf-8") as f:
            source = f.read()
        # Should have exactly default and bypass in the modes array
        assert "'default'" in source or '"default"' in source
        assert "'bypass'" in source or '"bypass"' in source
        # Plan and auto_safe should NOT be in the modes array for the switcher
        # (they can still exist in the type for backend compat)
        # Count mode definitions in the switcher's modes array
        import re
        # Find the modes array inside PermissionModeSwitcher
        match = re.search(r'const modes.*?\[.*?\]', source, re.DOTALL)
        if match:
            modes_block = match.group(0)
            assert "'plan'" not in modes_block, "Plan mode should not be in UI switcher"
            assert "'auto_safe'" not in modes_block, "Auto safe mode should not be in UI switcher"

    def test_permission_type_still_exists(self):
        """Le type PermissionMode garde les valeurs pour la compatibilite backend."""
        with open("frontend/src/components/Agent3PlanMode.tsx", "r", encoding="utf-8") as f:
            source = f.read()
        assert "PermissionMode" in source


# ══════════════════════════════════════════════════════════════════════════════
# 11. Skill Registry
# ══════════════════════════════════════════════════════════════════════════════

class TestSkillRegistry:
    """Tests du registre de skills."""

    def test_registry_has_skills(self):
        # Apres nettoyage : uniquement 2 skills auto-discovered (web_search + document).
        # trading_analysis et pine_script ont ete retires du auto_discover (tests TradingView
        # retires du flow principal ; les modules existent toujours dans le repo).
        from api.agent3_skills import get_skill_registry
        reg = get_skill_registry()
        assert reg.count >= 2

    def test_registry_skills_have_names(self):
        from api.agent3_skills import get_skill_registry
        reg = get_skill_registry()
        skills = reg.to_dict_list()
        names = {s["name"] for s in skills}
        assert "web_search" in names
        assert "document" in names
        # pine_script et trading_analysis ne sont plus auto-charges
        assert "pine_script" not in names
        assert "trading_analysis" not in names

    def test_registry_skills_have_triggers(self):
        from api.agent3_skills import get_skill_registry
        reg = get_skill_registry()
        for s in reg.to_dict_list():
            assert len(s.get("triggers", [])) > 0, f"Skill {s['name']} has no triggers"

    def test_registry_skills_have_category(self):
        from api.agent3_skills import get_skill_registry
        reg = get_skill_registry()
        for s in reg.to_dict_list():
            assert s.get("category"), f"Skill {s['name']} has no category"


# ══════════════════════════════════════════════════════════════════════════════
# 11. Hook Registry
# ══════════════════════════════════════════════════════════════════════════════

class TestHookRegistry:
    """Tests du registre de hooks."""

    def test_registry_has_hooks(self):
        from api.agent3_hooks import get_hook_registry
        reg = get_hook_registry()
        assert reg.count >= 1

    def test_hooks_have_required_fields(self):
        from api.agent3_hooks import get_hook_registry
        reg = get_hook_registry()
        for h in reg.list_hooks():
            assert "name" in h
            assert "phase" in h
            assert "priority" in h
            assert "enabled" in h


# ══════════════════════════════════════════════════════════════════════════════
# 12. Integration: Slash Commands via FastAPI TestClient
# ══════════════════════════════════════════════════════════════════════════════

class TestSlashCommandAPI:
    """Tests d'integration slash commands via FastAPI TestClient."""

    @pytest.fixture()
    def client(self, db):
        from api.main import app
        from api.dependencies import get_db, get_optional_user
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_optional_user] = lambda: TEST_USER_ID
        from fastapi.testclient import TestClient
        c = TestClient(app)
        yield c
        app.dependency_overrides.clear()

    def test_help_via_chat_endpoint(self, client):
        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "/help"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "Commandes disponibles" in data["message"]

    def test_status_via_chat_endpoint(self, client):
        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "/status"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "Statut Agent 3" in data["message"]

    def test_skills_via_chat_endpoint(self, client):
        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "/skills"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "disponible(s)" in data["message"]
        assert "OpenClaw" in data["message"]

    def test_cost_via_chat_endpoint(self, client):
        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "/cost"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "Cout de la session" in data["message"]

    def test_hooks_via_chat_endpoint(self, client):
        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "/hooks"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "hook(s) actif(s)" in data["message"]

    def test_help_via_stream_endpoint(self, client):
        resp = client.post("/api/agent3/chat/stream", json={
            "messages": [{"role": "user", "content": "/help"}],
        })
        assert resp.status_code == 200
        text = resp.text
        assert "Commandes disponibles" in text
        assert "event: result" in text

    def test_status_via_stream_endpoint(self, client):
        resp = client.post("/api/agent3/chat/stream", json={
            "messages": [{"role": "user", "content": "/status"}],
        })
        assert resp.status_code == 200
        assert "Statut Agent 3" in resp.text

    def test_clear_via_chat_endpoint(self, client, db):
        from api.routers.agent3_openclaw import _save_agent3_message
        _save_agent3_message(db, TEST_USER_ID, "user", "test msg", "text")

        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "/clear"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "efface" in data["message"].lower()

    def test_memory_via_chat_endpoint(self, client, db):
        from api.routers.agent3_openclaw import _save_memory
        _save_memory(db, TEST_USER_ID, "test_key_api", "test_value", "test")

        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "/memory"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "memoire(s)" in data["message"]
        assert "test_key_api" in data["message"]

    def test_alias_via_chat_endpoint(self, client):
        """Les alias fonctionnent aussi via l'API."""
        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "/h"}],
        })
        assert resp.status_code == 200
        assert "Commandes disponibles" in resp.json()["message"]

    def test_normal_message_not_intercepted(self, client):
        """Un message normal n'est PAS intercepte par le parseur slash."""
        resp = client.post("/api/agent3/chat", json={
            "messages": [{"role": "user", "content": "Bonjour comment ca va?"}],
        })
        assert resp.status_code == 200
        data = resp.json()
        # Should NOT contain slash command output
        assert "Commandes disponibles" not in data["message"]
