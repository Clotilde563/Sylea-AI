"""
Agent 3 — Hooks System.

Systeme de hooks pre/post action. Permet d'intercepter, modifier ou bloquer
toute action AVANT son execution, et de reagir APRES.

Inspire du hooks system de Claude Code (preToolUse / postToolUse).

Chaque hook est une fonction async qui recoit le contexte d'action
et retourne un HookResult (allow/modify/block/log).

Usage :
    hooks = HookRegistry()
    hooks.register_pre("PDF", audit_log_hook)
    hooks.register_pre("*", rate_limiter_hook)
    hooks.register_post("MEMORY", memory_analytics_hook)

    # Avant execution :
    result = await hooks.run_pre("PDF", action_data, context)
    if result.blocked:
        # Ne pas executer
    action_data = result.modified_data or action_data

    # Apres execution :
    await hooks.run_post("PDF", action_data, exec_result, context)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger("sylea.agent3.hooks")


class HookPhase(str, Enum):
    PRE = "pre"
    POST = "post"


class HookDecision(str, Enum):
    ALLOW = "allow"         # Laisser passer sans modification
    MODIFY = "modify"       # Modifier les donnees de l'action
    BLOCK = "block"         # Bloquer l'execution
    LOG_ONLY = "log_only"   # Juste logger, ne rien changer


@dataclass
class HookContext:
    """Contexte passe a chaque hook."""

    action_type: str
    action_data: dict
    user_id: str = ""
    user_msg: str = ""
    session_key: str = ""
    execution_result: Any = None   # rempli seulement en post-hook
    extra: dict = field(default_factory=dict)


@dataclass
class HookResult:
    """Resultat retourne par un hook."""

    decision: HookDecision = HookDecision.ALLOW
    modified_data: Optional[dict] = None   # Si decision == MODIFY
    block_reason: str = ""                 # Si decision == BLOCK
    log_message: str = ""                  # Message a logger / afficher
    hook_name: str = ""
    duration_ms: float = 0.0

    @property
    def blocked(self) -> bool:
        return self.decision == HookDecision.BLOCK

    @property
    def modified(self) -> bool:
        return self.decision == HookDecision.MODIFY and self.modified_data is not None

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "block_reason": self.block_reason,
            "log_message": self.log_message,
            "hook_name": self.hook_name,
            "duration_ms": round(self.duration_ms, 1),
        }


# Type alias pour les hook functions
PreHookFn = Callable[[HookContext], Any]    # async or sync -> HookResult
PostHookFn = Callable[[HookContext], Any]   # async or sync -> HookResult


@dataclass
class RegisteredHook:
    name: str
    phase: HookPhase
    action_pattern: str    # "*" = all actions, or specific type like "PDF"
    fn: Callable
    priority: int = 100    # Lower = runs first
    enabled: bool = True


class HookRegistry:
    """Registre central des hooks avec execution ordonnee."""

    def __init__(self):
        self._hooks: list[RegisteredHook] = []

    def register_pre(
        self,
        action_pattern: str,
        fn: Callable,
        name: str = "",
        priority: int = 100,
    ) -> str:
        """Enregistre un hook pre-action. Retourne le nom."""
        hook_name = name or f"pre_{action_pattern}_{len(self._hooks)}"
        self._hooks.append(RegisteredHook(
            name=hook_name,
            phase=HookPhase.PRE,
            action_pattern=action_pattern,
            fn=fn,
            priority=priority,
        ))
        self._hooks.sort(key=lambda h: h.priority)
        logger.debug(f"Hook registered: {hook_name} (pre, {action_pattern})")
        return hook_name

    def register_post(
        self,
        action_pattern: str,
        fn: Callable,
        name: str = "",
        priority: int = 100,
    ) -> str:
        """Enregistre un hook post-action. Retourne le nom."""
        hook_name = name or f"post_{action_pattern}_{len(self._hooks)}"
        self._hooks.append(RegisteredHook(
            name=hook_name,
            phase=HookPhase.POST,
            action_pattern=action_pattern,
            fn=fn,
            priority=priority,
        ))
        self._hooks.sort(key=lambda h: h.priority)
        logger.debug(f"Hook registered: {hook_name} (post, {action_pattern})")
        return hook_name

    def unregister(self, name: str) -> bool:
        before = len(self._hooks)
        self._hooks = [h for h in self._hooks if h.name != name]
        return len(self._hooks) < before

    def _matching_hooks(self, phase: HookPhase, action_type: str) -> list[RegisteredHook]:
        return [
            h for h in self._hooks
            if h.phase == phase
            and h.enabled
            and (h.action_pattern == "*" or h.action_pattern == action_type)
        ]

    async def run_pre(
        self,
        action_type: str,
        action_data: dict,
        user_id: str = "",
        user_msg: str = "",
        session_key: str = "",
    ) -> HookResult:
        """Execute les hooks pre-action dans l'ordre de priorite.

        Premier BLOCK arrete la chaine. Les MODIFY s'accumulent.
        """
        hooks = self._matching_hooks(HookPhase.PRE, action_type)
        if not hooks:
            return HookResult(decision=HookDecision.ALLOW)

        current_data = dict(action_data)
        for hook in hooks:
            ctx = HookContext(
                action_type=action_type,
                action_data=current_data,
                user_id=user_id,
                user_msg=user_msg,
                session_key=session_key,
            )
            t0 = time.perf_counter()
            try:
                if asyncio.iscoroutinefunction(hook.fn):
                    result = await hook.fn(ctx)
                else:
                    result = hook.fn(ctx)
                if not isinstance(result, HookResult):
                    result = HookResult(decision=HookDecision.ALLOW)
                result.hook_name = hook.name
                result.duration_ms = (time.perf_counter() - t0) * 1000
            except Exception as e:
                logger.warning(f"Hook {hook.name} failed: {e}")
                continue

            if result.log_message:
                logger.info(f"Hook {hook.name}: {result.log_message}")

            if result.blocked:
                return result

            if result.modified and result.modified_data:
                current_data = result.modified_data

        return HookResult(
            decision=HookDecision.MODIFY if current_data != action_data else HookDecision.ALLOW,
            modified_data=current_data if current_data != action_data else None,
        )

    async def run_post(
        self,
        action_type: str,
        action_data: dict,
        execution_result: Any = None,
        user_id: str = "",
        user_msg: str = "",
        session_key: str = "",
    ) -> list[HookResult]:
        """Execute les hooks post-action. Retourne la liste des resultats."""
        hooks = self._matching_hooks(HookPhase.POST, action_type)
        results = []
        for hook in hooks:
            ctx = HookContext(
                action_type=action_type,
                action_data=action_data,
                user_id=user_id,
                user_msg=user_msg,
                session_key=session_key,
                execution_result=execution_result,
            )
            t0 = time.perf_counter()
            try:
                if asyncio.iscoroutinefunction(hook.fn):
                    result = await hook.fn(ctx)
                else:
                    result = hook.fn(ctx)
                if not isinstance(result, HookResult):
                    result = HookResult(decision=HookDecision.LOG_ONLY)
                result.hook_name = hook.name
                result.duration_ms = (time.perf_counter() - t0) * 1000
                results.append(result)
            except Exception as e:
                logger.warning(f"Post-hook {hook.name} failed: {e}")
        return results

    def list_hooks(self) -> list[dict]:
        return [
            {
                "name": h.name,
                "phase": h.phase.value,
                "action_pattern": h.action_pattern,
                "priority": h.priority,
                "enabled": h.enabled,
            }
            for h in self._hooks
        ]

    @property
    def count(self) -> int:
        return len(self._hooks)


# ── Built-in Hooks ──

def _audit_log_hook(ctx: HookContext) -> HookResult:
    """Hook de logging automatique pour toutes les actions."""
    logger.info(
        f"[AUDIT] action={ctx.action_type} user={ctx.user_id[:8] if ctx.user_id else '?'} "
        f"keys={list(ctx.action_data.keys())[:5]}"
    )
    return HookResult(decision=HookDecision.LOG_ONLY, log_message=f"Audit: {ctx.action_type}")


class _RateLimiterHook:
    """Hook de rate limiting par action type."""

    def __init__(self, max_per_minute: int = 20):
        self.max_per_minute = max_per_minute
        self._calls: dict[str, list[float]] = {}

    def __call__(self, ctx: HookContext) -> HookResult:
        now = time.time()
        key = f"{ctx.user_id}:{ctx.action_type}"
        calls = self._calls.setdefault(key, [])
        # Nettoyer les appels de plus d'une minute
        calls[:] = [t for t in calls if now - t < 60]
        if len(calls) >= self.max_per_minute:
            return HookResult(
                decision=HookDecision.BLOCK,
                block_reason=f"Rate limit: {self.max_per_minute}/min pour {ctx.action_type}",
            )
        calls.append(now)
        return HookResult(decision=HookDecision.ALLOW)


def _sanitize_sensitive_hook(ctx: HookContext) -> HookResult:
    """Hook qui masque les donnees sensibles dans les logs."""
    sensitive_keys = {"password", "token", "secret", "api_key", "credit_card"}
    data = dict(ctx.action_data)
    modified = False
    for key in data:
        if any(sk in key.lower() for sk in sensitive_keys):
            data[key] = "***MASKED***"
            modified = True
    if modified:
        return HookResult(
            decision=HookDecision.MODIFY,
            modified_data=data,
            log_message="Donnees sensibles masquees",
        )
    return HookResult(decision=HookDecision.ALLOW)


# ── Singleton ──

_registry: Optional[HookRegistry] = None


def get_hook_registry() -> HookRegistry:
    """Retourne le registre singleton avec les hooks built-in."""
    global _registry
    if _registry is None:
        _registry = HookRegistry()
        # Enregistrer les hooks built-in
        _registry.register_pre("*", _audit_log_hook, name="audit_log", priority=10)
        _registry.register_pre("*", _RateLimiterHook(max_per_minute=30), name="rate_limiter", priority=20)
        _registry.register_pre("*", _sanitize_sensitive_hook, name="sanitize_sensitive", priority=50)
        logger.info(f"Hook registry initialized with {_registry.count} built-in hooks")
    return _registry
