"""
Agent 3 — Plan Mode.

Inspire ethiquement de l'approche Plan Mode de Claude Code : avant de lancer
une sequence d'actions potentiellement couteuses ou destructrices (notamment
le BrowserAgent qui consomme l'API Anthropic), on genere un plan structure
que l'utilisateur peut approuver, modifier ou rejeter.

Objectifs :
  1. Reduire la consommation d'API (pas d'exploration aveugle)
  2. Donner a l'utilisateur le controle avant actions irreversibles
  3. Structurer la reflexion de l'agent (moins de drift)
  4. Permettre la reprise d'un plan existant (pas de regeneration a chaque run)

Architecture :
  - PlanGenerator : demande a Claude de structurer la tache en etapes numerotees
  - PlanStep : une etape individuelle avec risque, estimation de temps, dependances
  - ExecutionPlan : collection de steps avec metadonnees et etats (pending/approved/...)
  - PlanStore : persistence en memoire (session) + optionnel SQLite pour reprise

Reimplementation from scratch, pas de copie de code proprietaire.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("sylea.agent3.plan_mode")


# ── Niveaux de risque ─────────────────────────────────────────────────────────

class RiskLevel(str, Enum):
    """Niveau de risque d'une etape / action.

    safe       : lecture / navigation / verification
    caution    : clics, saisie de texte, scroll (modifient l'UI mais reversible)
    destructive: suppression, soumission de formulaire, achat, envoi message,
                 modification de parametres compte, login, telechargement
    """
    SAFE = "safe"
    CAUTION = "caution"
    DESTRUCTIVE = "destructive"


# ── Etats d'un plan ──────────────────────────────────────────────────────────

class PlanStatus(str, Enum):
    DRAFT = "draft"          # Plan genere, en attente de review user
    APPROVED = "approved"    # User a valide, pret a executer
    EXECUTING = "executing"  # En cours d'execution
    COMPLETED = "completed"  # Execution terminee avec succes
    FAILED = "failed"        # Echec d'execution
    ABORTED = "aborted"      # Annule par user


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class PlanStep:
    """Une etape atomique du plan."""
    id: int
    description: str               # "Naviguer vers le tableau de bord"
    action_hint: str               # "goto|click|type|verify|..." — hint pour BrowserAgent
    risk: RiskLevel = RiskLevel.SAFE
    estimated_seconds: int = 5
    requires_user: bool = False    # Doit-on demander confirmation user avant ?
    status: StepStatus = StepStatus.PENDING
    depends_on: list[int] = field(default_factory=list)
    notes: str = ""                # Notes additionnelles (ex: "attention, modal bloquant")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["risk"] = self.risk.value
        d["status"] = self.status.value
        return d


@dataclass
class ExecutionPlan:
    """Plan complet pour une tache Agent 3 Computer Use."""
    id: str
    task: str                      # Demande originale de l'utilisateur
    goal: str                      # Objectif reformule par l'agent (clarifie)
    url: str = ""
    code: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: float = field(default_factory=time.time)
    approved_at: Optional[float] = None
    user_id: str = "default"
    max_risk: RiskLevel = RiskLevel.CAUTION  # Niveau max autorise en execution auto
    estimated_total_seconds: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task": self.task,
            "goal": self.goal,
            "url": self.url,
            "has_code": bool(self.code),
            "code_length": len(self.code),
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status.value,
            "created_at": self.created_at,
            "approved_at": self.approved_at,
            "user_id": self.user_id,
            "max_risk": self.max_risk.value,
            "estimated_total_seconds": self.estimated_total_seconds,
            "num_steps": len(self.steps),
            "num_destructive": sum(1 for s in self.steps if s.risk == RiskLevel.DESTRUCTIVE),
        }


# ── Generateur de plan ───────────────────────────────────────────────────────

PLAN_SYSTEM_PROMPT = """Tu es un planificateur d'agent IA. On te donne une tache a accomplir
dans un navigateur web. Tu dois la decouper en etapes concretes, numerotees, et courtes.

REGLES :
1. Entre 3 et 12 etapes maximum. Pas moins de 3, pas plus de 12.
2. Chaque etape est ATOMIQUE (une seule action logique : naviguer, cliquer, taper, verifier).
3. Tu dois reformuler l'OBJECTIF final en une phrase claire.
4. Pour chaque etape, classe son risque :
   - "safe" : lecture seule, navigation, verification visuelle
   - "caution" : click, saisie de texte, scroll (modifie l'UI mais pas destructeur)
   - "destructive" : suppression, envoi, achat, login, telechargement, modification parametres,
                     soumission formulaire important
5. Pour chaque etape : action_hint = un des verbes { "goto", "click", "type", "press",
                                                     "scroll", "select_all_and_type", "verify",
                                                     "wait", "compile", "need_user" }
6. Estime le temps en secondes (entre 2 et 30 par etape).
7. Indique dependances via "depends_on" (liste d'IDs d'etapes precedentes).
8. Si une etape demande une intervention utilisateur (login, captcha, paiement) :
   requires_user = true ET action_hint = "need_user".

REPONDS UNIQUEMENT en JSON de cette forme (aucun texte avant ou apres) :
{
  "goal": "Objectif reformule en une phrase",
  "steps": [
    {
      "id": 1,
      "description": "...",
      "action_hint": "...",
      "risk": "safe|caution|destructive",
      "estimated_seconds": N,
      "requires_user": true|false,
      "depends_on": [],
      "notes": ""
    },
    ...
  ]
}
"""


class PlanGenerator:
    """Genere un ExecutionPlan a partir d'une tache en langage naturel.

    Utilise Claude Haiku (rapide et peu couteux) — le plan est du texte structure,
    pas besoin de vision ni de Sonnet.
    """

    def __init__(self, anthropic_client, model: str = "claude-haiku-4-5-20251001"):
        self.client = anthropic_client
        self.model = model

    def generate(
        self,
        task: str,
        url: str = "",
        code: str = "",
        user_id: str = "default",
    ) -> ExecutionPlan:
        """Genere un plan synchronement. Appeler depuis un thread si besoin."""
        context_parts = [f"TACHE : {task}"]
        if url:
            context_parts.append(f"URL CIBLE : {url}")
        if code:
            context_parts.append(
                f"CODE A COLLER / APPLIQUER : {len(code)} caracteres disponibles "
                "(sera injecte dans l'editeur si etape de type 'type' / 'select_all_and_type')."
            )
        user_content = "\n".join(context_parts)

        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=[{
                    "type": "text",
                    "text": PLAN_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_content}],
            )
            raw = "".join(b.text for b in resp.content if hasattr(b, "text"))
        except Exception as e:
            logger.warning(f"PlanGenerator LLM call failed: {e}. Using fallback heuristic plan.")
            return self._fallback_plan(task, url, code, user_id)

        plan_data = self._parse_json(raw)
        if not plan_data:
            logger.warning(f"PlanGenerator could not parse JSON. Using fallback. Raw: {raw[:200]}")
            return self._fallback_plan(task, url, code, user_id)

        return self._build_plan(plan_data, task, url, code, user_id)

    # ── Parsing ──

    @staticmethod
    def _parse_json(raw: str) -> Optional[dict]:
        """Essai multi-etages : JSON pur, raw_decode, bloc markdown."""
        if not raw:
            return None
        # 1. JSON pur
        try:
            return json.loads(raw.strip())
        except Exception:
            pass
        # 2. raw_decode depuis la premiere accolade
        try:
            start = raw.find("{")
            if start >= 0:
                decoder = json.JSONDecoder()
                data, _ = decoder.raw_decode(raw[start:])
                return data
        except Exception:
            pass
        # 3. bloc markdown
        blocks = re.findall(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
        for b in blocks:
            try:
                return json.loads(b.strip())
            except Exception:
                continue
        return None

    # ── Construction ──

    @staticmethod
    def _parse_risk(v: Any) -> RiskLevel:
        if isinstance(v, str):
            v = v.lower().strip()
            if v in ("safe", "low"):
                return RiskLevel.SAFE
            if v in ("caution", "medium"):
                return RiskLevel.CAUTION
            if v in ("destructive", "high", "danger"):
                return RiskLevel.DESTRUCTIVE
        return RiskLevel.SAFE

    def _build_plan(
        self,
        data: dict,
        task: str,
        url: str,
        code: str,
        user_id: str,
    ) -> ExecutionPlan:
        steps: list[PlanStep] = []
        for i, s in enumerate(data.get("steps", []), start=1):
            try:
                steps.append(PlanStep(
                    id=int(s.get("id", i)),
                    description=str(s.get("description", "")).strip()[:300],
                    action_hint=str(s.get("action_hint", "")).strip().lower()[:40],
                    risk=self._parse_risk(s.get("risk", "safe")),
                    estimated_seconds=max(2, min(60, int(s.get("estimated_seconds", 5)))),
                    requires_user=bool(s.get("requires_user", False)),
                    depends_on=[int(x) for x in s.get("depends_on", []) if str(x).isdigit()],
                    notes=str(s.get("notes", "")).strip()[:200],
                ))
            except Exception as e:
                logger.warning(f"Skipping invalid step {s}: {e}")
                continue

        # Garde-fou : entre 3 et 12 etapes (le modele peut deraper)
        if len(steps) < 3:
            steps.extend(self._minimum_safety_steps(task, url)[len(steps):3])
        steps = steps[:12]

        # Renumeroter proprement si le modele a saute des IDs
        for i, s in enumerate(steps, start=1):
            s.id = i

        goal = str(data.get("goal", "")).strip()[:300] or f"Accomplir : {task[:120]}"
        total_est = sum(s.estimated_seconds for s in steps)

        return ExecutionPlan(
            id=uuid.uuid4().hex[:12],
            task=task,
            goal=goal,
            url=url,
            code=code,
            steps=steps,
            status=PlanStatus.DRAFT,
            user_id=user_id,
            estimated_total_seconds=total_est,
        )

    # ── Fallbacks heuristiques (sans LLM) ──

    @staticmethod
    def _minimum_safety_steps(task: str, url: str) -> list[PlanStep]:
        """3 etapes minimales si le LLM rate completement."""
        return [
            PlanStep(
                id=1,
                description=f"Ouvrir {url or 'la page cible'}",
                action_hint="goto",
                risk=RiskLevel.SAFE,
                estimated_seconds=5,
            ),
            PlanStep(
                id=2,
                description=f"Executer : {task[:140]}",
                action_hint="click",
                risk=RiskLevel.CAUTION,
                estimated_seconds=30,
            ),
            PlanStep(
                id=3,
                description="Verifier visuellement que la tache est terminee",
                action_hint="verify",
                risk=RiskLevel.SAFE,
                estimated_seconds=5,
            ),
        ]

    def _fallback_plan(self, task: str, url: str, code: str, user_id: str) -> ExecutionPlan:
        """Plan heuristique sans LLM — utilise seulement si l'API est down."""
        steps = self._minimum_safety_steps(task, url)
        if code:
            # Insere une etape "coller le code" au milieu
            steps.insert(1, PlanStep(
                id=2,
                description=f"Coller le code ({len(code)} chars) dans l'editeur",
                action_hint="select_all_and_type",
                risk=RiskLevel.CAUTION,
                estimated_seconds=15,
                notes="Code present dans le plan",
            ))
            for i, s in enumerate(steps, start=1):
                s.id = i
        return ExecutionPlan(
            id=uuid.uuid4().hex[:12],
            task=task,
            goal=f"Accomplir : {task[:200]}",
            url=url,
            code=code,
            steps=steps,
            status=PlanStatus.DRAFT,
            user_id=user_id,
            estimated_total_seconds=sum(s.estimated_seconds for s in steps),
        )


# ── Store en memoire ─────────────────────────────────────────────────────────

class PlanStore:
    """Persistence simple en memoire des plans par user_id.

    Note: pour un vrai usage multi-session, brancher sur SQLite via DatabaseManager.
    La structure est faite pour ca (to_dict / from_dict).
    """

    def __init__(self):
        self._plans: dict[str, ExecutionPlan] = {}  # keyed by plan_id
        self._by_user: dict[str, list[str]] = {}    # user_id -> [plan_id]

    def save(self, plan: ExecutionPlan) -> None:
        self._plans[plan.id] = plan
        self._by_user.setdefault(plan.user_id, []).append(plan.id)
        # Garder les 20 derniers plans par user
        if len(self._by_user[plan.user_id]) > 20:
            old_id = self._by_user[plan.user_id].pop(0)
            self._plans.pop(old_id, None)

    def get(self, plan_id: str) -> Optional[ExecutionPlan]:
        return self._plans.get(plan_id)

    def latest_for_user(self, user_id: str) -> Optional[ExecutionPlan]:
        ids = self._by_user.get(user_id, [])
        if not ids:
            return None
        return self._plans.get(ids[-1])

    def approve(self, plan_id: str) -> Optional[ExecutionPlan]:
        p = self._plans.get(plan_id)
        if not p:
            return None
        p.status = PlanStatus.APPROVED
        p.approved_at = time.time()
        return p

    def abort(self, plan_id: str) -> Optional[ExecutionPlan]:
        p = self._plans.get(plan_id)
        if p:
            p.status = PlanStatus.ABORTED
        return p

    def update_step(self, plan_id: str, step_id: int, status: StepStatus) -> None:
        p = self._plans.get(plan_id)
        if not p:
            return
        for s in p.steps:
            if s.id == step_id:
                s.status = status
                return

    def edit_step(self, plan_id: str, step_id: int, description: Optional[str] = None,
                  risk: Optional[RiskLevel] = None) -> bool:
        """Permet a l'utilisateur de modifier une etape avant approbation."""
        p = self._plans.get(plan_id)
        if not p or p.status != PlanStatus.DRAFT:
            return False
        for s in p.steps:
            if s.id == step_id:
                if description is not None:
                    s.description = description.strip()[:300]
                if risk is not None:
                    s.risk = risk
                return True
        return False


# ── Singleton ────────────────────────────────────────────────────────────────

_plan_store: Optional[PlanStore] = None


def get_plan_store() -> PlanStore:
    global _plan_store
    if _plan_store is None:
        _plan_store = PlanStore()
    return _plan_store
