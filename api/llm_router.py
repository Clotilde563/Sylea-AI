"""
LLM router + prompt caching — Syléa.AI (optimisation coûts Anthropic).

Deux optimisations qui économisent typiquement 40-60% sur la facture
Claude sans perte de qualité :

1. **Prompt caching** (Anthropic API) : marque les blocs de prompt système
   ré-utilisés comme cacheables (`cache_control: ephemeral`). Les writes
   coûtent 25% plus cher que normal, mais les reads coûtent 90% MOINS cher.
   Break-even dès 2 utilisations du même bloc en < 5 min (TTL cache).

2. **Model routing** : sélectionne dynamiquement Haiku/Sonnet/Opus selon
   la complexité de la tâche. Haiku = 60x moins cher qu'Opus, suffit pour
   80% des tâches conversationnelles.

Décision de routing :
- **Haiku 4.5**   : chat compagnon (Agent 1), classification, extraction,
                    résumés courts. Coût ~0.25$/Mtok input.
- **Sonnet 4.5**  : analyse de choix (dilemmes), génération de plan
                    d'action, génération de questions personnalisées.
                    Coût ~3$/Mtok input.
- **Opus 4.5**    : raisonnement critique (très peu fréquent — désactivé
                    par défaut, opt-in via env).

Utilisation :
    from api.llm_router import route_model, build_cached_system_blocks

    model = route_model(task="chat_companion", user_tier="free")
    system_blocks = build_cached_system_blocks(
        static_instructions=SYSTEM_PROMPT,
        user_profile=profile_text,  # dynamique, pas caché
    )
    resp = client.messages.create(model=model, system=system_blocks, ...)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger("sylea.llm_router")


# ─────────────────────────────────────────────────────────────────────────────
# Modèles disponibles
# ─────────────────────────────────────────────────────────────────────────────

class Model(str, Enum):
    """IDs Anthropic des modèles supportés (à jour mai 2026)."""
    HAIKU = "claude-haiku-4-5-20251001"
    SONNET = "claude-sonnet-4-6"
    OPUS = "claude-opus-4-5-20251001"


# Prix indicatifs USD / million tokens (mai 2026, à actualiser)
PRICING = {
    Model.HAIKU:  {"input": 0.25, "output": 1.25, "cache_read": 0.025, "cache_write": 0.3125},
    Model.SONNET: {"input": 3.00, "output": 15.0, "cache_read": 0.30,  "cache_write": 3.75},
    Model.OPUS:   {"input": 15.0, "output": 75.0, "cache_read": 1.50,  "cache_write": 18.75},
}


# ─────────────────────────────────────────────────────────────────────────────
# Tâches et leur classification de complexité
# ─────────────────────────────────────────────────────────────────────────────

class TaskComplexity(str, Enum):
    """Trois niveaux : trivial → standard → critique."""
    TRIVIAL = "trivial"      # Haiku
    STANDARD = "standard"    # Sonnet
    CRITICAL = "critical"    # Opus (rare, opt-in)


# Mapping tâche → complexité par défaut.
# Modifiable via SYLEA_LLM_ROUTE_OVERRIDES (JSON).
DEFAULT_TASK_COMPLEXITY: dict[str, TaskComplexity] = {
    # Agent 1 — compagnon textuel
    "chat_companion":          TaskComplexity.TRIVIAL,
    "summary_short":           TaskComplexity.TRIVIAL,
    "intent_classification":   TaskComplexity.TRIVIAL,
    "memory_extraction":       TaskComplexity.TRIVIAL,
    "language_detection":      TaskComplexity.TRIVIAL,
    "emotion_classification":  TaskComplexity.TRIVIAL,

    # Agent 2 — assistant exécutant (skills)
    "skill_execution":         TaskComplexity.STANDARD,
    "email_drafting":          TaskComplexity.STANDARD,
    "calendar_planning":       TaskComplexity.STANDARD,

    # Moteur métier
    "dilemma_analysis":        TaskComplexity.STANDARD,
    "action_plan_generation":  TaskComplexity.STANDARD,
    "question_generation":     TaskComplexity.STANDARD,
    "sub_objectives_gen":      TaskComplexity.STANDARD,
    "journee_analysis":        TaskComplexity.STANDARD,
    "event_impact_analysis":   TaskComplexity.STANDARD,

    # Critique (rare)
    "deep_reasoning":          TaskComplexity.CRITICAL,
    "code_generation":         TaskComplexity.CRITICAL,
}


# ─────────────────────────────────────────────────────────────────────────────
# Sélection du modèle
# ─────────────────────────────────────────────────────────────────────────────

def _load_overrides() -> dict[str, TaskComplexity]:
    """Lit SYLEA_LLM_ROUTE_OVERRIDES (JSON) pour override la table par défaut.

    Exemple :
        SYLEA_LLM_ROUTE_OVERRIDES='{"dilemma_analysis": "trivial"}'
    """
    import json
    raw = os.environ.get("SYLEA_LLM_ROUTE_OVERRIDES", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {k: TaskComplexity(v) for k, v in data.items()}
    except Exception as e:
        logger.warning("[llm_router] SYLEA_LLM_ROUTE_OVERRIDES parse failed: %s", e)
        return {}


_OVERRIDES = _load_overrides()
_OPUS_ENABLED = os.environ.get("SYLEA_LLM_OPUS_ENABLED", "").strip().lower() in (
    "1", "true", "yes", "on"
)


def get_complexity(task: str) -> TaskComplexity:
    """Retourne la complexité d'une tâche (overrides env > defaults)."""
    if task in _OVERRIDES:
        return _OVERRIDES[task]
    return DEFAULT_TASK_COMPLEXITY.get(task, TaskComplexity.STANDARD)


def route_model(task: str, user_tier: str = "free") -> str:
    """Sélectionne le modèle Anthropic optimal pour une tâche donnée.

    Args:
        task: identifier de la tâche (voir DEFAULT_TASK_COMPLEXITY).
        user_tier: "free" | "advanced" | "enterprise". Les tiers payants
                   peuvent obtenir Sonnet sur des tâches triviales s'ils
                   en ont besoin (config future). Défaut : pas d'upgrade.

    Returns:
        L'ID modèle Anthropic (string).
    """
    complexity = get_complexity(task)

    if complexity == TaskComplexity.CRITICAL:
        # Opus n'est activé qu'explicitement en prod (coût × 60)
        if _OPUS_ENABLED:
            return Model.OPUS.value
        return Model.SONNET.value

    if complexity == TaskComplexity.STANDARD:
        return Model.SONNET.value

    # TRIVIAL : Haiku
    return Model.HAIKU.value


# ─────────────────────────────────────────────────────────────────────────────
# Prompt caching
# ─────────────────────────────────────────────────────────────────────────────

# Seuil minimal en caractères pour qu'un bloc soit éligible au cache.
# En dessous, le surcoût write annule le gain read.
# Anthropic recommande : ≥ 1024 tokens (~4000 caractères) pour Sonnet/Opus,
# ≥ 2048 tokens (~8000 caractères) pour Haiku.
_MIN_CACHEABLE_HAIKU = 8000
_MIN_CACHEABLE_SONNET = 4000


@dataclass
class CachedBlock:
    """Bloc de prompt avec annotation cache_control optionnelle."""
    text: str
    cacheable: bool

    def to_anthropic(self) -> dict[str, Any]:
        """Format Anthropic API : block content (système ou messages)."""
        block: dict[str, Any] = {"type": "text", "text": self.text}
        if self.cacheable:
            block["cache_control"] = {"type": "ephemeral"}
        return block


def build_cached_system_blocks(
    static_instructions: str,
    user_profile: str | None = None,
    dynamic_context: str | None = None,
    model: str = Model.SONNET.value,
) -> list[dict[str, Any]]:
    """Construit les blocs système avec cache_control optimal.

    Stratégie :
      - Bloc 1 : `static_instructions` — RAREMENT modifié, TOUJOURS caché.
      - Bloc 2 : `user_profile` — modifié à chaque édition profil utilisateur,
                  caché si > seuil (économise sur les sessions multiples).
      - Bloc 3 : `dynamic_context` — change à chaque requête, JAMAIS caché.

    Anthropic API : seuls les 4 derniers blocs `cache_control` sont effectifs.
    On en utilise 2 max ici.

    Args:
        static_instructions: prompt système quasi-immuable (rules, ton, format).
        user_profile: bloc profil (nom, objectif, compétences). Optionnel.
        dynamic_context: contexte dynamique (historique récent). Optionnel.
        model: pour ajuster le seuil min cacheable.

    Returns:
        Liste de blocs au format Anthropic, prête à passer à `system=`.
    """
    threshold = (
        _MIN_CACHEABLE_HAIKU if model == Model.HAIKU.value
        else _MIN_CACHEABLE_SONNET
    )

    blocks: list[CachedBlock] = []

    # Bloc 1 : statique → toujours cacheable si assez long
    if static_instructions:
        blocks.append(CachedBlock(
            text=static_instructions,
            cacheable=len(static_instructions) >= threshold,
        ))

    # Bloc 2 : profil utilisateur → caché si long (réutilisé entre messages)
    if user_profile:
        blocks.append(CachedBlock(
            text=user_profile,
            cacheable=len(user_profile) >= threshold,
        ))

    # Bloc 3 : contexte dynamique → jamais caché (change à chaque req)
    if dynamic_context:
        blocks.append(CachedBlock(
            text=dynamic_context,
            cacheable=False,
        ))

    return [b.to_anthropic() for b in blocks]


# ─────────────────────────────────────────────────────────────────────────────
# Estimation coûts
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CostEstimate:
    """Décomposition coût d'une requête Anthropic."""
    model: str
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    cost_usd: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }


def estimate_cost(
    model: str,
    input_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    output_tokens: int = 0,
) -> CostEstimate:
    """Calcule le coût USD d'une requête Anthropic.

    Les tokens cache_read et cache_write sont COMPTÉS SÉPARÉMENT des
    input_tokens normaux (l'API Anthropic les sépare dans la réponse
    `usage`).
    """
    try:
        m = Model(model)
    except ValueError:
        # Modèle non listé : on tombe sur Sonnet par défaut
        m = Model.SONNET

    p = PRICING[m]
    cost = (
        input_tokens       * p["input"]       / 1_000_000
        + cache_read_tokens  * p["cache_read"]  / 1_000_000
        + cache_write_tokens * p["cache_write"] / 1_000_000
        + output_tokens      * p["output"]      / 1_000_000
    )

    return CostEstimate(
        model=model,
        input_tokens=input_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
    )


def estimate_savings_with_cache(
    model: str,
    cached_input_tokens: int,
    reuse_count: int,
) -> dict[str, Any]:
    """Estime l'économie d'une stratégie de cache sur N réutilisations.

    Ex. : prompt système 5000 tokens, réutilisé 10 fois en 5 min.
    Sans cache : 5000 × 10 = 50000 tokens @ prix input.
    Avec cache : 5000 × 1.25 (write) + 5000 × 0.1 × 9 (reads) — bien moins cher.
    """
    try:
        m = Model(model)
    except ValueError:
        m = Model.SONNET

    p = PRICING[m]

    cost_no_cache = cached_input_tokens * reuse_count * p["input"] / 1_000_000

    if reuse_count <= 0:
        cost_with_cache = 0.0
    else:
        cost_with_cache = (
            cached_input_tokens * p["cache_write"] / 1_000_000  # 1 write
            + cached_input_tokens * p["cache_read"] * (reuse_count - 1) / 1_000_000
        )

    savings = cost_no_cache - cost_with_cache
    savings_pct = (savings / cost_no_cache * 100) if cost_no_cache > 0 else 0.0

    return {
        "cost_without_cache_usd": round(cost_no_cache, 6),
        "cost_with_cache_usd": round(cost_with_cache, 6),
        "savings_usd": round(savings, 6),
        "savings_pct": round(savings_pct, 2),
        "break_even_at_reuse_count": _break_even_reuse(m),
    }


def _break_even_reuse(model: Model) -> int:
    """À partir de combien de réutilisations le cache devient rentable ?

    Math :
      Cost(no cache) = N × input
      Cost(with cache) = write + (N-1) × cache_read
      Break-even : N × input = write + (N-1) × cache_read
                   → N = (write - cache_read) / (input - cache_read)
    """
    p = PRICING[model]
    numerator = p["cache_write"] - p["cache_read"]
    denominator = p["input"] - p["cache_read"]
    if denominator <= 0:
        return 999
    return max(2, int(numerator / denominator) + 1)


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostic
# ─────────────────────────────────────────────────────────────────────────────

def get_router_config() -> dict[str, Any]:
    """Diagnostic /api/health/llm — config router actif."""
    return {
        "models": {
            "haiku": Model.HAIKU.value,
            "sonnet": Model.SONNET.value,
            "opus": Model.OPUS.value,
        },
        "opus_enabled": _OPUS_ENABLED,
        "overrides_count": len(_OVERRIDES),
        "default_routes_count": len(DEFAULT_TASK_COMPLEXITY),
        "pricing_usd_per_mtok": {
            m.value: PRICING[m] for m in Model
        },
    }
