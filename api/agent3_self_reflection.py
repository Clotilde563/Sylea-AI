"""
Agent 3 — Self-reflection auto sur longues reponses.

L'agent relit sa propre reponse AVANT de la renvoyer au user, et la corrige
si besoin. Utile pour :
  - Taches complexes ou l'agent a produit un rapport
  - Sequences de tool_use nombreuses (>3) ou des erreurs sont possibles
  - Reponses longues (>500 mots) ou des incoherences peuvent se glisser

Strategie :
  1. L'agent a produit `draft_response` (texte final).
  2. `should_reflect(draft, tool_uses_count)` heuristique decide.
  3. Si oui : `review_response(draft, client)` appelle Haiku avec prompt de
     review : cherche erreurs factuelles, contradictions, oublis.
  4. Si issues : `refine_response(draft, issues, client)` produit corrigee.

Couts controles :
  - Review via Haiku 4.5 (~$0.001 par review typique)
  - Cap max_tokens = 500 pour review
  - Skip si draft < 500 chars
  - Skip sous pytest

Config :
  - SYLEA_REFLECTION_ENABLED=1 (defaut 1)
  - SYLEA_REFLECTION_MIN_CHARS=500
  - SYLEA_REFLECTION_MIN_TOOL_USES=3
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger("sylea.self_reflection")


# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

def _is_enabled() -> bool:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return os.getenv("SYLEA_REFLECTION_ENABLED", "1") == "1"


_MIN_CHARS = int(os.getenv("SYLEA_REFLECTION_MIN_CHARS", "500"))
_MIN_TOOL_USES = int(os.getenv("SYLEA_REFLECTION_MIN_TOOL_USES", "3"))


# ─────────────────────────────────────────────────────────────────────────────
# Should reflect heuristique
# ─────────────────────────────────────────────────────────────────────────────

def should_reflect(
    draft: str,
    *,
    tool_uses_count: int = 0,
    user_opted_in: bool = True,
) -> tuple[bool, str]:
    """Decide si l'agent doit relire sa reponse.

    Retourne (should, reason).
    """
    if not _is_enabled():
        return False, "disabled"
    if not user_opted_in:
        return False, "user_opt_out"
    if not draft or not draft.strip():
        return False, "empty"

    # Reponse courte → skip
    if len(draft) < _MIN_CHARS and tool_uses_count < _MIN_TOOL_USES:
        return False, "short_response"

    # Longue OU bcp tool_uses → reflect
    if len(draft) >= _MIN_CHARS:
        return True, f"long_response({len(draft)} chars)"
    if tool_uses_count >= _MIN_TOOL_USES:
        return True, f"many_tool_uses({tool_uses_count})"
    return False, "below_thresholds"


# ─────────────────────────────────────────────────────────────────────────────
# Review + refine
# ─────────────────────────────────────────────────────────────────────────────

_REVIEW_SYSTEM = """Tu es un relecteur critique d'Agent 3. On te donne une reponse
produite par un autre agent. Tu dois identifier :

1. **Erreurs factuelles** : affirmations douteuses ou fausses.
2. **Contradictions internes** : la reponse se contredit.
3. **Oublis** : points importants de la demande non traites.
4. **Problemes de format** : structure confuse, repetitions, longueur excessive.
5. **Tonalite** : pas adaptee, trop formelle ou pas assez.

REGLES :
- Sois TRES concis. Pas de politesse inutile.
- Si la reponse est OK, reponds UNIQUEMENT "OK".
- Sinon, liste les issues en 3-5 bullets max, prefixes par [FACTUEL], [CONTRADICTION],
  [OUBLI], [FORMAT], [TON].
- N'invente pas de problemes. Ne sois pas trop pointilleux.
- La reponse peut utiliser des blocs [ACTION:...] ou references aux tools — c'est normal.
"""


_REFINE_SYSTEM = """Tu es un editeur. On te donne une reponse originale + une liste d'issues.
Tu produis une version corrigee, GARDANT le style et la longueur approximative.

REGLES :
- Corrige SEULEMENT les issues listees.
- Ne change pas le format (blocs [ACTION:...] restent intacts).
- Garde le tone et la fluidite.
- Ne rajoute PAS de disclaimer ou d'excuse.
- Reponds UNIQUEMENT avec la version corrigee, sans preambule.
"""


async def review_response(
    draft: str,
    client: Any,
    *,
    model: str = "claude-haiku-4-5-20251001",
    timeout_s: float = 10.0,
) -> dict[str, Any]:
    """Appelle Haiku pour reviewer le draft.

    Retourne {has_issues, issues: list, raw_review: str}.
    """
    if not draft or not draft.strip():
        return {"has_issues": False, "issues": [], "raw_review": ""}

    try:
        resp = await asyncio.wait_for(
            client.messages.create(
                model=model,
                max_tokens=400,
                system=[{
                    "type": "text",
                    "text": _REVIEW_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{
                    "role": "user",
                    "content": f"Reponse a reviewer :\n\n---\n{draft[:8000]}\n---",
                }],
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.debug("review_response timeout")
        return {"has_issues": False, "issues": [], "raw_review": "", "error": "timeout"}
    except Exception as e:
        logger.debug(f"review_response failed: {e}")
        return {"has_issues": False, "issues": [], "raw_review": "", "error": str(e)}

    raw = ""
    try:
        for b in resp.content or []:
            if hasattr(b, "text"):
                raw += b.text
    except Exception:
        pass

    raw = raw.strip()
    if raw.upper() == "OK" or raw.upper().startswith("OK"):
        return {"has_issues": False, "issues": [], "raw_review": raw}

    # Parse issues (lignes commencant par -, *, ou [TAG])
    issues: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("-", "*", "[")):
            issues.append(line.lstrip("-* ").strip())
    if not issues:
        # Fallback : tout le texte
        issues = [raw[:300]]
    return {"has_issues": True, "issues": issues, "raw_review": raw}


async def refine_response(
    draft: str, issues: list[str], client: Any,
    *,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 2000,
    timeout_s: float = 20.0,
) -> str:
    """Appelle Haiku pour corriger le draft a partir des issues.

    Retourne le texte corrige, ou le draft original si echec.
    """
    if not issues:
        return draft

    issues_text = "\n".join(f"- {i}" for i in issues)
    user_content = (
        f"Reponse originale :\n---\n{draft[:8000]}\n---\n\n"
        f"Issues a corriger :\n{issues_text}\n\n"
        f"Produis la version corrigee :"
    )

    try:
        resp = await asyncio.wait_for(
            client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{
                    "type": "text",
                    "text": _REFINE_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_content}],
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.debug("refine_response timeout")
        return draft
    except Exception as e:
        logger.debug(f"refine_response failed: {e}")
        return draft

    raw = ""
    try:
        for b in resp.content or []:
            if hasattr(b, "text"):
                raw += b.text
    except Exception:
        pass

    refined = raw.strip()
    if not refined or len(refined) < 50:
        return draft
    return refined


# ─────────────────────────────────────────────────────────────────────────────
# Full pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def reflect_and_refine(
    draft: str, client: Any,
    *,
    tool_uses_count: int = 0,
    user_opted_in: bool = True,
    model: str = "claude-haiku-4-5-20251001",
) -> dict[str, Any]:
    """Pipeline complet : decide -> review -> refine.

    Retourne {reflected, changed, final_text, issues, reason}.
    """
    should, reason = should_reflect(
        draft, tool_uses_count=tool_uses_count, user_opted_in=user_opted_in,
    )
    if not should:
        return {
            "reflected": False,
            "changed": False,
            "final_text": draft,
            "issues": [],
            "reason": reason,
        }

    review = await review_response(draft, client, model=model)
    if not review.get("has_issues"):
        return {
            "reflected": True,
            "changed": False,
            "final_text": draft,
            "issues": [],
            "reason": "no_issues",
        }

    issues = review["issues"]
    refined = await refine_response(draft, issues, client, model=model)
    changed = refined.strip() != draft.strip() and len(refined) > 50
    return {
        "reflected": True,
        "changed": changed,
        "final_text": refined if changed else draft,
        "issues": issues,
        "reason": reason,
    }


__all__ = [
    "should_reflect",
    "review_response",
    "refine_response",
    "reflect_and_refine",
]
