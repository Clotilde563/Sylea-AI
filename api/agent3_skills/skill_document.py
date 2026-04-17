"""
Skill Document — Generation de documents structures (rapports, notes, plans).

Genere du contenu structure via Claude, formate pour le workspace.
Peut produire du Markdown, du texte brut ou du JSON structure.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from api.agent3_skills.base import Skill, SkillResult, SkillContext

logger = logging.getLogger("sylea.agent3.skills.document")


DOC_SYSTEM = """Tu es un redacteur professionnel. Tu generes des documents STRUCTURES, CLAIRS et ACTIONNABLES.

REGLES :
1. Structure avec des titres hierarchiques (##, ###)
2. Utilise des listes a puces pour les points cles
3. Sois concis mais complet
4. Adapte le ton au type de document :
   - Business plan : formel, chiffre, structure
   - Note perso : decontracte, bref
   - Rapport : detaille, factuel, sourced
   - Plan d'action : etapes numerotees, deadlines
5. Ecris en francais sauf si demande contraire
6. Maximum 800 mots sauf si un format plus long est demande

Format de sortie : Markdown
"""


DOC_TYPES = {
    "rapport": ("Rapport", ["resume", "contexte", "analyse", "conclusions", "recommandations"]),
    "plan": ("Plan d'action", ["objectif", "etapes", "ressources", "timeline", "risques"]),
    "note": ("Note", ["points_cles", "details", "prochaines_etapes"]),
    "business_plan": ("Business Plan", ["executive_summary", "marche", "proposition_valeur", "modele_economique", "financier", "timeline"]),
    "email": ("Email professionnel", ["objet", "corps", "appel_action"]),
    "presentation": ("Plan de presentation", ["titre", "slides", "messages_cles"]),
}


class DocumentSkill(Skill):
    name = "document"
    description = "Generation de documents structures : rapports, notes, plans, emails, presentations"
    category = "productivite"
    triggers = [
        "redige", "ecris", "genere un document", "rapport",
        "note", "business plan", "plan d'action",
        "email professionnel", "presentation", "memo",
        "synthese", "resume", "compte-rendu",
        "template", "modele", "brouillon",
        "document", "redaction",
    ]
    required_tools = []
    is_async_heavy = True

    def _detect_doc_type(self, instruction: str) -> str:
        """Detecte le type de document demande."""
        low = instruction.lower()
        keywords = {
            "rapport": ["rapport", "report", "compte-rendu", "compte rendu"],
            "plan": ["plan d'action", "plan action", "roadmap", "planning", "etapes"],
            "note": ["note", "memo", "synthese", "resume"],
            "business_plan": ["business plan", "plan business", "business model", "modele economique"],
            "email": ["email", "mail", "courriel", "courrier"],
            "presentation": ["presentation", "slides", "pitch", "deck"],
        }
        for doc_type, kws in keywords.items():
            if any(kw in low for kw in kws):
                return doc_type
        return "note"  # default

    async def execute(
        self,
        instruction: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        doc_type = self._detect_doc_type(instruction)
        doc_label, sections = DOC_TYPES.get(doc_type, ("Document", ["contenu"]))

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return SkillResult(
                success=False,
                error="Cle API Anthropic requise pour la generation de documents",
            )

        # Enrichir avec le profil utilisateur si dispo
        user_context = ""
        if context:
            if context.profil:
                nom = context.profil.get("nom", "")
                profession = context.profil.get("profession", "")
                if nom or profession:
                    user_context += f"\nAuteur : {nom} ({profession})"
            if context.memories:
                relevant = [
                    m for m in context.memories
                    if m.get("category") in ("pro", "preference", "entite")
                ][:5]
                if relevant:
                    user_context += "\nContexte utilisateur :\n" + "\n".join(
                        f"  - {m['key']}: {m['value']}" for m in relevant
                    )

        sections_hint = ", ".join(sections)
        user_prompt = (
            f"Type de document : {doc_label}\n"
            f"Sections suggerees : {sections_hint}\n"
            f"Demande : {instruction}"
            f"{user_context}\n\n"
            "Genere le document complet en Markdown."
        )

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            resp = await asyncio.to_thread(
                client.messages.create,
                model="claude-haiku-4-5-20251001",
                max_tokens=1500,
                system=[{
                    "type": "text",
                    "text": DOC_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_prompt}],
            )
            content = "".join(b.text for b in resp.content if hasattr(b, "text"))
        except Exception as e:
            return SkillResult(success=False, error=f"Generation echouee: {e}")

        # Extraire le titre du document
        title_match = re.match(r'^#\s+(.+)', content)
        title = title_match.group(1).strip() if title_match else doc_label

        # Compter les sections
        section_count = len(re.findall(r'^#{2,3}\s', content, re.MULTILINE))

        return SkillResult(
            success=True,
            content=content,
            data={
                "doc_type": doc_type,
                "title": title,
                "section_count": section_count,
                "word_count": len(content.split()),
                "format": "markdown",
            },
        )
