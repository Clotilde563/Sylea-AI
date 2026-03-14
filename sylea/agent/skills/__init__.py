"""Skills de l'agent Syléa.AI."""

from sylea.agent.skills.email_skill import SkillEmail
from sylea.agent.skills.document_skill import SkillDocument
from sylea.agent.skills.research_skill import SkillRecherche
from sylea.agent.skills.calendar_skill import SkillCalendrier
from sylea.agent.skills.todo_skill import SkillTodo

__all__ = [
    "SkillEmail",
    "SkillDocument",
    "SkillRecherche",
    "SkillCalendrier",
    "SkillTodo",
]
