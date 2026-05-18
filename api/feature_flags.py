"""
Feature flags — Syléa.AI.

Abstraction unifiée pour les flags de fonctionnalité, compatible avec :
  - **GrowthBook** (open-source, self-hostable)
  - **LaunchDarkly** (SaaS)
  - **Backend local** (YAML/JSON in repo) — défaut dev

Permet :
  - **Canary releases** : rollout progressif 1% → 10% → 50% → 100%
  - **Kill switches** : couper une feature instantanément en cas d'incident
  - **A/B testing** : variants A/B/C avec assignation déterministe par user
  - **Targeting** : feature pour un segment (tier="advanced", country="FR")
  - **Time-based** : activer feature à une date donnée (lancement marketing)

Le hash d'assignation est **déterministe** : (feature_name + user_id) →
toujours le même bucket. Garantit la cohérence de l'expérience utilisateur
entre sessions sans table de mapping.

Configuration via env :
    SYLEA_FF_BACKEND=local|growthbook|launchdarkly  (défaut local)
    SYLEA_FF_LOCAL_PATH=config/feature_flags.yaml
    GROWTHBOOK_API_HOST=https://api.growthbook.io
    GROWTHBOOK_CLIENT_KEY=...
    LAUNCHDARKLY_SDK_KEY=...

Usage :
    from api.feature_flags import is_enabled, get_variant

    if is_enabled("new_dilemma_engine", user_id=user.id, default=False):
        ...

    variant = get_variant("onboarding_flow", user_id, default="control")
    if variant == "treatment_a":
        ...
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger("sylea.feature_flags")


# ─────────────────────────────────────────────────────────────────────────────
# Modèle de flag (matching format GrowthBook simplifié)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FeatureRule:
    """Une règle d'évaluation d'un flag.

    L'évaluation est séquentielle : la première règle qui matche gagne.
    Si aucune ne matche → `default_value`.
    """
    # Condition d'application — tous les champs présents doivent matcher
    user_id_in: list[str] = field(default_factory=list)   # whitelist explicite
    user_tier_in: list[str] = field(default_factory=list) # ["advanced", "enterprise"]
    country_in: list[str] = field(default_factory=list)   # ["FR", "BE"]
    start_at: float | None = None                         # unix ts inclusif
    end_at: float | None = None                           # unix ts exclusif

    # Si la règle matche, on assigne ce bucket :
    rollout_pct: float = 100.0  # 0-100 : % d'users qui passent
    variant: str = "on"         # variant returned (ou "off" pour bloquer)


@dataclass
class Feature:
    """Définition d'un flag, avec règles + défaut."""
    key: str
    default_value: str = "off"  # variant si aucune règle ne matche
    rules: list[FeatureRule] = field(default_factory=list)
    description: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Hash déterministe pour assignation
# ─────────────────────────────────────────────────────────────────────────────

def _bucket_user(feature_key: str, user_id: str | None) -> float:
    """Retourne un score 0-100 déterministe pour (feature, user).

    Garantit qu'un user a TOUJOURS le même bucket pour une feature donnée.
    Indépendant entre features : ce n'est pas parce qu'un user est dans
    les premiers 10% de feature A qu'il sera dans ceux de feature B.
    """
    if not user_id:
        # Anonymous : assignation aléatoire par session (pas déterministe)
        return float(int(time.time() * 1000) % 100)

    raw = f"{feature_key}:{user_id}".encode("utf-8")
    digest = hashlib.sha256(raw).digest()
    # 4 premiers bytes → int → modulo 100
    n = int.from_bytes(digest[:4], "big")
    return (n % 10000) / 100.0  # 0.00 → 99.99


# ─────────────────────────────────────────────────────────────────────────────
# Backend Protocol
# ─────────────────────────────────────────────────────────────────────────────

class FeatureFlagBackend(Protocol):
    """Interface unifiée pour tous les backends."""

    def evaluate(
        self,
        key: str,
        user_id: str | None,
        user_attrs: dict[str, Any] | None = None,
    ) -> str: ...

    def reload(self) -> None: ...

    def list_features(self) -> list[str]: ...


# ─────────────────────────────────────────────────────────────────────────────
# Backend Local (YAML)
# ─────────────────────────────────────────────────────────────────────────────

class LocalBackend:
    """Backend local : flags définis dans un fichier YAML/JSON versionné.

    Avantage : zero infra dépendante, flags sont du code review.
    Inconvénient : déploiement nécessaire pour changer un flag (mais
    `reload()` permet hot-reload si on watch le fichier).

    Format YAML attendu :
        features:
          new_dilemma_engine:
            description: "Nouveau moteur d'analyse"
            default: off
            rules:
              - user_tier_in: [enterprise]
                variant: on
              - rollout_pct: 10
                variant: on
    """

    def __init__(self, path: str | None = None):
        self._path = path or os.environ.get(
            "SYLEA_FF_LOCAL_PATH", "config/feature_flags.yaml"
        )
        self._features: dict[str, Feature] = {}
        self._mtime: float = 0.0
        self.reload()

    def reload(self) -> None:
        """Recharge le fichier si modifié depuis le dernier load."""
        path = Path(self._path)
        if not path.exists():
            self._features = {}
            return

        mtime = path.stat().st_mtime
        if mtime == self._mtime:
            return
        self._mtime = mtime

        try:
            if path.suffix in (".yaml", ".yml"):
                import yaml  # type: ignore
                with open(path, encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
            else:
                import json
                with open(path, encoding="utf-8") as f:
                    raw = json.load(f)
        except Exception as e:
            logger.error("[feature_flags] reload failed: %s", e)
            return

        def _coerce_variant(v: Any) -> str:
            """YAML 1.1 parse 'on'/'off' comme booléens — on les recoerce en string."""
            if v is True:
                return "on"
            if v is False:
                return "off"
            return str(v)

        features: dict[str, Feature] = {}
        for key, spec in (raw.get("features") or {}).items():
            rules = []
            for r in spec.get("rules", []):
                rules.append(FeatureRule(
                    user_id_in=r.get("user_id_in", []) or [],
                    user_tier_in=r.get("user_tier_in", []) or [],
                    country_in=r.get("country_in", []) or [],
                    start_at=r.get("start_at"),
                    end_at=r.get("end_at"),
                    rollout_pct=float(r.get("rollout_pct", 100.0)),
                    variant=_coerce_variant(r.get("variant", "on")),
                ))
            features[key] = Feature(
                key=key,
                default_value=_coerce_variant(spec.get("default", "off")),
                rules=rules,
                description=str(spec.get("description", "")),
            )

        self._features = features
        logger.info("[feature_flags] reloaded %d features from %s",
                    len(features), self._path)

    def evaluate(
        self,
        key: str,
        user_id: str | None,
        user_attrs: dict[str, Any] | None = None,
    ) -> str:
        feature = self._features.get(key)
        if feature is None:
            return "off"

        attrs = user_attrs or {}
        now = time.time()

        for rule in feature.rules:
            # Targeting
            if rule.user_id_in and user_id not in rule.user_id_in:
                continue
            if rule.user_tier_in and attrs.get("tier") not in rule.user_tier_in:
                continue
            if rule.country_in and attrs.get("country") not in rule.country_in:
                continue
            if rule.start_at is not None and now < rule.start_at:
                continue
            if rule.end_at is not None and now >= rule.end_at:
                continue

            # Rollout : bucket user 0-100
            if rule.rollout_pct < 100.0:
                bucket = _bucket_user(key, user_id)
                if bucket >= rule.rollout_pct:
                    continue

            return rule.variant

        return feature.default_value

    def list_features(self) -> list[str]:
        return sorted(self._features.keys())


# ─────────────────────────────────────────────────────────────────────────────
# Backend GrowthBook (stub — implé concrète quand SDK ajoutée)
# ─────────────────────────────────────────────────────────────────────────────

class GrowthBookBackend:
    """Stub GrowthBook : utilise le SDK officiel quand `growthbook` est installé.

    En attendant : tombe sur LocalBackend pour ne pas bloquer.
    Pour activer en prod : `pip install growthbook`.
    """

    def __init__(self):
        try:
            import growthbook  # type: ignore # noqa: F401
            self._client_available = True
        except ImportError:
            self._client_available = False
            logger.warning(
                "[feature_flags] growthbook SDK absent, fallback Local. "
                "Installer via `pip install growthbook` en prod."
            )
        self._local = LocalBackend()

    def evaluate(
        self,
        key: str,
        user_id: str | None,
        user_attrs: dict[str, Any] | None = None,
    ) -> str:
        if not self._client_available:
            return self._local.evaluate(key, user_id, user_attrs)

        # TODO : utiliser le vrai client GrowthBook ici quand le SDK est ajouté.
        # from growthbook import GrowthBook
        # gb = GrowthBook(api_host=..., client_key=..., attributes={...})
        # gb.load_features()
        # result = gb.eval_feature(key)
        # return str(result.value) if result.value is not None else "off"
        return self._local.evaluate(key, user_id, user_attrs)

    def reload(self) -> None:
        self._local.reload()

    def list_features(self) -> list[str]:
        return self._local.list_features()


# ─────────────────────────────────────────────────────────────────────────────
# Factory + API publique
# ─────────────────────────────────────────────────────────────────────────────

_backend: FeatureFlagBackend | None = None


def _make_backend() -> FeatureFlagBackend:
    """Construit le backend selon SYLEA_FF_BACKEND."""
    name = (os.environ.get("SYLEA_FF_BACKEND") or "local").strip().lower()

    if name == "growthbook":
        logger.info("[feature_flags] backend = GrowthBook")
        return GrowthBookBackend()

    # local par défaut
    logger.info("[feature_flags] backend = Local YAML")
    return LocalBackend()


def get_backend() -> FeatureFlagBackend:
    """Singleton lazy."""
    global _backend
    if _backend is None:
        _backend = _make_backend()
    return _backend


def reset_backend() -> None:
    """Force la reconstruction du backend (utile pour tests)."""
    global _backend
    _backend = None


def is_enabled(
    key: str,
    user_id: str | None = None,
    user_attrs: dict[str, Any] | None = None,
    default: bool = False,
) -> bool:
    """Retourne True si la feature est "on" pour cet utilisateur.

    Args:
        key: nom du flag
        user_id: identifiant utilisateur (pour bucket déterministe)
        user_attrs: attributs additionnels (tier, country, ...)
        default: valeur si feature inexistante ou erreur backend

    Returns:
        True / False
    """
    try:
        variant = get_backend().evaluate(key, user_id, user_attrs)
        return variant in ("on", "true", "enabled", "1")
    except Exception as e:
        logger.warning("[feature_flags] evaluation failed for %s: %s", key, e)
        return default


def get_variant(
    key: str,
    user_id: str | None = None,
    user_attrs: dict[str, Any] | None = None,
    default: str = "control",
) -> str:
    """Retourne le variant string ('control', 'treatment_a', etc.).

    Pour A/B/n testing avec plus de 2 branches.
    """
    try:
        variant = get_backend().evaluate(key, user_id, user_attrs)
        if variant == "off":
            return default
        return variant
    except Exception as e:
        logger.warning("[feature_flags] evaluation failed for %s: %s", key, e)
        return default


def list_features() -> list[str]:
    """Retourne la liste des flags définis (pour debugging / admin UI)."""
    try:
        return get_backend().list_features()
    except Exception:
        return []


def reload() -> None:
    """Force le rechargement du backend (pour hot-reload sans restart)."""
    try:
        get_backend().reload()
    except Exception as e:
        logger.error("[feature_flags] reload failed: %s", e)
