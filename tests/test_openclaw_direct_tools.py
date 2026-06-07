"""Tests Phase 5 : exposition directe des 38 outils OpenClaw au LLM.

Verifie :
  - `build_openclaw_tool_schemas()` retourne les 38 outils avec input_schema valide
  - Les noms Anthropic evitent les collisions avec les tools natifs d'Agent 3
  - `build_tool_schemas()` inclut les 38 outils quand `include_openclaw_direct_tools=True`
  - Le dispatcher route correctement les tool_use OpenClaw vers `openclaw_invoke_tool`
  - Le flag `DESTRUCTIVE_ACTIONS` inclut les 14 outils OpenClaw destructifs (UPPER)
  - Les tests existants continuent de passer sans l'opt-in (rien expose par defaut a
    travers les tests de dispatcher pre-existants)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.agent3_native_dispatcher import Agent3ActionDispatcher
from api.agent3_native_tools import AgenticLoop, build_tool_schemas
from api.openclaw_tool_schemas import (
    DESTRUCTIVE_OPENCLAW_TOOLS,
    all_anthropic_tool_names,
    build_openclaw_tool_schemas,
    openclaw_name_from_anthropic,
)
from sylea.core.storage.database import DatabaseManager


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    d = DatabaseManager(db_path=Path(":memory:"))
    d.connect()
    return d


@pytest.fixture
def dispatcher(db):
    return Agent3ActionDispatcher(db=db, user_id="user_test", session_key="sess_test")


# ─────────────────────────────────────────────────────────────────────────────
# 1. Module openclaw_tool_schemas
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenClawSchemasModule:
    def test_exactly_38_tools(self):
        schemas = build_openclaw_tool_schemas()
        assert len(schemas) == 38, f"Expected 38 OpenClaw tools, got {len(schemas)}"

    def test_all_schemas_have_required_fields(self):
        for s in build_openclaw_tool_schemas():
            assert "name" in s and isinstance(s["name"], str) and s["name"]
            assert "description" in s and isinstance(s["description"], str)
            assert "input_schema" in s and isinstance(s["input_schema"], dict)
            assert s["input_schema"]["type"] == "object"
            assert "properties" in s["input_schema"]

    def test_all_names_anthropic_compatible(self):
        # Anthropic : tool names must match [a-zA-Z0-9_-], max 64 chars.
        import re
        pattern = re.compile(r"^[a-zA-Z0-9_-]+$")
        for s in build_openclaw_tool_schemas():
            assert pattern.match(s["name"]), f"Invalid name: {s['name']}"
            assert len(s["name"]) <= 64

    def test_enabled_tools_filter(self):
        subset = {"browser", "exec", "image_generate"}
        schemas = build_openclaw_tool_schemas(enabled_tools=subset)
        names = {s["name"] for s in schemas}
        assert names == subset

    def test_mapping_fs_read_to_openclaw_read(self):
        # Certains noms Anthropic different du nom OpenClaw (collision avec natif).
        assert openclaw_name_from_anthropic("fs_read") == "read"
        assert openclaw_name_from_anthropic("fs_write") == "write"
        assert openclaw_name_from_anthropic("fs_edit") == "edit"
        assert openclaw_name_from_anthropic("fs_apply_patch") == "apply_patch"
        assert openclaw_name_from_anthropic("oc_memory_search") == "memory_search"
        assert openclaw_name_from_anthropic("oc_memory_get") == "memory_get"
        assert openclaw_name_from_anthropic("oc_cron") == "cron"
        # Les autres sont identiques des deux cotes.
        assert openclaw_name_from_anthropic("browser") == "browser"
        assert openclaw_name_from_anthropic("exec") == "exec"
        assert openclaw_name_from_anthropic("image_generate") == "image_generate"

    def test_all_anthropic_names_is_38(self):
        names = all_anthropic_tool_names()
        assert len(names) == 38

    def test_destructive_subset_is_14(self):
        # 14 outils OpenClaw potentiellement destructifs (voir DESTRUCTIVE_OPENCLAW_TOOLS).
        assert len(DESTRUCTIVE_OPENCLAW_TOOLS) == 14
        # Sanity : tous sont dans l'ensemble des noms exposes.
        assert DESTRUCTIVE_OPENCLAW_TOOLS.issubset(all_anthropic_tool_names())


# ─────────────────────────────────────────────────────────────────────────────
# 2. Integration avec build_tool_schemas()
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildToolSchemasIntegration:
    def test_default_does_not_expose_openclaw_tools(self):
        # Par defaut (opt-in off), les outils OpenClaw-only (i.e. ceux SANS
        # equivalent natif) ne sont pas exposes. Les outils ayant un handler
        # natif (browser, canvas, web_fetch, x_search) restent exposes via
        # leur nom natif uppercase.
        schemas = build_tool_schemas(enabled_actions=Agent3ActionDispatcher.SUPPORTED)
        names = {s["name"] for s in schemas}
        # Sample d'outils OpenClaw-only qui ne doivent PAS etre la sans opt-in
        assert "exec" not in names
        assert "image_generate" not in names
        assert "firecrawl" not in names
        assert "bash" not in names

    def test_opt_in_adds_openclaw_tools_minus_collisions(self):
        # Les 38 outils OpenClaw sont ajoutes, MOINS ceux qui partagent un nom
        # avec un tool natif d'Agent 3 (4 collisions actuelles : browser,
        # canvas, web_fetch, x_search). Les collisions sont gardees cote natif.
        schemas_without = build_tool_schemas(
            enabled_actions=Agent3ActionDispatcher.SUPPORTED,
        )
        schemas_with = build_tool_schemas(
            enabled_actions=Agent3ActionDispatcher.SUPPORTED,
            include_openclaw_direct_tools=True,
        )
        added = len(schemas_with) - len(schemas_without)
        # 4 collisions attendues : web_fetch, x_search, canvas, browser
        assert added == 38 - 4, f"Expected +34 (38 - 4 collisions), got +{added}"

        # Verifie que quelques OpenClaw-only tools sont bien la
        names = {s["name"] for s in schemas_with}
        assert "exec" in names
        assert "image_generate" in names
        assert "firecrawl" in names

    def test_filter_subset_of_openclaw_tools(self):
        schemas = build_tool_schemas(
            enabled_actions=Agent3ActionDispatcher.SUPPORTED,
            include_openclaw_direct_tools=True,
            enabled_openclaw_tools={"browser", "exec", "image_generate"},
        )
        names = {s["name"] for s in schemas}
        # Les 3 OpenClaw filtres sont bien la
        assert "browser" in names
        assert "exec" in names
        assert "image_generate" in names
        # Les autres OpenClaw filtered-out ne sont pas la
        assert "bash" not in names
        assert "firecrawl" not in names
        # Note : "canvas" native reste, meme si OpenClaw "canvas" est filtre.


# ─────────────────────────────────────────────────────────────────────────────
# 3. Dispatcher — routage des tool_use OpenClaw
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestDispatcherRoutesOpenClaw:
    async def test_image_generate_routes_to_invoke_tool(self, dispatcher):
        # Note : BROWSER est devenu un handler natif (Phase 14I, Playwright direct),
        # plus route via openclaw_invoke_tool. On valide donc le routage avec
        # IMAGE_GENERATE qui reste un outil OpenClaw direct.
        fake_resp = {"success": True, "result": {"image_url": "/tmp/img.png"}}
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(return_value=fake_resp),
        ) as m:
            r = await dispatcher.execute("IMAGE_GENERATE", {
                "action": "generate",
                "args": {"prompt": "a cat"},
            })
            assert r["is_error"] is False
            m.assert_awaited_once()
            kwargs = m.call_args.kwargs
            assert kwargs["tool_name"] == "image_generate"
            assert kwargs["action"] == "generate"
            assert kwargs["args"] == {"prompt": "a cat"}
            assert kwargs["session_key"] == "sess_test"

    async def test_fs_read_maps_to_openclaw_read(self, dispatcher):
        # Le LLM appelle `fs_read`, le dispatcher convertit vers `read` cote OpenClaw.
        fake_resp = {"success": True, "result": {"content": "file bytes"}}
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(return_value=fake_resp),
        ) as m:
            r = await dispatcher.execute("FS_READ", {"args": {"path": "/tmp/a.txt"}})
            assert r["is_error"] is False
            kwargs = m.call_args.kwargs
            assert kwargs["tool_name"] == "read"  # renomme !

    async def test_openclaw_error_is_reported(self, dispatcher):
        # BROWSER est natif maintenant, on teste avec EXEC qui reste OpenClaw.
        fake_resp = {"success": False, "error": "Tool not configured"}
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(return_value=fake_resp),
        ):
            r = await dispatcher.execute("EXEC", {"args": {"command": "ls"}})
            assert r["is_error"] is True
            assert "Tool not configured" in r["content"] or "exec" in r["content"].lower()

    async def test_openclaw_exception_is_handled(self, dispatcher):
        # Si openclaw_invoke_tool raise, le dispatcher ne doit pas propager.
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(side_effect=RuntimeError("Gateway down")),
        ):
            r = await dispatcher.execute("EXEC", {"args": {"command": "ls"}})
            assert isinstance(r, dict)
            assert r["is_error"] is True
            assert "exec" in r["content"].lower() or "gateway" in r["content"].lower() or "erreur" in r["content"].lower()

    async def test_openclaw_empty_result_ok(self, dispatcher):
        fake_resp = {"success": True, "result": None}
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(return_value=fake_resp),
        ):
            r = await dispatcher.execute("SESSIONS_LIST", {})
            assert r["is_error"] is False

    async def test_native_actions_still_work_unchanged(self, dispatcher):
        # Verifie que l'ajout du routage OpenClaw ne casse pas les actions natives
        # (un simple CODE doit passer par _code, pas par _openclaw_direct).
        r = await dispatcher.execute("CODE", {"content": "print('hi')", "language": "python"})
        assert r["is_error"] is False
        assert r["raw"]["language"] == "python"


# ─────────────────────────────────────────────────────────────────────────────
# 4. DESTRUCTIVE_ACTIONS extension
# ─────────────────────────────────────────────────────────────────────────────

class TestDestructiveExtension:
    def test_destructive_includes_openclaw_uppercase(self):
        dest = AgenticLoop.DESTRUCTIVE_ACTIONS
        # OpenClaw destructifs (UPPER) doivent tous etre dans DESTRUCTIVE_ACTIONS.
        expected = {
            "EXEC", "BASH", "PROCESS",
            "FS_WRITE", "FS_EDIT", "FS_APPLY_PATCH",
            "BROWSER",
            "MESSAGE",
            "IMAGE_GENERATE", "MUSIC_GENERATE", "VIDEO_GENERATE",
            "OC_CRON", "GATEWAY",
            "SESSIONS_SPAWN",
        }
        missing = expected - dest
        assert not missing, f"Manque dans DESTRUCTIVE_ACTIONS: {missing}"

    def test_destructive_does_not_include_readonly_openclaw(self):
        # Les read-only (fs_read, oc_memory_search, sessions_list, ...) ne doivent
        # PAS etre flaggees destructives pour eviter une confirmation inutile.
        dest = AgenticLoop.DESTRUCTIVE_ACTIONS
        safe_tools = {"FS_READ", "OC_MEMORY_SEARCH", "OC_MEMORY_GET", "SESSIONS_LIST", "SESSIONS_HISTORY"}
        unexpected = safe_tools & dest
        assert not unexpected, f"Ne devraient PAS etre destructives: {unexpected}"
