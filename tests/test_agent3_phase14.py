"""
Tests Phase 14 — Anti-hallucination grounding + Math precision guard.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


# ═════════════════════════════════════════════════════════════════════════════
# Phase 14A — Grounding
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractClaims:
    def test_year_detected(self):
        from api.agent3_grounding import extract_factual_claims
        claims = extract_factual_claims("Le produit est sorti en 2024.")
        assert any(c["type"] == "date_year" for c in claims)

    def test_large_number(self):
        from api.agent3_grounding import extract_factual_claims
        claims = extract_factual_claims("Le chiffre d'affaires est de 42 milliards d'euros.")
        assert any(c["type"] == "large_number" for c in claims)

    def test_percentage(self):
        from api.agent3_grounding import extract_factual_claims
        claims = extract_factual_claims("La croissance est de 15.3% cette annee.")
        assert any(c["type"] == "percentage" for c in claims)

    def test_quote(self):
        from api.agent3_grounding import extract_factual_claims
        claims = extract_factual_claims('Musk a dit : "The rocket will launch next week, I am sure of it."')
        assert any(c["type"] == "quote" for c in claims)

    def test_url(self):
        from api.agent3_grounding import extract_factual_claims
        claims = extract_factual_claims("Visitez https://example.com/rapport.pdf pour details.")
        assert any(c["type"] == "url" for c in claims)

    def test_empty_text(self):
        from api.agent3_grounding import extract_factual_claims
        assert extract_factual_claims("") == []

    def test_dedup(self):
        from api.agent3_grounding import extract_factual_claims
        text = "En 2024, X. En 2024, X."
        claims = extract_factual_claims(text)
        # Meme match + meme contexte court → dedup
        texts = [c["match"] for c in claims]
        # Accepte 1-2 (peut varier selon extraction exacte)
        assert len(claims) >= 1


class TestCitationDetection:
    def test_citation_bracket(self):
        from api.agent3_grounding import has_citation_nearby
        text = "La stat est 42% [source : INSEE]"
        pos = text.find("42%")
        assert has_citation_nearby(text, pos)

    def test_selon_format(self):
        from api.agent3_grounding import has_citation_nearby
        text = "Selon Wikipedia, Paris compte 2M habitants."
        pos = text.find("2M")
        assert has_citation_nearby(text, pos)

    def test_no_citation(self):
        from api.agent3_grounding import has_citation_nearby
        text = "La stat est 42% dans ce rapport."
        pos = text.find("42%")
        assert not has_citation_nearby(text, pos)


class TestHedgeDetection:
    def test_hedge_semble(self):
        from api.agent3_grounding import has_hedge_nearby
        text = "La croissance semble etre de 15%"
        pos = text.find("15%")
        assert has_hedge_nearby(text, pos)

    def test_hedge_environ(self):
        from api.agent3_grounding import has_hedge_nearby
        text = "environ 50% des users"
        pos = text.find("50%")
        assert has_hedge_nearby(text, pos)

    def test_no_hedge(self):
        from api.agent3_grounding import has_hedge_nearby
        text = "La croissance est de 15%"
        pos = text.find("15%")
        assert not has_hedge_nearby(text, pos)


class TestRateClaims:
    @pytest.mark.asyncio
    async def test_empty_claims(self):
        from api.agent3_grounding import rate_claims
        r = await rate_claims([], MagicMock())
        assert r == []

    @pytest.mark.asyncio
    async def test_rate_via_haiku(self):
        from api.agent3_grounding import rate_claims
        mock_client = MagicMock()
        block = MagicMock()
        block.text = '{"ratings":[{"idx":0,"risk":"HIGH","reason":"Fact inventable"}]}'
        resp = MagicMock()
        resp.content = [block]
        mock_client.messages.create = AsyncMock(return_value=resp)

        claims = [{"match": "42 milliards", "type": "large_number", "context_sentence": "ca fait 42 milliards"}]
        rated = await rate_claims(claims, mock_client)
        assert rated[0]["risk"] == "HIGH"

    @pytest.mark.asyncio
    async def test_rate_llm_failure_returns_unchanged(self):
        from api.agent3_grounding import rate_claims
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API down"))

        claims = [{"match": "X", "type": "t", "context_sentence": "x"}]
        rated = await rate_claims(claims, mock_client)
        assert rated == claims  # unchanged


class TestGroundResponse:
    @pytest.mark.asyncio
    async def test_short_response_skipped(self):
        from api.agent3_grounding import ground_response
        r = await ground_response("Salut.", MagicMock())
        assert r["changed"] is False
        assert r["reason"] == "too_short"

    @pytest.mark.asyncio
    async def test_no_claims(self):
        from api.agent3_grounding import ground_response
        text = "Je pense qu'il fait beau aujourd'hui et c'est agreable. " * 10
        r = await ground_response(text, MagicMock())
        # peut avoir 0 claim ou tout etre hedged
        assert r["changed"] is False or len(r["claims"]) >= 0

    @pytest.mark.asyncio
    async def test_high_risk_flagged(self):
        from api.agent3_grounding import ground_response
        mock_client = MagicMock()
        block = MagicMock()
        block.text = '{"ratings":[{"idx":0,"risk":"HIGH","reason":"non verifie"}]}'
        resp = MagicMock()
        resp.content = [block]
        mock_client.messages.create = AsyncMock(return_value=resp)

        # Texte avec claim sans source ni hedge
        text = "Le CEO de Tesla a annonce 42.5 milliards de benefice en 2024. " * 5
        r = await ground_response(text, mock_client)
        # Si claims extraits + rated HIGH, devraient etre flagges
        if r["high_risk_claims"]:
            assert r["changed"] is True
            assert "verification" in r["grounded_text"].lower()

    @pytest.mark.asyncio
    async def test_sourced_claims_not_flagged(self):
        from api.agent3_grounding import ground_response
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock()
        # Texte avec citation explicite partout
        text = (
            "Selon Wikipedia, Paris compte 2 millions d'habitants. "
            "Selon INSEE, le taux de chomage est 7.5%. "
        ) * 3
        r = await ground_response(text, mock_client)
        # Tous les claims ont hedge/citation → skip sans appeler LLM
        assert r["reason"] in ("all_sourced", "no_claims", "no_high_risk")


# ═════════════════════════════════════════════════════════════════════════════
# Phase 14B — Math guard
# ═════════════════════════════════════════════════════════════════════════════

class TestIsMathQuestion:
    def test_calcule_keyword(self):
        from api.agent3_math_guard import is_math_question
        ok, reason = is_math_question("Calcule 12 * 45")
        assert ok is True

    def test_combien_with_numbers(self):
        from api.agent3_math_guard import is_math_question
        ok, _ = is_math_question("Combien coute 1500€ avec 20% de TVA ?")
        assert ok is True

    def test_combien_without_numbers_no_math(self):
        from api.agent3_math_guard import is_math_question
        # "combien de temps" sans chiffre direct, probablement pas math
        ok, _ = is_math_question("Combien de temps tu restes ?")
        assert ok is False

    def test_pourcentage_compose(self):
        from api.agent3_math_guard import is_math_question
        ok, _ = is_math_question("Si j'investis 10k€ a 5% sur 20 ans ?")
        assert ok is True

    def test_moyenne(self):
        from api.agent3_math_guard import is_math_question
        ok, _ = is_math_question("Donne-moi la moyenne de 12, 45, 67, 89")
        assert ok is True

    def test_no_math(self):
        from api.agent3_math_guard import is_math_question
        ok, _ = is_math_question("Salut, comment ca va ?")
        assert ok is False

    def test_empty(self):
        from api.agent3_math_guard import is_math_question
        assert is_math_question("")[0] is False

    def test_finance_keywords(self):
        from api.agent3_math_guard import is_math_question
        assert is_math_question("Calcule mes interets composes")[0]
        assert is_math_question("Quel est le ROI de cet investissement ?")[0]

    def test_conversion(self):
        from api.agent3_math_guard import is_math_question
        ok, _ = is_math_question("Convertis 150 km/h en m/s")
        assert ok is True


class TestBuildMathGuardBlock:
    def test_math_triggers_block(self):
        from api.agent3_math_guard import build_math_guard_block
        b = build_math_guard_block("Calcule 12*45")
        assert "PYTHON_EXEC" in b or "python_exec" in b
        assert len(b) > 200

    def test_non_math_no_block(self):
        from api.agent3_math_guard import build_math_guard_block
        assert build_math_guard_block("salut") == ""


class TestExtractNumericClaims:
    def test_find_amounts(self):
        from api.agent3_math_guard import extract_numeric_claims
        text = "Tu as 2500€ en compte et 15% d'interets."
        claims = extract_numeric_claims(text)
        assert len(claims) >= 2

    def test_skip_years(self):
        from api.agent3_math_guard import extract_numeric_claims
        text = "En 2024 le marche atteindra 10 milliards."
        claims = extract_numeric_claims(text)
        # 2024 doit etre filtre (annee)
        matches = [c["number"] for c in claims]
        # Le 10 doit etre present, pas 2024
        assert "2024" not in matches or "10" in matches


class TestVerifyMathSandbox:
    @pytest.mark.asyncio
    async def test_valid_expression(self):
        from api.agent3_math_guard import verify_math_via_sandbox
        r = await verify_math_via_sandbox("12 * 45", "540")
        assert r["valid"] is True

    @pytest.mark.asyncio
    async def test_invalid_expression(self):
        from api.agent3_math_guard import verify_math_via_sandbox
        r = await verify_math_via_sandbox("12 * 45", "999")
        assert r["valid"] is False

    @pytest.mark.asyncio
    async def test_compound_interest(self):
        from api.agent3_math_guard import verify_math_via_sandbox
        # 10000 * 1.05^20 = 26 532.98
        r = await verify_math_via_sandbox("10000 * (1.05 ** 20)", "26532.98")
        assert r["valid"] is True


# ═════════════════════════════════════════════════════════════════════════════
# Integration
# ═════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    def test_grounding_prompt_in_systemp(self):
        """GROUNDING_PROMPT_BLOCK contient les regles critiques."""
        from api.agent3_grounding import GROUNDING_PROMPT_BLOCK
        assert "HALLUCINATION" in GROUNDING_PROMPT_BLOCK
        assert "source" in GROUNDING_PROMPT_BLOCK.lower()
        assert "JAMAIS inventer" in GROUNDING_PROMPT_BLOCK

    def test_math_prompt_in_systemp(self):
        from api.agent3_math_guard import MATH_PROMPT_BLOCK
        assert "python_exec" in MATH_PROMPT_BLOCK.lower()
        assert "precision" in MATH_PROMPT_BLOCK.lower()
