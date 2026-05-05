"""
Tests Sprint 2 Ecoute active — transcription incrementale (faster-whisper).

On mock entierement faster_whisper.WhisperModel pour eviter de charger le
modele (480MB+ download au 1er run, 5-30s d'init). Les tests verifient :
  - le endpoint POST /api/lecture/transcribe-chunk (auth, contract, cleanup)
  - le service api.transcription.Transcriber (lazy load, langue par defaut,
    forwarding des params)
  - le singleton get_transcriber() (un seul modele en memoire)
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.dependencies import get_optional_user
from api.main import app


TEST_USER_ID = "test-user-transcribe"


# ── Fixtures ────────────────────────────────────────────────────────────────

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
def _reset_transcriber():
    """Reset le singleton entre tests pour decoupler les fixtures."""
    from api import transcription as trx_mod
    trx_mod.reset_transcriber()
    yield
    trx_mod.reset_transcriber()


def _fake_wav_bytes() -> bytes:
    """Wrapper minimal d'un faux WAV — pas de vrai PCM, juste les bytes
    d'un fichier-like upload. faster-whisper est mocke donc le contenu n'est
    jamais decode."""
    return b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00" + b"\x00" * 64


def _make_segment(start: float, end: float, text: str):
    """Mimique l'objet Segment retourne par faster_whisper."""
    seg = MagicMock()
    seg.start = start
    seg.end = end
    seg.text = text
    return seg


# ════════════════════════════════════════════════════════════════════════════
#  POST /api/lecture/transcribe-chunk
# ════════════════════════════════════════════════════════════════════════════

def test_transcribe_requires_auth(anon_client):
    files = {"audio": ("chunk_0.wav", _fake_wav_bytes(), "audio/wav")}
    r = anon_client.post(
        "/api/lecture/transcribe-chunk",
        files=files,
        data={"session_id": "sess1", "chunk_index": 0},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": False, "error": "auth_required"}


def test_transcribe_returns_text_and_metadata(auth_client):
    fake_segments = [
        _make_segment(0.0, 1.5, " Bonjour la classe."),
        _make_segment(1.5, 3.2, " Aujourd'hui on va faire de la mecanique."),
    ]
    fake_info = MagicMock()
    fake_info.language = "fr"
    fake_info.language_probability = 0.99
    fake_info.duration = 3.2

    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter(fake_segments), fake_info)

    with patch("faster_whisper.WhisperModel", return_value=fake_model):
        files = {"audio": ("chunk_0.wav", _fake_wav_bytes(), "audio/wav")}
        r = auth_client.post(
            "/api/lecture/transcribe-chunk",
            files=files,
            data={"session_id": "sess1", "chunk_index": 0, "language": "fr"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["session_id"] == "sess1"
    assert body["chunk_index"] == 0
    assert body["text"] == "Bonjour la classe. Aujourd'hui on va faire de la mecanique."
    assert body["language"] == "fr"
    assert body["language_probability"] == pytest.approx(0.99)
    assert body["duration_s"] == pytest.approx(3.2)
    assert len(body["segments"]) == 2
    assert body["segments"][0] == {"start": 0.0, "end": 1.5, "text": "Bonjour la classe."}


def test_transcribe_forwards_language_override(auth_client):
    """Si language='en' est envoye (cours d'anglais), il doit etre passe a
    faster-whisper."""
    fake_info = MagicMock()
    fake_info.language = "en"
    fake_info.language_probability = 0.95
    fake_info.duration = 2.0

    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([_make_segment(0, 2, " Hello class.")]), fake_info)

    with patch("faster_whisper.WhisperModel", return_value=fake_model):
        files = {"audio": ("c.wav", _fake_wav_bytes(), "audio/wav")}
        r = auth_client.post(
            "/api/lecture/transcribe-chunk",
            files=files,
            data={"session_id": "x", "chunk_index": 0, "language": "en"},
        )
    body = r.json()
    assert body["language"] == "en"
    # Verifie que language="en" a bien ete passe au modele
    call_kwargs = fake_model.transcribe.call_args.kwargs
    assert call_kwargs["language"] == "en"


def test_transcribe_handles_whisper_error_gracefully(auth_client):
    fake_model = MagicMock()
    fake_model.transcribe.side_effect = RuntimeError("CUDA out of memory")

    with patch("faster_whisper.WhisperModel", return_value=fake_model):
        files = {"audio": ("c.wav", _fake_wav_bytes(), "audio/wav")}
        r = auth_client.post(
            "/api/lecture/transcribe-chunk",
            files=files,
            data={"session_id": "s", "chunk_index": 0},
        )
    body = r.json()
    assert body["ok"] is False
    assert "transcription_failed" in body["error"]
    assert "CUDA out of memory" in body["error"]


def test_transcribe_cleans_up_temp_file(auth_client, tmp_path, monkeypatch):
    """Apres un transcribe (succes ou echec), le fichier temp doit etre supprime
    (privacy : pas de WAV qui traine sur le serveur)."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    fake_info = MagicMock()
    fake_info.language = "fr"
    fake_info.language_probability = 0.9
    fake_info.duration = 1.0
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([_make_segment(0, 1, " test.")]), fake_info)

    with patch("faster_whisper.WhisperModel", return_value=fake_model):
        files = {"audio": ("c.wav", _fake_wav_bytes(), "audio/wav")}
        auth_client.post(
            "/api/lecture/transcribe-chunk",
            files=files,
            data={"session_id": "cleanup", "chunk_index": 0},
        )

    # Le dossier temp existe mais doit etre vide (pas de chunk_*.wav qui traine)
    user_dir = tmp_path / "sylea-lecture" / TEST_USER_ID
    assert user_dir.exists()
    leftover = list(user_dir.glob("chunk_*.wav"))
    assert leftover == [], f"Fichiers temp non nettoyes: {leftover}"


def test_transcribe_sanitises_session_id(auth_client, tmp_path, monkeypatch):
    """Un session_id avec / ou \\ ne doit pas creer de chemin parent (path
    traversal protection)."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    fake_info = MagicMock()
    fake_info.language = "fr"
    fake_info.language_probability = 0.9
    fake_info.duration = 1.0
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([_make_segment(0, 1, " ok")]), fake_info)

    with patch("faster_whisper.WhisperModel", return_value=fake_model):
        files = {"audio": ("c.wav", _fake_wav_bytes(), "audio/wav")}
        r = auth_client.post(
            "/api/lecture/transcribe-chunk",
            files=files,
            data={"session_id": "../../etc/passwd", "chunk_index": 0},
        )
    assert r.json()["ok"] is True
    user_dir = tmp_path / "sylea-lecture" / TEST_USER_ID
    # Aucun fichier ne doit etre cree au-dessus du user_dir
    suspicious = list((tmp_path).rglob("passwd*"))
    assert suspicious == []


def test_transcribe_user_isolation(tmp_path, monkeypatch):
    """Le dossier temp est par-user : pas de fuite entre users."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    fake_info = MagicMock()
    fake_info.language = "fr"
    fake_info.language_probability = 0.9
    fake_info.duration = 1.0
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([_make_segment(0, 1, " ok")]), fake_info)

    with patch("faster_whisper.WhisperModel", return_value=fake_model):
        # User A
        app.dependency_overrides[get_optional_user] = lambda: "user-alpha"
        ca = TestClient(app)
        files = {"audio": ("c.wav", _fake_wav_bytes(), "audio/wav")}
        ca.post("/api/lecture/transcribe-chunk", files=files,
                data={"session_id": "s", "chunk_index": 0})

        # User B
        app.dependency_overrides[get_optional_user] = lambda: "user-beta"
        cb = TestClient(app)
        files = {"audio": ("c.wav", _fake_wav_bytes(), "audio/wav")}
        cb.post("/api/lecture/transcribe-chunk", files=files,
                data={"session_id": "s", "chunk_index": 0})

    app.dependency_overrides.clear()

    # Les 2 dossiers user doivent exister, separes
    base = tmp_path / "sylea-lecture"
    assert (base / "user-alpha").exists()
    assert (base / "user-beta").exists()


# ════════════════════════════════════════════════════════════════════════════
#  Service api.transcription.Transcriber
# ════════════════════════════════════════════════════════════════════════════

def test_transcriber_lazy_loads_model():
    from api import transcription as trx_mod
    trx_mod.reset_transcriber()
    t = trx_mod.Transcriber()
    # Au constructeur, le modele n'est PAS encore charge
    assert t._model is None


def test_transcriber_singleton_returns_same_instance():
    from api import transcription as trx_mod
    trx_mod.reset_transcriber()
    a = trx_mod.get_transcriber()
    b = trx_mod.get_transcriber()
    assert a is b


def test_transcriber_uses_default_french_language():
    from api import transcription as trx_mod
    trx_mod.reset_transcriber()
    t = trx_mod.Transcriber()

    fake_info = MagicMock()
    fake_info.language = "fr"
    fake_info.language_probability = 0.9
    fake_info.duration = 1.0
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([_make_segment(0, 1, " salut")]), fake_info)
    t._model = fake_model

    t.transcribe("/tmp/doesnt-exist.wav")
    call_kwargs = fake_model.transcribe.call_args.kwargs
    assert call_kwargs["language"] == "fr", "default lang doit etre fr"
    assert call_kwargs["vad_filter"] is True, "VAD doit etre actif (skip silences)"


def test_transcriber_respects_explicit_language():
    from api import transcription as trx_mod
    trx_mod.reset_transcriber()
    t = trx_mod.Transcriber()

    fake_info = MagicMock()
    fake_info.language = "en"
    fake_info.language_probability = 0.9
    fake_info.duration = 1.0
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([_make_segment(0, 1, " hi")]), fake_info)
    t._model = fake_model

    t.transcribe("/tmp/x.wav", language="en")
    assert fake_model.transcribe.call_args.kwargs["language"] == "en"


def test_transcriber_concatenates_segments_with_spaces():
    from api import transcription as trx_mod
    trx_mod.reset_transcriber()
    t = trx_mod.Transcriber()

    fake_info = MagicMock()
    fake_info.language = "fr"
    fake_info.language_probability = 0.9
    fake_info.duration = 5.0
    fake_model = MagicMock()
    # Whisper retourne souvent un espace en debut de segment, on doit gerer
    fake_model.transcribe.return_value = (
        iter([
            _make_segment(0, 2, " Premier paragraphe."),
            _make_segment(2, 4, " Deuxieme paragraphe."),
        ]),
        fake_info,
    )
    t._model = fake_model

    out = t.transcribe("/tmp/x.wav")
    assert out["text"] == "Premier paragraphe. Deuxieme paragraphe."


def test_transcriber_returns_segments_array():
    from api import transcription as trx_mod
    trx_mod.reset_transcriber()
    t = trx_mod.Transcriber()

    fake_info = MagicMock()
    fake_info.language = "fr"
    fake_info.language_probability = 0.95
    fake_info.duration = 4.5
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (
        iter([
            _make_segment(0.0, 2.0, " A"),
            _make_segment(2.0, 4.5, " B"),
        ]),
        fake_info,
    )
    t._model = fake_model

    out = t.transcribe("/tmp/x.wav")
    assert out["segments"] == [
        {"start": 0.0, "end": 2.0, "text": "A"},
        {"start": 2.0, "end": 4.5, "text": "B"},
    ]
