"""
Agent 3 — detection automatique de taches complexes + generation de plan visible.

Objectif : avant d'executer une tache utilisateur, detecter si elle est complexe
(necessite plusieurs tools, etapes, ou temps) et si oui, generer un plan
en langage naturel qui est affiche a l'utilisateur (SSE event `task_plan`)
AVANT que l'agent ne commence les tool_uses.

Benefices :
  - Transparence : l'utilisateur voit ce qui va etre fait
  - Structure : le LLM est guide par un plan explicite (moins de drift)
  - Possibilite d'abandonner tot si le plan n'est pas aligne

Ce module est DIFFERENT du `agent3_plan_mode.py` existant qui cible specifiquement
le Computer Use / navigateur avec approbation formelle. Ici on fait plus leger :
heuristique + mini-generation Haiku, sans state machine.

API :
  - `is_complex_task(text, context)` -> (bool, reason)
  - `generate_task_plan(text, client, model)` -> list[str]
  - `format_plan_for_sse(plan)` -> dict pour event SSE
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger("sylea.task_complexity")


# ─────────────────────────────────────────────────────────────────────────────
# Heuristiques de complexite (rapide, sans LLM)
# ─────────────────────────────────────────────────────────────────────────────

# Mots-cles qui indiquent multi-step
_COMPLEX_VERBS = {
    # Verbes impliquant plusieurs etapes
    "analyse", "analyser", "analysez",
    "compare", "comparer", "comparez",
    "synthetise", "synthetiser", "synthese",
    "rapport", "etude", "evaluer", "evaluation",
    "planifie", "planifier", "organise", "organiser",
    "automatise", "automatiser", "orchestre",
    "recherche approfondie", "deep research",
    "audit", "diagnosti",
    "refactor", "migre", "migration", "deploi",
}

# Verbes d'actions composees
_COMPOUND_VERBS = {
    # "X et Y", "X puis Y"
    r"\b(cherche|recherche|fetch|lit).{1,30}(et|puis)\s+(envoie|sauve|cree|ecris|partage)",
    r"\b(analyse|synthetise).{1,30}(et|puis)\s+(envoie|sauve|cree|redige)",
    r"\b(trouve|identifie).{1,30}(et|puis)\s+(compare|evalue|classe)",
}

# Indicateurs quantitatifs : "5 articles", "chaque", "tous"
_QUANTIFIER_PATTERNS = [
    r"\b\d+\s+(articles|posts|documents|fichiers|items|personnes|clients)",
    r"\b(chaque|tous|toutes|pour chacun)\s+",
    r"\b(plusieurs|differentes?|multiples)\s+",
]

# Longueur : si le prompt est TRES long, probablement complexe
_LONG_PROMPT_THRESHOLD = 400  # chars


def _match_any(patterns: list[str], text: str) -> bool:
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False


def is_complex_task(text: str, *, has_files_uploaded: bool = False) -> tuple[bool, str]:
    """Heuristique : est-ce une tache complexe necessitant un plan ?

    Retourne (is_complex, reason).
    """
    if not text or not text.strip():
        return False, ""
    t = text.lower().strip()

    # Message court + simple salutation => trivial
    if len(t) < 40 and any(
        t.startswith(kw) for kw in ("salut", "bonjour", "bjr", "coucou", "hey", "merci", "ok", "yes", "non")
    ):
        return False, "trivial"

    # Verbe complexe explicite
    for verb in _COMPLEX_VERBS:
        if verb in t:
            return True, f"verb:{verb}"

    # Verbes composes (ET, PUIS)
    if _match_any(list(_COMPOUND_VERBS), t):
        return True, "compound_verbs"

    # Quantificateurs ("5 articles", "chaque client", ...)
    if _match_any(_QUANTIFIER_PATTERNS, t):
        return True, "quantifier"

    # Prompt tres long
    if len(text) > _LONG_PROMPT_THRESHOLD:
        return True, f"long_prompt:{len(text)}"

    # Fichier uploade => probablement analyse sur le fichier
    if has_files_uploaded and len(t) > 20:
        return True, "files_uploaded"

    # Presence de plusieurs imperatifs separes par virgules/points
    # "Fais X. Fais Y. Fais Z."
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if len(sentences) >= 3:
        return True, "multi_sentence"

    return False, ""


# ─────────────────────────────────────────────────────────────────────────────
# Generation du plan via Haiku (rapide, peu couteux)
# ─────────────────────────────────────────────────────────────────────────────

_PLAN_SYSTEM_PROMPT = """Tu es un planificateur concis. Tu recois une demande utilisateur
et tu dois produire un PLAN court en 3 a 6 etapes MAX, chacune en une phrase (20 mots max).

REGLES :
1. Chaque etape commence par un verbe d'action.
2. Pas d'explications, juste les etapes.
3. Liste markdown avec `1.`, `2.`, `3.`.
4. Ne pas commencer par "Bien sur, voici le plan". Direct sur la liste.
5. Si la demande est triviale, retourne juste une ligne: "Trivial — pas de plan necessaire."

FORMAT STRICT de sortie :
1. [verbe] [objet court]
2. [verbe] [objet court]
3. [verbe] [objet court]
"""


async def generate_task_plan(
    text: str,
    client: Any,
    *,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 300,
    timeout_s: float = 8.0,
) -> list[str]:
    """Genere un plan en 3-6 etapes via Haiku. Retourne les etapes en string.

    Si echec LLM, retourne une liste vide (silencieux).
    """
    if not text or not text.strip():
        return []

    try:
        resp = await asyncio.wait_for(
            client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=[{
                    "type": "text",
                    "text": _PLAN_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": text}],
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        logger.debug("generate_task_plan timeout")
        return []
    except Exception as e:
        logger.debug(f"generate_task_plan failed: {e}")
        return []

    raw = ""
    try:
        for block in resp.content or []:
            if hasattr(block, "text"):
                raw += block.text
    except Exception:
        return []

    if "trivial" in raw.lower() and "pas de plan" in raw.lower():
        return []

    # Parse les lignes qui commencent par un numero ou un tiret
    steps: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        m = re.match(r"^\s*(\d+[.)]\s*|[-*]\s+)(.+)$", line)
        if m:
            step = m.group(2).strip().rstrip(".")
            if step and len(step) > 3:
                steps.append(step)
    return steps[:6]


def format_plan_for_sse(steps: list[str], reason: str = "") -> dict:
    """Formate le plan pour un event SSE `task_plan`.

    L'UI affiche les etapes comme un checklist animé.
    """
    return {
        "steps": steps,
        "count": len(steps),
        "reason": reason,
        "type": "task_plan",
    }


__all__ = [
    "is_complex_task",
    "generate_task_plan",
    "format_plan_for_sse",
]
