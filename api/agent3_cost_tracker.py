"""
Agent 3 — Cost Tracker.

Traque les tokens consommes et le cout estime par session BrowserAgent.
Expose un snapshot via endpoint REST pour l'UI, et alerte l'utilisateur
quand un seuil est atteint.

Tarification indicative (avril 2025, USD/1M tokens) :
  - Sonnet 4  : input 3 / output 15 / cached-read 0.30
  - Haiku 4.5 : input 0.80 / output 4 / cached-read 0.08

Ajuste via ANTHROPIC_PRICING si besoin (fichier .env).

Reimplementation Python from scratch pour Sylea.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("sylea.agent3.cost_tracker")


# Tarifs par defaut (USD per million tokens)
DEFAULT_PRICING = {
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00, "cache_read": 0.08},
    # Fallback generique
    "_default": {"input": 3.00, "output": 15.00, "cache_read": 0.30},
}


@dataclass
class UsageSnapshot:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    calls: int = 0
    errors: int = 0
    estimated_usd: float = 0.0
    model_breakdown: dict[str, dict] = field(default_factory=dict)
    session_started_at: float = field(default_factory=time.time)
    last_call_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "calls": self.calls,
            "errors": self.errors,
            "estimated_usd": round(self.estimated_usd, 6),
            "model_breakdown": self.model_breakdown,
            "session_started_at": self.session_started_at,
            "last_call_at": self.last_call_at,
            "session_duration_seconds": int(time.time() - self.session_started_at),
        }


class CostTracker:
    """Tracker thread-safe pour une session user."""

    def __init__(self, user_id: str = "default", pricing: Optional[dict] = None):
        self.user_id = user_id
        self.pricing = pricing or DEFAULT_PRICING
        self.snapshot = UsageSnapshot()
        self._lock = threading.Lock()
        self._warned_thresholds: set[float] = set()

    def record(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
    ):
        """Enregistre l'usage d'un appel API."""
        with self._lock:
            self.snapshot.input_tokens += input_tokens
            self.snapshot.output_tokens += output_tokens
            self.snapshot.cache_read_tokens += cache_read_tokens
            self.snapshot.cache_creation_tokens += cache_creation_tokens
            self.snapshot.calls += 1
            self.snapshot.last_call_at = time.time()

            # Cout
            prices = self.pricing.get(model, self.pricing["_default"])
            usd = (
                input_tokens * prices["input"]
                + output_tokens * prices["output"]
                + cache_read_tokens * prices["cache_read"]
            ) / 1_000_000.0
            self.snapshot.estimated_usd += usd

            # Breakdown par modele
            mb = self.snapshot.model_breakdown.setdefault(model, {
                "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                "cache_creation_tokens": 0, "calls": 0, "usd": 0.0,
            })
            mb["input_tokens"] += input_tokens
            mb["output_tokens"] += output_tokens
            mb["cache_read_tokens"] += cache_read_tokens
            mb["cache_creation_tokens"] += cache_creation_tokens
            mb["calls"] += 1
            mb["usd"] = round(mb["usd"] + usd, 6)

    def record_error(self):
        with self._lock:
            self.snapshot.errors += 1

    def record_from_response(self, response: object, model: str = "") -> None:
        """Extrait les usage stats d'une reponse anthropic.Messages."""
        try:
            usage = getattr(response, "usage", None)
            if usage is None:
                return
            model_name = model or getattr(response, "model", "") or "_default"
            self.record(
                model=model_name,
                input_tokens=getattr(usage, "input_tokens", 0) or 0,
                output_tokens=getattr(usage, "output_tokens", 0) or 0,
                cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
                cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            )
        except Exception as e:
            logger.debug(f"record_from_response failed silently: {e}")

    def crossed_threshold(self, threshold_usd: float) -> bool:
        """True si on vient de franchir un seuil (une seule fois par seuil)."""
        with self._lock:
            if self.snapshot.estimated_usd >= threshold_usd and threshold_usd not in self._warned_thresholds:
                self._warned_thresholds.add(threshold_usd)
                return True
            return False

    def get(self) -> dict:
        with self._lock:
            return self.snapshot.to_dict()

    def reset(self):
        with self._lock:
            self.snapshot = UsageSnapshot()
            self._warned_thresholds.clear()


# ── Registry ──────────────────────────────────────────────────────────────────

_trackers: dict[str, CostTracker] = {}
_registry_lock = threading.Lock()


def get_cost_tracker(user_id: str = "default") -> CostTracker:
    with _registry_lock:
        if user_id not in _trackers:
            _trackers[user_id] = CostTracker(user_id=user_id)
        return _trackers[user_id]


def reset_cost_tracker(user_id: str = "default"):
    with _registry_lock:
        if user_id in _trackers:
            _trackers[user_id].reset()
