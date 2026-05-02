"""
Agent 3 — Compaction de contexte pour BrowserAgent.

Inspire ethiquement de la strategie compact de Claude Code :
quand l'historique de messages d'un agent grossit trop (cout token +
risque de derive), on resume les anciens tours en un bloc memoire.

Strategie :
  - On garde toujours les N derniers messages intacts (defaut 6).
  - Les messages plus anciens sont resumes via Haiku en un seul bloc
    "SOUVENIRS" qui remplace la section compactee.
  - Les images sont strippees lors de la compaction (trop couteuses).
  - On garde le premier message (la tache originale) intact si possible.

Limite budgetaire :
  - max_messages (defaut 18) : quand depasse, trigger compaction.
  - target_messages (defaut 8) : taille cible post-compaction.

Reimplementation Python from scratch, pas de code proprietaire.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("sylea.agent3.compaction")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 8D : observabilite compaction
# ─────────────────────────────────────────────────────────────────────────────

_compaction_metrics_lock = threading.Lock()
_compaction_metrics: dict[str, Any] = {
    "total_compactions": 0,
    "total_tokens_before": 0,
    "total_tokens_after": 0,
    "total_messages_before": 0,
    "total_messages_after": 0,
    "total_duration_s": 0.0,
    "failures": 0,
    "last_compaction_at": None,
    "by_user": {},  # user_id -> {count, tokens_saved, last_at}
}


def _record_compaction(
    user_id: str | None,
    *,
    tokens_before: int,
    tokens_after: int,
    messages_before: int,
    messages_after: int,
    duration_s: float,
    success: bool = True,
) -> None:
    """Enregistre une compaction pour metrics."""
    with _compaction_metrics_lock:
        _compaction_metrics["total_compactions"] += 1
        _compaction_metrics["total_tokens_before"] += tokens_before
        _compaction_metrics["total_tokens_after"] += tokens_after
        _compaction_metrics["total_messages_before"] += messages_before
        _compaction_metrics["total_messages_after"] += messages_after
        _compaction_metrics["total_duration_s"] += duration_s
        if not success:
            _compaction_metrics["failures"] += 1
        _compaction_metrics["last_compaction_at"] = time.time()

        if user_id:
            bucket = _compaction_metrics["by_user"].setdefault(
                user_id, {"count": 0, "tokens_saved": 0, "last_at": None},
            )
            bucket["count"] += 1
            bucket["tokens_saved"] += max(0, tokens_before - tokens_after)
            bucket["last_at"] = time.time()


def get_compaction_metrics() -> dict[str, Any]:
    """Snapshot des metrics (thread-safe copy)."""
    with _compaction_metrics_lock:
        total_before = _compaction_metrics["total_tokens_before"]
        total_after = _compaction_metrics["total_tokens_after"]
        saved = max(0, total_before - total_after)
        ratio = (total_after / total_before) if total_before > 0 else 1.0
        return {
            "total_compactions": _compaction_metrics["total_compactions"],
            "total_tokens_saved": saved,
            "compression_ratio": round(ratio, 3),
            "avg_duration_s": round(
                _compaction_metrics["total_duration_s"]
                / max(1, _compaction_metrics["total_compactions"]),
                3,
            ),
            "failures": _compaction_metrics["failures"],
            "last_compaction_at": _compaction_metrics["last_compaction_at"],
            "total_messages_before": _compaction_metrics["total_messages_before"],
            "total_messages_after": _compaction_metrics["total_messages_after"],
            "users_with_compactions": len(_compaction_metrics["by_user"]),
            "by_user": {
                u: dict(v) for u, v in _compaction_metrics["by_user"].items()
            },
        }


def reset_compaction_metrics() -> None:
    """Reset pour tests."""
    with _compaction_metrics_lock:
        _compaction_metrics["total_compactions"] = 0
        _compaction_metrics["total_tokens_before"] = 0
        _compaction_metrics["total_tokens_after"] = 0
        _compaction_metrics["total_messages_before"] = 0
        _compaction_metrics["total_messages_after"] = 0
        _compaction_metrics["total_duration_s"] = 0.0
        _compaction_metrics["failures"] = 0
        _compaction_metrics["last_compaction_at"] = None
        _compaction_metrics["by_user"] = {}


SUMMARIZATION_SYSTEM = """Tu resumes l'historique d'un agent qui navigue un site web.
Je te donne une suite d'echanges (actions effectuees, screenshots decrits, feedback).
Tu produis un resume factuel, en francais, sous forme de bullets courts.

REGLES :
1. Maximum 8 bullets, chacun une phrase courte.
2. Mentionne : URLs visitees, actions importantes accomplies, erreurs rencontrees,
   decisions prises, etat actuel apparent.
3. N'invente rien. Si l'info n'est pas claire, ne l'inclus pas.
4. Ne recopie pas de code, juste "code colle X chars" ou "code compile".
5. Pas de JSON, juste les bullets avec tirets '-'.

Commence par "HISTORIQUE CONDENSE :" puis les bullets."""


class ContextCompactor:
    """Compacte un historique de messages LLM quand il depasse un seuil.

    Usage :
        compactor = ContextCompactor(client)
        messages = await compactor.maybe_compact(messages)
    """

    def __init__(
        self,
        anthropic_client,
        model: str = "claude-haiku-4-5-20251001",
        max_messages: int = 18,
        target_messages: int = 8,
        keep_last: int = 6,
    ):
        self.client = anthropic_client
        self.model = model
        self.max_messages = max_messages
        self.target_messages = target_messages
        self.keep_last = keep_last

    async def maybe_compact(
        self, messages: list[dict], *, user_id: str | None = None,
    ) -> list[dict]:
        """Compacte si necessaire. Retourne la nouvelle liste.

        Non destructif : retourne messages inchange si sous le seuil.
        Enregistre des metrics (Phase 8D) quand une compaction a lieu.
        """
        if len(messages) <= self.max_messages:
            return messages

        logger.info(f"Compacting {len(messages)} messages -> target {self.target_messages}")
        tokens_before = estimate_tokens(messages)
        messages_before = len(messages)
        start = time.time()
        success = True
        try:
            new_messages = await self._compact(messages)
        except Exception as e:
            logger.exception(f"Compaction crashed : {e}")
            success = False
            new_messages = messages  # fallback : retourne inchange
        duration_s = time.time() - start
        tokens_after = estimate_tokens(new_messages) if success else tokens_before

        _record_compaction(
            user_id,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            messages_before=messages_before,
            messages_after=len(new_messages),
            duration_s=duration_s,
            success=success,
        )
        return new_messages

    async def _compact(self, messages: list[dict]) -> list[dict]:
        if len(messages) <= self.keep_last + 1:
            return messages  # Rien a compacter

        # On garde : le premier (tache initiale) + les keep_last derniers
        first = messages[0]
        last_segment = messages[-self.keep_last:]
        middle = messages[1:-self.keep_last] if len(messages) > self.keep_last + 1 else []

        if not middle:
            return messages

        summary_text = await self._summarize(middle)
        memory_block = {
            "role": "user",
            "content": [{
                "type": "text",
                "text": f"[MEMOIRE CONDENSEE DES {len(middle)} DERNIERS TOURS]\n{summary_text}\n"
                        f"(Reprends la tache en te basant sur ce souvenir + le dernier screenshot.)",
            }],
        }

        new_messages = [first, memory_block] + last_segment
        logger.info(f"Compacted: {len(messages)} -> {len(new_messages)} messages")
        return new_messages

    async def _summarize(self, messages: list[dict]) -> str:
        """Appelle Haiku pour resumer une tranche de messages."""
        transcript_lines: list[str] = []
        for m in messages:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text_parts = []
                for c in content:
                    if isinstance(c, dict):
                        if c.get("type") == "text":
                            text_parts.append(c.get("text", ""))
                        elif c.get("type") == "image":
                            text_parts.append("[screenshot]")
                text = " | ".join(text_parts)
            else:
                text = str(content)
            # Tronquer pour limiter le prompt
            if len(text) > 800:
                text = text[:800] + "..."
            transcript_lines.append(f"[{role}] {text}")
        transcript = "\n".join(transcript_lines)

        try:
            resp = await asyncio.to_thread(
                self.client.messages.create,
                model=self.model,
                max_tokens=600,
                system=[{
                    "type": "text",
                    "text": SUMMARIZATION_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{
                    "role": "user",
                    "content": f"Voici les echanges a resumer :\n\n{transcript}",
                }],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
            if not text:
                return "HISTORIQUE CONDENSE : (resume indisponible, tours omis)"
            return text
        except Exception as e:
            logger.warning(f"Summarization failed: {e}")
            # Fallback : liste brute tronquee
            lines = [f"- {l[:120]}" for l in transcript_lines[-5:]]
            return "HISTORIQUE CONDENSE :\n" + "\n".join(lines)


def estimate_tokens(messages: list[dict]) -> int:
    """Estimation rapide du cout token d'une conversation.

    Heuristique : ~4 chars per token for text, +350 for each image (low-detail).
    Pas precis, juste pour decider de compacter.
    """
    total_chars = 0
    n_images = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for c in content:
                if isinstance(c, dict):
                    if c.get("type") == "text":
                        total_chars += len(c.get("text", ""))
                    elif c.get("type") == "image":
                        n_images += 1
    return total_chars // 4 + n_images * 350
