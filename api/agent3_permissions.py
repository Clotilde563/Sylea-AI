"""
Agent 3 — Systeme de permissions par action.

Inspire ethiquement du modele de permissions de Claude Code :
chaque action du BrowserAgent est classee par niveau de risque, et
l'utilisateur choisit un mode de permission global.

Modes :
  default         — demande confirmation pour toute action destructive
  plan            — n'execute rien, genere un plan affiche a l'user
  auto_safe       — execute safe et caution sans demander, bloque destructive
  bypass          — execute tout sans jamais demander (mode "power user",
                    documente comme risque aux yeux de l'utilisateur)

L'utilisateur peut aussi definir des whitelists/blacklists de domaines
(ex: jamais de destructive sur banque.com, toujours OK sur localhost).

Reimplementation Python from scratch pour Sylea.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from urllib.parse import urlparse

from api.agent3_plan_mode import RiskLevel

logger = logging.getLogger("sylea.agent3.permissions")


# ── Modes de permission ──────────────────────────────────────────────────────

class PermissionMode(str, Enum):
    DEFAULT = "default"          # Demande pour destructive
    PLAN = "plan"                # Plan Mode : dry-run
    AUTO_SAFE = "auto_safe"      # Auto pour safe+caution, bloque destructive
    BYPASS = "bypass"            # Autorise tout


# ── Decisions ────────────────────────────────────────────────────────────────

class Decision(str, Enum):
    ALLOW = "allow"                  # Action autorisee, continuer
    ASK_USER = "ask_user"            # Suspendre et demander confirmation
    DENY = "deny"                    # Bloquer definitivement
    DEFER_TO_PLAN = "defer_to_plan"  # On n'execute pas, on doit planifier


@dataclass
class PermissionResult:
    decision: Decision
    reason: str = ""
    risk: RiskLevel = RiskLevel.SAFE
    action: str = ""
    confirmation_prompt: str = ""   # Texte a afficher si ASK_USER


# ── Classifier : action -> risque ────────────────────────────────────────────

# Keywords dans les textes/URLs qui augmentent le risque d'une action
_DESTRUCTIVE_URL_HINTS = (
    "checkout", "payment", "pay", "billing", "buy", "purchase",
    "delete", "remove", "drop", "destroy",
    "logout", "signout", "disable",
    "admin", "settings/security", "password",
    "transfer", "withdraw", "wire",
    "confirm-order", "place-order", "submit-order",
)

_DESTRUCTIVE_TEXT_HINTS = (
    "supprimer", "delete", "remove", "effacer", "purger",
    "acheter", "buy now", "place order", "commander",
    "payer", "pay now", "confirmer achat",
    "envoyer", "send", "publier", "publish", "post",
    "se deconnecter", "logout", "sign out",
    "resilier", "cancel subscription", "close account",
)

_DESTRUCTIVE_KEYS = (
    # Keyboard shortcuts qui peuvent vider du contenu / supprimer
    "control+a+delete", "ctrl+a+delete",
    # Ctrl+S + overwrite, Ctrl+Shift+Delete (historique), Alt+F4
    "alt+f4", "control+shift+delete",
)

_CAUTION_TEXT_HINTS = (
    "submit", "envoyer", "save", "sauvegarder", "valider",
)


def _classify_text_risk(text: str) -> RiskLevel:
    """Examine du texte (contenu tape, texte de bouton) pour detecter du destructif."""
    if not text:
        return RiskLevel.SAFE
    t = text.lower()
    for hint in _DESTRUCTIVE_TEXT_HINTS:
        if hint in t:
            return RiskLevel.DESTRUCTIVE
    for hint in _CAUTION_TEXT_HINTS:
        if hint in t:
            return RiskLevel.CAUTION
    return RiskLevel.SAFE


def _classify_url_risk(url: str) -> RiskLevel:
    if not url:
        return RiskLevel.SAFE
    u = url.lower()
    for hint in _DESTRUCTIVE_URL_HINTS:
        if hint in u:
            return RiskLevel.DESTRUCTIVE
    return RiskLevel.SAFE


def _classify_key_risk(key: str) -> RiskLevel:
    if not key:
        return RiskLevel.SAFE
    k = key.lower().replace(" ", "")
    for hint in _DESTRUCTIVE_KEYS:
        if hint in k:
            return RiskLevel.CAUTION  # Destructif potentiel mais pas confirme
    # Enter apres un form = submit potentiel
    if k in ("enter", "return"):
        return RiskLevel.CAUTION
    return RiskLevel.SAFE


def classify_action(action: str, params: dict, current_url: str = "") -> RiskLevel:
    """Classe une action BrowserAgent (click/type/goto/press/...) par risque.

    Heuristique multi-signal :
    - Type d'action (goto=safe, click=caution, etc.)
    - Contexte URL (banque / checkout => destructif)
    - URL cible d'un goto (navigation vers /checkout => caution)
    - Texte saisi (si 'envoyer'/'payer' => destructif)
    - Touche appuyee (Enter sur formulaire => caution)
    """
    action = (action or "").lower()
    url_risk = _classify_url_risk(current_url)

    # Baseline par type d'action
    if action in ("wait", "screenshot"):
        base = RiskLevel.SAFE
    elif action == "scroll":
        base = RiskLevel.SAFE
    elif action == "goto":
        # Navigation : on regarde aussi l'URL cible
        target_risk = _classify_url_risk(params.get("url", ""))
        base = target_risk if target_risk != RiskLevel.SAFE else RiskLevel.SAFE
    elif action in ("click",):
        base = RiskLevel.CAUTION
    elif action in ("type", "select_all_and_type"):
        base = RiskLevel.CAUTION
    elif action in ("press",):
        base = _classify_key_risk(params.get("key", ""))
    elif action in ("done", "need_user"):
        base = RiskLevel.SAFE
    else:
        base = RiskLevel.CAUTION

    # Texte tape : regarde si destructif
    text = params.get("text", "")
    text_risk = _classify_text_risk(text)

    # On prend le max
    levels = [base, url_risk, text_risk]
    order = [RiskLevel.SAFE, RiskLevel.CAUTION, RiskLevel.DESTRUCTIVE]
    return max(levels, key=order.index)


# ── Policy ───────────────────────────────────────────────────────────────────

@dataclass
class PermissionPolicy:
    """Policy effective pour une session Agent 3."""
    mode: PermissionMode = PermissionMode.DEFAULT
    # Domaines ou on exige toujours confirmation (ex: banque.com)
    always_ask_domains: set[str] = field(default_factory=set)
    # Domaines de confiance (bypass auto) — use avec precaution
    trusted_domains: set[str] = field(default_factory=set)
    # Domaines totalement bloques
    blocked_domains: set[str] = field(default_factory=set)
    # Compteur d'actions destructives dans la session (quota)
    destructive_count: int = 0
    destructive_quota: int = 5  # Max 5 destructive dans une session sans reset

    @staticmethod
    def _domain_of(url: str) -> str:
        try:
            p = urlparse(url)
            return (p.hostname or "").lower()
        except Exception:
            return ""

    def _domain_matches(self, url: str, domains: set[str]) -> bool:
        if not url or not domains:
            return False
        host = self._domain_of(url)
        if not host:
            return False
        for d in domains:
            d = d.lower().lstrip(".")
            if host == d or host.endswith("." + d):
                return True
        return False

    def evaluate(self, action: str, params: dict, current_url: str = "") -> PermissionResult:
        """Retourne la decision (ALLOW / ASK_USER / DENY / DEFER_TO_PLAN)."""
        # Domaine bloque = DENY immediat
        if self._domain_matches(current_url, self.blocked_domains):
            return PermissionResult(
                decision=Decision.DENY,
                reason=f"Domaine bloque : {self._domain_of(current_url)}",
                action=action,
                risk=RiskLevel.DESTRUCTIVE,
            )

        # Mode PLAN = on n'execute rien
        if self.mode == PermissionMode.PLAN:
            return PermissionResult(
                decision=Decision.DEFER_TO_PLAN,
                reason="Mode Plan actif : genere un plan, pas d'execution",
                action=action,
            )

        # Mode BYPASS = tout passe (sauf domaines bloques deja traites)
        if self.mode == PermissionMode.BYPASS:
            return PermissionResult(
                decision=Decision.ALLOW,
                reason="Mode bypass",
                action=action,
            )

        risk = classify_action(action, params, current_url)

        # Domaines de confiance : on ne demande qu'en cas de DESTRUCTIVE
        if self._domain_matches(current_url, self.trusted_domains):
            if risk == RiskLevel.DESTRUCTIVE:
                # Toujours demander pour destructive, meme en trusted
                return self._ask(action, params, current_url, risk)
            return PermissionResult(
                decision=Decision.ALLOW,
                reason=f"Domaine de confiance + risque {risk.value}",
                risk=risk,
                action=action,
            )

        # Domaines "always_ask" : demande systematique si caution+
        if self._domain_matches(current_url, self.always_ask_domains):
            if risk != RiskLevel.SAFE:
                return self._ask(action, params, current_url, risk)

        # Mode AUTO_SAFE : bloque destructive, autorise le reste
        if self.mode == PermissionMode.AUTO_SAFE:
            if risk == RiskLevel.DESTRUCTIVE:
                return self._ask(action, params, current_url, risk)
            return PermissionResult(
                decision=Decision.ALLOW,
                reason="Mode auto_safe",
                risk=risk,
                action=action,
            )

        # Mode DEFAULT : ask sur destructive
        if risk == RiskLevel.DESTRUCTIVE:
            # Quota atteint = DENY
            if self.destructive_count >= self.destructive_quota:
                return PermissionResult(
                    decision=Decision.DENY,
                    reason=f"Quota destructif atteint ({self.destructive_quota}). "
                           "Relance l'agent pour reinitialiser.",
                    risk=risk,
                    action=action,
                )
            return self._ask(action, params, current_url, risk)

        return PermissionResult(
            decision=Decision.ALLOW,
            reason="Risque acceptable",
            risk=risk,
            action=action,
        )

    def _ask(self, action: str, params: dict, current_url: str, risk: RiskLevel) -> PermissionResult:
        prompt = self._build_prompt(action, params, current_url, risk)
        return PermissionResult(
            decision=Decision.ASK_USER,
            reason=f"Action {risk.value} detectee",
            risk=risk,
            action=action,
            confirmation_prompt=prompt,
        )

    @staticmethod
    def _build_prompt(action: str, params: dict, current_url: str, risk: RiskLevel) -> str:
        """Texte lisible pour la popup de confirmation user."""
        if action == "click":
            x, y = params.get("x", "?"), params.get("y", "?")
            return f"Clic en ({x},{y}) sur {current_url or 'la page'} ({risk.value}). Autoriser ?"
        if action in ("type", "select_all_and_type"):
            t = params.get("text", "")[:60]
            return f"Saisir '{t}{'...' if len(params.get('text','')) > 60 else ''}' ({risk.value}). Autoriser ?"
        if action == "press":
            return f"Appuyer sur '{params.get('key','?')}' ({risk.value}). Autoriser ?"
        if action == "goto":
            return f"Naviguer vers {params.get('url','?')} ({risk.value}). Autoriser ?"
        return f"Executer action '{action}' ({risk.value}). Autoriser ?"

    def record_destructive(self):
        self.destructive_count += 1


# ── Registry par user ────────────────────────────────────────────────────────

_policies: dict[str, PermissionPolicy] = {}


def get_policy(user_id: str = "default") -> PermissionPolicy:
    if user_id not in _policies:
        _policies[user_id] = PermissionPolicy()
    return _policies[user_id]


def set_mode(user_id: str, mode: PermissionMode) -> PermissionPolicy:
    p = get_policy(user_id)
    p.mode = mode
    logger.info(f"Permission mode changed for {user_id}: {mode.value}")
    return p


def reset_counters(user_id: str = "default"):
    p = get_policy(user_id)
    p.destructive_count = 0
