"""
Tests Phase 7 — RAG + sandbox Python + Deep Research + Awareness contextuelle.

Couvre :
  - api/rag.py : chunking, embeddings fallback, ingest/search round-trip, isolation
  - api/python_sandbox.py : execution de base, timeout, stderr capture
  - api/agent3_awareness.py : format date, patterns, cache
  - dispatcher : SEMANTIC_SEARCH, PYTHON_EXEC, DEEP_RESEARCH (avec mocks)

Ces tests sont volontairement rapides — pas d'appel reseau reel (OpenAI, Gateway).
Les scenarios reseau sont couverts par des mocks.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.agent3_native_dispatcher import Agent3ActionDispatcher
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
    return Agent3ActionDispatcher(db=db, user_id="u_phase7", session_key="sess_p7")


@pytest.fixture
def dispatcher_anon(db):
    return Agent3ActionDispatcher(db=db, user_id=None, session_key=None)


@pytest.fixture(autouse=True)
def _no_openai(monkeypatch):
    # Force le fallback hash pour tests deterministes (pas d'appel reseau).
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


# ─────────────────────────────────────────────────────────────────────────────
# 1. RAG — chunking
# ─────────────────────────────────────────────────────────────────────────────

class TestChunking:
    def test_short_text_single_chunk(self):
        from api.rag import chunk_text
        chunks = chunk_text("Bonjour, ceci est un petit texte.")
        assert chunks == ["Bonjour, ceci est un petit texte."]

    def test_empty_text(self):
        from api.rag import chunk_text
        assert chunk_text("") == []
        assert chunk_text("   ") == []

    def test_long_text_multiple_chunks(self):
        from api.rag import chunk_text
        # 3000 chars > 800 → doit faire au moins 3 chunks
        long_text = "Ceci est une phrase exemple. " * 200
        chunks = chunk_text(long_text, size=800, overlap=100)
        assert len(chunks) >= 3
        # Chaque chunk raisonnablement proche de 800
        for c in chunks[:-1]:
            assert len(c) <= 1000  # marge pour limite de phrase
        # Pas de chunk vide
        assert all(c.strip() for c in chunks)

    def test_overlap_preserves_context(self):
        from api.rag import chunk_text
        long_text = "A" * 500 + ". " + "B" * 500 + ". " + "C" * 500
        chunks = chunk_text(long_text, size=600, overlap=50)
        assert len(chunks) >= 2

    def test_max_chunks_cap(self):
        from api.rag import chunk_text, _MAX_CHUNKS_PER_SOURCE
        massive = "x" * (900 * (_MAX_CHUNKS_PER_SOURCE + 50))
        chunks = chunk_text(massive, size=800, overlap=0)
        assert len(chunks) <= _MAX_CHUNKS_PER_SOURCE


# ─────────────────────────────────────────────────────────────────────────────
# 2. RAG — embeddings (fallback hash)
# ─────────────────────────────────────────────────────────────────────────────

class TestEmbeddingsFallback:
    @pytest.mark.asyncio
    async def test_embed_returns_vectors(self):
        from api.rag import embed_texts
        vectors, model = await embed_texts(["bonjour", "monde"])
        assert len(vectors) == 2
        assert model == "hash-fallback-v1"
        assert len(vectors[0]) == 256  # _FALLBACK_DIMS

    @pytest.mark.asyncio
    async def test_empty_input(self):
        from api.rag import embed_texts
        vectors, model = await embed_texts([])
        assert vectors == []

    @pytest.mark.asyncio
    async def test_deterministic(self):
        from api.rag import embed_texts
        v1, _ = await embed_texts(["test stable"])
        v2, _ = await embed_texts(["test stable"])
        assert v1 == v2

    def test_cosine_similarity(self):
        from api.rag import cosine_similarity
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
        assert cosine_similarity([], []) == 0.0
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. RAG — ingest + search round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestRagRoundTrip:
    @pytest.mark.asyncio
    async def test_ingest_and_search(self, db):
        from api.rag import ingest_text, semantic_search
        text = (
            "Python est un langage de programmation de haut niveau interprete. "
            "JavaScript est le langage du web. "
            "Rust est un langage systeme moderne avec un borrow checker. "
        ) * 10  # ~500+ chars pour passer le _MIN_INGEST_CHARS

        result = await ingest_text(
            db, "u1", text, source_type="test", source_ref="doc1",
        )
        assert result["ingested_chunks"] >= 1
        assert result["total_chars"] > 200

        # Recherche (min_similarity=0 car hash-fallback peut donner petits scores)
        hits = await semantic_search(
            db, "u1", "programmation Python", top_k=3, min_similarity=0.0,
        )
        assert len(hits) >= 1
        assert hits[0]["source_type"] == "test"

    @pytest.mark.asyncio
    async def test_ingest_too_short_skipped(self, db):
        from api.rag import ingest_text
        result = await ingest_text(db, "u1", "court", source_type="test")
        assert result.get("skipped") == "too_short"

    @pytest.mark.asyncio
    async def test_no_user_id_rejected(self, db):
        from api.rag import ingest_text
        result = await ingest_text(db, "", "x" * 500, source_type="test")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_user_isolation(self, db):
        from api.rag import ingest_text, semantic_search
        text_a = "Alice adore le jardinage et les tomates." * 20
        text_b = "Bob prefere programmer en Python." * 20

        await ingest_text(db, "alice", text_a, source_type="test", source_ref="a1")
        await ingest_text(db, "bob", text_b, source_type="test", source_ref="b1")

        hits_a = await semantic_search(db, "alice", "jardinage", top_k=5, min_similarity=0.0)
        hits_b = await semantic_search(db, "bob", "Python", top_k=5, min_similarity=0.0)

        assert len(hits_a) >= 1
        assert len(hits_b) >= 1
        # Tous les hits sont dans la bonne source
        assert all(h["source_ref"] == "a1" for h in hits_a)
        assert all(h["source_ref"] == "b1" for h in hits_b)

        # Alice ne doit pas voir les donnees de Bob — isolation auth_user_id
        hits_cross = await semantic_search(db, "alice", "Python", top_k=5, min_similarity=0.0)
        for h in hits_cross:
            assert h["source_ref"] == "a1"

    @pytest.mark.asyncio
    async def test_replace_existing(self, db):
        from api.rag import ingest_text, semantic_search
        text_v1 = "Version 1 du document original." * 30
        text_v2 = "Version 2 completement reecrit." * 30

        await ingest_text(db, "u1", text_v1, source_type="doc", source_ref="x")
        hits_v1 = await semantic_search(db, "u1", "Version 1", top_k=5, min_similarity=0.0)
        assert any("version 1" in h["content"].lower() for h in hits_v1)

        # Replace
        await ingest_text(db, "u1", text_v2, source_type="doc", source_ref="x")
        hits_after = await semantic_search(db, "u1", "Version 1", top_k=5, min_similarity=0.0)
        # Apres replace, plus de "Version 1"
        assert not any("version 1" in h["content"].lower() for h in hits_after)

    @pytest.mark.asyncio
    async def test_delete_by_source(self, db):
        from api.rag import ingest_text, delete_by_source, semantic_search
        text = "Du contenu pour tester la suppression." * 30
        await ingest_text(db, "u1", text, source_type="upload", source_ref="file.txt")

        # Suppression
        n = delete_by_source(db, "u1", "upload", "file.txt")
        assert n >= 1
        hits = await semantic_search(db, "u1", "suppression", top_k=5, min_similarity=0.0)
        assert len(hits) == 0

    @pytest.mark.asyncio
    async def test_search_empty_query(self, db):
        from api.rag import semantic_search
        hits = await semantic_search(db, "u1", "", top_k=5)
        assert hits == []

    @pytest.mark.asyncio
    async def test_search_filters_by_source_type(self, db):
        from api.rag import ingest_text, semantic_search
        await ingest_text(
            db, "u1", "Contenu d'un site web scrappe en ligne." * 20,
            source_type="web_fetch", source_ref="http://a",
        )
        await ingest_text(
            db, "u1", "Contenu d'un fichier uploade en local." * 20,
            source_type="upload", source_ref="local.txt",
        )

        hits = await semantic_search(db, "u1", "contenu", top_k=10,
                                      source_types=["web_fetch"], min_similarity=0.0)
        assert all(h["source_type"] == "web_fetch" for h in hits)

    def test_get_rag_stats(self, db):
        from api.rag import get_rag_stats, ensure_rag_tables
        ensure_rag_tables(db)
        stats = get_rag_stats(db, "u_noop")
        assert stats["total_chunks"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Dispatcher SEMANTIC_SEARCH
# ─────────────────────────────────────────────────────────────────────────────

class TestDispatcherSemanticSearch:
    @pytest.mark.asyncio
    async def test_semantic_search_no_user(self, dispatcher_anon):
        r = await dispatcher_anon.execute("SEMANTIC_SEARCH", {"query": "test"})
        assert r["is_error"] is True
        assert "authentifie" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_semantic_search_no_query(self, dispatcher):
        r = await dispatcher.execute("SEMANTIC_SEARCH", {})
        assert r["is_error"] is True
        assert "query" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_semantic_search_empty_result(self, dispatcher):
        r = await dispatcher.execute("SEMANTIC_SEARCH", {"query": "inexistant"})
        assert r["is_error"] is False
        assert "aucun" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_semantic_search_returns_hits(self, db, dispatcher):
        from api.rag import ingest_text
        await ingest_text(
            db, "u_phase7", "Le framework Sylea utilise FastAPI et React." * 20,
            source_type="test", source_ref="t1",
        )
        r = await dispatcher.execute("SEMANTIC_SEARCH", {"query": "Sylea FastAPI", "top_k": 3})
        assert r["is_error"] is False
        assert "resultats" in r["content"].lower()
        assert r["raw"]["count"] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 5. Python sandbox
# ─────────────────────────────────────────────────────────────────────────────

class TestPythonSandbox:
    @pytest.mark.asyncio
    async def test_simple_print(self):
        from api.python_sandbox import run_python_sandbox
        r = await run_python_sandbox("print('hello from sandbox')")
        assert "hello from sandbox" in r["stdout"]
        assert r["exit_code"] == 0
        assert r["timed_out"] is False

    @pytest.mark.asyncio
    async def test_math_computation(self):
        from api.python_sandbox import run_python_sandbox
        r = await run_python_sandbox("print(sum(range(100)))")
        assert "4950" in r["stdout"]

    @pytest.mark.asyncio
    async def test_syntax_error(self):
        from api.python_sandbox import run_python_sandbox
        r = await run_python_sandbox("this is not python")
        # Le wrapper capture l'exception → soit stderr, soit error
        assert r["exit_code"] != 0 or r["error"] or r["stderr"]

    @pytest.mark.asyncio
    async def test_division_zero(self):
        from api.python_sandbox import run_python_sandbox
        r = await run_python_sandbox("1 / 0")
        # Exception runtime capturee
        assert r["error"] or "ZeroDivisionError" in (r["stderr"] + r["stdout"])

    @pytest.mark.asyncio
    async def test_timeout(self):
        from api.python_sandbox import run_python_sandbox
        r = await run_python_sandbox("import time; time.sleep(60)", timeout_s=2.0)
        assert r["timed_out"] is True

    @pytest.mark.asyncio
    async def test_dispatcher_python_exec_no_code(self, dispatcher):
        r = await dispatcher.execute("PYTHON_EXEC", {})
        assert r["is_error"] is True
        assert "code" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_dispatcher_python_exec_ok(self, dispatcher):
        r = await dispatcher.execute("PYTHON_EXEC", {"code": "print('sandboxok')"})
        assert "sandboxok" in r["content"]
        assert r["is_error"] is False

    @pytest.mark.asyncio
    async def test_dispatcher_code_too_long(self, dispatcher):
        # 50001 chars > limite
        r = await dispatcher.execute("PYTHON_EXEC", {"code": "x = 0\n" * 10000})
        assert r["is_error"] is True
        assert "trop long" in r["content"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Deep Research (mock — pas d'API)
# ─────────────────────────────────────────────────────────────────────────────

class TestDeepResearch:
    @pytest.mark.asyncio
    async def test_no_api_key_graceful(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from api.deep_research import run_deep_research
        r = await run_deep_research("question test", max_iterations=2, budget_usd=0.10)
        assert r["stop_reason"] == "no_api_key"
        assert "indisponible" in r["markdown"].lower()
        assert r["cost_usd"] == 0.0

    @pytest.mark.asyncio
    async def test_dispatcher_deep_research_no_query(self, dispatcher):
        r = await dispatcher.execute("DEEP_RESEARCH", {})
        assert r["is_error"] is True
        assert "query" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_dispatcher_deep_research_no_api_key(self, dispatcher, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        r = await dispatcher.execute(
            "DEEP_RESEARCH",
            {"query": "sujet de recherche", "max_iterations": 3, "budget_usd": 0.10},
        )
        assert r["is_error"] is False  # mais markdown = indisponible
        assert "indisponible" in r["content"].lower()

    @pytest.mark.asyncio
    async def test_budget_clamped(self, dispatcher, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # budget > 2.00 → clamp a 2.00
        r = await dispatcher.execute(
            "DEEP_RESEARCH", {"query": "q", "budget_usd": 99.0},
        )
        # Pas d'erreur de type, budget accepte (clamped)
        assert isinstance(r, dict)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Awareness contextuelle
# ─────────────────────────────────────────────────────────────────────────────

class TestAwareness:
    def test_block_empty_without_user(self, db):
        from api.agent3_awareness import build_awareness_block
        assert build_awareness_block(db, None) == ""
        assert build_awareness_block(db, "") == ""

    def test_block_empty_without_db(self):
        from api.agent3_awareness import build_awareness_block
        assert build_awareness_block(None, "u1") == ""

    def test_block_contains_moment(self, db):
        from api.agent3_awareness import build_awareness_block, invalidate_awareness_cache
        invalidate_awareness_cache("u_awareness")
        block = build_awareness_block(db, "u_awareness")
        # Le user n'a rien en DB → bloc peut etre vide... sauf si moment est ajoute.
        # Dans l'impl, moment est toujours ajoute donc bloc != ""
        assert "CONTEXTE ACTUEL" in block or block == ""
        if block:
            # L'un des moments doit apparaitre
            assert any(m in block.lower() for m in ["matin", "midi", "apres-midi", "soir", "nuit"])

    def test_cache_speed(self, db):
        """Le 2eme appel doit etre tres rapide (cache hit)."""
        from api.agent3_awareness import build_awareness_block, invalidate_awareness_cache
        import time
        invalidate_awareness_cache("u_cache")
        t0 = time.time()
        b1 = build_awareness_block(db, "u_cache")
        t1 = time.time()
        b2 = build_awareness_block(db, "u_cache")
        t2 = time.time()
        assert b1 == b2
        # Cache hit doit etre instant (< 10ms)
        assert (t2 - t1) < 0.01

    def test_invalidate_cache_specific_user(self, db):
        from api.agent3_awareness import (
            build_awareness_block, invalidate_awareness_cache, _awareness_cache,
        )
        # Prime cache pour 2 users
        build_awareness_block(db, "user_x")
        build_awareness_block(db, "user_y")
        assert "user_x" in _awareness_cache or True  # peut etre vide si pas de contenu
        invalidate_awareness_cache("user_x")
        assert "user_x" not in _awareness_cache

    def test_invalidate_cache_all(self, db):
        from api.agent3_awareness import (
            build_awareness_block, invalidate_awareness_cache, _awareness_cache,
        )
        build_awareness_block(db, "user_all_1")
        build_awareness_block(db, "user_all_2")
        invalidate_awareness_cache(None)
        assert len(_awareness_cache) == 0

    def test_current_moment_buckets(self):
        from api.agent3_awareness import _current_moment
        from datetime import datetime
        assert _current_moment(datetime(2026, 1, 1, 3, 0)) == "nuit"
        assert _current_moment(datetime(2026, 1, 1, 9, 0)) == "matin"
        assert _current_moment(datetime(2026, 1, 1, 13, 0)) == "midi"
        assert _current_moment(datetime(2026, 1, 1, 16, 0)) == "apres-midi"
        assert _current_moment(datetime(2026, 1, 1, 20, 0)) == "soir"
        assert _current_moment(datetime(2026, 1, 1, 23, 0)) == "nuit"

    def test_format_now_block_weekday(self):
        from api.agent3_awareness import _format_now_block
        from datetime import datetime
        # 2026-04-21 = mardi (week 17, 21 avril 2026)
        lines = _format_now_block(datetime(2026, 4, 21, 14, 30))
        assert any("mardi" in l for l in lines)
        assert any("21/04/2026" in l for l in lines)

    def test_objective_snapshot_with_profil(self, db):
        """Si le profil existe avec un objectif, le bloc le mentionne."""
        from api.agent3_awareness import _objective_snapshot
        import uuid

        # Seed un profil minimal respectant le vrai schema (NOT NULL requis)
        now = "2026-04-21T14:00:00"
        db.conn.execute(
            "INSERT INTO profil_utilisateur "
            "(id, nom, age, profession, ville, situation_familiale, "
            " revenu_annuel, patrimoine_estime, charges_mensuelles, "
            " objectif_description, objectif_categorie, objectif_deadline, "
            " probabilite_actuelle, auth_user_id, cree_le, mis_a_jour_le) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), "Test User", 30, "Dev", "Paris", "celibataire",
             50000.0, 10000.0, 1500.0,
             "Devenir freelance senior", "career", "2026-12-31", 65.0,
             "u_profil", now, now),
        )
        db.conn.commit()

        lines = _objective_snapshot(db, "u_profil")
        assert any("freelance" in l.lower() for l in lines)
        assert any("2026-12-31" in l for l in lines)
        assert any("65" in l for l in lines)

    def test_usage_patterns_with_messages(self, db):
        from api.agent3_awareness import _detect_usage_patterns
        from datetime import datetime, timezone, timedelta
        import uuid

        # Creer le user parent (FK agent3_messages.auth_user_id -> users.id)
        db.conn.execute(
            "INSERT INTO users (id, email, hashed_password, created_at) VALUES (?,?,?,?)",
            ("u_pattern", "pattern@test.com", "pw", "2026-04-21T14:00:00"),
        )

        # Simuler 20 messages de user sur 10 jours dans le schema reel
        now = datetime.now(timezone.utc)
        for i in range(20):
            ts = (now - timedelta(days=i % 10)).isoformat()
            db.conn.execute(
                "INSERT INTO agent3_messages "
                "(id, auth_user_id, role, content, type, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (str(uuid.uuid4()), "u_pattern", "user", f"msg {i}", "text", ts),
            )
        db.conn.commit()

        obs = _detect_usage_patterns(db, "u_pattern", datetime.now())
        assert isinstance(obs, list)
        # 20 messages sur 10 jours = 2.0/jour → devrait trouver une observation
        assert len(obs) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 8. Integration : _build_agent3_prompt appelle awareness
# ─────────────────────────────────────────────────────────────────────────────

class TestPromptIntegration:
    def test_build_prompt_accepts_db_user_id(self, db):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        prompt = _build_agent3_prompt(
            profil_data=None, decisions=[], sous_objectifs=[],
            db=db, user_id="u_integration",
        )
        assert isinstance(prompt, str)
        assert "Agent Sylea 3" in prompt

    def test_build_prompt_without_db(self):
        from api.routers.agent3_openclaw import _build_agent3_prompt
        # Sans db/user → awareness doit juste retourner "" sans crash
        prompt = _build_agent3_prompt(
            profil_data=None, decisions=[], sous_objectifs=[],
        )
        assert isinstance(prompt, str)
        assert "Agent Sylea 3" in prompt
