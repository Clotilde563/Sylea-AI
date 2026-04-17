"""
Base class pour les Skills Agent 3.

Chaque skill herite de Skill et implemente :
  - name / description / triggers  (metadata)
  - execute(instruction, context)   (logique async)

Le resultat est toujours un SkillResult structure.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class SkillResult:
    """Resultat normalise retourne par chaque skill."""

    success: bool
    content: str = ""
    data: dict = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0
    skill_name: str = ""

    def to_dict(self) -> dict:
        out = {
            "success": self.success,
            "content": self.content,
            "skill_name": self.skill_name,
            "duration_ms": round(self.duration_ms, 1),
        }
        if self.data:
            out["data"] = self.data
        if self.error:
            out["error"] = self.error
        return out


@dataclass
class SkillContext:
    """Contexte passe a chaque skill lors de l'execution."""

    user_id: str = ""
    user_msg: str = ""
    profil: dict = field(default_factory=dict)
    memories: list[dict] = field(default_factory=list)
    session_key: str = ""
    extra: dict = field(default_factory=dict)


class Skill(ABC):
    """Classe de base pour toutes les skills Agent 3."""

    # ── Metadata (a surcharger) ──
    name: str = "base_skill"
    description: str = "Skill de base"
    category: str = "general"

    # Mots-cles / phrases qui declenchent cette skill
    triggers: list[str] = []

    # Outils OpenClaw requis (pour info)
    required_tools: list[str] = []

    # True = la skill fait des appels reseau / LLM
    is_async_heavy: bool = False

    @abstractmethod
    async def execute(
        self,
        instruction: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """Execute la skill et retourne un resultat structure."""
        ...

    async def safe_execute(
        self,
        instruction: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        """Wrapper avec timing + error handling."""
        t0 = time.perf_counter()
        try:
            result = await self.execute(instruction, context)
            result.duration_ms = (time.perf_counter() - t0) * 1000
            result.skill_name = self.name
            return result
        except Exception as e:
            return SkillResult(
                success=False,
                error=str(e),
                skill_name=self.name,
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

    def matches(self, text: str) -> float:
        """Score de correspondance (0.0–1.0) entre le texte et les triggers."""
        if not self.triggers:
            return 0.0
        text_low = text.lower()
        score = 0.0
        for trigger in self.triggers:
            trig_low = trigger.lower()
            if trig_low in text_low:
                # Plus le trigger est long, plus le match est fort
                score = max(score, min(1.0, len(trig_low) / 20.0))
        return score

    def to_prompt_block(self) -> str:
        """Formate la skill pour injection dans le system prompt."""
        triggers_str = ", ".join(self.triggers[:5]) if self.triggers else "(auto)"
        return (
            f"  - **{self.name}** : {self.description}\n"
            f"    Declencheurs : {triggers_str}\n"
            f"    Categorie : {self.category}"
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "triggers": self.triggers[:10],
            "required_tools": self.required_tools,
            "is_async_heavy": self.is_async_heavy,
        }
