"""
Tests unitaires pour Agent3ActionDispatcher.

Verifie :
  - Actions supportees retournent un dict {content, is_error, raw} bien forme
  - Actions non supportees retournent is_error=True avec message pedagogique
  - Validation des parametres (query manquant, URL invalide, user non auth pour MEMORY)
  - Memoire : save + search fonctionnent avec DB in-memory
  - WEB_FETCH : URL invalide rejetee
  - Le dispatcher ne leve JAMAIS d'exception (toutes les erreurs via is_error=True)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from api.agent3_native_dispatcher import Agent3ActionDispatcher
from sylea.core.storage.database import DatabaseManager


@pytest.fixture
def db():
    d = DatabaseManager(db_path=Path(":memory:"))
    d.connect()
    return d


@pytest.fixture
def dispatcher(db):
    return Agent3ActionDispatcher(db=db, user_id="test_user", session_key="test_session")


@pytest.fixture
def dispatcher_anon(db):
    return Agent3ActionDispatcher(db=db, user_id=None, session_key=None)


class TestSupportedSet:
    def test_supported_is_exact(self):
        assert Agent3ActionDispatcher.SUPPORTED == {
            "SEARCH", "X_SEARCH", "WEB_FETCH",
            "MEMORY", "MEMORY_SEARCH",
            "PDF", "CODE", "CANVAS",
            "FILE_READ", "CALENDAR_LIST", "GMAIL_READ",
            # Destructives (gated by AgenticLoop confirmation flow)
            "FILE_CREATE", "EMAIL", "GMAIL_SEND", "CALENDAR_EVENT", "DRIVE_SAVE",
            "CRON", "COMPUTER_USE",
            # Meta
            "SPAWN_AGENT",
            # Planification (in-memory)
            "TODO_WRITE",
        }


@pytest.mark.asyncio
class TestNotImplemented:
    async def test_unknown_action_returns_error(self, dispatcher):
        # SCREENSHOT n'est pas (encore) cable dans le dispatcher native.
        r = await dispatcher.execute("SCREENSHOT", {"url": "https://x.com"})
        assert r["is_error"] is True
        assert "pas encore cable" in r["content"]

    async def test_not_implemented_lists_supported(self, dispatcher):
        r = await dispatcher.execute("SCREENSHOT", {"url": "https://x.com"})
        assert r["is_error"] is True
        # doit mentionner les actions supportees pour que le LLM puisse pivoter
        assert "search" in r["content"].lower()

    async def test_never_raises(self, dispatcher):
        # Input garbage : doit quand meme retourner un dict, pas raise
        r = await dispatcher.execute("FOO_BAR_BAZ", None)
        assert isinstance(r, dict)
        assert r["is_error"] is True


@pytest.mark.asyncio
class TestSearch:
    async def test_missing_query_returns_error(self, dispatcher):
        r = await dispatcher.execute("SEARCH", {})
        assert r["is_error"] is True
        assert "query" in r["content"].lower()

    async def test_empty_query_returns_error(self, dispatcher):
        r = await dispatcher.execute("SEARCH", {"query": "   "})
        assert r["is_error"] is True

    async def test_search_calls_openclaw(self, dispatcher):
        """Verifie que SEARCH passe bien par openclaw_web_search avec les bons args."""
        from api.openclaw_bridge import OpenClawResponse

        mock_resp = OpenClawResponse(content="Resultats de recherche...", error=None)
        with patch("api.openclaw_bridge.openclaw_web_search", new=AsyncMock(return_value=mock_resp)) as m:
            r = await dispatcher.execute("SEARCH", {"query": "Ada Lovelace", "max_results": 5})
            assert r["is_error"] is False
            assert "Resultats" in r["content"]
            m.assert_called_once()
            kwargs = m.call_args.kwargs
            assert kwargs["query"] == "Ada Lovelace"

    async def test_search_error_propagates(self, dispatcher):
        from api.openclaw_bridge import OpenClawResponse

        mock_resp = OpenClawResponse(content="", error="Gateway down")
        with patch("api.openclaw_bridge.openclaw_web_search", new=AsyncMock(return_value=mock_resp)):
            r = await dispatcher.execute("SEARCH", {"query": "x"})
            assert r["is_error"] is True
            assert "Gateway down" in r["content"]


@pytest.mark.asyncio
class TestWebFetch:
    async def test_missing_url(self, dispatcher):
        r = await dispatcher.execute("WEB_FETCH", {})
        assert r["is_error"] is True

    async def test_invalid_scheme(self, dispatcher):
        r = await dispatcher.execute("WEB_FETCH", {"url": "ftp://example.com"})
        assert r["is_error"] is True
        assert "http" in r["content"].lower()

    async def test_file_scheme_rejected(self, dispatcher):
        # Securite : pas de lecture de file:// via WEB_FETCH.
        r = await dispatcher.execute("WEB_FETCH", {"url": "file:///etc/passwd"})
        assert r["is_error"] is True


@pytest.mark.asyncio
class TestMemory:
    async def test_save_requires_auth(self, dispatcher_anon):
        r = await dispatcher_anon.execute("MEMORY", {"key": "k", "value": "v"})
        assert r["is_error"] is True
        assert "authentif" in r["content"].lower()

    async def test_search_requires_auth(self, dispatcher_anon):
        r = await dispatcher_anon.execute("MEMORY_SEARCH", {"query": "x"})
        assert r["is_error"] is True

    async def test_save_missing_fields(self, dispatcher):
        r = await dispatcher.execute("MEMORY", {"key": "only_key"})
        assert r["is_error"] is True

    async def test_save_and_search_roundtrip(self, dispatcher, db):
        # Creer la table agent3_memory si elle n'existe pas en test
        db.conn.execute(
            "CREATE TABLE IF NOT EXISTS agent3_memory ("
            "id TEXT PRIMARY KEY, auth_user_id TEXT, key TEXT, value TEXT, "
            "category TEXT, created_at TEXT, updated_at TEXT)"
        )

        # Sauvegarder
        r1 = await dispatcher.execute("MEMORY", {
            "key": "preference_couleur",
            "value": "bleu nuit",
        })
        assert r1["is_error"] is False
        assert "Memorise" in r1["content"]

        # Chercher
        r2 = await dispatcher.execute("MEMORY_SEARCH", {"query": "couleur"})
        assert r2["is_error"] is False
        assert "preference_couleur" in r2["content"]
        assert "bleu nuit" in r2["content"]

    async def test_search_empty_returns_no_error(self, dispatcher, db):
        db.conn.execute(
            "CREATE TABLE IF NOT EXISTS agent3_memory ("
            "id TEXT PRIMARY KEY, auth_user_id TEXT, key TEXT, value TEXT, "
            "category TEXT, created_at TEXT, updated_at TEXT)"
        )
        r = await dispatcher.execute("MEMORY_SEARCH", {"query": "introuvable_xyz"})
        # Pas d'erreur — juste "aucun souvenir".
        assert r["is_error"] is False
        assert "aucun" in r["content"].lower()


@pytest.mark.asyncio
class TestCode:
    async def test_empty_content_errors(self, dispatcher):
        r = await dispatcher.execute("CODE", {"content": "   "})
        assert r["is_error"] is True

    async def test_passthrough_ok(self, dispatcher):
        r = await dispatcher.execute("CODE", {
            "content": "print('hello')",
            "language": "python",
        })
        assert r["is_error"] is False
        assert r["raw"]["language"] == "python"
        assert r["raw"]["content"] == "print('hello')"


@pytest.mark.asyncio
class TestCanvas:
    async def test_missing_fields(self, dispatcher):
        r = await dispatcher.execute("CANVAS", {"title": "x"})
        assert r["is_error"] is True

    async def test_ok(self, dispatcher):
        r = await dispatcher.execute("CANVAS", {
            "title": "Pie chart",
            "content": "# Canvas content",
        })
        assert r["is_error"] is False
        assert r["raw"]["title"] == "Pie chart"


@pytest.mark.asyncio
class TestFileRead:
    async def test_missing_filename(self, dispatcher):
        r = await dispatcher.execute("FILE_READ", {})
        assert r["is_error"] is True

    async def test_traversal_blocked(self, dispatcher):
        r = await dispatcher.execute("FILE_READ", {"filename": "../../../etc/passwd"})
        # Soit traversal bloque (refuse), soit fichier introuvable — jamais un leak.
        assert r["is_error"] is True
        # Le contenu NE DOIT PAS contenir de donnees sensibles
        assert "root:" not in r["content"]

    async def test_not_found(self, dispatcher):
        r = await dispatcher.execute("FILE_READ", {"filename": "nonexistent_xyz_123.txt"})
        assert r["is_error"] is True
        assert "introuvable" in r["content"].lower() or "hors workspace" in r["content"].lower()


@pytest.mark.asyncio
class TestCalendarList:
    async def test_requires_auth(self, dispatcher_anon):
        r = await dispatcher_anon.execute("CALENDAR_LIST", {})
        assert r["is_error"] is True
        assert "authentif" in r["content"].lower()

    async def test_no_integration_returns_error(self, dispatcher):
        # Pas d'integration Google Calendar configuree dans une DB vide -> erreur pedagogique
        r = await dispatcher.execute("CALENDAR_LIST", {})
        assert r["is_error"] is True
        assert r["content"]


@pytest.mark.asyncio
class TestFileCreate:
    async def test_missing_filename(self, dispatcher):
        r = await dispatcher.execute("FILE_CREATE", {"content": "hello"})
        assert r["is_error"] is True
        assert "filename" in r["content"].lower()

    async def test_empty_content(self, dispatcher):
        r = await dispatcher.execute("FILE_CREATE", {"filename": "a.txt", "content": ""})
        assert r["is_error"] is True

    async def test_anonymous_fallback(self, dispatcher_anon, tmp_path, monkeypatch):
        # Sans user_id, on tombe dans le fallback file_create
        from api.routers import agent3_openclaw
        monkeypatch.setattr(agent3_openclaw, "_save_file_create_fallback",
                             lambda fn, c: {"stored_filename": fn, "size": len(c),
                                             "download_url": f"/fake/{fn}"})
        r = await dispatcher_anon.execute("FILE_CREATE", {"filename": "note.txt", "content": "Hello"})
        assert r["is_error"] is False
        assert r["raw"]["fallback"] is True
        assert "note.txt" in r["content"]


@pytest.mark.asyncio
class TestEmail:
    async def test_missing_fields(self, dispatcher):
        r = await dispatcher.execute("EMAIL", {"to": "a@b.c"})
        assert r["is_error"] is True

    async def test_requires_auth(self, dispatcher_anon):
        r = await dispatcher_anon.execute("EMAIL", {
            "to": "a@b.c", "subject": "x", "body": "y",
        })
        assert r["is_error"] is True
        assert "authentif" in r["content"].lower()

    async def test_smtp_success(self, dispatcher, monkeypatch):
        from api.routers import agent3_openclaw
        monkeypatch.setattr(agent3_openclaw, "_send_email_smtp",
                             lambda db, uid, to, sub, body, html=False: {"ok": True, "message": "Envoye"})
        r = await dispatcher.execute("EMAIL", {
            "to": "a@b.c", "subject": "Hi", "body": "Bonjour",
        })
        assert r["is_error"] is False
        assert r["raw"]["method"] == "smtp"


@pytest.mark.asyncio
class TestCalendarEvent:
    async def test_missing_fields(self, dispatcher):
        r = await dispatcher.execute("CALENDAR_EVENT", {"title": "Meeting"})
        assert r["is_error"] is True

    async def test_requires_auth(self, dispatcher_anon):
        r = await dispatcher_anon.execute("CALENDAR_EVENT", {
            "title": "x", "start": "2025-01-01T10:00:00",
            "end": "2025-01-01T11:00:00",
        })
        assert r["is_error"] is True

    async def test_no_integration(self, dispatcher):
        r = await dispatcher.execute("CALENDAR_EVENT", {
            "title": "Sync", "start": "2025-01-01T10:00:00",
            "end": "2025-01-01T11:00:00",
        })
        assert r["is_error"] is True


@pytest.mark.asyncio
class TestGmailSend:
    async def test_missing_fields(self, dispatcher):
        r = await dispatcher.execute("GMAIL_SEND", {"to": "a@b.c"})
        assert r["is_error"] is True

    async def test_requires_auth(self, dispatcher_anon):
        r = await dispatcher_anon.execute("GMAIL_SEND", {
            "to": "a@b.c", "subject": "x", "body": "y",
        })
        assert r["is_error"] is True


@pytest.mark.asyncio
class TestDriveSave:
    async def test_empty_content(self, dispatcher):
        r = await dispatcher.execute("DRIVE_SAVE", {"filename": "a.txt", "content": ""})
        assert r["is_error"] is True

    async def test_requires_auth(self, dispatcher_anon):
        r = await dispatcher_anon.execute("DRIVE_SAVE", {"filename": "a.txt", "content": "hi"})
        assert r["is_error"] is True


@pytest.mark.asyncio
class TestGmailRead:
    async def test_requires_auth(self, dispatcher_anon):
        r = await dispatcher_anon.execute("GMAIL_READ", {"query": "is:unread"})
        assert r["is_error"] is True

    async def test_no_integration_returns_error(self, dispatcher):
        r = await dispatcher.execute("GMAIL_READ", {})
        assert r["is_error"] is True


@pytest.mark.asyncio
class TestCron:
    async def test_missing_instruction(self, dispatcher):
        r = await dispatcher.execute("CRON", {"label": "Ping", "cron_expr": "0 9 * * *"})
        assert r["is_error"] is True
        assert "instruction" in r["content"].lower()

    async def test_requires_auth(self, dispatcher_anon):
        r = await dispatcher_anon.execute("CRON", {
            "label": "Ping", "instruction": "Rappel hydratation",
            "cron_expr": "0 10 * * *",
        })
        assert r["is_error"] is True

    async def test_insert_ok(self, dispatcher):
        r = await dispatcher.execute("CRON", {
            "label": "Hydratation",
            "instruction": "Rappelle-moi de boire de l'eau",
            "cron_expr": "0 */2 * * *",
        })
        assert r["is_error"] is False
        assert "hydratation" in r["content"].lower()
        assert r["raw"]["cron_id"]
        assert r["raw"]["cron_expr"] == "0 */2 * * *"
        # Verifie que la ligne est bien en base
        row = dispatcher.db.conn.execute(
            "SELECT label, instruction, cron_expr FROM agent3_cron WHERE id = ?",
            (r["raw"]["cron_id"],),
        ).fetchone()
        assert row is not None
        assert row[0] == "Hydratation"


@pytest.mark.asyncio
class TestComputerUse:
    async def test_missing_prompt(self, dispatcher):
        r = await dispatcher.execute("COMPUTER_USE", {})
        assert r["is_error"] is True
        assert "prompt" in r["content"].lower()

    async def test_missing_api_key(self, dispatcher, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        r = await dispatcher.execute("COMPUTER_USE", {"prompt": "Ouvre example.com"})
        assert r["is_error"] is True
        assert "api" in r["content"].lower()

    async def test_delegates_to_session(self, dispatcher, monkeypatch):
        """Verifie que COMPUTER_USE consomme bien l'async-generator de la session
        et consolide steps + cost + final text."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")

        class _FakeSession:
            async def run(self, prompt):
                yield {"type": "step", "current": 1}
                yield {"type": "action", "action": "screenshot"}
                yield {"type": "cost_update", "estimated_usd": 0.012}
                yield {"type": "step", "current": 2}
                yield {"type": "complete", "text": "Tache terminee : formulaire envoye."}

        monkeypatch.setattr(
            "api.computer_use.get_session",
            lambda user_id, api_key: _FakeSession(),
        )
        r = await dispatcher.execute("COMPUTER_USE", {"prompt": "Remplis le formulaire"})
        assert r["is_error"] is False
        assert "formulaire envoye" in r["content"]
        assert r["raw"]["steps"] == 2
        assert r["raw"]["cost_usd"] == 0.012
        assert r["raw"]["last_action"] == "screenshot"

    async def test_propagates_error_event(self, dispatcher, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")

        class _FailingSession:
            async def run(self, prompt):
                yield {"type": "step", "current": 1}
                yield {"type": "error", "message": "Navigateur introuvable"}

        monkeypatch.setattr(
            "api.computer_use.get_session",
            lambda user_id, api_key: _FailingSession(),
        )
        r = await dispatcher.execute("COMPUTER_USE", {"prompt": "Va sur example.com"})
        assert r["is_error"] is True
        assert "navigateur" in r["content"].lower()


@pytest.mark.asyncio
class TestSpawnAgent:
    async def test_missing_description(self, dispatcher):
        r = await dispatcher.execute("SPAWN_AGENT", {"task": "Cherche des infos sur X."})
        assert r["is_error"] is True

    async def test_missing_task(self, dispatcher):
        r = await dispatcher.execute("SPAWN_AGENT", {"description": "Recherche concurrents"})
        assert r["is_error"] is True

    async def test_missing_api_key(self, dispatcher, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        r = await dispatcher.execute("SPAWN_AGENT", {
            "description": "Recherche IA",
            "task": "Liste 3 concurrents de Claude.",
        })
        assert r["is_error"] is True
        assert "api" in r["content"].lower()

    async def test_child_loop_runs_and_returns_final_text(self, dispatcher, monkeypatch):
        """Verifie que SPAWN_AGENT instancie une AgenticLoop enfant avec un
        perimetre restreint (pas de SPAWN_AGENT recursif, pas de destructives),
        et consolide son final_text."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")

        from api.agent3_native_tools import LoopEvent, LoopResult

        class _FakeChildLoop:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.result = None
                # On capture les tools pour valider le perimetre enfant
                _FakeChildLoop.last_tools = kwargs.get("tools")
                _FakeChildLoop.last_system = kwargs.get("system_prompt")
                _FakeChildLoop.last_max_turns = kwargs.get("max_turns")

            async def run(self, task):
                yield LoopEvent("turn_start", {"turn": 1})
                yield LoopEvent("tool_use", {"action_type": "SEARCH"})
                yield LoopEvent("turn_start", {"turn": 2})
                self.result = LoopResult(
                    final_text="3 concurrents identifies : A, B, C.",
                    turns=2, actions_executed=[], stop_reason="end_turn",
                )
                yield LoopEvent("done", {})

        monkeypatch.setattr("api.agent3_native_tools.AgenticLoop", _FakeChildLoop)
        monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: object())

        r = await dispatcher.execute("SPAWN_AGENT", {
            "description": "Recherche concurrents Claude",
            "task": "Liste 3 produits IA comparables.",
            "max_turns": 3,
        })
        assert r["is_error"] is False
        assert "3 concurrents" in r["content"]
        assert r["raw"]["turns_used"] == 2
        assert "SEARCH" in r["raw"]["actions_ran"]

        # Verifie que l'enfant n'a PAS acces a SPAWN_AGENT ni aux destructives
        tool_names = {t["name"] for t in _FakeChildLoop.last_tools}
        assert "spawn_agent" not in tool_names
        assert "email" not in tool_names
        assert "file_create" not in tool_names
        assert "computer_use" not in tool_names
        # Mais a bien les outils de lecture
        assert "search" in tool_names
        assert "memory_search" in tool_names

        # Le max_turns est respecte (cap a 10)
        assert _FakeChildLoop.last_max_turns == 3

    async def test_max_turns_capped(self, dispatcher, monkeypatch):
        """max_turns est cap a 10 quoi qu'il arrive."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake")

        from api.agent3_native_tools import LoopEvent, LoopResult

        class _FakeChildLoop:
            def __init__(self, **kwargs):
                _FakeChildLoop.last_max_turns = kwargs.get("max_turns")
                self.result = LoopResult(
                    final_text="ok", turns=1, actions_executed=[], stop_reason="end_turn"
                )

            async def run(self, task):
                yield LoopEvent("done", {})

        monkeypatch.setattr("api.agent3_native_tools.AgenticLoop", _FakeChildLoop)
        monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: object())

        await dispatcher.execute("SPAWN_AGENT", {
            "description": "Test", "task": "test", "max_turns": 999,
        })
        assert _FakeChildLoop.last_max_turns == 10


@pytest.mark.asyncio
class TestPdf:
    async def test_missing_title(self, dispatcher):
        r = await dispatcher.execute("PDF", {"sections": [{"heading": "x", "content": "y"}]})
        assert r["is_error"] is True

    async def test_missing_sections(self, dispatcher):
        r = await dispatcher.execute("PDF", {"title": "Rapport"})
        assert r["is_error"] is True

    async def test_empty_sections(self, dispatcher):
        r = await dispatcher.execute("PDF", {"title": "Rapport", "sections": []})
        assert r["is_error"] is True

    async def test_generate_ok(self, dispatcher):
        # Le generateur PDF reel est appele — on verifie juste que ca ne leve pas
        # et qu'on recoit un filename dans raw.
        r = await dispatcher.execute("PDF", {
            "title": "Test Report",
            "sections": [
                {"heading": "Intro", "content": "Bonjour."},
                {"heading": "Conclusion", "content": "Fin."},
            ],
        })
        # Peut echouer si fpdf n'est pas installe dans l'env de test — accepter les 2 cas.
        if r["is_error"]:
            # Si erreur, elle doit etre pedagogique (pas de crash)
            assert isinstance(r["content"], str)
        else:
            assert r["raw"]["filename"].endswith(".pdf")
            assert "/api/agent3/pdf/" in r["raw"]["url"]


# ═══════════════════════════════════════════════════════════════════════════
# TODO_WRITE — tracker in-memory expose au LLM.
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.asyncio
class TestTodoWrite:
    async def _dispatcher_with_fresh_tracker(self, db, user_id="todo_test_user"):
        # Assure un tracker neuf : on purge l'ancien via reset_todo_tracker si deja existant.
        from api.agent3_todo_tracker import reset_todo_tracker
        reset_todo_tracker(user_id)
        return Agent3ActionDispatcher(db=db, user_id=user_id, session_key="sess")

    async def test_invalid_mode_returns_error(self, db):
        d = await self._dispatcher_with_fresh_tracker(db)
        r = await d.execute("TODO_WRITE", {"mode": "bogus"})
        assert r["is_error"] is True
        assert "mode" in r["content"].lower()

    async def test_list_without_tracker_errors(self, db):
        from api.agent3_todo_tracker import reset_todo_tracker
        reset_todo_tracker("fresh_user")
        d = Agent3ActionDispatcher(db=db, user_id="fresh_user", session_key="sess")
        r = await d.execute("TODO_WRITE", {"mode": "list"})
        assert r["is_error"] is True
        assert "tracker" in r["content"].lower()

    async def test_create_then_list_and_transition(self, db):
        d = await self._dispatcher_with_fresh_tracker(db)
        created = await d.execute("TODO_WRITE", {
            "mode": "create",
            "items": [
                {"title": "Etape 1", "active_form": "Traitement etape 1"},
                {"title": "Etape 2"},
            ],
        })
        assert created["is_error"] is False
        snap = created["raw"]["snapshot"]
        assert snap["total"] == 2
        assert len(snap["items"]) == 2
        first_id = snap["items"][0]["id"]

        started = await d.execute("TODO_WRITE", {"mode": "start", "item_id": first_id})
        assert started["is_error"] is False
        assert started["raw"]["transition"]["new_status"] == "running"

        completed = await d.execute("TODO_WRITE", {
            "mode": "complete", "item_id": first_id, "result": "ok",
        })
        assert completed["is_error"] is False
        assert completed["raw"]["transition"]["new_status"] == "done"

        listed = await d.execute("TODO_WRITE", {"mode": "list"})
        assert listed["is_error"] is False
        counts = listed["raw"]["snapshot"]["counts"]
        assert counts["done"] == 1
        assert counts["pending"] == 1

    async def test_invalid_transition_returns_error(self, db):
        d = await self._dispatcher_with_fresh_tracker(db)
        await d.execute("TODO_WRITE", {
            "mode": "create",
            "items": [{"title": "T"}],
        })
        # complete sans start -> erreur (status pending, pas running)
        listed = await d.execute("TODO_WRITE", {"mode": "list"})
        item_id = listed["raw"]["snapshot"]["items"][0]["id"]
        r = await d.execute("TODO_WRITE", {"mode": "complete", "item_id": item_id})
        assert r["is_error"] is True
        assert "impossible" in r["content"].lower()

    async def test_create_requires_non_empty_items(self, db):
        d = await self._dispatcher_with_fresh_tracker(db)
        r = await d.execute("TODO_WRITE", {"mode": "create", "items": []})
        assert r["is_error"] is True
        assert "items" in r["content"].lower()
