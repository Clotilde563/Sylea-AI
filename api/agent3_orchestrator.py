"""
Agent 3 — Sub-Agent Orchestrator.

Orchestre des sous-agents locaux (pas OpenClaw) pour les taches complexes :
  1. Isolation : chaque sous-agent a son propre contexte, pas d'etat partage
  2. Budget : chaque sous-agent a un token/cost budget via CostTracker
  3. Resultat structure : {status, summary, data, cost_usd, tokens, duration_s}
  4. Timeout : annulation automatique apres N secondes

Inspire de AgentTool / TaskCreate de Claude Code, reimplemente from scratch.

Usage :
    orchestrator = SubAgentOrchestrator()
    result = await orchestrator.spawn(
        task="Analyse le cours du BTC cette semaine",
        agent_type="analyst",
        budget_usd=0.05,
        timeout_s=60,
    )
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from api.agent3_cost_tracker import CostTracker, get_cost_tracker

logger = logging.getLogger("sylea.agent3.orchestrator")


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    BUDGET_EXCEEDED = "budget_exceeded"


@dataclass
class SubAgentResult:
    """Resultat structure d'un sous-agent."""

    agent_id: str
    agent_type: str
    status: AgentStatus
    summary: str = ""
    data: dict = field(default_factory=dict)
    error: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_s: float = 0.0
    task: str = ""

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "status": self.status.value,
            "summary": self.summary,
            "data": self.data,
            "error": self.error,
            "cost_usd": round(self.cost_usd, 6),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "duration_s": round(self.duration_s, 2),
            "task": self.task[:200],
        }


# ── Agent types et system prompts ──

AGENT_TYPES = {
    "analyst": {
        "description": "Analyste — recherche, synthese, rapport",
        "system": (
            "Tu es un analyste expert. Tu recois une tache de recherche ou d'analyse. "
            "Tu dois fournir une reponse factuelle, structuree, avec des sources quand possible. "
            "Reponds en francais. Sois concis (max 400 mots)."
        ),
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 800,
    },
    "coder": {
        "description": "Codeur — generation, review, debug de code",
        "system": (
            "Tu es un developpeur senior. Tu recois une tache de code (generation, review, debug). "
            "Tu produis du code PROPRE, COMMENTE, FONCTIONNEL. "
            "Si c'est un review, pointe les problemes specifiques avec des suggestions concretes."
        ),
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1500,
    },
    "writer": {
        "description": "Redacteur — documents, emails, contenus",
        "system": (
            "Tu es un redacteur professionnel. Tu recois une tache de redaction. "
            "Tu produis un document structure, clair, avec le bon ton et le bon format. "
            "Ecris en francais sauf si demande contraire."
        ),
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1200,
    },
    "planner": {
        "description": "Planificateur — decomposition de taches, roadmaps",
        "system": (
            "Tu es un chef de projet expert. Tu recois un objectif complexe et tu le decomposes "
            "en etapes concretes, actionnables, avec des estimations de temps. "
            "Formate ta reponse en JSON : {\"steps\": [{\"title\": \"...\", \"description\": \"...\", "
            "\"estimated_minutes\": N}], \"total_minutes\": N, \"risks\": [\"...\"]}"
        ),
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1000,
    },
    "default": {
        "description": "Agent generique multi-tache",
        "system": (
            "Tu es un assistant specialise qui recoit une tache unique. "
            "Tu la realises de maniere complete et structuree. "
            "Reponds en francais. Sois factuel et concis."
        ),
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 800,
    },
}


class SubAgentOrchestrator:
    """Orchestre les sous-agents locaux avec isolation, budget et timeout."""

    def __init__(self, parent_user_id: str = "default"):
        self.parent_user_id = parent_user_id
        self._running: dict[str, SubAgentResult] = {}  # agent_id -> result (tracking)

    async def spawn(
        self,
        task: str,
        agent_type: str = "default",
        context: str = "",
        budget_usd: float = 0.10,
        timeout_s: float = 90.0,
        extra_system: str = "",
    ) -> SubAgentResult:
        """Lance un sous-agent isole et retourne son resultat.

        Args:
            task: La tache a realiser
            agent_type: Type d'agent (analyst, coder, writer, planner, default)
            context: Contexte supplementaire a injecter
            budget_usd: Budget maximum en USD
            timeout_s: Timeout en secondes
            extra_system: Instructions supplementaires a ajouter au system prompt
        """
        agent_id = f"sub_{uuid.uuid4().hex[:10]}"
        agent_config = AGENT_TYPES.get(agent_type, AGENT_TYPES["default"])
        t0 = time.perf_counter()

        result = SubAgentResult(
            agent_id=agent_id,
            agent_type=agent_type,
            status=AgentStatus.PENDING,
            task=task,
        )
        self._running[agent_id] = result

        logger.info(f"SubAgent {agent_id} ({agent_type}) starting: {task[:80]}...")

        try:
            result.status = AgentStatus.RUNNING
            agent_result = await asyncio.wait_for(
                self._execute_agent(
                    agent_id=agent_id,
                    task=task,
                    context=context,
                    agent_config=agent_config,
                    extra_system=extra_system,
                    budget_usd=budget_usd,
                    result=result,
                ),
                timeout=timeout_s,
            )
            return agent_result

        except asyncio.TimeoutError:
            result.status = AgentStatus.TIMEOUT
            result.error = f"Timeout apres {timeout_s}s"
            result.duration_s = time.perf_counter() - t0
            logger.warning(f"SubAgent {agent_id} timeout after {timeout_s}s")
            return result

        except Exception as e:
            result.status = AgentStatus.FAILED
            result.error = str(e)
            result.duration_s = time.perf_counter() - t0
            logger.error(f"SubAgent {agent_id} failed: {e}")
            return result

        finally:
            self._running.pop(agent_id, None)

    async def spawn_multiple(
        self,
        tasks: list[dict],
        budget_usd_per_task: float = 0.05,
        timeout_s: float = 120.0,
    ) -> list[SubAgentResult]:
        """Lance plusieurs sous-agents en parallele.

        tasks: [{"task": "...", "agent_type": "analyst", "context": "..."}, ...]
        """
        coros = [
            self.spawn(
                task=t["task"],
                agent_type=t.get("agent_type", "default"),
                context=t.get("context", ""),
                budget_usd=budget_usd_per_task,
                timeout_s=timeout_s,
            )
            for t in tasks
        ]
        return await asyncio.gather(*coros, return_exceptions=False)

    async def _execute_agent(
        self,
        agent_id: str,
        task: str,
        context: str,
        agent_config: dict,
        extra_system: str,
        budget_usd: float,
        result: SubAgentResult,
    ) -> SubAgentResult:
        """Execution isolee d'un sous-agent via Claude API directe."""
        t0 = time.perf_counter()

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            result.status = AgentStatus.FAILED
            result.error = "ANTHROPIC_API_KEY manquante"
            result.duration_s = time.perf_counter() - t0
            return result

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
        except Exception as e:
            result.status = AgentStatus.FAILED
            result.error = f"Client init failed: {e}"
            result.duration_s = time.perf_counter() - t0
            return result

        # Construire le system prompt isole
        system_prompt = agent_config["system"]
        if extra_system:
            system_prompt += f"\n\n{extra_system}"
        system_prompt += f"\n\nTon identifiant : {agent_id}. Tu es un sous-agent autonome."

        # Construire le user message
        user_content = f"TACHE : {task}"
        if context:
            user_content = f"CONTEXTE :\n{context}\n\n{user_content}"

        # CostTracker isole pour ce sous-agent
        sub_tracker = CostTracker(user_id=f"{self.parent_user_id}:{agent_id}")

        try:
            resp = await asyncio.to_thread(
                client.messages.create,
                model=agent_config["model"],
                max_tokens=agent_config["max_tokens"],
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_content}],
            )

            # Extraire le texte de la reponse
            output_text = "".join(
                b.text for b in resp.content if hasattr(b, "text")
            )

            # Enregistrer les couts
            sub_tracker.record_from_response(resp, model=agent_config["model"])
            cost_snapshot = sub_tracker.get()

            # Aussi enregistrer dans le tracker parent
            parent_tracker = get_cost_tracker(self.parent_user_id)
            parent_tracker.record_from_response(resp, model=agent_config["model"])

            # Verifier le budget
            if cost_snapshot["estimated_usd"] > budget_usd:
                result.status = AgentStatus.BUDGET_EXCEEDED
                result.error = f"Budget depasse: ${cost_snapshot['estimated_usd']:.4f} > ${budget_usd:.4f}"
                result.summary = output_text[:500]
                result.cost_usd = cost_snapshot["estimated_usd"]
                result.input_tokens = cost_snapshot["input_tokens"]
                result.output_tokens = cost_snapshot["output_tokens"]
                result.duration_s = time.perf_counter() - t0
                return result

            # Succes
            result.status = AgentStatus.COMPLETED
            result.summary = output_text
            result.cost_usd = cost_snapshot["estimated_usd"]
            result.input_tokens = cost_snapshot["input_tokens"]
            result.output_tokens = cost_snapshot["output_tokens"]
            result.duration_s = time.perf_counter() - t0

            # Tenter de parser du JSON dans la reponse (pour planner)
            import json as _json
            try:
                if output_text.strip().startswith("{"):
                    result.data = _json.loads(output_text.strip())
                else:
                    # Chercher un bloc JSON
                    import re
                    json_blocks = re.findall(r"```(?:json)?\s*\n?(.*?)```", output_text, re.DOTALL)
                    for block in json_blocks:
                        try:
                            result.data = _json.loads(block.strip())
                            break
                        except Exception:
                            continue
            except Exception:
                pass

            logger.info(
                f"SubAgent {agent_id} completed in {result.duration_s:.1f}s "
                f"(${result.cost_usd:.4f}, {result.input_tokens}+{result.output_tokens} tokens)"
            )
            return result

        except Exception as e:
            sub_tracker.record_error()
            result.status = AgentStatus.FAILED
            result.error = str(e)
            result.duration_s = time.perf_counter() - t0
            return result

    def get_running(self) -> list[dict]:
        """Retourne les sous-agents en cours d'execution."""
        return [r.to_dict() for r in self._running.values()]

    @staticmethod
    def list_agent_types() -> list[dict]:
        """Retourne les types de sous-agents disponibles."""
        return [
            {"type": k, "description": v["description"], "model": v["model"]}
            for k, v in AGENT_TYPES.items()
        ]


# ── Singleton ──

_orchestrators: dict[str, SubAgentOrchestrator] = {}


def get_orchestrator(user_id: str = "default") -> SubAgentOrchestrator:
    """Retourne l'orchestrateur pour un user (cree si besoin)."""
    if user_id not in _orchestrators:
        _orchestrators[user_id] = SubAgentOrchestrator(parent_user_id=user_id)
    return _orchestrators[user_id]
