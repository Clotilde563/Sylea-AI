"""
Deep Research mode — sous-agent specialise dans la recherche profonde.

Reutilise l'infrastructure `AgenticLoop` existante avec un **prompt systeme
dedie research** et un sous-ensemble de tools (read-only + ingestion) + max_turns eleve.

Strategie du sous-agent :
  1. Plan : decompose la question user en 5-10 sous-questions
  2. Explore : pour chaque sous-question, SEARCH + WEB_FETCH les sources les + pertinentes
  3. Cross-reference : utilise SEMANTIC_SEARCH pour retrouver le contexte dans les docs ingeres
  4. Synthese : produit un rapport markdown structure avec citations

Sortie : rapport markdown + liste des sources consultees + cout total.

Budget cap : defaut $0.50, override possible jusqu'a $2.
Max iterations : defaut 10, cap 25.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("sylea.deep_research")


_RESEARCH_SYSTEM_PROMPT = """Tu es un AGENT DE RECHERCHE PROFONDE (Deep Research), sous-agent specialise de Sylea Agent 3.

Ta mission : effectuer une recherche exhaustive sur un sujet donne et produire un rapport structure avec citations.

**Methodologie OBLIGATOIRE** :
1. **PLAN** : au premier tour, decompose la question en 5-10 sous-questions precises. Liste-les en <plan>...</plan> dans ta reflexion.
2. **EXPLORE** : pour chaque sous-question, utilise SEARCH (moteur web) puis WEB_FETCH sur les 2-3 sources les plus pertinentes. Ingere automatiquement les contenus longs dans le RAG.
3. **CROSS-REFERENCE** : utilise SEMANTIC_SEARCH pour croiser les sources ingerees et verifier les faits.
4. **SYNTHESE** : quand tu as >= 10 sources consultees OU que tu n'apprends plus rien, produis le rapport final.

**Format du rapport final** (markdown strict) :
```
# [Titre du rapport]

## Synthese executive
[3-5 lignes : la reponse courte a la question user]

## Reponse detaillee
[Sections organisees par sous-question avec reponses factuelles]

## Points cles
- [Fact 1 avec source [1]]
- [Fact 2 avec source [2]]

## Divergences ou incertitudes
[Si les sources se contredisent, expose les divergences]

## Sources consultees
[1] Titre — URL — date de consultation
[2] Titre — URL — date de consultation
```

**Regles critiques** :
- JAMAIS inventer une source ou un fait. Si incertain, dis-le.
- TOUJOURS citer la source entre crochets [1] dans le texte.
- TOUJOURS consulter AU MOINS 5 sources distinctes avant de conclure.
- TOUJOURS croiser : si une info vient d'une seule source, le signaler.
- Si tu hallucines, tu seras penalise. La fiabilite > l'exhaustivite.
- Tu dois TERMINER par le rapport complet dans ta derniere reponse (pas un prochain tour).
"""


async def run_deep_research(
    query: str,
    *,
    max_iterations: int = 10,
    budget_usd: float = 0.50,
    db: Any = None,
    user_id: str | None = None,
    session_key: str | None = None,
) -> dict[str, Any]:
    """Lance un AgenticLoop enfant specialise research.

    Retourne : {markdown, iterations_used, sources_consulted, cost_usd, stop_reason}
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {
            "markdown": "Deep Research indisponible : ANTHROPIC_API_KEY non configuree.",
            "iterations_used": 0,
            "sources_consulted": [],
            "cost_usd": 0.0,
            "stop_reason": "no_api_key",
        }

    try:
        from anthropic import AsyncAnthropic
        from api.agent3_native_tools import AgenticLoop, build_tool_schemas
        from api.agent3_native_dispatcher import Agent3ActionDispatcher
    except Exception as e:
        return {
            "markdown": f"Deep Research indisponible : import error {e}",
            "iterations_used": 0,
            "sources_consulted": [],
            "cost_usd": 0.0,
            "stop_reason": "import_error",
        }

    # Tools autorises pour le sous-agent researcher :
    # uniquement read-only + generation locale + memory/semantic.
    child_actions = {
        "SEARCH", "X_SEARCH", "WEB_FETCH",
        "MEMORY", "MEMORY_SEARCH", "SEMANTIC_SEARCH",
        "FILE_READ",
        "PDF", "CODE", "CANVAS",
    }

    try:
        child_tools = build_tool_schemas(
            enabled_actions=child_actions,
            include_clawhub_skills=False,
            include_clawhub_meta_tools=False,
            include_openclaw_direct_tools=True,
            # Subset OpenClaw : moteurs de recherche uniquement + fetch
            enabled_openclaw_tools={
                "perplexity_search", "brave_search", "google_search",
                "tavily_search", "exa_search", "firecrawl",
            },
            auth_user_id=user_id,
        )
    except Exception as e:
        logger.warning(f"deep_research tools build failed: {e}")
        return {
            "markdown": f"Deep Research indisponible : tools build error {e}",
            "iterations_used": 0,
            "sources_consulted": [],
            "cost_usd": 0.0,
            "stop_reason": "tools_error",
        }

    child_executor = Agent3ActionDispatcher(db=db, user_id=user_id, session_key=session_key)
    child_client = AsyncAnthropic(api_key=api_key)

    # Sonnet pour la qualite de raisonnement (cout controle par budget_usd)
    child_loop = AgenticLoop(
        client=child_client,
        system_prompt=_RESEARCH_SYSTEM_PROMPT,
        tools=child_tools,
        executor=child_executor,
        model="claude-sonnet-4-6",
        max_turns=max_iterations,
        max_tokens=8000,  # plus genereux car rapport final peut etre long
        input_usd_per_mtok=3.0,
        output_usd_per_mtok=15.0,
        cost_hard_cap_usd=budget_usd,
        cache_tools=True,
        permission_mode="bypass",  # read-only, pas besoin de confirmation
    )

    sources_consulted: list[str] = []
    iterations_used = 0
    try:
        async for event in child_loop.run(query):
            if event.type == "turn_start":
                iterations_used = event.data.get("turn", iterations_used)
            elif event.type == "tool_use":
                tool_name = event.data.get("action_type", "")
                inp = event.data.get("input", {}) or {}
                if tool_name in ("SEARCH", "WEB_FETCH") or tool_name.lower().endswith("_search"):
                    if isinstance(inp, dict):
                        url = inp.get("url") or inp.get("query") or ""
                        if url:
                            sources_consulted.append(str(url)[:200])
    except Exception as e:
        logger.exception(f"Deep research child loop crashed: {e}")

    final_text = ""
    cost_usd = 0.0
    stop_reason = "unknown"
    if child_loop.result:
        final_text = child_loop.result.final_text or ""
        input_tok = child_loop.result.total_input_tokens or 0
        output_tok = child_loop.result.total_output_tokens or 0
        cost_usd = input_tok * 3.0 / 1_000_000.0 + output_tok * 15.0 / 1_000_000.0
        stop_reason = child_loop.result.stop_reason or "unknown"

    if not final_text:
        final_text = (
            f"# Rapport vide\n\nLa recherche profonde n'a pas produit de rapport. "
            f"Raison probable : {stop_reason}. Iterations : {iterations_used}."
        )

    return {
        "markdown": final_text,
        "iterations_used": iterations_used,
        "sources_consulted": sources_consulted[:30],
        "cost_usd": round(cost_usd, 4),
        "stop_reason": stop_reason,
    }


__all__ = ["run_deep_research"]
