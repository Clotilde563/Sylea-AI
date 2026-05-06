"""
Tests Sprint 3.2 Ecoute active — refonte du flux post-recording :
  - Endpoint /api/lecture/render-html (markdown -> HTML standalone)
  - Endpoint /api/lecture/generate-cards (LLM Q/A depuis transcript)
  - Endpoint /api/lecture/export-anki avec cards LLM en input
  - Filtre _is_garbage_card (rejette les paires antinomiques type
    "**Faute du salarie** : Fait non-fautif du salarie")
  - build_apkg_from_cards (build direct sans extraction markdown)

faster-whisper et anthropic mockes integralement, tests rapides.
"""

from __future__ import annotations

import zipfile
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_optional_user
from api.main import app


TEST_USER_ID = "test-user-3-2"


@pytest.fixture()
def auth_client():
    app.dependency_overrides[get_optional_user] = lambda: TEST_USER_ID
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def anon_client():
    app.dependency_overrides[get_optional_user] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_real_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/lecture/render-html
# ════════════════════════════════════════════════════════════════════════════

class TestRenderHtmlEndpoint:
    def test_requires_auth(self, anon_client):
        r = anon_client.post(
            "/api/lecture/render-html",
            json={"fiche_markdown": "# Test"},
        )
        assert r.json() == {"ok": False, "error": "auth_required"}

    def test_requires_markdown(self, auth_client):
        r = auth_client.post("/api/lecture/render-html", json={})
        assert r.json()["error"] == "fiche_markdown_required"

    def test_renders_basic_markdown(self, auth_client):
        r = auth_client.post(
            "/api/lecture/render-html",
            json={
                "fiche_markdown": "# Cours\n\n## Section\n\nUn **paragraphe**.",
                "titre": "Test cinematique",
                "matiere": "physique",
            },
        )
        body = r.json()
        assert body["ok"] is True
        html = body["html"]
        assert "<!DOCTYPE html>" in html
        assert "<h1>" in html and "Cours</h1>" in html
        assert "<h2>" in html and "Section</h2>" in html
        assert "<strong>paragraphe</strong>" in html
        # CSS embarque
        assert "<style>" in html
        # KaTeX inclus
        assert "katex" in html.lower()
        # Meta affichee
        assert "PHYSIQUE" in html

    def test_includes_session_meta(self, auth_client):
        r = auth_client.post(
            "/api/lecture/render-html",
            json={
                "fiche_markdown": "# X",
                "titre": "T",
                "matiere": "maths",
                "formation": "MPSI",
                "session_id": "lec_abc123",
                "matiere_auto_detected": True,
            },
        )
        html = r.json()["html"]
        assert "MATHS (auto-detect)" in html
        assert "MPSI" in html
        assert "lec_abc123" in html

    def test_html_is_safe_self_contained(self, auth_client):
        """Pas de includes locaux/JS suspects, juste CDN KaTeX."""
        r = auth_client.post(
            "/api/lecture/render-html",
            json={"fiche_markdown": "# Hello"},
        )
        html = r.json()["html"]
        # Le seul script externe doit etre KaTeX (CDN jsdelivr)
        assert "cdn.jsdelivr.net" in html
        # Pas de file:// ou autre protocole non-https
        assert "file://" not in html
        assert "javascript:" not in html.lower()


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/lecture/generate-cards
# ════════════════════════════════════════════════════════════════════════════

class TestGenerateCardsEndpoint:
    def test_requires_auth(self, anon_client):
        r = anon_client.post(
            "/api/lecture/generate-cards",
            json={"transcript": "test", "matiere": "maths"},
        )
        assert r.json() == {"ok": False, "error": "auth_required"}

    def test_requires_transcript(self, auth_client):
        r = auth_client.post("/api/lecture/generate-cards", json={})
        assert r.json()["error"] == "transcript_required"

    def test_rejects_too_long(self, auth_client):
        r = auth_client.post(
            "/api/lecture/generate-cards",
            json={"transcript": "x" * 200_001, "matiere": "maths"},
        )
        assert r.json()["error"] == "transcript_too_long"

    def test_returns_no_api_key_when_unset(self, auth_client):
        """Sans ANTHROPIC_API_KEY, retourne ok:true avec used_llm:false
        et cards vide (l'app frontend fallback sur extract_cards heuristique)."""
        r = auth_client.post(
            "/api/lecture/generate-cards",
            json={"transcript": "Le theoreme de Pythagore...", "matiere": "maths"},
        )
        body = r.json()
        assert body["ok"] is True
        assert body["used_llm"] is False
        assert body["cards"] == []
        assert body["error"] == "no_api_key"


class TestGenerateAnkiCardsService:
    """Tests directs du service generate_anki_cards()."""

    def test_returns_no_api_key_when_unset(self):
        from api.fiche_generator import generate_anki_cards
        result = generate_anki_cards(
            transcript="...",
            matiere="maths",
        )
        assert result == {"cards": [], "used_llm": False, "error": "no_api_key"}

    def test_uses_injected_client_factory(self):
        """Avec un mock client, parse le JSON et retourne les cards."""
        from api.fiche_generator import generate_anki_cards

        fake_block = MagicMock()
        fake_block.text = (
            '{"cards": ['
            '{"q": "Quel est le theoreme de Pythagore ?", "a": "Dans un triangle rectangle, $a^2+b^2=c^2$."},'
            '{"q": "Quand applique-t-on Pythagore ?", "a": "Triangle rectangle uniquement."}'
            ']}'
        )
        fake_resp = MagicMock()
        fake_resp.content = [fake_block]
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_resp

        result = generate_anki_cards(
            transcript="Pythagore...",
            matiere="maths",
            _client_factory=lambda: fake_client,
        )
        assert result["used_llm"] is True
        assert len(result["cards"]) == 2
        assert "Pythagore" in result["cards"][0]["q"]
        assert "$a^2" in result["cards"][0]["a"]

    def test_strips_markdown_code_fences(self):
        """Claude wrappe parfois sa reponse en ```json ... ```."""
        from api.fiche_generator import generate_anki_cards

        fake_block = MagicMock()
        fake_block.text = (
            '```json\n'
            '{"cards": [{"q": "Q1", "a": "A1"}]}\n'
            '```'
        )
        fake_resp = MagicMock()
        fake_resp.content = [fake_block]
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_resp

        result = generate_anki_cards(
            transcript="x", matiere="autre",
            _client_factory=lambda: fake_client,
        )
        assert len(result["cards"]) == 1
        assert result["cards"][0]["q"] == "Q1"

    def test_filters_invalid_cards(self):
        """q ou a vide -> filtre. Trop long -> filtre."""
        from api.fiche_generator import generate_anki_cards

        fake_block = MagicMock()
        fake_block.text = (
            '{"cards": ['
            '{"q": "OK", "a": "Reponse OK"},'
            '{"q": "", "a": "answer"},'                     # q vide
            '{"q": "Q", "a": ""},'                          # a vide
            '{"q": "x", "a": "' + "z" * 900 + '"},'         # a trop long
            '{"q": "valid2", "a": "answer2"}'
            ']}'
        )
        fake_resp = MagicMock()
        fake_resp.content = [fake_block]
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_resp

        result = generate_anki_cards(
            transcript="x", matiere="autre",
            _client_factory=lambda: fake_client,
        )
        # Seul "OK" et "valid2" passent
        questions = [c["q"] for c in result["cards"]]
        assert "OK" in questions
        assert "valid2" in questions
        assert "" not in questions
        assert "x" not in questions  # answer 900 chars

    def test_caps_at_50_cards(self):
        """Cap eleve a 50 (sprint 3.5) pour les longs cours denses,
        mais le prompt LLM pousse au minimum a 5 cartes qualitatives."""
        from api.fiche_generator import generate_anki_cards
        import json
        cards = [{"q": f"q{i}", "a": f"a{i}"} for i in range(80)]
        fake_block = MagicMock()
        fake_block.text = json.dumps({"cards": cards})
        fake_resp = MagicMock()
        fake_resp.content = [fake_block]
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_resp

        result = generate_anki_cards(
            transcript="x", matiere="autre",
            _client_factory=lambda: fake_client,
        )
        assert len(result["cards"]) == 50

    def test_accepts_low_count_when_content_sparse(self):
        """Si le LLM ne retourne que 3-4 cartes (transcript pauvre),
        on les accepte telles quelles — pas de remplissage artificiel."""
        from api.fiche_generator import generate_anki_cards
        import json
        cards = [{"q": f"q{i}", "a": f"answer {i}"} for i in range(3)]
        fake_block = MagicMock()
        fake_block.text = json.dumps({"cards": cards})
        fake_resp = MagicMock()
        fake_resp.content = [fake_block]
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_resp

        result = generate_anki_cards(
            transcript="x", matiere="autre",
            _client_factory=lambda: fake_client,
        )
        # Pas de minimum impose cote backend — le LLM est seul juge.
        assert len(result["cards"]) == 3

    def test_handles_invalid_json_gracefully(self):
        from api.fiche_generator import generate_anki_cards
        fake_block = MagicMock()
        fake_block.text = "not json at all"
        fake_resp = MagicMock()
        fake_resp.content = [fake_block]
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_resp

        result = generate_anki_cards(
            transcript="x", matiere="autre",
            _client_factory=lambda: fake_client,
        )
        assert result["used_llm"] is False
        assert "llm_failed" in (result["error"] or "")


# ════════════════════════════════════════════════════════════════════════════
#  Filtre _is_garbage_card
# ════════════════════════════════════════════════════════════════════════════

class TestGarbageCardFilter:
    def test_rejects_too_short_definition(self):
        from api.anki_export import _is_garbage_card
        assert _is_garbage_card("Loi", "ok") is True
        assert _is_garbage_card("Loi", "Une loi physique fondamentale.") is False

    def test_rejects_too_long_definition(self):
        from api.anki_export import _is_garbage_card
        long_def = "x" * 700
        assert _is_garbage_card("Term", long_def) is True

    def test_rejects_definition_that_is_just_another_bold_term(self):
        """Cas reel : '**Faute du salarie** : **Fait non-fautif du salarie**'
        -> la definition est juste un autre terme en gras, sans contenu."""
        from api.anki_export import _is_garbage_card
        assert _is_garbage_card("Faute du salarie", "**Fait non-fautif du salarie**") is True
        assert _is_garbage_card("Faute du salarie", "**Fait non-fautif du salarie**.") is True

    def test_rejects_titre_seul_sans_verbe(self):
        """Definition = phrase courte sans verbe, probablement un titre."""
        from api.anki_export import _is_garbage_card
        assert _is_garbage_card("Concept", "Quelque chose de tres important") is True

    def test_accepts_definition_with_verbe_etre(self):
        from api.anki_export import _is_garbage_card
        assert _is_garbage_card(
            "Limite",
            "La limite est la valeur vers laquelle tend une fonction.",
        ) is False

    def test_rejects_negation_of_term(self):
        """Anti-paradoxe : terme + meme racine prefixe non-/in/etc dans def."""
        from api.anki_export import _is_garbage_card
        assert _is_garbage_card("possible", "C'est impossible a realiser") is True
        assert _is_garbage_card("conscient", "Etre inconscient ne signifie rien") is True

    def test_rejects_theoreme_n_seul(self):
        from api.anki_export import _is_garbage_card
        assert _is_garbage_card("Theoreme 1", "Quelque chose existe ici aussi") is True
        assert _is_garbage_card("Loi 3", "Ceci est une loi avec contenu") is True


# ════════════════════════════════════════════════════════════════════════════
#  build_apkg_from_cards
# ════════════════════════════════════════════════════════════════════════════

class TestBuildApkgFromCards:
    def test_writes_valid_apkg(self, tmp_path):
        from api.anki_export import build_apkg_from_cards
        cards = [
            ("Quel est X ?", "Reponse X."),
            ("Comment fait-on Y ?", "On fait Z."),
        ]
        out = tmp_path / "deck.apkg"
        result = build_apkg_from_cards("Test", "maths", cards, out)
        assert result["ok"] is True
        assert result["card_count"] == 2
        assert out.exists()
        # ZIP magic
        assert out.read_bytes()[:2] == b"PK"
        with zipfile.ZipFile(out) as z:
            assert any("anki" in n.lower() for n in z.namelist())

    def test_returns_error_for_empty_list(self, tmp_path):
        from api.anki_export import build_apkg_from_cards
        result = build_apkg_from_cards("Test", "maths", [], tmp_path / "empty.apkg")
        assert result["ok"] is False
        assert result["error"] == "no_cards_extracted"

    def test_deck_id_stable(self, tmp_path):
        """Meme titre+matiere -> meme deck_id (re-imports fusionnent)."""
        from api.anki_export import build_apkg_from_cards
        cards = [("Q", "A")]
        r1 = build_apkg_from_cards("Test", "maths", cards, tmp_path / "1.apkg")
        r2 = build_apkg_from_cards("Test", "maths", cards, tmp_path / "2.apkg")
        assert r1["deck_id"] == r2["deck_id"]


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/lecture/export-anki avec cards LLM en input
# ════════════════════════════════════════════════════════════════════════════

class TestExportAnkiWithLlmCards:
    def test_accepts_explicit_cards_array(self, auth_client):
        import base64
        r = auth_client.post(
            "/api/lecture/export-anki",
            json={
                "cards": [
                    {"q": "Q1 ?", "a": "A1."},
                    {"q": "Q2 ?", "a": "A2."},
                    {"q": "Q3 ?", "a": "A3."},
                ],
                "titre": "Cours LLM",
                "matiere": "philo",
            },
        )
        body = r.json()
        assert body["ok"] is True
        assert body["card_count"] == 3
        # Decode b64 -> ZIP
        raw = base64.b64decode(body["data_base64"])
        assert raw[:2] == b"PK"

    def test_rejects_empty_cards_array(self, auth_client):
        r = auth_client.post(
            "/api/lecture/export-anki",
            json={"cards": [], "titre": "X", "matiere": "autre"},
        )
        # Sans cards ET sans fiche_markdown -> cards_or_fiche_required
        assert r.json()["error"] == "cards_or_fiche_required"

    def test_filters_invalid_cards_in_array(self, auth_client):
        r = auth_client.post(
            "/api/lecture/export-anki",
            json={
                "cards": [
                    {"q": "OK", "a": "valid"},
                    {"q": "", "a": "no q"},
                    {"q": "no a", "a": ""},
                    {"q": "OK2", "a": "valid2"},
                ],
                "titre": "T",
                "matiere": "autre",
            },
        )
        body = r.json()
        assert body["ok"] is True
        assert body["card_count"] == 2  # seuls OK + OK2

    def test_falls_back_to_fiche_markdown_when_no_cards(self, auth_client):
        """Si l'utilisateur ne fournit que fiche_markdown (pas de cards),
        on utilise extract_cards heuristique."""
        r = auth_client.post(
            "/api/lecture/export-anki",
            json={
                "fiche_markdown": (
                    "## Definitions\n"
                    "- **Limite** : la valeur vers laquelle tend la fonction.\n"
                    "- **Derivee** : le taux de variation instantane d'une fonction.\n"
                ),
                "titre": "T",
                "matiere": "maths",
            },
        )
        body = r.json()
        assert body["ok"] is True
        assert body["card_count"] >= 1
