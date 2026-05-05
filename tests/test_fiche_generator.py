"""
Tests Sprint 3 Ecoute active — generation de fiche + export Anki.

Couvre :
  - Auto-detection de matiere (heuristique mots-cles)
  - generate_fiche() avec mock Claude + fallback sans cle API
  - extract_cards() pour Anki
  - build_apkg() ecriture du .apkg
  - Endpoints HTTP /api/lecture/generate-fiche et /export-anki
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_optional_user
from api.main import app


TEST_USER_ID = "test-user-fiche"


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
    """Force ANTHROPIC_API_KEY a vide pour s'assurer que le fallback se
    declenche sauf si on injecte un client_factory."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# ════════════════════════════════════════════════════════════════════════════
#  Auto-detection matiere
# ════════════════════════════════════════════════════════════════════════════

class TestDetectMatiere:
    def test_detects_maths_from_theoreme_keywords(self):
        from api.fiche_generator import detect_matiere
        text = (
            "Aujourd'hui on demontre le theoreme des accroissements finis. "
            "Cette demonstration utilise la derivee et la limite. "
            "Soit f une fonction continue et derivable sur l'intervalle."
        )
        assert detect_matiere(text) == "maths"

    def test_detects_physique_from_force_energie(self):
        from api.fiche_generator import detect_matiere
        text = (
            "On va etudier la force exercee sur la masse, l'energie cinetique, "
            "la vitesse acceleration et la loi de Newton. Circuit electrique "
            "avec courant et tension."
        )
        assert detect_matiere(text) == "physique"

    def test_detects_philo_from_authors_and_concepts(self):
        from api.fiche_generator import detect_matiere
        text = (
            "Pour Kant la liberte est centrale. La these de Hegel "
            "synthese et antithese dialectique. Conscience morale verite ethique."
        )
        assert detect_matiere(text) == "philo"

    def test_detects_histoire_from_war_and_dates(self):
        from api.fiche_generator import detect_matiere
        text = (
            "La Seconde Guerre mondiale a ete suivie par la guerre froide. "
            "La decolonisation et la chute des regimes. Le traite de Versailles. "
            "Napoleon et l'empire."
        )
        assert detect_matiere(text) == "histoire"

    def test_detects_ses(self):
        from api.fiche_generator import detect_matiere
        text = (
            "L'economie de marche avec offre et demande. "
            "Bourdieu sur la classe sociale et la mobilite sociale. "
            "Inflation, chomage, croissance, PIB. Politique publique."
        )
        assert detect_matiere(text) == "ses"

    def test_returns_anglais_when_language_is_en(self):
        from api.fiche_generator import detect_matiere
        # Meme avec un transcript francophone, language="en" force anglais
        assert detect_matiere("Test francais", language="en") == "anglais"

    def test_returns_autre_for_short_or_neutral_text(self):
        from api.fiche_generator import detect_matiere
        assert detect_matiere("") == "autre"
        assert detect_matiere("Bonjour, j'ai mange une pomme aujourd'hui.") == "autre"

    def test_returns_autre_when_below_threshold(self):
        """Un seul mot-cle isole ne doit pas suffire (seuil = 3 points)."""
        from api.fiche_generator import detect_matiere
        # "fonction" pese 1 point en maths -> en dessous du seuil
        assert detect_matiere("Cette fonction est utile.") == "autre"


# ════════════════════════════════════════════════════════════════════════════
#  generate_fiche()
# ════════════════════════════════════════════════════════════════════════════

class TestGenerateFiche:
    def test_returns_fallback_without_api_key(self):
        """Sans ANTHROPIC_API_KEY, on tombe sur le fallback heuristique."""
        from api.fiche_generator import generate_fiche
        result = generate_fiche(
            transcript="Le theoreme de Pythagore. Pour tout triangle rectangle, "
                       "le carre de l'hypotenuse est egal a la somme des carres des cotes.",
            titre="Pythagore",
        )
        assert result["fallback_used"] is True
        assert result["matiere"] == "maths"
        assert result["matiere_auto_detected"] is True
        assert "# Pythagore" in result["fiche_markdown"]
        assert "MODE DEGRADE" in result["fiche_markdown"].upper() or "degrade" in result["fiche_markdown"].lower()

    def test_uses_explicit_matiere_when_provided(self):
        from api.fiche_generator import generate_fiche
        # Transcript en philo, mais user force "maths"
        result = generate_fiche(
            transcript="Pour Kant la liberte est centrale.",
            matiere="maths",
        )
        assert result["matiere"] == "maths"
        assert result["matiere_auto_detected"] is False

    def test_auto_detects_when_matiere_is_autre(self):
        from api.fiche_generator import generate_fiche
        result = generate_fiche(
            transcript="Le theoreme des accroissements finis. "
                       "On utilise la derivee de la fonction continue.",
            matiere="autre",
        )
        assert result["matiere"] == "maths"
        assert result["matiere_auto_detected"] is True

    def test_uses_injected_client_factory(self):
        """Avec un client_factory mocke, on appelle Claude au lieu du fallback."""
        from api.fiche_generator import generate_fiche

        fake_response = MagicMock()
        fake_block = MagicMock()
        fake_block.text = "# Cours de maths\n\n## Theoreme\nEnonce..."
        fake_response.content = [fake_block]

        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_response

        result = generate_fiche(
            transcript="Le theoreme.",
            matiere="maths",
            titre="Test",
            _client_factory=lambda: fake_client,
        )
        assert result["fallback_used"] is False
        assert "# Cours de maths" in result["fiche_markdown"]

    def test_fallback_when_llm_returns_empty(self):
        from api.fiche_generator import generate_fiche

        fake_block = MagicMock()
        fake_block.text = ""
        fake_response = MagicMock()
        fake_response.content = [fake_block]
        fake_client = MagicMock()
        fake_client.messages.create.return_value = fake_response

        result = generate_fiche(
            transcript="Du contenu test.",
            matiere="maths",
            _client_factory=lambda: fake_client,
        )
        # Empty LLM response -> fallback
        assert result["fallback_used"] is True

    def test_fallback_when_llm_raises(self):
        from api.fiche_generator import generate_fiche
        fake_client = MagicMock()
        fake_client.messages.create.side_effect = RuntimeError("rate limit")

        result = generate_fiche(
            transcript="Contenu",
            matiere="philo",
            _client_factory=lambda: fake_client,
        )
        assert result["fallback_used"] is True


# ════════════════════════════════════════════════════════════════════════════
#  extract_cards()
# ════════════════════════════════════════════════════════════════════════════

class TestExtractCards:
    def test_extracts_definitions(self):
        from api.anki_export import extract_cards
        md = """# Cours
## Definitions
- **Limite** : valeur vers laquelle tend une fonction.
- **Continuite** : absence de saut dans le graphe.
"""
        cards = extract_cards(md)
        questions = [q for q, _ in cards]
        assert any("Limite" in q for q in questions)
        assert any("Continuite" in q for q in questions)

    def test_extracts_theoreme_blockquotes(self):
        from api.anki_export import extract_cards
        md = """## Theoremes
> **Theoreme 1** (Pythagore) — Dans un triangle rectangle, le carre de l'hypotenuse...

> **Loi de Newton** — F = ma.
"""
        cards = extract_cards(md)
        questions = [q for q, _ in cards]
        # Au moins un "Theoreme 1" et "Loi de Newton" doivent apparaitre
        joined = " ".join(questions)
        assert "Theoreme 1" in joined
        assert "Loi de Newton" in joined

    def test_extracts_a_retenir_bullets(self):
        from api.anki_export import extract_cards
        md = """## A retenir
- Toujours verifier le domaine de definition
- La derivee s'annule aux extrema
- L'integrale est l'aire sous la courbe
"""
        cards = extract_cards(md)
        # 3 bullets -> 3 cards
        assert len([c for c in cards if "Point" in c[0]]) == 3

    def test_fallback_to_h2_sections_when_no_explicit_card(self):
        from api.anki_export import extract_cards
        md = """## Section A
Du contenu sans bullets ni gras.
## Section B
Plus de contenu generique sans pattern explicite.
"""
        cards = extract_cards(md)
        questions = [q for q, _ in cards]
        assert any("Section A" in q for q in questions)
        assert any("Section B" in q for q in questions)

    def test_dedupes_cards(self):
        from api.anki_export import extract_cards
        md = """## Definitions
- **Terme** : meme definition.
- **Terme** : meme definition.
"""
        cards = extract_cards(md)
        # Doublons elimines
        assert len(cards) == 1


# ════════════════════════════════════════════════════════════════════════════
#  build_apkg()
# ════════════════════════════════════════════════════════════════════════════

class TestBuildApkg:
    def test_writes_valid_apkg_zip(self, tmp_path):
        from api.anki_export import build_apkg
        md = """# Cours test
## Definitions
- **Vitesse** : derivee de la position par rapport au temps.
- **Acceleration** : derivee de la vitesse.
"""
        out = tmp_path / "test.apkg"
        result = build_apkg(
            titre="Cinematique",
            matiere="physique",
            fiche_markdown=md,
            output_path=out,
        )
        assert result["ok"] is True
        assert result["card_count"] == 2
        assert out.exists()
        # .apkg = ZIP
        with zipfile.ZipFile(out) as z:
            names = z.namelist()
            # genanki ecrit collection.anki2 (sqlite db) + media
            assert any("anki" in n.lower() for n in names)

    def test_returns_error_when_no_cards(self, tmp_path):
        from api.anki_export import build_apkg
        out = tmp_path / "empty.apkg"
        result = build_apkg(
            titre="Vide",
            matiere="autre",
            fiche_markdown="# Juste un titre, rien d'autre",
            output_path=out,
        )
        assert result["ok"] is False
        assert result["error"] == "no_cards_extracted"

    def test_deck_id_is_stable_for_same_input(self, tmp_path):
        """Permet aux re-imports Anki de fusionner avec le deck existant."""
        from api.anki_export import build_apkg
        md = "## A retenir\n- Item de test\n"
        r1 = build_apkg("Titre", "maths", md, tmp_path / "a.apkg")
        r2 = build_apkg("Titre", "maths", md, tmp_path / "b.apkg")
        assert r1["deck_id"] == r2["deck_id"]


# ════════════════════════════════════════════════════════════════════════════
#  Endpoint POST /api/lecture/generate-fiche
# ════════════════════════════════════════════════════════════════════════════

class TestGenerateFicheEndpoint:
    def test_requires_auth(self, anon_client):
        r = anon_client.post(
            "/api/lecture/generate-fiche",
            json={"transcript": "test"},
        )
        assert r.json() == {"ok": False, "error": "auth_required"}

    def test_requires_transcript(self, auth_client):
        r = auth_client.post("/api/lecture/generate-fiche", json={})
        assert r.json()["ok"] is False
        assert r.json()["error"] == "transcript_required"

        r = auth_client.post("/api/lecture/generate-fiche", json={"transcript": "  "})
        assert r.json()["error"] == "transcript_required"

    def test_rejects_too_long_transcript(self, auth_client):
        r = auth_client.post(
            "/api/lecture/generate-fiche",
            json={"transcript": "x" * 200_001},
        )
        assert r.json()["error"] == "transcript_too_long"

    def test_returns_fiche_in_fallback_mode(self, auth_client):
        """Sans cle API, l'endpoint utilise le fallback heuristique."""
        r = auth_client.post(
            "/api/lecture/generate-fiche",
            json={
                "transcript": "Le theoreme de Pythagore est essentiel.",
                "titre": "Pythagore",
                "matiere": "maths",
                "formation": "MPSI",
            },
        )
        body = r.json()
        assert body["ok"] is True
        assert body["matiere"] == "maths"
        assert body["fallback_used"] is True
        assert "Pythagore" in body["fiche_markdown"]


# ════════════════════════════════════════════════════════════════════════════
#  Endpoint POST /api/lecture/export-anki
# ════════════════════════════════════════════════════════════════════════════

class TestExportAnkiEndpoint:
    def test_requires_auth(self, anon_client):
        r = anon_client.post(
            "/api/lecture/export-anki",
            json={"fiche_markdown": "## a\n- **t** : d"},
        )
        assert r.json()["error"] == "auth_required"

    def test_requires_markdown(self, auth_client):
        r = auth_client.post("/api/lecture/export-anki", json={})
        assert r.json()["error"] == "fiche_markdown_required"

    def test_returns_base64_apkg_with_cards(self, auth_client):
        import base64
        r = auth_client.post(
            "/api/lecture/export-anki",
            json={
                "fiche_markdown": (
                    "# Test\n## Definitions\n"
                    "- **Limite** : valeur vers laquelle tend une fonction.\n"
                    "- **Derivee** : taux de variation instantane.\n"
                ),
                "titre": "Test cinematique",
                "matiere": "maths",
            },
        )
        body = r.json()
        assert body["ok"] is True
        assert body["card_count"] == 2
        assert body["filename"].endswith(".apkg")
        assert body["size_bytes"] > 0
        # data_base64 doit decoder en ZIP
        raw = base64.b64decode(body["data_base64"])
        assert raw[:2] == b"PK"  # ZIP magic

    def test_handles_no_cards_extracted(self, auth_client):
        r = auth_client.post(
            "/api/lecture/export-anki",
            json={
                "fiche_markdown": "# Juste un titre",
                "titre": "Vide",
                "matiere": "autre",
            },
        )
        assert r.json()["ok"] is False
        assert r.json()["error"] == "no_cards_extracted"
