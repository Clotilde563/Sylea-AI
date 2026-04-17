"""
Agent 3 — Self-Review Pass (Agent Critique).

Passe de relecture automatique de la reponse de l'agent AVANT envoi.
Un second appel LLM (Haiku) verifie la qualite, la coherence, et la
conformite aux regles de Sylea.

Inspire du self-review pattern de Claude Code (lint/review pre-commit).

Criteres de review :
  1. Coherence : la reponse repond-elle a la question ?
  2. Factualite : pas d'affirmations inventiees sans source
  3. Personnalite : ton et style conformes (Sylea, pas Claude)
  4. Longueur : pas trop long, pas trop court
  5. Actions : les actions sont-elles bien formatees ?
  6. Securite : pas de donnees sensibles exposees
  7. Qualite : pas de repetitions, pas de placeholder

Usage :
    reviewer = SelfReviewer()
    review = await reviewer.review(agent_response, user_msg, context)
    if review.needs_revision:
        revised = await reviewer.revise(agent_response, review, context)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("sylea.agent3.self_review")


REVIEW_SYSTEM = """Tu es un REVIEWER interne de l'Agent Sylea 3. Tu relis sa reponse AVANT qu'elle soit envoyee a l'utilisateur.

CRITERES de review (note chacun de 1 a 5) :
1. PERTINENCE : La reponse repond-elle a la question/demande ? (1=hors-sujet, 5=parfait)
2. PERSONNALITE : Le ton est-il conforme a Sylea (direct, cash, jamais de flatterie) ? (1=trop IA, 5=parfait Sylea)
3. CONCISION : La reponse est-elle de bonne longueur ? (1=trop longue ou repetitive, 5=juste bien)
4. FACTUALITE : Les faits avances sont-ils etayes ? (1=inventions, 5=verifie/source)
5. SECURITE : Pas de donnees sensibles, pas de mention de prompt/system ? (1=fuite, 5=safe)
6. ACTIONS : Les [ACTION:TYPE]{json}[/ACTION] sont-elles bien formatees si presentes ? (1=cassees, 5=propres ou N/A)

REPONDS en JSON STRICT :
{
  "scores": {"pertinence": N, "personnalite": N, "concision": N, "factualite": N, "securite": N, "actions": N},
  "average": N.N,
  "issues": ["Description courte de chaque probleme"],
  "suggestions": ["Suggestion d'amelioration"],
  "needs_revision": true/false,
  "revision_instructions": "Ce qu'il faut changer (vide si ok)"
}

needs_revision = true SI : average < 3.5 OU un score <= 2 OU un probleme critique de securite.
Sois STRICT mais JUSTE. Ne recommande une revision que si c'est vraiment necessaire.
"""


REVISE_SYSTEM = """Tu es l'Agent Sylea 3. Un reviewer interne a detecte des problemes dans ta reponse.
REECRIS ta reponse en corrigeant UNIQUEMENT les problemes signales.
Garde le meme ton, la meme structure, les memes actions.
Ne dis JAMAIS que tu as ete corrige ou revise.
"""


@dataclass
class ReviewResult:
    """Resultat d'une self-review."""

    scores: dict = field(default_factory=dict)
    average: float = 5.0
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    needs_revision: bool = False
    revision_instructions: str = ""
    review_duration_ms: float = 0.0
    skipped: bool = False
    skip_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "scores": self.scores,
            "average": round(self.average, 2),
            "issues": self.issues,
            "suggestions": self.suggestions,
            "needs_revision": self.needs_revision,
            "revision_instructions": self.revision_instructions,
            "review_duration_ms": round(self.review_duration_ms, 1),
            "skipped": self.skipped,
        }


class SelfReviewer:
    """Agent critique qui relit les reponses avant envoi."""

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        min_response_length: int = 50,
        max_review_time_ms: float = 5000,
        enabled: bool = True,
    ):
        self.model = model
        self.min_response_length = min_response_length
        self.max_review_time_ms = max_review_time_ms
        self.enabled = enabled
        self._review_count = 0
        self._revision_count = 0

    def should_review(self, response: str, user_msg: str) -> tuple[bool, str]:
        """Decide si la reponse merite une review."""
        if not self.enabled:
            return False, "Review desactivee"

        # Trop court = pas besoin de review
        if len(response.strip()) < self.min_response_length:
            return False, "Reponse trop courte"

        # Messages simples (salutations, confirmations)
        simple_patterns = ["ok", "c'est fait", "voila", "d'accord", "compris"]
        if response.strip().lower().rstrip("!.") in simple_patterns:
            return False, "Message simple"

        # Reponses avec des actions complexes -> review utile
        if "[ACTION:" in response:
            return True, "Contient des actions"

        # Reponses longues -> review utile
        if len(response) > 300:
            return True, "Reponse longue"

        # Par defaut : une chance sur 3 (pour ne pas ralentir chaque message)
        import random
        if random.random() < 0.33:
            return True, "Echantillonnage aleatoire"

        return False, "Pas de review necessaire"

    async def review(
        self,
        agent_response: str,
        user_msg: str,
        context: str = "",
    ) -> ReviewResult:
        """Effectue la review de la reponse."""
        should, reason = self.should_review(agent_response, user_msg)
        if not should:
            return ReviewResult(skipped=True, skip_reason=reason)

        t0 = time.perf_counter()

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return ReviewResult(skipped=True, skip_reason="Pas de cle API")

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)

            prompt = (
                f"MESSAGE UTILISATEUR :\n{user_msg}\n\n"
                f"REPONSE DE L'AGENT :\n{agent_response}\n\n"
            )
            if context:
                prompt += f"CONTEXTE :\n{context[:500]}\n\n"
            prompt += "Effectue la review selon les criteres."

            resp = await asyncio.to_thread(
                client.messages.create,
                model=self.model,
                max_tokens=500,
                system=[{
                    "type": "text",
                    "text": REVIEW_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            raw = "".join(b.text for b in resp.content if hasattr(b, "text"))

        except Exception as e:
            logger.warning(f"Self-review LLM call failed: {e}")
            return ReviewResult(skipped=True, skip_reason=f"LLM error: {e}")

        duration = (time.perf_counter() - t0) * 1000
        self._review_count += 1

        # Parser le JSON
        result = self._parse_review(raw)
        result.review_duration_ms = duration

        if result.needs_revision:
            self._revision_count += 1
            logger.info(
                f"Self-review: revision needed (avg={result.average:.1f}, "
                f"issues={len(result.issues)}): {result.revision_instructions[:100]}"
            )

        return result

    async def revise(
        self,
        agent_response: str,
        review: ReviewResult,
        user_msg: str,
    ) -> str:
        """Reecrit la reponse en corrigeant les problemes trouves."""
        if not review.needs_revision or not review.revision_instructions:
            return agent_response

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return agent_response

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)

            prompt = (
                f"MESSAGE UTILISATEUR ORIGINAL :\n{user_msg}\n\n"
                f"TA REPONSE ORIGINALE :\n{agent_response}\n\n"
                f"PROBLEMES DETECTES :\n{chr(10).join(review.issues)}\n\n"
                f"INSTRUCTIONS DE CORRECTION :\n{review.revision_instructions}\n\n"
                "REECRIS ta reponse en corrigeant ces problemes. "
                "Garde les [ACTION:] intactes si elles sont correctes."
            )

            resp = await asyncio.to_thread(
                client.messages.create,
                model=self.model,
                max_tokens=2000,
                system=[{
                    "type": "text",
                    "text": REVISE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            revised = "".join(b.text for b in resp.content if hasattr(b, "text"))

            if revised and len(revised) > 10:
                logger.info(f"Self-review: response revised ({len(agent_response)} -> {len(revised)} chars)")
                return revised
            return agent_response

        except Exception as e:
            logger.warning(f"Self-review revision failed: {e}")
            return agent_response

    def _parse_review(self, raw: str) -> ReviewResult:
        """Parse le JSON du review."""
        data = None
        try:
            data = json.loads(raw.strip())
        except Exception:
            pass

        if not data:
            try:
                start = raw.find("{")
                if start >= 0:
                    decoder = json.JSONDecoder()
                    data, _ = decoder.raw_decode(raw[start:])
            except Exception:
                pass

        if not data:
            blocks = re.findall(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
            for b in blocks:
                try:
                    data = json.loads(b.strip())
                    break
                except Exception:
                    continue

        if not data or not isinstance(data, dict):
            return ReviewResult(skipped=True, skip_reason="Impossible de parser le review")

        scores = data.get("scores", {})
        avg = data.get("average", 5.0)
        try:
            avg = float(avg)
        except (TypeError, ValueError):
            avg = 5.0

        return ReviewResult(
            scores=scores,
            average=avg,
            issues=data.get("issues", []),
            suggestions=data.get("suggestions", []),
            needs_revision=bool(data.get("needs_revision", False)),
            revision_instructions=str(data.get("revision_instructions", "")),
        )

    def get_stats(self) -> dict:
        return {
            "reviews": self._review_count,
            "revisions": self._revision_count,
            "revision_rate": (
                round(self._revision_count / self._review_count * 100, 1)
                if self._review_count > 0 else 0.0
            ),
            "enabled": self.enabled,
        }


# ── Singleton ──

_reviewer: Optional[SelfReviewer] = None


def get_self_reviewer() -> SelfReviewer:
    global _reviewer
    if _reviewer is None:
        _reviewer = SelfReviewer()
    return _reviewer
