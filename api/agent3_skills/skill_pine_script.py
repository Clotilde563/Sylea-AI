"""
Skill PineScript — Generation et analyse de code Pine Script (TradingView).

Genere du Pine Script v5 via Claude, avec validation syntaxique de base.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Optional

from api.agent3_skills.base import Skill, SkillResult, SkillContext

logger = logging.getLogger("sylea.agent3.skills.pine_script")


PINE_SYSTEM = """Tu es un expert Pine Script v5 (TradingView). Tu generes du code PROPRE, COMPLET, FONCTIONNEL.

REGLES :
1. Toujours //@version=5
2. Utiliser indicator() ou strategy() correctement
3. Commenter chaque section importante
4. Utiliser les bonnes pratiques : var pour les variables persistantes, input() pour les params
5. Code pret a copier-coller dans TradingView sans modification
6. Si l'utilisateur demande une modification, fournir le code COMPLET (pas de "...reste inchange...")

STRUCTURE du code :
  - Header (version, indicator/strategy)
  - Inputs
  - Calculs
  - Conditions
  - Plots / alerts

Reponds UNIQUEMENT avec le code Pine Script, precede d'une explication de 2-3 lignes max.
"""


class PineScriptSkill(Skill):
    name = "pine_script"
    description = "Generation et analyse de code Pine Script v5 pour TradingView"
    category = "tech"
    triggers = [
        "pine script", "pinescript", "pine", "tradingview",
        "indicateur", "indicator", "strategy", "strategie",
        "moving average", "moyenne mobile", "rsi", "macd",
        "bollinger", "stochastic", "stochastique",
        "ema", "sma", "vwap", "atr",
        "backtest", "signal", "alerte", "alert",
        "creer un indicateur", "code tradingview",
    ]
    required_tools = []
    is_async_heavy = True

    def _detect_type(self, instruction: str) -> str:
        """Detecte si c'est une generation, modification ou explication."""
        low = instruction.lower()
        if any(kw in low for kw in ("modifie", "ajoute", "change", "corrige", "fix", "edit")):
            return "modify"
        if any(kw in low for kw in ("explique", "comment", "qu'est-ce", "decode", "analyse ce code")):
            return "explain"
        return "generate"

    def _validate_pine(self, code: str) -> list[str]:
        """Validation syntaxique basique du Pine Script genere."""
        warnings = []
        if "//@version=5" not in code:
            warnings.append("Missing //@version=5 header")
        if not re.search(r'\b(indicator|strategy)\s*\(', code):
            warnings.append("Missing indicator() or strategy() declaration")
        # Check for common v4 syntax mistakes
        if "study(" in code:
            warnings.append("study() is v4 — use indicator() for v5")
        if "security(" in code and "request.security(" not in code:
            warnings.append("security() is deprecated — use request.security() in v5")
        if "input(" in code and "input." not in code:
            # v5 prefers input.int(), input.float(), etc. mais input() simple est OK
            pass
        return warnings

    async def execute(
        self,
        instruction: str,
        context: Optional[SkillContext] = None,
    ) -> SkillResult:
        task_type = self._detect_type(instruction)

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return SkillResult(
                success=False,
                error="Cle API Anthropic requise pour la generation Pine Script",
            )

        # Adapter le prompt selon le type
        if task_type == "explain":
            user_prompt = f"Explique ce code Pine Script ou ce concept :\n{instruction}"
        elif task_type == "modify":
            user_prompt = f"Modifie ce code Pine Script selon la demande :\n{instruction}\n\nFournis le code COMPLET modifie."
        else:
            # Enrichir avec le contexte memoire (timeframes preferes, etc.)
            mem_context = ""
            if context and context.memories:
                relevant = [
                    m for m in context.memories
                    if m.get("category") in ("tech", "preference", "habitude")
                    and any(kw in str(m.get("value", "")).lower() for kw in ("pine", "trading", "timeframe", "indicat"))
                ]
                if relevant:
                    mem_context = "\nPreferences utilisateur :\n" + "\n".join(
                        f"  - {m['key']}: {m['value']}" for m in relevant[:5]
                    )
            user_prompt = f"Genere du code Pine Script v5 pour :\n{instruction}{mem_context}"

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            resp = await asyncio.to_thread(
                client.messages.create,
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                system=[{
                    "type": "text",
                    "text": PINE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_prompt}],
            )
            output = "".join(b.text for b in resp.content if hasattr(b, "text"))
        except Exception as e:
            return SkillResult(success=False, error=f"Generation echouee: {e}")

        # Extraire le code des blocks markdown si present
        code_blocks = re.findall(r"```(?:pine|pinescript)?\s*\n(.*?)```", output, re.DOTALL)
        pine_code = code_blocks[0].strip() if code_blocks else ""

        # Valider
        validation_warnings = []
        if pine_code:
            validation_warnings = self._validate_pine(pine_code)

        return SkillResult(
            success=True,
            content=output,
            data={
                "task_type": task_type,
                "pine_code": pine_code,
                "validation_warnings": validation_warnings,
                "has_code": bool(pine_code),
            },
        )
