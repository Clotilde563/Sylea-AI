"""
Tests Phase 8 — File ingestion + Vision tool + Plan auto-trigger + Compaction metrics.

Couvre :
  - api/file_ingestion.py : detection mime, extraction CSV/TXT/JSON, fallback
  - api/agent3_task_complexity.py : heuristiques + parse du plan
  - api/agent3_context_compaction.py : metrics recording + get/reset
  - dispatcher : VISION_ANALYZE (avec mocks)
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.agent3_native_dispatcher import Agent3ActionDispatcher
from sylea.core.storage.database import DatabaseManager
from tests.conftest import make_shared_db, dispose_shared_db


@pytest.fixture
def db(tmp_path, monkeypatch):
    """DB SQLite partagee (sync + async) via fichier temp.
    Migration shared-DB : remplace `:memory:` pour permettre a l'async
    session_factory de pointer sur la meme DB."""
    d = make_shared_db(tmp_path, monkeypatch)
    yield d
    dispose_shared_db(d)


@pytest.fixture
def dispatcher(db):
    return Agent3ActionDispatcher(db=db, user_id="u_phase8", session_key="sess_p8")


@pytest.fixture
def dispatcher_anon(db):
    return Agent3ActionDispatcher(db=db, user_id=None, session_key=None)


@pytest.fixture(autouse=True)
def _no_openai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# ─────────────────────────────────────────────────────────────────────────────
# 1. File ingestion — detection MIME + extraction CSV/TXT/JSON
# ─────────────────────────────────────────────────────────────────────────────

class TestMimeDetection:
    def test_detect_pdf(self):
        from api.file_ingestion import detect_mime
        assert detect_mime("document.pdf") == "application/pdf"

    def test_detect_docx(self):
        from api.file_ingestion import detect_mime
        mime = detect_mime("rapport.docx")
        assert "wordprocessingml" in mime or mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def test_detect_xlsx(self):
        from api.file_ingestion import detect_mime
        mime = detect_mime("data.xlsx")
        assert "spreadsheetml" in mime

    def test_detect_csv(self):
        from api.file_ingestion import detect_mime
        assert detect_mime("data.csv") == "text/csv"

    def test_detect_txt(self):
        from api.file_ingestion import detect_mime
        assert detect_mime("notes.txt") == "text/plain"

    def test_respects_provided(self):
        from api.file_ingestion import detect_mime
        assert detect_mime("whatever.bin", "application/pdf") == "application/pdf"

    def test_unknown_defaults(self):
        from api.file_ingestion import detect_mime
        mime = detect_mime("file.xyz")
        assert mime == "application/octet-stream"


class TestExtractText:
    def test_csv(self, tmp_path):
        from api.file_ingestion import extract_text
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25\n", encoding="utf-8")
        r = extract_text(str(csv_file))
        assert "Alice" in r["text"] and "Bob" in r["text"]
        assert r["backend"] == "csv"

    def test_txt(self, tmp_path):
        from api.file_ingestion import extract_text
        f = tmp_path / "note.txt"
        f.write_text("Ceci est un texte de test.", encoding="utf-8")
        r = extract_text(str(f))
        assert "test" in r["text"]
        assert r["backend"] == "text"

    def test_json_pretty(self, tmp_path):
        from api.file_ingestion import extract_text
        f = tmp_path / "data.json"
        f.write_text('{"a":1,"b":[1,2,3]}', encoding="utf-8")
        r = extract_text(str(f))
        # Pretty-printed => newlines + indent
        assert "\n" in r["text"]
        assert r["backend"] == "json"

    def test_missing_file(self, tmp_path):
        from api.file_ingestion import extract_text
        r = extract_text(str(tmp_path / "nonexistent.txt"))
        assert r["backend"] == "missing"
        assert r["text"] == ""

    def test_docx_fallback_if_lib_absent(self, tmp_path):
        """Si python-docx n'est pas installe, fallback propre."""
        from api.file_ingestion import extract_text
        f = tmp_path / "empty.docx"
        f.write_bytes(b"fake docx content")
        r = extract_text(str(f))
        # Soit extraction reussie (python-docx installe), soit message metadata
        assert r["backend"] in ("python-docx", "metadata_only", "error")

    def test_image_skip(self, tmp_path):
        from api.file_ingestion import extract_text
        f = tmp_path / "pic.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n")
        r = extract_text(str(f))
        assert r["backend"] == "skip_image"
        assert "VISION_ANALYZE" in r["text"]

    def test_max_chars_truncation(self, tmp_path):
        from api.file_ingestion import extract_text, _MAX_TEXT_CHARS
        f = tmp_path / "huge.txt"
        f.write_text("A" * (_MAX_TEXT_CHARS + 5000), encoding="utf-8")
        r = extract_text(str(f))
        assert r["truncated"] is True
        assert "tronque" in r["text"]


class TestAutoRag:
    @pytest.mark.asyncio
    async def test_extract_and_ingest_short_skips_rag(self, db, tmp_path):
        from api.file_ingestion import extract_and_ingest
        f = tmp_path / "short.txt"
        f.write_text("Petit texte", encoding="utf-8")
        r = await extract_and_ingest(db, "u1", str(f))
        assert r["ingested"] is False

    @pytest.mark.asyncio
    async def test_extract_and_ingest_long_triggers_rag(self, db, tmp_path):
        from api.file_ingestion import extract_and_ingest
        f = tmp_path / "long.txt"
        f.write_text("Texte long. " * 500, encoding="utf-8")
        r = await extract_and_ingest(db, "u1", str(f))
        assert r["ingested"] is True
        assert r["chunks"] >= 1

    @pytest.mark.asyncio
    async def test_no_user_id_no_rag(self, db, tmp_path):
        from api.file_ingestion import extract_and_ingest
        f = tmp_path / "long.txt"
        f.write_text("Texte long. " * 500, encoding="utf-8")
        r = await extract_and_ingest(db, None, str(f))
        assert r["ingested"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Task complexity heuristics
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskComplexity:
    def test_trivial_greetings(self):
        from api.agent3_task_complexity import is_complex_task
        assert is_complex_task("salut")[0] is False
        assert is_complex_task("bonjour")[0] is False
        assert is_complex_task("merci beaucoup")[0] is False
        assert is_complex_task("ok")[0] is False

    def test_empty(self):
        from api.agent3_task_complexity import is_complex_task
        assert is_complex_task("")[0] is False
        assert is_complex_task("   ")[0] is False

    def test_analyse_trigger(self):
        from api.agent3_task_complexity import is_complex_task
        ok, reason = is_complex_task("Analyse la rentabilite du marche IA sante")
        assert ok is True
        assert "analyse" in reason or "analys" in reason

    def test_rapport_trigger(self):
        from api.agent3_task_complexity import is_complex_task
        ok, _ = is_complex_task("Fais-moi un rapport sur les concurrents Stripe")
        assert ok is True

    def test_compound_verbs(self):
        from api.agent3_task_complexity import is_complex_task
        ok, _ = is_complex_task("Cherche les 5 meilleurs articles et envoie-les par email")
        assert ok is True

    def test_quantifier(self):
        from api.agent3_task_complexity import is_complex_task
        ok, _ = is_complex_task("Genere un rapport pour chaque client")
        assert ok is True

    def test_long_prompt(self):
        from api.agent3_task_complexity import is_complex_task
        long_msg = "Fais ceci " + "avec cet objectif tres precis " * 30
        ok, reason = is_complex_task(long_msg)
        assert ok is True
        assert "long" in reason.lower()

    def test_multi_sentence(self):
        from api.agent3_task_complexity import is_complex_task
        ok, reason = is_complex_task(
            "Cherche X sur le web. Trouve Y dans la doc. Envoie un email a Z."
        )
        assert ok is True

    def test_files_uploaded_even_short(self):
        from api.agent3_task_complexity import is_complex_task
        ok, _ = is_complex_task(
            "Analyse ce document pour moi s'il te plait",
            has_files_uploaded=True,
        )
        assert ok is True

    def test_format_for_sse(self):
        from api.agent3_task_complexity import format_plan_for_sse
        evt = format_plan_for_sse(["Etape 1", "Etape 2"], reason="analyse")
        assert evt["type"] == "task_plan"
        assert evt["count"] == 2
        assert evt["reason"] == "analyse"


class TestGeneratePlan:
    @pytest.mark.asyncio
    async def test_parse_numbered_list(self):
        from api.agent3_task_complexity import generate_task_plan

        # Mock client retournant une liste numerotee
        mock_client = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "1. Chercher les concurrents\n2. Comparer les prix\n3. Rediger le rapport"
        mock_resp = MagicMock()
        mock_resp.content = [mock_block]
        mock_client.messages.create = AsyncMock(return_value=mock_resp)

        steps = await generate_task_plan("Analyse les concurrents", mock_client)
        assert len(steps) == 3
        assert "concurrents" in steps[0]

    @pytest.mark.asyncio
    async def test_parse_bullets(self):
        from api.agent3_task_complexity import generate_task_plan
        mock_client = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "- Etape 1 : chercher\n- Etape 2 : analyser\n- Etape 3 : envoyer"
        mock_resp = MagicMock()
        mock_resp.content = [mock_block]
        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        steps = await generate_task_plan("Fais-moi ca", mock_client)
        assert len(steps) == 3

    @pytest.mark.asyncio
    async def test_empty_plan_returns_empty(self):
        from api.agent3_task_complexity import generate_task_plan
        steps = await generate_task_plan("", MagicMock())
        assert steps == []

    @pytest.mark.asyncio
    async def test_trivial_detected(self):
        from api.agent3_task_complexity import generate_task_plan
        mock_client = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "Trivial — pas de plan necessaire."
        mock_resp = MagicMock()
        mock_resp.content = [mock_block]
        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        steps = await generate_task_plan("salut", mock_client)
        assert steps == []

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self):
        from api.agent3_task_complexity import generate_task_plan
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))
        steps = await generate_task_plan("Analyse la situation", mock_client)
        assert steps == []

    @pytest.mark.asyncio
    async def test_max_6_steps(self):
        from api.agent3_task_complexity import generate_task_plan
        mock_client = MagicMock()
        mock_block = MagicMock()
        # 10 etapes -> cap a 6
        mock_block.text = "\n".join(f"{i}. Etape {i}" for i in range(1, 11))
        mock_resp = MagicMock()
        mock_resp.content = [mock_block]
        mock_client.messages.create = AsyncMock(return_value=mock_resp)
        steps = await generate_task_plan("Fais tout", mock_client)
        assert len(steps) <= 6


# ─────────────────────────────────────────────────────────────────────────────
# 3. VISION_ANALYZE dispatcher
# ─────────────────────────────────────────────────────────────────────────────

class TestVisionAnalyze:
    @pytest.mark.asyncio
    async def test_no_user(self, dispatcher_anon):
        r = await dispatcher_anon.execute("VISION_ANALYZE", {"file_id": "x", "prompt": "?"})
        assert r["is_error"] is True
        assert "authentifie" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_no_file_id(self, dispatcher):
        r = await dispatcher.execute("VISION_ANALYZE", {"prompt": "Que vois-tu?"})
        assert r["is_error"] is True
        assert "file_id" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_no_prompt(self, dispatcher):
        r = await dispatcher.execute("VISION_ANALYZE", {"file_id": "abc"})
        assert r["is_error"] is True
        assert "prompt" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_prompt_too_long(self, dispatcher):
        r = await dispatcher.execute(
            "VISION_ANALYZE", {"file_id": "abc", "prompt": "x" * 3000},
        )
        assert r["is_error"] is True
        assert "trop long" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_file_not_found(self, db, dispatcher):
        # Assurer que la table existe
        from api.routers.agent3_openclaw import _ensure_agent3_tables_async
        await _ensure_agent3_tables_async()
        r = await dispatcher.execute(
            "VISION_ANALYZE", {"file_id": "zzz_inexistant", "prompt": "?"},
        )
        assert r["is_error"] is True
        assert "introuvable" in r["content"].lower() or "appartient" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_file_not_image(self, db, dispatcher, tmp_path):
        from api.routers.agent3_openclaw import _ensure_agent3_tables_async
        await _ensure_agent3_tables_async()
        # Creer un file PDF enregistre pour ce user
        pdf_path = tmp_path / "doc.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake")
        db.conn.execute(
            "INSERT INTO agent3_files (id, auth_user_id, filename, filetype, filesize, filepath, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("pdf01", "u_phase8", "doc.pdf", "application/pdf", 12, str(pdf_path), "now"),
        )
        db.conn.commit()
        r = await dispatcher.execute(
            "VISION_ANALYZE", {"file_id": "pdf01", "prompt": "Lis ce fichier"},
        )
        assert r["is_error"] is True
        assert "image" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_image_ok_mocked(self, db, dispatcher, tmp_path, monkeypatch):
        from api.routers.agent3_openclaw import _ensure_agent3_tables_async
        await _ensure_agent3_tables_async()
        img_path = tmp_path / "pic.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        db.conn.execute(
            "INSERT INTO agent3_files (id, auth_user_id, filename, filetype, filesize, filepath, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("img01", "u_phase8", "pic.png", "image/png", 16, str(img_path), "now"),
        )
        db.conn.commit()

        # Mock la fonction vision pour ne pas appeler l'API
        async def fake_vision(*args, **kwargs):
            return "C'est une belle photo avec un chat sur un canape."
        monkeypatch.setattr(
            "api.routers.agent3_openclaw._analyze_image_with_vision", fake_vision,
        )
        r = await dispatcher.execute(
            "VISION_ANALYZE", {"file_id": "img01", "prompt": "Que vois-tu?"},
        )
        assert r["is_error"] is False
        assert "chat" in r["content"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Compaction metrics (Phase 8D)
# ─────────────────────────────────────────────────────────────────────────────

class TestCompactionMetrics:
    def setup_method(self):
        from api.agent3_context_compaction import reset_compaction_metrics
        reset_compaction_metrics()

    def test_initial_state(self):
        from api.agent3_context_compaction import get_compaction_metrics
        m = get_compaction_metrics()
        assert m["total_compactions"] == 0
        assert m["failures"] == 0
        assert m["users_with_compactions"] == 0

    def test_record_increments(self):
        from api.agent3_context_compaction import (
            _record_compaction, get_compaction_metrics,
        )
        _record_compaction(
            "user_a",
            tokens_before=10000, tokens_after=3000,
            messages_before=20, messages_after=8,
            duration_s=1.5, success=True,
        )
        m = get_compaction_metrics()
        assert m["total_compactions"] == 1
        assert m["total_tokens_saved"] == 7000
        assert m["users_with_compactions"] == 1
        assert "user_a" in m["by_user"]
        assert m["by_user"]["user_a"]["tokens_saved"] == 7000

    def test_failures_tracked(self):
        from api.agent3_context_compaction import (
            _record_compaction, get_compaction_metrics,
        )
        _record_compaction(
            "user_a",
            tokens_before=5000, tokens_after=5000,
            messages_before=20, messages_after=20,
            duration_s=0.1, success=False,
        )
        m = get_compaction_metrics()
        assert m["failures"] == 1

    def test_multiple_users(self):
        from api.agent3_context_compaction import (
            _record_compaction, get_compaction_metrics,
        )
        _record_compaction("alice", tokens_before=5000, tokens_after=1000,
                           messages_before=15, messages_after=5, duration_s=0.5)
        _record_compaction("bob", tokens_before=8000, tokens_after=2000,
                           messages_before=18, messages_after=6, duration_s=0.8)
        _record_compaction("alice", tokens_before=6000, tokens_after=2000,
                           messages_before=16, messages_after=7, duration_s=0.7)

        m = get_compaction_metrics()
        assert m["total_compactions"] == 3
        assert m["users_with_compactions"] == 2
        assert m["by_user"]["alice"]["count"] == 2
        assert m["by_user"]["alice"]["tokens_saved"] == 8000
        assert m["by_user"]["bob"]["count"] == 1

    def test_reset_clears(self):
        from api.agent3_context_compaction import (
            _record_compaction, reset_compaction_metrics, get_compaction_metrics,
        )
        _record_compaction("x", tokens_before=100, tokens_after=50,
                           messages_before=10, messages_after=5, duration_s=0.1)
        reset_compaction_metrics()
        m = get_compaction_metrics()
        assert m["total_compactions"] == 0

    @pytest.mark.asyncio
    async def test_maybe_compact_records_metrics(self):
        """ContextCompactor.maybe_compact doit enregistrer des metrics."""
        from api.agent3_context_compaction import (
            ContextCompactor, reset_compaction_metrics, get_compaction_metrics,
        )
        reset_compaction_metrics()

        # Mock client pour _summarize
        mock_client = MagicMock()
        mock_block = MagicMock()
        mock_block.text = "HISTORIQUE CONDENSE : 5 tours anciens"
        mock_resp = MagicMock()
        mock_resp.content = [mock_block]
        mock_client.messages.create = MagicMock(return_value=mock_resp)

        compactor = ContextCompactor(mock_client, max_messages=5, target_messages=3, keep_last=2)
        # 8 messages > max=5 → compaction
        msgs = [
            {"role": "user", "content": f"msg {i} " * 100} for i in range(8)
        ]
        new_msgs = await compactor.maybe_compact(msgs, user_id="u_compact")
        assert len(new_msgs) < len(msgs)

        m = get_compaction_metrics()
        assert m["total_compactions"] == 1
        assert "u_compact" in m["by_user"]

    @pytest.mark.asyncio
    async def test_under_threshold_no_compact(self):
        from api.agent3_context_compaction import (
            ContextCompactor, reset_compaction_metrics, get_compaction_metrics,
        )
        reset_compaction_metrics()
        compactor = ContextCompactor(MagicMock(), max_messages=100)
        msgs = [{"role": "user", "content": "x"} for _ in range(3)]
        new_msgs = await compactor.maybe_compact(msgs, user_id="u")
        assert new_msgs == msgs  # pas touche
        m = get_compaction_metrics()
        assert m["total_compactions"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 5. Dispatcher SUPPORTED integration
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatcherIntegration:
    def test_vision_analyze_supported(self):
        assert "VISION_ANALYZE" in Agent3ActionDispatcher.SUPPORTED

    def test_vision_analyze_tool_schema(self):
        from api.agent3_native_tools import build_tool_schemas
        schemas = build_tool_schemas(enabled_actions={"VISION_ANALYZE"})
        names = [s["name"] for s in schemas]
        assert "vision_analyze" in names

    def test_semantic_search_tool_schema(self):
        """Phase 7 tools aussi exposes maintenant."""
        from api.agent3_native_tools import build_tool_schemas
        schemas = build_tool_schemas(
            enabled_actions={"SEMANTIC_SEARCH", "PYTHON_EXEC", "DEEP_RESEARCH"}
        )
        names = {s["name"] for s in schemas}
        assert "semantic_search" in names
        assert "python_exec" in names
        assert "deep_research" in names
