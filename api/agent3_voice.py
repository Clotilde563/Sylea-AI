"""
Agent 3 — Voice pipeline bidirectionnel (STT -> LLM -> TTS).

Anthropic n'expose pas encore d'API Realtime natif pour Claude. On utilise :
  - STT : OpenAI Whisper API (transcription audio -> texte)
  - LLM : Claude (via /chat/native existant)
  - TTS : OpenAI TTS-1 (deja en place dans _generate_tts_audio)

Mode actuel MVP :
  - Endpoint `/api/agent3/voice/transcribe` : audio upload -> texte
  - Endpoint `/api/agent3/voice/tts` : texte -> audio MP3 base64
  - Le client orchestre : record audio -> transcribe -> appelle /chat/native ->
    TTS chunks par phrase pendant le streaming

Futur (quand Anthropic Realtime dispo) : WebSocket full-duplex direct.

Securite :
  - Audio files max 25 Mo (limite Whisper)
  - Formats supportes : mp3, mp4, webm, wav, m4a
  - Cleanup automatique des uploads temp

Couts :
  - Whisper : $0.006 / minute audio
  - TTS-1 : $15 / 1M chars
  - Chiffre dans recorded dans external_cost si activated
"""

from __future__ import annotations

import base64
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("sylea.voice")


_WHISPER_MODEL = "whisper-1"
_TTS_MODEL = "tts-1"
_TTS_DEFAULT_VOICE = "nova"
_MAX_AUDIO_SIZE_BYTES = 25 * 1024 * 1024  # 25 Mo (limit Whisper)
_SUPPORTED_AUDIO_EXTS = {".mp3", ".mp4", ".webm", ".wav", ".m4a", ".ogg"}


# ─────────────────────────────────────────────────────────────────────────────
# STT : audio -> texte
# ─────────────────────────────────────────────────────────────────────────────

async def transcribe_audio(
    audio_bytes: bytes,
    *,
    filename: str = "audio.mp3",
    language: str = "fr",
) -> dict[str, Any]:
    """Transcrit un fichier audio via Whisper API.

    Retourne {text, duration_s, cost_usd, error}.
    """
    if not audio_bytes:
        return {"text": "", "error": "audio vide"}
    if len(audio_bytes) > _MAX_AUDIO_SIZE_BYTES:
        return {
            "text": "",
            "error": f"audio trop volumineux ({len(audio_bytes) / 1024 / 1024:.1f} Mo, max 25 Mo)",
        }
    ext = Path(filename).suffix.lower()
    if ext not in _SUPPORTED_AUDIO_EXTS:
        return {"text": "", "error": f"format non supporte : {ext}"}

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"text": "", "error": "OPENAI_API_KEY non configuree"}

    try:
        import httpx
    except ImportError:
        return {"text": "", "error": "httpx missing"}

    # Ecrit en tempo file (Whisper API multipart)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        async with httpx.AsyncClient(timeout=60.0) as client:
            files = {
                "file": (filename, open(tmp_path, "rb"), f"audio/{ext[1:]}"),
            }
            data = {
                "model": _WHISPER_MODEL,
                "language": language,
                "response_format": "json",
            }
            resp = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {api_key}"},
                files=files,
                data=data,
            )
            if resp.status_code != 200:
                return {
                    "text": "",
                    "error": f"Whisper API : HTTP {resp.status_code} {resp.text[:200]}",
                }
            result = resp.json()
            # Estimation cout : ~1min par 1MB MP3 (grossier)
            estimated_minutes = len(audio_bytes) / (1024 * 1024)
            cost_usd = estimated_minutes * 0.006
            return {
                "text": result.get("text", "").strip(),
                "cost_usd": round(cost_usd, 4),
                "estimated_minutes": round(estimated_minutes, 2),
            }
    except Exception as e:
        logger.exception(f"transcribe_audio crashed: {e}")
        return {"text": "", "error": f"{type(e).__name__}: {str(e)[:200]}"}
    finally:
        if tmp_path:
            try:
                Path(tmp_path).unlink()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# TTS : texte -> audio MP3
# ─────────────────────────────────────────────────────────────────────────────

async def synthesize_speech(
    text: str,
    *,
    voice: str = _TTS_DEFAULT_VOICE,
    speed: float = 1.0,
    return_base64: bool = True,
) -> dict[str, Any]:
    """Genere un audio TTS via OpenAI.

    Retourne {audio_b64 OR audio_bytes, format, chars, cost_usd, error}.
    """
    if not text or not text.strip():
        return {"error": "texte vide"}
    if len(text) > 4096:
        text = text[:4096]  # Cap Whisper/TTS

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"error": "OPENAI_API_KEY non configuree"}

    voice = voice if voice in ("alloy", "echo", "fable", "onyx", "nova", "shimmer") else _TTS_DEFAULT_VOICE
    speed = max(0.25, min(4.0, float(speed)))

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _TTS_MODEL,
                    "voice": voice,
                    "input": text,
                    "speed": speed,
                    "response_format": "mp3",
                },
            )
            if resp.status_code != 200:
                return {"error": f"TTS API HTTP {resp.status_code}"}
            audio_bytes = resp.content
            cost_usd = len(text) * 15.0 / 1_000_000.0
            out: dict[str, Any] = {
                "format": "mp3",
                "chars": len(text),
                "voice": voice,
                "cost_usd": round(cost_usd, 4),
            }
            if return_base64:
                out["audio_b64"] = base64.b64encode(audio_bytes).decode("ascii")
            else:
                out["audio_bytes"] = audio_bytes
            return out
    except Exception as e:
        logger.exception(f"synthesize_speech crashed: {e}")
        return {"error": f"{type(e).__name__}: {str(e)[:200]}"}


# ─────────────────────────────────────────────────────────────────────────────
# Sentence chunker pour streaming TTS (appele par /chat/native)
# ─────────────────────────────────────────────────────────────────────────────

_SENTENCE_END_PUNCT = ".!?"


def chunk_for_tts_stream(text: str, *, min_chars: int = 40) -> list[str]:
    """Decoupe un texte en phrases/chunks pour TTS streaming.

    Objectif : prononcer chaque phrase des qu'elle est complete,
    sans attendre tout le message. Retourne des chunks >=min_chars.
    """
    if not text:
        return []
    chunks: list[str] = []
    buf = ""
    i = 0
    while i < len(text):
        ch = text[i]
        buf += ch
        # Fin de phrase ?
        if ch in _SENTENCE_END_PUNCT and len(buf) >= min_chars:
            # Prochain char doit etre espace/newline/EOF
            if i + 1 >= len(text) or text[i + 1] in " \n\t":
                chunks.append(buf.strip())
                buf = ""
        i += 1
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


__all__ = [
    "transcribe_audio",
    "synthesize_speech",
    "chunk_for_tts_stream",
]
