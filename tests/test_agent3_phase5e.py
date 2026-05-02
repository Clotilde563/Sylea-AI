"""Tests Phase 5e — Messages d'erreur structures par tool OpenClaw.

Couvre :
  1. `friendly_openclaw_tool_error` map les erreurs typiques de chaque tool
     en messages FR user-friendly (pas de jargon technique).
  2. Patterns communs (rate limit, quota, unauthorized) sont appliques en
     fallback si le tool n'a pas de match specifique.
  3. `_openclaw_direct` (dispatcher) retourne un content FR lisible au LLM
     quand le Gateway renvoie une erreur, au lieu du raw error brut.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.agent3_native_dispatcher import Agent3ActionDispatcher
from api.agent3_security import friendly_openclaw_tool_error
from sylea.core.storage.database import DatabaseManager


@pytest.fixture
def db():
    d = DatabaseManager(db_path=Path(":memory:"))
    d.connect()
    return d


@pytest.fixture
def dispatcher(db):
    return Agent3ActionDispatcher(db=db, user_id="err_user", session_key="sess")


# ─────────────────────────────────────────────────────────────────────────────
# 1. friendly_openclaw_tool_error — patterns specifiques par tool
# ─────────────────────────────────────────────────────────────────────────────

class TestToolSpecificErrors:
    def test_browser_timeout(self):
        msg = friendly_openclaw_tool_error("browser", "Navigation timeout of 30000 ms exceeded")
        assert "navigation" in msg.lower() or "temps" in msg.lower()

    def test_browser_element_not_clickable(self):
        msg = friendly_openclaw_tool_error("browser", "Element is not clickable at point (x, y)")
        assert "cliquable" in msg.lower()

    def test_browser_captcha(self):
        msg = friendly_openclaw_tool_error("browser", "Cloudflare challenge captcha detected")
        # Cloudflare pattern match en premier dans l'ordre.
        assert "cloudflare" in msg.lower() or "captcha" in msg.lower()

    def test_exec_command_not_found(self):
        msg = friendly_openclaw_tool_error("exec", "/bin/sh: banana: command not found")
        assert "introuvable" in msg.lower() or "path" in msg.lower()

    def test_exec_permission_denied(self):
        msg = friendly_openclaw_tool_error("exec", "sh: ./script.sh: Permission denied")
        assert "permission" in msg.lower()

    def test_exec_exit_code_124(self):
        msg = friendly_openclaw_tool_error("exec", "Process killed by signal SIGTERM (exit code 124)")
        # Ce pattern matche "exit code 124" specifiquement
        assert "timeout" in msg.lower() or "interrompue" in msg.lower()

    def test_fs_read_not_found(self):
        msg = friendly_openclaw_tool_error("fs_read", "FileNotFoundError: No such file or directory: /tmp/x")
        assert "introuvable" in msg.lower()

    def test_fs_write_no_space(self):
        msg = friendly_openclaw_tool_error("fs_write", "OSError: No space left on device")
        assert "plein" in msg.lower() or "disque" in msg.lower()

    def test_fs_edit_old_string_not_found(self):
        msg = friendly_openclaw_tool_error("fs_edit", "Error: old_string not found in file")
        assert "n'a pas ete trouvee" in msg.lower() or "chaine" in msg.lower()

    def test_image_generate_content_policy(self):
        msg = friendly_openclaw_tool_error(
            "image_generate", "Your request was rejected as a result of our safety system / content policy"
        )
        # Match soit "content policy" soit "safety system" (premier match gagne)
        assert "politique" in msg.lower() or "filtre" in msg.lower() or "securite" in msg.lower()

    def test_video_generate_duration_too_long(self):
        msg = friendly_openclaw_tool_error("video_generate", "duration must be <= 10 seconds")
        assert "duree" in msg.lower() or "longue" in msg.lower()

    def test_perplexity_rate_limit(self):
        msg = friendly_openclaw_tool_error("perplexity_search", "429 rate limit exceeded")
        assert "perplexity" in msg.lower() or "limite" in msg.lower()

    def test_firecrawl_robots_txt(self):
        msg = friendly_openclaw_tool_error("firecrawl", "Blocked by robots.txt rule")
        assert "robots.txt" in msg.lower() or "crawling" in msg.lower()

    def test_message_channel_not_configured(self):
        msg = friendly_openclaw_tool_error("message", "Channel 'whatsapp' not configured in gateway")
        assert "canal" in msg.lower() and "configure" in msg.lower()

    def test_sessions_spawn_budget(self):
        msg = friendly_openclaw_tool_error("sessions_spawn", "budget exceeded (0.10 USD)")
        assert "budget" in msg.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Patterns communs (fallback inter-tools)
# ─────────────────────────────────────────────────────────────────────────────

class TestCommonPatterns:
    def test_rate_limit_generic(self):
        # Pour un tool sans pattern specifique sur rate limit -> fallback commun
        msg = friendly_openclaw_tool_error("exa_search", "rate limit exceeded")
        # exa_search n'a pas "rate limit" en specifique, fallback sur commun
        assert "limite" in msg.lower() and "reessaie" in msg.lower()

    def test_quota_generic(self):
        msg = friendly_openclaw_tool_error("unknown_tool", "quota exceeded for today")
        assert "quota" in msg.lower()

    def test_unauthorized(self):
        msg = friendly_openclaw_tool_error("unknown_tool", "401 Unauthorized - bad API key")
        assert "authentification" in msg.lower() or "cle api" in msg.lower()

    def test_payment_required(self):
        msg = friendly_openclaw_tool_error("unknown_tool", "402 Payment Required")
        assert "payante" in msg.lower() or "credits" in msg.lower()

    def test_service_unavailable(self):
        msg = friendly_openclaw_tool_error("unknown_tool", "503 Service Unavailable")
        assert "indisponible" in msg.lower() or "reessaie" in msg.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Fallback generique
# ─────────────────────────────────────────────────────────────────────────────

class TestFallback:
    def test_empty_error(self):
        msg = friendly_openclaw_tool_error("browser", "")
        assert "browser" in msg.lower() or "echoue" in msg.lower()

    def test_unrecognized_error_uses_fallback(self):
        msg = friendly_openclaw_tool_error(
            "browser", "Some very specific error message that no pattern matches xyz123"
        )
        # Pas de match specifique -> extrait de l'erreur brute inclus
        assert "xyz123" in msg or "browser" in msg.lower()

    def test_custom_fallback_used(self):
        msg = friendly_openclaw_tool_error(
            "browser", "Some obscure error",
            fallback="Le navigateur a rencontre un probleme. Reessaie dans quelques secondes.",
        )
        assert "probleme" in msg.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Integration dispatcher : _openclaw_direct retourne le message friendly
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestDispatcherFriendlyErrors:
    async def test_gateway_returns_error_dispatcher_makes_friendly(self, dispatcher):
        fake_resp = {"success": False, "error": "content policy violation detected"}
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(return_value=fake_resp),
        ):
            r = await dispatcher.execute("IMAGE_GENERATE", {"args": {"prompt": "bad prompt"}})
        assert r["is_error"] is True
        # Le content doit etre le message FR, pas l'erreur brute.
        assert "politique" in r["content"].lower() or "filtre" in r["content"].lower()
        # La raw contient toujours l'erreur originale + la version friendly.
        assert r["raw"]["error"] == "content policy violation detected"
        assert r["raw"]["friendly"] == r["content"]

    async def test_exception_in_dispatcher_also_friendly(self, dispatcher):
        from httpx import TimeoutException
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(side_effect=TimeoutException("Navigation timeout after 30s")),
        ):
            r = await dispatcher.execute("BROWSER", {"args": {"url": "https://x.com"}})
        assert r["is_error"] is True
        # "timeout" doit etre dans le message FR (pattern specifique browser
        # OU fallback commun "timeout" du _COMMON_OPENCLAW_ERRORS).
        assert ("navigation" in r["content"].lower()
                or "temps" in r["content"].lower()
                or "delai" in r["content"].lower())

    async def test_rate_limit_propagated_friendly(self, dispatcher):
        fake_resp = {"success": False, "error": "429 rate limit exceeded for Perplexity API"}
        with patch(
            "api.openclaw_bridge.openclaw_invoke_tool",
            new=AsyncMock(return_value=fake_resp),
        ):
            r = await dispatcher.execute("PERPLEXITY_SEARCH", {"args": {"query": "ai"}})
        assert r["is_error"] is True
        # Doit mentionner Perplexity ou "limite"
        assert ("perplexity" in r["content"].lower()
                or "limite" in r["content"].lower())
