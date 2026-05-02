"""
Tests unitaires pour les 12 nouveaux wrappers OpenClaw (Phase 3).

Chaque wrapper est teste dans DEUX modes :
  1. API externe disponible (cle presente) — mock httpx.AsyncClient
  2. Fallback OpenClaw (pas de cle) — mock openclaw_invoke_tool

Le wrapper "pii_scrub" fait exception : il est 100% local (regex), donc
teste directement sans mock.

Couvre :
  - openclaw_firecrawl        (web)
  - openclaw_perplexity_search (web)
  - openclaw_brave_search     (web)
  - openclaw_google_search    (web)
  - openclaw_tavily_search    (web)
  - openclaw_exa_search       (web)
  - openclaw_music_generate   (media — fallback only)
  - openclaw_video_generate   (media — fallback only)
  - openclaw_voice_generate   (media)
  - openclaw_content_moderation (safety)
  - openclaw_url_safety_check (safety)
  - openclaw_pii_scrub        (safety, regex locale)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════


def _run(coro):
    """Execute une coroutine dans une event loop isolee."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _mock_httpx_response(status_code: int = 200, json_data: dict | None = None,
                        content: bytes = b"", text: str = ""):
    """Construit un mock de response httpx avec les attributs attendus."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=json_data or {})
    resp.content = content
    resp.text = text or (str(json_data) if json_data else "")
    return resp


def _mock_httpx_client(response):
    """Wrap une response dans un mock AsyncClient qui peut etre utilise en `async with`."""
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock(return_value=response)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.fixture()
def no_keys(monkeypatch):
    """Efface toutes les cles API pour forcer le fallback OpenClaw."""
    for key in (
        "FIRECRAWL_API_KEY", "PERPLEXITY_API_KEY", "BRAVE_SEARCH_API_KEY",
        "SERPAPI_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY",
        "OPENAI_API_KEY", "GOOGLE_SAFE_BROWSING_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture()
def mock_invoke():
    """Mock openclaw_invoke_tool (fallback Gateway)."""
    with patch("api.openclaw_bridge.openclaw_invoke_tool",
               new=AsyncMock(return_value={"success": True, "source": "openclaw_fallback"})) as m:
        yield m


# ══════════════════════════════════════════════════════════════════════════════
# 1. openclaw_firecrawl
# ══════════════════════════════════════════════════════════════════════════════


class TestFirecrawl:
    """Crawl ou scrape via Firecrawl."""

    def test_firecrawl_api_mode_scrape(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
        from api import openclaw_bridge

        resp = _mock_httpx_response(200, {"markdown": "# Title\nContent..."})
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_firecrawl(
                url="https://example.com", mode="scrape"))

        assert result["success"] is True
        assert result["source"] == "firecrawl_api"
        assert "markdown" in result["data"]

    def test_firecrawl_api_mode_crawl(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
        from api import openclaw_bridge

        resp = _mock_httpx_response(200, {"jobId": "abc-123", "pages": []})
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_firecrawl(
                url="https://example.com", mode="crawl", max_pages=5))

        assert result["success"] is True
        assert result["source"] == "firecrawl_api"

    def test_firecrawl_api_error(self, monkeypatch):
        monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test-key")
        from api import openclaw_bridge

        resp = _mock_httpx_response(500, text="Internal Server Error")
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_firecrawl(
                url="https://example.com"))

        assert result["success"] is False
        assert "500" in result["error"]

    def test_firecrawl_fallback_no_key(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_firecrawl(url="https://example.com"))
        assert result["source"] == "openclaw_fallback"
        mock_invoke.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════════════════
# 2. openclaw_perplexity_search
# ══════════════════════════════════════════════════════════════════════════════


class TestPerplexitySearch:
    """Recherche IA avec citations."""

    def test_perplexity_api_success(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        from api import openclaw_bridge

        resp = _mock_httpx_response(200, {
            "choices": [{"message": {"content": "La reponse synthese."}}],
            "citations": ["https://src1.com", "https://src2.com"],
        })
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_perplexity_search(
                query="Quel est le climat de Mars ?"))

        assert result["success"] is True
        assert result["source"] == "perplexity_api"
        assert result["answer"] == "La reponse synthese."
        assert len(result["citations"]) == 2

    def test_perplexity_with_recency(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        from api import openclaw_bridge

        resp = _mock_httpx_response(200, {
            "choices": [{"message": {"content": "Recent news."}}],
            "citations": [],
        })
        mock_post = AsyncMock(return_value=resp)
        client = MagicMock()
        client.post = mock_post
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=client)
        ctx.__aexit__ = AsyncMock(return_value=False)
        with patch("api.openclaw_bridge.httpx.AsyncClient", return_value=ctx):
            result = _run(openclaw_bridge.openclaw_perplexity_search(
                query="news", recency="week"))

        assert result["success"] is True
        # Verifier que le recency a ete ajoute au payload
        payload_sent = mock_post.call_args.kwargs["json"]
        assert payload_sent.get("search_recency_filter") == "week"

    def test_perplexity_fallback(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_perplexity_search(query="test"))
        assert result["source"] == "openclaw_fallback"


# ══════════════════════════════════════════════════════════════════════════════
# 3. openclaw_brave_search
# ══════════════════════════════════════════════════════════════════════════════


class TestBraveSearch:
    def test_brave_api_success(self, monkeypatch):
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-test-key")
        from api import openclaw_bridge

        resp = _mock_httpx_response(200, {
            "web": {"results": [
                {"title": "R1", "url": "https://r1.com", "description": "d1"},
                {"title": "R2", "url": "https://r2.com", "description": "d2"},
            ]}
        })
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_brave_search(
                query="privacy search", max_results=5))

        assert result["success"] is True
        assert result["source"] == "brave_api"
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "R1"

    def test_brave_api_rate_limited(self, monkeypatch):
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-test-key")
        from api import openclaw_bridge

        resp = _mock_httpx_response(429)
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_brave_search(query="test"))

        assert result["success"] is False

    def test_brave_fallback(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_brave_search(query="test"))
        assert result["source"] == "openclaw_fallback"


# ══════════════════════════════════════════════════════════════════════════════
# 4. openclaw_google_search (SerpAPI)
# ══════════════════════════════════════════════════════════════════════════════


class TestGoogleSearch:
    def test_google_api_success(self, monkeypatch):
        monkeypatch.setenv("SERPAPI_API_KEY", "serp-test-key")
        from api import openclaw_bridge

        resp = _mock_httpx_response(200, {
            "organic_results": [
                {"title": "T1", "link": "https://t1.com", "snippet": "s1"},
                {"title": "T2", "link": "https://t2.com", "snippet": "s2"},
                {"title": "T3", "link": "https://t3.com", "snippet": "s3"},
            ]
        })
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_google_search(
                query="test", max_results=10))

        assert result["success"] is True
        assert result["source"] == "serpapi"
        assert len(result["results"]) == 3
        assert result["results"][0]["url"] == "https://t1.com"

    def test_google_fallback(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_google_search(query="test"))
        assert result["source"] == "openclaw_fallback"


# ══════════════════════════════════════════════════════════════════════════════
# 5. openclaw_tavily_search
# ══════════════════════════════════════════════════════════════════════════════


class TestTavilySearch:
    def test_tavily_api_success(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")
        from api import openclaw_bridge

        resp = _mock_httpx_response(200, {
            "answer": "Reponse agentic RAG.",
            "results": [
                {"title": "A", "url": "https://a.com", "content": "..."},
                {"title": "B", "url": "https://b.com", "content": "..."},
            ],
        })
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_tavily_search(
                query="test", search_depth="advanced"))

        assert result["success"] is True
        assert result["source"] == "tavily_api"
        assert result["answer"] == "Reponse agentic RAG."
        assert len(result["results"]) == 2

    def test_tavily_fallback(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_tavily_search(query="test"))
        assert result["source"] == "openclaw_fallback"


# ══════════════════════════════════════════════════════════════════════════════
# 6. openclaw_exa_search
# ══════════════════════════════════════════════════════════════════════════════


class TestExaSearch:
    def test_exa_api_success(self, monkeypatch):
        monkeypatch.setenv("EXA_API_KEY", "exa-test-key")
        from api import openclaw_bridge

        resp = _mock_httpx_response(200, {
            "results": [
                {"title": "Neural1", "url": "https://n1.com", "text": "texte long..."},
                {"title": "Neural2", "url": "https://n2.com", "text": "texte long 2..."},
            ]
        })
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_exa_search(
                query="quantum computing", search_type="neural"))

        assert result["success"] is True
        assert result["source"] == "exa_api"
        assert len(result["results"]) == 2

    def test_exa_fallback(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_exa_search(query="test"))
        assert result["source"] == "openclaw_fallback"


# ══════════════════════════════════════════════════════════════════════════════
# 7-8. Music & Video generate (fallback-only, pas d'API directe)
# ══════════════════════════════════════════════════════════════════════════════


class TestMusicAndVideoGenerate:
    def test_music_generate_delegates_to_invoke(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_music_generate(
            prompt="epic orchestral", duration_seconds=60, style="cinematic"))
        assert result["source"] == "openclaw_fallback"
        mock_invoke.assert_awaited_once()
        call_args = mock_invoke.call_args
        # Verifier les args transmis
        assert call_args.kwargs["tool_name"] == "music_generate"
        assert call_args.kwargs["args"]["prompt"] == "epic orchestral"
        assert call_args.kwargs["args"]["duration"] == 60
        assert call_args.kwargs["args"]["style"] == "cinematic"

    def test_music_generate_no_style(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        _run(openclaw_bridge.openclaw_music_generate(prompt="jazz"))
        args = mock_invoke.call_args.kwargs["args"]
        assert "style" not in args

    def test_video_generate_delegates(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        _run(openclaw_bridge.openclaw_video_generate(
            prompt="a cat skating", duration_seconds=10, aspect_ratio="9:16"))
        args = mock_invoke.call_args.kwargs["args"]
        assert args["prompt"] == "a cat skating"
        assert args["duration"] == 10
        assert args["aspectRatio"] == "9:16"


# ══════════════════════════════════════════════════════════════════════════════
# 9. openclaw_voice_generate (OpenAI TTS ou fallback)
# ══════════════════════════════════════════════════════════════════════════════


class TestVoiceGenerate:
    def test_voice_openai_tts_success(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from api import openclaw_bridge

        fake_audio_bytes = b"RIFF....WAV data..."
        resp = _mock_httpx_response(200, content=fake_audio_bytes)
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_voice_generate(
                text="Bonjour !", voice="nova", provider="openai"))

        assert result["success"] is True
        assert result["source"] == "openai_tts"
        assert result["voice"] == "nova"
        assert result["length_bytes"] == len(fake_audio_bytes)
        # audio encode en base64
        import base64
        decoded = base64.b64decode(result["audio_base64"])
        assert decoded == fake_audio_bytes

    def test_voice_openai_error_fallback(self, monkeypatch, mock_invoke):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from api import openclaw_bridge

        resp = _mock_httpx_response(401, text="Unauthorized")
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_voice_generate(
                text="Test", provider="openai"))

        # Status non-200 -> renvoie un echec de l'API (sans fallback)
        assert result["success"] is False
        assert "401" in result["error"]

    def test_voice_elevenlabs_delegates_to_fallback(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_voice_generate(
            text="Hello", voice="Rachel", provider="elevenlabs"))
        assert result["source"] == "openclaw_fallback"
        assert mock_invoke.call_args.kwargs["tool_name"] == "voice_generate"


# ══════════════════════════════════════════════════════════════════════════════
# 10. openclaw_content_moderation (OpenAI Moderation)
# ══════════════════════════════════════════════════════════════════════════════


class TestContentModeration:
    def test_moderation_api_clean(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from api import openclaw_bridge

        resp = _mock_httpx_response(200, {
            "results": [{
                "flagged": False,
                "categories": {"hate": False, "violence": False, "sexual": False},
                "category_scores": {"hate": 0.001, "violence": 0.002, "sexual": 0.001},
            }]
        })
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_content_moderation(
                text="Bonjour, comment vas-tu ?"))

        assert result["success"] is True
        assert result["flagged"] is False
        assert result["categories_flagged"] == []

    def test_moderation_api_flagged(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from api import openclaw_bridge

        resp = _mock_httpx_response(200, {
            "results": [{
                "flagged": True,
                "categories": {"hate": True, "violence": True, "sexual": False},
                "category_scores": {"hate": 0.95, "violence": 0.80, "sexual": 0.01},
            }]
        })
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_content_moderation(
                text="Contenu problematique"))

        assert result["flagged"] is True
        assert set(result["categories_flagged"]) == {"hate", "violence"}

    def test_moderation_fallback(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_content_moderation(text="test"))
        assert result["source"] == "openclaw_fallback"


# ══════════════════════════════════════════════════════════════════════════════
# 11. openclaw_url_safety_check (Google Safe Browsing)
# ══════════════════════════════════════════════════════════════════════════════


class TestUrlSafetyCheck:
    def test_url_safe(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_SAFE_BROWSING_API_KEY", "gsb-test-key")
        from api import openclaw_bridge

        # Pas de matches = URL safe
        resp = _mock_httpx_response(200, {})
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_url_safety_check(
                url="https://google.com"))

        assert result["success"] is True
        assert result["is_safe"] is True
        assert result["threats"] == []

    def test_url_malicious(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_SAFE_BROWSING_API_KEY", "gsb-test-key")
        from api import openclaw_bridge

        resp = _mock_httpx_response(200, {
            "matches": [
                {"threatType": "MALWARE"},
                {"threatType": "SOCIAL_ENGINEERING"},
            ]
        })
        with patch("api.openclaw_bridge.httpx.AsyncClient",
                   return_value=_mock_httpx_client(resp)):
            result = _run(openclaw_bridge.openclaw_url_safety_check(
                url="http://evil.example.com"))

        assert result["is_safe"] is False
        assert set(result["threats"]) == {"MALWARE", "SOCIAL_ENGINEERING"}

    def test_url_fallback(self, no_keys, mock_invoke):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_url_safety_check(url="https://x.com"))
        assert result["source"] == "openclaw_fallback"


# ══════════════════════════════════════════════════════════════════════════════
# 12. openclaw_pii_scrub (100% local, regex)
# ══════════════════════════════════════════════════════════════════════════════


class TestPiiScrub:
    """PII scrubbing est entierement local — pas de mock necessaire."""

    def test_detects_email(self):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_pii_scrub(
            text="Contact : alice@example.com ou bob@test.org"))

        assert result["success"] is True
        assert result["has_pii"] is True
        assert "email" in result["findings"]
        assert len(result["findings"]["email"]) == 2
        assert "[REDACTED:email]" in result["scrubbed_text"]

    def test_detects_phone_fr(self):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_pii_scrub(
            text="Mon num : 06 12 34 56 78 ou +33 6 98 76 54 32"))

        assert result["has_pii"] is True
        assert "phone_fr" in result["findings"]
        assert len(result["findings"]["phone_fr"]) >= 1

    def test_detects_iban(self):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_pii_scrub(
            text="IBAN : FR7630001007941234567890185"))

        assert result["has_pii"] is True
        assert "iban" in result["findings"]

    def test_detects_ipv4(self):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_pii_scrub(
            text="Server IP: 192.168.1.100 or 10.0.0.1"))

        assert result["has_pii"] is True
        assert "ipv4" in result["findings"]
        assert len(result["findings"]["ipv4"]) == 2

    def test_no_pii_clean_text(self):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_pii_scrub(
            text="Bonjour, j'aime les chats et les pommes."))

        assert result["success"] is True
        assert result["has_pii"] is False
        assert result["findings"] == {}
        assert result["total_matches"] == 0

    def test_redact_false_keeps_original(self):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_pii_scrub(
            text="Email : a@b.com", redact=False))

        # Detection OK mais pas de scrubbed_text
        assert result["has_pii"] is True
        assert result["scrubbed_text"] is None

    def test_redact_replaces_all_matches(self):
        from api import openclaw_bridge
        result = _run(openclaw_bridge.openclaw_pii_scrub(
            text="emails a@b.com et c@d.fr"))

        # Les 2 emails doivent etre rediges
        assert "a@b.com" not in result["scrubbed_text"]
        assert "c@d.fr" not in result["scrubbed_text"]
        assert result["scrubbed_text"].count("[REDACTED:email]") == 2

    def test_multi_pii_types(self):
        from api import openclaw_bridge
        text = (
            "Contact: alice@example.com, tel: 06 12 34 56 78, "
            "IBAN: FR7630001007941234567890185, IP: 192.168.1.1"
        )
        result = _run(openclaw_bridge.openclaw_pii_scrub(text=text))

        assert result["has_pii"] is True
        # Au moins 3 types detectes (email, phone_fr, iban, ipv4)
        assert len(result["findings"]) >= 3


# ══════════════════════════════════════════════════════════════════════════════
# Sanity : ALL_OPENCLAW_TOOLS contient bien les 38 outils Phase 3
# ══════════════════════════════════════════════════════════════════════════════


class TestToolsRegistry:
    def test_total_is_38(self):
        from api.openclaw_bridge import ALL_OPENCLAW_TOOLS
        assert len(ALL_OPENCLAW_TOOLS) == 38

    def test_all_new_phase3_tools_registered(self):
        from api.openclaw_bridge import ALL_OPENCLAW_TOOLS
        names = {t["name"] for t in ALL_OPENCLAW_TOOLS}
        new_tools = {
            "firecrawl", "perplexity_search", "brave_search", "google_search",
            "tavily_search", "exa_search",
            "music_generate", "video_generate", "voice_generate",
            "content_moderation", "url_safety_check", "pii_scrub",
        }
        missing = new_tools - names
        assert not missing, f"Outils Phase 3 absents du registre: {missing}"

    def test_all_tools_have_group(self):
        from api.openclaw_bridge import ALL_OPENCLAW_TOOLS
        for tool in ALL_OPENCLAW_TOOLS:
            assert "group" in tool, f"{tool['name']} sans group"
            assert "description" in tool

    def test_safety_group_has_3_tools(self):
        from api.openclaw_bridge import ALL_OPENCLAW_TOOLS
        safety = [t for t in ALL_OPENCLAW_TOOLS if t["group"] == "safety"]
        assert len(safety) == 3

    def test_web_group_has_9_tools(self):
        from api.openclaw_bridge import ALL_OPENCLAW_TOOLS
        web = [t for t in ALL_OPENCLAW_TOOLS if t["group"] == "web"]
        assert len(web) == 9

    def test_media_group_has_5_tools(self):
        from api.openclaw_bridge import ALL_OPENCLAW_TOOLS
        media = [t for t in ALL_OPENCLAW_TOOLS if t["group"] == "media"]
        assert len(media) == 5
