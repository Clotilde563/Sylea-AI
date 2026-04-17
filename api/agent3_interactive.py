"""
Agent 3 — Interactive Correction.

Permet a l'utilisateur de CLIQUER sur une capture d'ecran live
pour corriger / guider l'agent. Le click est converti en coordonnees
relatives, puis envoye comme instruction de correction.

Inspire de l'interactive feedback de Claude Code Computer Use.

Workflow :
  1. L'agent prend un screenshot (Computer Use / Browser Agent)
  2. Le frontend affiche le screenshot avec un overlay cliquable
  3. L'utilisateur clique sur un element (ou dessine un rectangle)
  4. Le frontend envoie les coordonnees + annotation au backend
  5. Le backend construit une instruction de correction
  6. L'agent reprend avec le nouveau contexte

Types de corrections :
  - click_here     : "Clique ici" (coordonnees x, y)
  - select_region  : "Selectionne cette zone" (rect x1,y1,x2,y2)
  - annotate       : "Ce texte est incorrect" (zone + commentaire)
  - retry          : "Recommence cette etape"
  - skip           : "Ignore cette etape"
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("sylea.agent3.interactive")


class CorrectionType(str, Enum):
    CLICK_HERE = "click_here"
    SELECT_REGION = "select_region"
    ANNOTATE = "annotate"
    RETRY = "retry"
    SKIP = "skip"
    TEXT_INPUT = "text_input"


@dataclass
class ScreenRegion:
    """Region rectangulaire sur un screenshot (coordonnees normalisees 0-1)."""

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0

    # Coordonnees absolues (pixels) si resolution connue
    abs_x: int = 0
    abs_y: int = 0
    abs_width: int = 0
    abs_height: int = 0

    def to_dict(self) -> dict:
        return {
            "x": self.x, "y": self.y,
            "width": self.width, "height": self.height,
            "abs_x": self.abs_x, "abs_y": self.abs_y,
            "abs_width": self.abs_width, "abs_height": self.abs_height,
        }

    @classmethod
    def from_click(cls, x: float, y: float, abs_x: int = 0, abs_y: int = 0) -> ScreenRegion:
        """Region ponctuelle (click)."""
        return cls(x=x, y=y, width=0.01, height=0.01, abs_x=abs_x, abs_y=abs_y)

    @classmethod
    def from_rect(cls, x1: float, y1: float, x2: float, y2: float) -> ScreenRegion:
        return cls(
            x=min(x1, x2), y=min(y1, y2),
            width=abs(x2 - x1), height=abs(y2 - y1),
        )


@dataclass
class Correction:
    """Correction de l'utilisateur sur un screenshot."""

    id: str
    correction_type: CorrectionType
    region: Optional[ScreenRegion] = None
    text: str = ""                           # Commentaire / texte a taper
    screenshot_id: str = ""                  # ID du screenshot concerne
    session_id: str = ""                     # Session Computer Use / Browser Agent
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.correction_type.value,
            "region": self.region.to_dict() if self.region else None,
            "text": self.text,
            "screenshot_id": self.screenshot_id,
            "session_id": self.session_id,
        }

    def to_agent_instruction(self) -> str:
        """Convertit la correction en instruction textuelle pour l'agent."""
        if self.correction_type == CorrectionType.CLICK_HERE:
            if self.region:
                return (
                    f"L'utilisateur demande de CLIQUER aux coordonnees "
                    f"({self.region.abs_x}, {self.region.abs_y}) sur le screenshot. "
                    f"Utilise click a cette position exacte."
                )
            return "L'utilisateur demande de cliquer a un endroit specifique."

        elif self.correction_type == CorrectionType.SELECT_REGION:
            if self.region:
                return (
                    f"L'utilisateur a selectionne une zone sur le screenshot : "
                    f"position ({self.region.x:.2f}, {self.region.y:.2f}), "
                    f"taille ({self.region.width:.2f} x {self.region.height:.2f}). "
                    f"Concentre-toi sur cette zone."
                )
            return "L'utilisateur a selectionne une zone du screenshot."

        elif self.correction_type == CorrectionType.ANNOTATE:
            base = f"L'utilisateur a annote le screenshot"
            if self.region:
                base += f" (zone : {self.region.x:.2f},{self.region.y:.2f})"
            if self.text:
                base += f" avec le commentaire : \"{self.text}\""
            return base + ". Tiens-en compte pour la suite."

        elif self.correction_type == CorrectionType.TEXT_INPUT:
            return f"L'utilisateur veut que tu tapes le texte suivant : \"{self.text}\""

        elif self.correction_type == CorrectionType.RETRY:
            return "L'utilisateur demande de RECOMMENCER cette etape."

        elif self.correction_type == CorrectionType.SKIP:
            return "L'utilisateur demande de SAUTER cette etape et passer a la suivante."

        return f"Correction utilisateur : {self.correction_type.value} — {self.text}"


class InteractiveCorrectionManager:
    """Gere les corrections interactives pour une session."""

    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self._corrections: list[Correction] = []
        self._current_screenshot_id: str = ""
        self._screenshot_resolution: tuple[int, int] = (1280, 720)

    def set_screenshot(self, screenshot_id: str, width: int = 1280, height: int = 720):
        """Enregistre le screenshot actuel (pour les coordonnees)."""
        self._current_screenshot_id = screenshot_id
        self._screenshot_resolution = (width, height)

    def create_correction(
        self,
        correction_type: str,
        x: float = 0.0,
        y: float = 0.0,
        x2: float = 0.0,
        y2: float = 0.0,
        text: str = "",
    ) -> Correction:
        """Cree une correction a partir des donnees du frontend."""
        ct = CorrectionType(correction_type)
        cid = f"corr_{uuid.uuid4().hex[:8]}"
        w, h = self._screenshot_resolution

        region = None
        if ct in (CorrectionType.CLICK_HERE, CorrectionType.TEXT_INPUT):
            region = ScreenRegion.from_click(x, y, abs_x=int(x * w), abs_y=int(y * h))
        elif ct in (CorrectionType.SELECT_REGION, CorrectionType.ANNOTATE):
            region = ScreenRegion.from_rect(x, y, x2, y2)
            region.abs_x = int(min(x, x2) * w)
            region.abs_y = int(min(y, y2) * h)
            region.abs_width = int(abs(x2 - x) * w)
            region.abs_height = int(abs(y2 - y) * h)

        correction = Correction(
            id=cid,
            correction_type=ct,
            region=region,
            text=text,
            screenshot_id=self._current_screenshot_id,
            session_id=self.session_id,
        )
        self._corrections.append(correction)
        logger.info(f"Correction created: {cid} ({ct.value}) for session {self.session_id}")
        return correction

    def get_pending_instructions(self) -> list[str]:
        """Retourne les instructions non encore envoyees a l'agent."""
        return [c.to_agent_instruction() for c in self._corrections]

    def get_all(self) -> list[dict]:
        return [c.to_dict() for c in self._corrections]

    def clear(self):
        self._corrections.clear()

    @property
    def count(self) -> int:
        return len(self._corrections)


# ── Singleton registry ──

_managers: dict[str, InteractiveCorrectionManager] = {}


def get_correction_manager(session_id: str) -> InteractiveCorrectionManager:
    if session_id not in _managers:
        _managers[session_id] = InteractiveCorrectionManager(session_id)
    return _managers[session_id]


def remove_correction_manager(session_id: str):
    _managers.pop(session_id, None)
