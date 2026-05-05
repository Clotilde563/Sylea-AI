"""
Transcription service pour la feature "Ecoute active" (Sprint 2 cours
universite/prepa).

Wrapper sur faster-whisper (CTranslate2) avec :
  - Chargement paresseux du modele (1-3 GB selon taille, on ne charge
    qu'au 1er appel a transcribe()).
  - Singleton thread-safe : un seul modele en memoire pour toute l'app.
  - Forcage langue francaise par defaut (cours en France → minimise les
    faux positifs detection langue).
  - VAD activee : Whisper voice-activity-detection saute les silences,
    accelere de 30-50% sur les cours avec pauses.

Usage :
    from api.transcription import get_transcriber
    result = get_transcriber().transcribe("/path/to/chunk.wav")
    # → {"text": "...", "language": "fr", "duration_s": 30.0}

Modeles disponibles (FASTER_WHISPER_MODEL env var) :
    tiny     — 75MB,  rapide, qualite mediocre
    base     — 145MB, OK pour test
    small    — 480MB, bon equilibre (defaut)
    medium   — 1.5GB, prod prepa (vocabulaire technique)
    large-v3 — 3GB,   max accuracy
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional


# ── Singleton service ───────────────────────────────────────────────────────

_lock = threading.Lock()
_transcriber: Optional["Transcriber"] = None


def get_transcriber() -> "Transcriber":
    """Retourne le service singleton, en l'initialisant a la 1re demande."""
    global _transcriber
    if _transcriber is None:
        with _lock:
            if _transcriber is None:
                _transcriber = Transcriber()
    return _transcriber


def reset_transcriber() -> None:
    """Reset (utile dans les tests pour decoupler les fixtures)."""
    global _transcriber
    with _lock:
        _transcriber = None


# ── Service ────────────────────────────────────────────────────────────────

class Transcriber:
    """Wrapper paresseux sur faster_whisper.WhisperModel."""

    def __init__(self) -> None:
        self.model_name = os.environ.get("FASTER_WHISPER_MODEL", "small")
        self.device = os.environ.get("FASTER_WHISPER_DEVICE", "cpu")  # ou "cuda"
        self.compute_type = os.environ.get("FASTER_WHISPER_COMPUTE", "int8")
        self.default_language = os.environ.get("FASTER_WHISPER_LANG", "fr")
        self._model = None  # chargement paresseux

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        # Import paresseux : evite de charger faster_whisper au boot du serveur
        # si la feature n'est jamais utilisee (l'import seul est ~50ms).
        from faster_whisper import WhisperModel
        self._model = WhisperModel(
            self.model_name,
            device=self.device,
            compute_type=self.compute_type,
        )

    def transcribe(
        self,
        audio_path: str | Path,
        language: Optional[str] = None,
        beam_size: int = 5,
    ) -> dict:
        """Transcrit un fichier audio. Retourne {text, language, duration_s,
        segments}. `language` overrides la langue par defaut (utile pour les
        cours d'anglais).
        """
        self._ensure_loaded()
        assert self._model is not None  # type narrow

        lang = language if language is not None else self.default_language

        segments_iter, info = self._model.transcribe(
            str(audio_path),
            language=lang,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )

        segments = []
        full_text_parts = []
        for seg in segments_iter:
            segments.append({
                "start": float(seg.start),
                "end": float(seg.end),
                "text": seg.text.strip(),
            })
            full_text_parts.append(seg.text)

        full_text = " ".join(t.strip() for t in full_text_parts).strip()

        return {
            "text": full_text,
            "language": info.language,
            "language_probability": float(info.language_probability),
            "duration_s": float(info.duration),
            "segments": segments,
        }
