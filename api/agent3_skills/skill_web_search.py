"""
Skill WebSearch — Recherche web en temps reel via OpenClaw.

Delegue la recherche a openclaw_web_search puis synthetise les resultats
via un appel Claude (Haiku) pour fournir une reponse concise.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from api.agent3_skills.base import Skill, SkillResult, SkillContext

logger = logging.getLogger("sylea.agent3.skills.web_search")


class WebSearchSkill(Skill):
    name = "web_search"
    description = "Recherche web en temps reel et synthese des resultats"
    category = "recherche"
    triggers = [
        "cherche", "recherche", "google", "search",
        "trouve-moi", "trouve moi", "c'est quoi",
        "quelle est", "quel est", "qui est",
        "actualites", "news", "derniere nouvelle",
        "cours de", "prix de", "combien coute",
    ]
    required_tools = ["web_search"]
    is_async_heavy = True

    async def execute(
        self,
        instruction: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        from api.openclaw_bridge import openclaw_web_search

        session_key = context.session_key if context else ""

        # 1. Lancer la recherche OpenClaw
        try:
            search_result = await openclaw_web_search(
                query=instruction,
                session_key=session_key,
                max_results=8,
            )
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Recherche echouee: {e}",
            )

        if not search_result.get("success"):
            return SkillResult(
                success=False,
                error=search_result.get("error", "Recherche sans resultat"),
            )

        results = search_result.get("results", [])
        if not results:
            return SkillResult(
                success=True,
                content="Aucun resultat pertinent trouve pour cette recherche.",
                data={"query": instruction, "count": 0},
            )

        # 2. Formater les resultats bruts
        formatted_results = []
        for i, r in enumerate(results[:8], 1):
            title = r.get("title", "Sans titre")
            url = r.get("url", "")
            snippet = r.get("snippet", r.get("description", ""))[:200]
            formatted_results.append(f"{i}. [{title}]({url})\n   {snippet}")

        results_text = "\n\n".join(formatted_results)

        # 3. Synthese via Haiku (optionnel — si cle dispo)
        summary = ""
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key and len(results) > 0:
            try:
                import anthropic
                client = anthropic.Anthropic(api_key=key)
                resp = await asyncio.to_thread(
                    client.messages.create,
                    model="claude-haiku-4-5-20251001",
                    max_tokens=400,
                    system=[{
                        "type": "text",
                        "text": "Tu synthetises des resultats de recherche web en 3-4 phrases claires et factuelles, en francais.",
                        "cache_control": {"type": "ephemeral"},
                    }],
                    messages=[{"role": "user", "content": f"Recherche: {instruction}\n\nResultats:\n{results_text}\n\nSynthese concise:"}],
                )
                summary = "".join(b.text for b in resp.content if hasattr(b, "text"))
            except Exception as e:
                logger.debug(f"WebSearch synthesis failed: {e}")

        content = summary if summary else results_text

        return SkillResult(
            success=True,
            content=content,
            data={
                "query": instruction,
                "count": len(results),
                "results": results[:8],
                "has_synthesis": bool(summary),
            },
        )
