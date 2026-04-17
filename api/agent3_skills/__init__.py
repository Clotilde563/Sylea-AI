"""
Agent 3 Skills — systeme modulaire de competences specialisees.

Chaque skill est un module autonome qui :
  1. Declare ses capacites (description, exemples de triggers)
  2. S'enregistre dans le SkillRegistry
  3. Peut etre invoquee par l'agent via son identifiant
  4. Retourne un resultat structure (SkillResult)

Inspire de l'architecture Skills de Claude Code, reimplemente from scratch.
"""

from api.agent3_skills.base import Skill, SkillResult
from api.agent3_skills.registry import SkillRegistry, get_skill_registry

__all__ = ["Skill", "SkillResult", "SkillRegistry", "get_skill_registry"]
