"""
SkillRegistry — Registre central des skills Agent 3.

Responsabilites :
  1. Enregistrer / decouvrir les skills (register, auto_discover)
  2. Trouver la meilleure skill pour une instruction (find_best)
  3. Generer le bloc system prompt listant les skills disponibles
  4. Lister / inspecter les skills (API REST)
"""

from __future__ import annotations

import logging
from typing import Optional

from api.agent3_skills.base import Skill, SkillResult, SkillContext

logger = logging.getLogger("sylea.agent3.skills")


class SkillRegistry:
    """Registre thread-safe des skills disponibles."""

    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """Enregistre une skill (ecrase si meme nom)."""
        self._skills[skill.name] = skill
        logger.info(f"Skill registered: {skill.name} ({skill.category})")

    def unregister(self, name: str) -> bool:
        """Desenregistre une skill. Retourne True si elle existait."""
        return self._skills.pop(name, None) is not None

    def get(self, name: str) -> Optional[Skill]:
        """Retourne la skill par nom exact."""
        return self._skills.get(name)

    def list_all(self) -> list[Skill]:
        """Retourne toutes les skills enregistrees."""
        return list(self._skills.values())

    def list_by_category(self, category: str) -> list[Skill]:
        """Retourne les skills d'une categorie donnee."""
        return [s for s in self._skills.values() if s.category == category]

    def find_best(self, text: str, min_score: float = 0.15) -> Optional[Skill]:
        """Trouve la skill la plus pertinente pour le texte donne.

        Retourne None si aucune skill ne depasse min_score.
        """
        best_skill = None
        best_score = 0.0
        for skill in self._skills.values():
            score = skill.matches(text)
            if score > best_score:
                best_score = score
                best_skill = skill
        if best_score >= min_score and best_skill is not None:
            return best_skill
        return None

    def find_all_matching(self, text: str, min_score: float = 0.1) -> list[tuple[Skill, float]]:
        """Retourne toutes les skills matchant, triees par score desc."""
        matches = []
        for skill in self._skills.values():
            score = skill.matches(text)
            if score >= min_score:
                matches.append((skill, score))
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches

    def build_prompt_block(self) -> str:
        """Genere le bloc a injecter dans le system prompt de l'agent."""
        if not self._skills:
            return ""
        lines = ["\n=== SKILLS DISPONIBLES ==="]
        lines.append("Tu peux utiliser ces skills specialisees via [ACTION:SKILL]{...}[/ACTION] :")
        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            lines.append(skill.to_prompt_block())
        lines.append("\nFormat d'invocation : [ACTION:SKILL]{\"skill\": \"nom_skill\", \"instruction\": \"...\"}[/ACTION]")
        return "\n".join(lines)

    def to_dict_list(self) -> list[dict]:
        """Serialise le registre pour l'API REST."""
        return [s.to_dict() for s in sorted(self._skills.values(), key=lambda s: s.name)]

    @property
    def count(self) -> int:
        return len(self._skills)

    def auto_discover(self) -> int:
        """Charge et enregistre automatiquement les skills built-in.

        Retourne le nombre de skills enregistrees.
        """
        count_before = self.count
        # Import lazy des skills built-in
        try:
            from api.agent3_skills.skill_web_search import WebSearchSkill
            self.register(WebSearchSkill())
        except Exception as e:
            logger.debug(f"Could not load WebSearchSkill: {e}")
        # NOTE: TradingAnalysisSkill + PineScriptSkill retires du auto-discover :
        # ils n'etaient presents que pour les tests initiaux de Computer Use (TradingView).
        # Les modules restent dans le repo pour reference ; pour les reactiver, decommenter.
        # try:
        #     from api.agent3_skills.skill_trading import TradingAnalysisSkill
        #     self.register(TradingAnalysisSkill())
        # except Exception as e:
        #     logger.debug(f"Could not load TradingAnalysisSkill: {e}")
        # try:
        #     from api.agent3_skills.skill_pine_script import PineScriptSkill
        #     self.register(PineScriptSkill())
        # except Exception as e:
        #     logger.debug(f"Could not load PineScriptSkill: {e}")
        try:
            from api.agent3_skills.skill_document import DocumentSkill
            self.register(DocumentSkill())
        except Exception as e:
            logger.debug(f"Could not load DocumentSkill: {e}")

        loaded = self.count - count_before
        logger.info(f"Auto-discovered {loaded} skills (total: {self.count})")
        return loaded


# ── Singleton ──

_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """Retourne le registre singleton. Auto-discover au premier appel."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
        _registry.auto_discover()
    return _registry
