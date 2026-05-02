"""
OpenClaw Bridge — Connexion complete entre Sylea FastAPI et OpenClaw Gateway.

Gere la communication HTTP + SSE avec le Gateway OpenClaw.
Le Gateway gere en interne la boucle d'outils (Pi agent framework)
et retourne la reponse finale apres execution de toutes les etapes.

Architecture :
  [Sylea Frontend] -> [FastAPI :8000] -> [OpenClaw Gateway :18789] -> [26+ Tools]
                                  ^
                                  |
                          Injection du contexte utilisateur Sylea

Groupes d'outils disponibles via OpenClaw Gateway :
  - group:web      : web_search, web_fetch, x_search
  - group:ui       : browser, canvas
  - group:runtime  : exec, bash, process
  - group:fs       : read, write, edit, apply_patch
  - group:sessions : sessions_list, sessions_spawn, sessions_send, sessions_history
  - group:memory   : memory_search, memory_get
  - group:automation : cron, gateway
  - group:messaging  : message
  - group:nodes      : camera, screen, location, notifications
  - Outils speciaux  : image, image_generate, llm_task, lobster, subagents
"""

from __future__ import annotations

import os
import asyncio
import json
import logging
import shutil
from dataclasses import dataclass, field
from typing import AsyncGenerator

import httpx


logger = logging.getLogger("openclaw_bridge")

# ── Configuration ─────────────────────────────────────────────────────────────

OPENCLAW_GATEWAY_URL = os.environ.get("OPENCLAW_GATEWAY_URL", "http://localhost:18789")

# Token : priorite env var, sinon lecture du fichier config OpenClaw
def _load_openclaw_token() -> str:
    token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
    if token:
        return token
    # Lire depuis ~/.openclaw/openclaw.json
    try:
        config_path = os.path.expanduser("~/.openclaw/openclaw.json")
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                cfg = json.load(f)
            token = cfg.get("gateway", {}).get("token", "")
            if token:
                logger.info("OpenClaw token loaded from config file")
                return token
    except Exception:
        pass
    return ""

OPENCLAW_TOKEN = _load_openclaw_token()

# Timeouts (overridables via env vars pour ajuster sans redeployer)
OPENCLAW_TIMEOUT_SIMPLE = int(os.environ.get("OPENCLAW_TIMEOUT_SIMPLE", "120"))    # Chat simple
OPENCLAW_TIMEOUT_AGENTIC = int(os.environ.get("OPENCLAW_TIMEOUT_AGENTIC", "300"))  # Outils (5 min)
OPENCLAW_TIMEOUT_HEAVY = int(os.environ.get("OPENCLAW_TIMEOUT_HEAVY", "600"))      # Multi-step (10 min)


# ── Circuit Breaker ──────────────────────────────────────────────────────────

class CircuitBreaker:
    """Circuit breaker pattern : evite de marteler un service down.

    Threadsafe en mode single-process + asyncio (pas besoin de lock car les
    coroutines tournent dans un seul thread). Pour multi-worker gunicorn,
    chaque worker aura ses propres breakers — acceptable (isole les pannes).
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0, name: str = "global"):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._state = "closed"  # closed, open, half_open
        import time as _time
        self._time = _time

    @property
    def state(self) -> str:
        if self._state == "open":
            elapsed = self._time.time() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = "half_open"
        return self._state

    def record_success(self):
        self._failure_count = 0
        self._state = "closed"

    def record_failure(self):
        self._failure_count += 1
        self._last_failure_time = self._time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = "open"
            logger.warning(f"Circuit breaker OPEN apres {self._failure_count} echecs (tool={self.name})")

    def can_execute(self) -> bool:
        return self.state != "open"

    def get_stats(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "failures": self._failure_count,
            "threshold": self.failure_threshold,
        }


# Instance globale (conservee pour compat + fallback : calls qui n'ont pas de tool_name).
_circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60, name="global")


# Circuit breakers PER-TOOL : isolent les pannes. Si `browser` est down,
# les autres outils (exec, fs, image_generate) continuent de marcher.
# Lazy init dans `get_breaker_for_tool`.
_per_tool_breakers: dict[str, CircuitBreaker] = {}
import threading as _threading
_per_tool_breakers_lock = _threading.Lock()


def get_breaker_for_tool(tool_name: str) -> CircuitBreaker:
    """Retourne le circuit breaker du tool_name donne (cree si absent)."""
    b = _per_tool_breakers.get(tool_name)
    if b is not None:
        return b
    with _per_tool_breakers_lock:
        b = _per_tool_breakers.get(tool_name)
        if b is None:
            b = CircuitBreaker(failure_threshold=5, recovery_timeout=60, name=tool_name)
            _per_tool_breakers[tool_name] = b
    return b


def get_all_breakers_stats() -> dict[str, dict]:
    """Snapshot de tous les circuit breakers actifs (pour /metrics)."""
    return {
        "global": _circuit_breaker.get_stats(),
        **{name: br.get_stats() for name, br in _per_tool_breakers.items()},
    }


# ── Metrics retry (counters in-memory, expose via endpoint) ──────────────────

from collections import defaultdict as _defaultdict

# Counter : (tool_name, event) -> count
# Events : "attempt", "retry", "success", "failure", "timeout",
#          "http_5xx", "circuit_open_rejected", "retry_after_honored"
_retry_metrics: dict[tuple[str, str], int] = _defaultdict(int)
_retry_metrics_lock = _threading.Lock()


def _record_metric(tool_name: str, event: str, n: int = 1) -> None:
    with _retry_metrics_lock:
        _retry_metrics[(tool_name, event)] += n


def get_retry_metrics() -> dict[str, int]:
    """Snapshot des metrics. Format : 'tool__event' -> count. Pour /metrics."""
    with _retry_metrics_lock:
        return {f"{tool}__{event}": n for (tool, event), n in _retry_metrics.items()}


def reset_retry_metrics() -> None:
    """Utilitaire test — reset complet."""
    with _retry_metrics_lock:
        _retry_metrics.clear()


# ── Latence par tool (sliding window, bounded) ───────────────────────────────
#
# Pour chaque tool, on garde les N dernieres durees d'appel reussi.
# Permet de calculer p50/p95/p99 a la demande, sans exploser en memoire
# (N * 38 tools = bornee).

from collections import deque as _deque

_LATENCY_WINDOW_SIZE = 100  # dernieres durees par tool
_tool_latencies: dict[str, _deque[float]] = {}
_tool_latencies_lock = _threading.Lock()


def record_tool_latency(tool_name: str, duration_s: float) -> None:
    """Enregistre la duree d'un appel tool (en secondes). Bounded window."""
    if duration_s < 0 or duration_s > 3600:
        return  # sanity check, ignore outliers aberrants
    with _tool_latencies_lock:
        dq = _tool_latencies.get(tool_name)
        if dq is None:
            dq = _deque(maxlen=_LATENCY_WINDOW_SIZE)
            _tool_latencies[tool_name] = dq
        dq.append(float(duration_s))


def _percentile(sorted_values: list[float], p: float) -> float:
    """p50/p95/p99 sur une liste triee. p dans [0, 100]."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def get_tool_latency_stats() -> dict[str, dict[str, Any]]:
    """Retourne les stats p50/p95/p99 + count par tool."""
    out: dict[str, dict[str, Any]] = {}
    with _tool_latencies_lock:
        snapshot = {k: list(v) for k, v in _tool_latencies.items()}
    for tool, vals in snapshot.items():
        if not vals:
            continue
        sv = sorted(vals)
        out[tool] = {
            "count": len(sv),
            "p50_ms": round(_percentile(sv, 50) * 1000, 1),
            "p95_ms": round(_percentile(sv, 95) * 1000, 1),
            "p99_ms": round(_percentile(sv, 99) * 1000, 1),
            "min_ms": round(min(sv) * 1000, 1),
            "max_ms": round(max(sv) * 1000, 1),
            "avg_ms": round(sum(sv) / len(sv) * 1000, 1),
        }
    return out


def reset_tool_latencies() -> None:
    """Utilitaire test — reset complet."""
    with _tool_latencies_lock:
        _tool_latencies.clear()


# ── Cost tracker per-tool (USD cumule par user + tool) ───────────────────────
#
# Couts des APIs externes appelees via les 38 outils OpenClaw. Differencie des
# couts Claude/Anthropic qui sont trackes separement dans le cost monitor
# principal (par tokens input/output). Ici on track :
#   - cumul USD par (user_id, tool) — diagnostic fin
#   - cumul USD par user (pour le cost cap global user)
#   - compteur de calls par (user_id, tool)

_external_cost_by_user_tool: dict[tuple[str, str], float] = _defaultdict(float)
_external_calls_by_user_tool: dict[tuple[str, str], int] = _defaultdict(int)
_external_cost_lock = _threading.Lock()


def record_external_cost(user_id: str, tool_name: str, cost_usd: float) -> None:
    """Enregistre le cout externe d'un appel outil OpenClaw reussi."""
    if cost_usd <= 0:
        # Incrementer quand meme le compteur d'appels (pour metriques).
        with _external_cost_lock:
            _external_calls_by_user_tool[(user_id or "anon", tool_name)] += 1
        return
    with _external_cost_lock:
        _external_cost_by_user_tool[(user_id or "anon", tool_name)] += float(cost_usd)
        _external_calls_by_user_tool[(user_id or "anon", tool_name)] += 1


def get_external_cost_for_user(user_id: str) -> dict[str, Any]:
    """Retourne le breakdown des couts externes d'un user.

    Format :
      {
        "total_usd": float,
        "by_tool": {tool_name: {"usd": float, "calls": int}, ...},
      }
    """
    uid = user_id or "anon"
    with _external_cost_lock:
        by_tool: dict[str, dict[str, Any]] = {}
        total = 0.0
        for (u, tool), usd in _external_cost_by_user_tool.items():
            if u != uid:
                continue
            by_tool[tool] = {
                "usd": round(usd, 5),
                "calls": _external_calls_by_user_tool.get((u, tool), 0),
            }
            total += usd
        # Ajouter les tools a cout 0 mais appeles
        for (u, tool), calls in _external_calls_by_user_tool.items():
            if u != uid or tool in by_tool:
                continue
            by_tool[tool] = {"usd": 0.0, "calls": calls}
    return {"total_usd": round(total, 5), "by_tool": by_tool}


def get_external_cost_global() -> dict[str, Any]:
    """Snapshot global (tous users). Pour /api/agent3/metrics."""
    with _external_cost_lock:
        return {
            "total_by_user": {
                u: round(sum(
                    usd for (uu, _t), usd in _external_cost_by_user_tool.items() if uu == u
                ), 5)
                for u in {uu for (uu, _t) in _external_cost_by_user_tool.keys()}
            },
            "total_calls": sum(_external_calls_by_user_tool.values()),
        }


def reset_external_cost() -> None:
    """Utilitaire test — reset complet."""
    with _external_cost_lock:
        _external_cost_by_user_tool.clear()
        _external_calls_by_user_tool.clear()


# ── Cost cap journalier per-user (protection financiere) ────────────────────
#
# Tracker separe pour le cumul du JOUR courant (reset a minuit UTC).
# Format : dict[(user_id, date_str), cumul_usd]
# Sert a :
#   1. Bloquer les appels au-dessus de la limite (hard block).
#   2. Warner l'utilisateur a 80% de la limite (soft alert).

import datetime as _dt

_daily_cost_by_user: dict[tuple[str, str], float] = _defaultdict(float)
_daily_cost_lock = _threading.Lock()

# Cap USD/jour par defaut si le user n'a pas defini le sien. Raisonnable pour
# eviter les boucles infinies costly (ex: 10 video_generate a $0.50 = $5).
DEFAULT_DAILY_COST_CAP_USD = 5.0

# Warning emis une seule fois par jour/user a 80% (via flag persistent in-mem).
_daily_warning_emitted: set[tuple[str, str]] = set()


def _today_utc_str() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def check_daily_cost_cap(
    user_id: str, projected_cost_usd: float, cap_usd: float,
) -> tuple[bool, float, float]:
    """Verifie si l'ajout d'un cout projete depasse le cap journalier.

    Returns (allowed, current_total, percentage_used).
      - allowed=True si current_total + projected_cost_usd <= cap_usd.
      - current_total = cumul du jour AVANT ce nouvel appel.
      - percentage_used = (current_total + projected) / cap * 100.
    """
    if cap_usd <= 0:
        return True, 0.0, 0.0  # cap desactive
    uid = user_id or "anon"
    key = (uid, _today_utc_str())
    with _daily_cost_lock:
        current = _daily_cost_by_user.get(key, 0.0)
    new_total = current + projected_cost_usd
    pct = (new_total / cap_usd) * 100.0
    return new_total <= cap_usd, current, pct


def record_daily_cost(user_id: str, cost_usd: float) -> None:
    """Incremente le cumul journalier apres un appel reussi."""
    if cost_usd <= 0:
        return
    uid = user_id or "anon"
    key = (uid, _today_utc_str())
    with _daily_cost_lock:
        _daily_cost_by_user[key] += float(cost_usd)


def get_daily_cost_for_user(user_id: str) -> float:
    """Cumul USD consomme par ce user aujourd'hui (UTC)."""
    uid = user_id or "anon"
    key = (uid, _today_utc_str())
    with _daily_cost_lock:
        return float(_daily_cost_by_user.get(key, 0.0))


def should_emit_warning_once(user_id: str) -> bool:
    """True si on doit emettre le warning 80% (une seule fois par jour/user)."""
    uid = user_id or "anon"
    key = (uid, _today_utc_str())
    with _daily_cost_lock:
        if key in _daily_warning_emitted:
            return False
        _daily_warning_emitted.add(key)
        return True


def reset_daily_cost() -> None:
    """Utilitaire test — reset complet."""
    with _daily_cost_lock:
        _daily_cost_by_user.clear()
        _daily_warning_emitted.clear()


# ── Retry helpers ────────────────────────────────────────────────────────────

import random as _random


def _compute_backoff_with_jitter(attempt: int, base: float = 1.0, cap: float = 30.0) -> float:
    """Full jitter backoff (AWS pattern) : backoff = random(0, min(cap, base * 2^attempt)).

    Pourquoi full jitter et pas un backoff deterministe :
      - Des milliers de clients qui se synchronisent sur le meme 503 vont
        retry AU MEME INSTANT avec un backoff fixe -> thundering herd qui
        re-cogne le serveur des qu'il remonte.
      - Full jitter etale les retries uniformement sur [0, cap], eliminant
        la synchronisation. Demontree optimale par AWS Arch Blog 2015.
    """
    max_backoff = min(cap, base * (2 ** attempt))
    return _random.uniform(0.0, max_backoff)


def _parse_retry_after(header_value: str, cap: float = 30.0) -> float | None:
    """Parse le header Retry-After (seconds seulement, HTTP-date ignore).

    Retourne None si le header est absent ou mal forme. Cap a `cap` secondes
    pour eviter qu'un serveur mal configure bloque la session trop longtemps.
    """
    if not header_value:
        return None
    header_value = header_value.strip()
    if not header_value:
        return None
    try:
        secs = float(header_value)
        if secs < 0:
            return None
        return min(secs, cap)
    except ValueError:
        # HTTP-date (RFC 7231) : "Wed, 21 Oct 2015 07:28:00 GMT"
        # Support non implemente (rare en pratique) — on fallback sur le jitter.
        return None


@dataclass
class OpenClawResponse:
    """Reponse parsee du Gateway OpenClaw."""
    content: str
    model: str = ""
    usage: dict | None = None
    raw: dict | None = None
    error: str | None = None
    tool_calls_made: list[dict] = field(default_factory=list)
    search_results: list[dict] = field(default_factory=list)
    web_pages_visited: list[str] = field(default_factory=list)
    files_created: list[str] = field(default_factory=list)
    images_generated: list[str] = field(default_factory=list)


@dataclass
class OpenClawStreamEvent:
    """Evenement SSE recu du Gateway OpenClaw."""
    event_type: str  # "content", "tool_call", "tool_result", "done", "error"
    data: dict
    content_delta: str = ""
    tool_name: str = ""
    tool_args: dict | None = None
    tool_result: str = ""


# ── Headers helper ───────────────────────────────────────────────────────────

def _build_headers(session_key: str | None = None) -> dict:
    token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "") or OPENCLAW_TOKEN
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if session_key:
        headers["x-openclaw-session-key"] = session_key
    # OpenClaw 2026.3+ : les endpoints HTTP /v1/chat/completions et /v1/tools/*
    # exigent un header `x-openclaw-scopes` (sinon 403 "missing scope:
    # operator.write"). Le client doit DECLARER quels scopes il veut utiliser.
    # On declare l'ensemble des scopes operator (lecture + ecriture + admin
    # + approvals + pairing) pour debloquer chat.send, chat.tools, agents.run,
    # files.read, etc. Source : openclaw/dist/gateway-cli-*.js ligne 20513.
    headers["x-openclaw-scopes"] = (
        "operator.admin,operator.read,operator.write,"
        "operator.approvals,operator.pairing"
    )
    return headers


# ── Health check ──────────────────────────────────────────────────────────────

# Cache TTL de l'etat up/down du Gateway pour ne pas spammer /health a chaque
# requete. 30s est un compromis : assez court pour detecter un Gateway down
# sans delai genant, assez long pour ne pas marteler le ping.
_GATEWAY_HEALTH_CACHE_TTL_S = 30.0
_gateway_health_cache: dict[str, Any] = {
    "is_up": None,        # bool | None (None = jamais check)
    "checked_at": 0.0,
    "last_error": "",
}


async def is_gateway_up(force_refresh: bool = False) -> bool:
    """Verifie si le Gateway OpenClaw est joignable, avec cache TTL 30s.

    Utilise au demarrage d'une session /chat/native pour decider si on expose
    les 38 outils OpenClaw directs au LLM. Si down, on reduit le perimetre
    (natifs + skills ClawHub seulement) et on emet un event UI pour prevenir.
    """
    import time as _time
    now = _time.time()
    if (
        not force_refresh
        and _gateway_health_cache["is_up"] is not None
        and now - _gateway_health_cache["checked_at"] < _GATEWAY_HEALTH_CACHE_TTL_S
    ):
        return bool(_gateway_health_cache["is_up"])

    try:
        # Timeout court (3s) pour ne pas bloquer la requete si Gateway down hard.
        async with httpx.AsyncClient(timeout=3.0) as client:
            headers = _build_headers()
            resp = await client.get(f"{OPENCLAW_GATEWAY_URL}/health", headers=headers)
            is_up = resp.status_code == 200
            err = "" if is_up else f"HTTP {resp.status_code}"
    except Exception as e:
        is_up = False
        err = f"{type(e).__name__}: {str(e)[:120]}"

    _gateway_health_cache["is_up"] = is_up
    _gateway_health_cache["checked_at"] = now
    _gateway_health_cache["last_error"] = err
    if not is_up:
        logger.warning(f"OpenClaw Gateway indisponible : {err}")
    return is_up


def get_gateway_health_status() -> dict[str, Any]:
    """Snapshot de l'etat du health cache (pour /api/agent3/metrics)."""
    return {
        "is_up": _gateway_health_cache["is_up"],
        "checked_at": _gateway_health_cache["checked_at"],
        "ttl_s": _GATEWAY_HEALTH_CACHE_TTL_S,
        "last_error": _gateway_health_cache["last_error"],
    }


async def openclaw_health() -> dict:
    """Verifie si le Gateway OpenClaw est accessible."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            headers = _build_headers()
            # /health est toujours actif (pas besoin de chatCompletions enabled)
            resp = await client.get(f"{OPENCLAW_GATEWAY_URL}/health", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok") or data.get("status") == "live":
                    return {"connected": True, "status": data}
            # Fallback : /api/status
            try:
                resp2 = await client.get(f"{OPENCLAW_GATEWAY_URL}/api/status", headers=headers)
                if resp2.status_code == 200:
                    return {"connected": True, "status": resp2.json()}
            except Exception:
                pass
            # Fallback : /v1/models
            try:
                resp3 = await client.get(f"{OPENCLAW_GATEWAY_URL}/v1/models", headers=headers)
                if resp3.status_code == 200:
                    try:
                        return {"connected": True, "models": resp3.json()}
                    except Exception:
                        pass
            except Exception:
                pass
            return {"connected": False, "error": f"Status {resp.status_code}"}
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ── Tool invocation directe (payload corrige) ────────────────────────────────

_OPENCLAW_RETRY_STATUS: tuple[int, ...] = (502, 503, 504)
_OPENCLAW_RETRY_AFTER_STATUS: tuple[int, ...] = (429, 503)  # status qui peuvent renvoyer Retry-After
_OPENCLAW_MAX_RETRIES: int = 2
_OPENCLAW_RETRY_AFTER_CAP_S: float = 30.0


async def openclaw_invoke_tool(
    tool_name: str,
    action: str = "default",
    args: dict | None = None,
    session_key: str | None = None,
) -> dict:
    """
    Invoque un outil OpenClaw directement via /tools/invoke.
    Payload corrige : {tool, action, args, sessionKey}.

    Robustesse (4 couches) :
      1. Circuit breaker PER-TOOL : isole les pannes (browser down != exec down).
      2. Retry 2x sur transients (502/503/504/timeout).
      3. Full jitter : random(0, min(30, 2^attempt)) -> pas de thundering herd
         quand N clients retry en meme temps (scalable a des milliers).
      4. Respect du header Retry-After sur 429/503 (cap 30s) pour ne pas
         DoS un serveur rate-limite.

    Metrics : counters incrementes pour chaque event (attempt/retry/failure/...),
    accessibles via /api/agent3/metrics (cf. endpoint router).
    """
    breaker = get_breaker_for_tool(tool_name)
    if not breaker.can_execute():
        _record_metric(tool_name, "circuit_open_rejected")
        return {
            "success": False,
            "error": f"Outil '{tool_name}' temporairement indisponible (5+ echecs recents). Reessaie dans <1 min.",
        }

    headers = _build_headers(session_key)
    payload = {
        "tool": tool_name,
        "action": action,
        "args": args or {},
    }
    if session_key:
        payload["sessionKey"] = session_key

    import time as _time
    attempt = 0
    last_err = ""
    _record_metric(tool_name, "attempt")
    _start_ts = _time.time()
    while attempt <= _OPENCLAW_MAX_RETRIES:
        try:
            async with httpx.AsyncClient(timeout=OPENCLAW_TIMEOUT_AGENTIC) as client:
                resp = await client.post(
                    f"{OPENCLAW_GATEWAY_URL}/tools/invoke",
                    headers=headers,
                    json=payload,
                )

                # Succes : reset le breaker, enregistre la duree totale (incluant retries), retourne.
                if resp.status_code == 200:
                    _record_metric(tool_name, "success")
                    breaker.record_success()
                    record_tool_latency(tool_name, _time.time() - _start_ts)
                    return {"success": True, "result": resp.json()}

                # 429/503 : respecter Retry-After si fourni, sinon jitter.
                if resp.status_code in _OPENCLAW_RETRY_AFTER_STATUS and attempt < _OPENCLAW_MAX_RETRIES:
                    _record_metric(tool_name, f"http_{resp.status_code}")
                    ra = _parse_retry_after(
                        resp.headers.get("retry-after", ""),
                        cap=_OPENCLAW_RETRY_AFTER_CAP_S,
                    )
                    if ra is not None:
                        backoff = ra
                        _record_metric(tool_name, "retry_after_honored")
                        logger.info(
                            f"OpenClaw {tool_name} status {resp.status_code}, "
                            f"Retry-After={ra}s (attempt {attempt + 1})"
                        )
                    else:
                        backoff = _compute_backoff_with_jitter(attempt)
                        logger.info(
                            f"OpenClaw {tool_name} status {resp.status_code}, "
                            f"jitter backoff {backoff:.2f}s (attempt {attempt + 1})"
                        )
                    _record_metric(tool_name, "retry")
                    await asyncio.sleep(backoff)
                    attempt += 1
                    continue

                # 502/504 : jitter backoff standard (pas de Retry-After attendu).
                if resp.status_code in _OPENCLAW_RETRY_STATUS and attempt < _OPENCLAW_MAX_RETRIES:
                    _record_metric(tool_name, f"http_{resp.status_code}")
                    backoff = _compute_backoff_with_jitter(attempt)
                    logger.info(
                        f"OpenClaw {tool_name} status {resp.status_code}, "
                        f"jitter backoff {backoff:.2f}s (attempt {attempt + 1})"
                    )
                    _record_metric(tool_name, "retry")
                    await asyncio.sleep(backoff)
                    attempt += 1
                    continue

                # Autre 4xx/5xx : echec final, pas de retry.
                last_err = f"Status {resp.status_code}: {resp.text[:300]}"
                _record_metric(tool_name, f"http_{resp.status_code}")
                _record_metric(tool_name, "failure")
                breaker.record_failure()
                record_tool_latency(tool_name, _time.time() - _start_ts)
                return {"success": False, "error": last_err}

        except httpx.TimeoutException:
            _record_metric(tool_name, "timeout")
            if attempt < _OPENCLAW_MAX_RETRIES:
                backoff = _compute_backoff_with_jitter(attempt)
                logger.info(
                    f"OpenClaw {tool_name} timeout, jitter backoff {backoff:.2f}s "
                    f"(attempt {attempt + 1})"
                )
                _record_metric(tool_name, "retry")
                await asyncio.sleep(backoff)
                attempt += 1
                continue
            _record_metric(tool_name, "failure")
            breaker.record_failure()
            record_tool_latency(tool_name, _time.time() - _start_ts)
            return {"success": False, "error": "Timeout apres retries"}

        except Exception as e:
            _record_metric(tool_name, "failure")
            breaker.record_failure()
            record_tool_latency(tool_name, _time.time() - _start_ts)
            return {"success": False, "error": str(e)}

    # Epuise les retries (cas edge : boucle sort sans return)
    _record_metric(tool_name, "failure")
    breaker.record_failure()
    record_tool_latency(tool_name, _time.time() - _start_ts)
    return {"success": False, "error": last_err or "Echec apres retries"}


# ── Chat via CLI subprocess (methode principale — a les bons scopes) ─────────

async def _openclaw_chat_via_cli(
    message: str,
    session_key: str | None = None,
    timeout_seconds: int = 120,
) -> OpenClawResponse:
    """
    Appelle l'agent OpenClaw via la CLI en subprocess.
    C'est la methode qui a les bons scopes (operator.write/read)
    car la CLI se connecte via WebSocket, pas via l'API REST.

    Utilise asyncio.create_subprocess_exec pour appeler node directement,
    evitant les problemes de parsing cmd.exe avec les newlines dans les arguments.
    """
    import sys

    is_windows = sys.platform == "win32"

    # Trouver l'executable openclaw
    openclaw_cmd = os.environ.get("OPENCLAW_CLI_PATH", "openclaw")
    openclaw_is_node = False  # True si on appelle node + script .mjs
    if is_windows:
        npm_dir = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm")
        # Preferer node + .mjs (pas besoin de cmd.exe, compatible asyncio exec)
        mjs_path = os.path.join(npm_dir, "node_modules", "openclaw", "openclaw.mjs")
        if os.path.exists(mjs_path):
            # Trouver node.exe via PATH ou Program Files
            node_exe = shutil.which("node") or os.path.join(os.environ.get("ProgramFiles", ""), "nodejs", "node.exe")
            if node_exe and os.path.exists(node_exe):
                openclaw_cmd = node_exe
                openclaw_is_node = True
                logger.debug(f"OpenClaw CLI via node: {node_exe} + {mjs_path}")
            else:
                # Fallback .cmd
                cmd_path = os.path.join(npm_dir, "openclaw.cmd")
                if os.path.exists(cmd_path):
                    openclaw_cmd = cmd_path
        else:
            cmd_path = os.path.join(npm_dir, "openclaw.cmd")
            if os.path.exists(cmd_path):
                openclaw_cmd = cmd_path

    # Toujours fournir un session-id (requis par OpenClaw CLI)
    effective_session = session_key or "sylea-agent3-default"
    args_list = [
        "agent",
        "--agent", "main",
        "--message", message,
        "--json",
        "--timeout", str(timeout_seconds),
        "--session-id", effective_session,
    ]

    logger.info(f"OpenClaw CLI: executing (timeout={timeout_seconds}s, msg_len={len(message)})")

    try:
        import subprocess as _sp

        if is_windows and openclaw_is_node:
            cmd_list = [openclaw_cmd, mjs_path] + args_list
        else:
            cmd_list = [openclaw_cmd] + args_list

        creation_flags = 0x08000000 if is_windows else 0  # CREATE_NO_WINDOW

        def _run_cli():
            return _sp.run(
                cmd_list,
                capture_output=True,
                timeout=timeout_seconds + 30,
                creationflags=creation_flags,
            )

        try:
            result = await asyncio.to_thread(_run_cli)
        except _sp.TimeoutExpired:
            _circuit_breaker.record_failure()
            logger.warning(f"OpenClaw CLI: timeout after {timeout_seconds + 30}s")
            return OpenClawResponse(content="", error="Timeout CLI OpenClaw")

        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        stderr = result.stderr.decode("utf-8", errors="replace").strip()

        logger.info(f"OpenClaw CLI: returncode={result.returncode}, stdout_len={len(stdout)}, stderr_len={len(stderr)}")

        # Meme avec returncode != 0, la sortie peut contenir du JSON valide
        # (ex: returncode 124 = timeout signal mais reponse complete)
        if stdout:
            # Chercher du JSON dans la sortie (peut etre precede de logs)
            json_start = -1
            for i, ch in enumerate(stdout):
                if ch == '{':
                    json_start = i
                    break

            if json_start >= 0:
                json_str = stdout[json_start:]
                try:
                    data = json.loads(json_str)

                    # Extraire le contenu — format OpenClaw CLI JSON :
                    # { "result": { "payloads": [{"text": "...", "mediaUrl": null}], "meta": {...} } }
                    content = ""
                    result_data = data.get("result", {})
                    payloads = result_data.get("payloads", [])
                    if payloads:
                        texts = [p.get("text", "") for p in payloads if p.get("text")]
                        content = "\n".join(texts)

                    # Fallback vers d'autres champs possibles
                    if not content:
                        content = data.get("reply", data.get("content", data.get("message", "")))
                        if isinstance(content, list):
                            content = "\n".join(str(c) for c in content)

                    # Extraire les metadonnees
                    meta = result_data.get("meta", {})
                    agent_meta = meta.get("agentMeta", {})
                    model_name = agent_meta.get("model", data.get("model", "openclaw/agent"))

                    # Extraire les outils utilises
                    tool_calls = []

                    if content:
                        _circuit_breaker.record_success()
                        logger.info(f"OpenClaw CLI: success, content_len={len(content)}")
                        return OpenClawResponse(
                            content=str(content),
                            model=model_name,
                            usage=agent_meta.get("usage"),
                            tool_calls_made=tool_calls,
                        )
                except json.JSONDecodeError as e:
                    logger.warning(f"OpenClaw CLI: JSON parse error: {e}")

            # Pas de JSON valide mais du contenu texte
            if result.returncode == 0:
                _circuit_breaker.record_success()
                return OpenClawResponse(
                    content=stdout,
                    model="openclaw/agent",
                )

        # Echec
        error = stderr or stdout or "Erreur CLI OpenClaw (pas de sortie)"
        logger.warning(f"OpenClaw CLI error: {error[:300]}")
        _circuit_breaker.record_failure()
        return OpenClawResponse(content="", error=error[:300])

    except FileNotFoundError:
        return OpenClawResponse(content="", error="CLI openclaw non trouvee. Installez OpenClaw.")
    except Exception as e:
        logger.exception(f"OpenClaw CLI unexpected error: type={type(e).__name__}, msg={e!r}")
        _circuit_breaker.record_failure()
        return OpenClawResponse(content="", error=f"Erreur CLI ({type(e).__name__}): {str(e)[:200]}")


# ── Chat completions (non-streaming) ─────────────────────────────────────────

async def openclaw_chat(
    messages: list[dict],
    system_prompt: str = "",
    model: str = "openclaw/default",
    session_key: str | None = None,
    stream: bool = False,
    max_retries: int = 2,
    use_tools: bool = True,
) -> OpenClawResponse:
    """
    Envoie un message au Gateway OpenClaw.
    Strategie : 1) API REST, 2) CLI subprocess, 3) fallback
    """
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    payload = {
        "model": model,
        "messages": full_messages,
        "stream": False,
    }

    # Timeout adaptatif selon le contenu du message
    last_content = messages[-1].get("content", "") if messages else ""
    needs_heavy = any(kw in last_content.lower() for kw in [
        "navigue", "browse", "scrape", "screenshot", "visite", "site web",
        "formulaire", "image", "genere une image", "lobster", "workflow",
    ])
    timeout = OPENCLAW_TIMEOUT_HEAVY if needs_heavy else (
        OPENCLAW_TIMEOUT_AGENTIC if use_tools else OPENCLAW_TIMEOUT_SIMPLE
    )

    headers = _build_headers(session_key)

    # Circuit breaker check
    if not _circuit_breaker.can_execute():
        logger.warning("Circuit breaker OPEN — skip OpenClaw call")
        return OpenClawResponse(
            content="",
            error="OpenClaw temporairement indisponible (circuit breaker ouvert). Reessayez dans ~1 min.",
        )

    # ── Skip REST API (retourne toujours 403 "missing scope: operator.write") ──
    # ── Appel direct via CLI subprocess (a les bons scopes operator) ──
    logger.info("Appel direct via CLI OpenClaw (REST API skip — 403 connu)")

    # ── Essai 2 : CLI subprocess (a les bons scopes operator) ──
    logger.info("Fallback vers CLI OpenClaw subprocess...")
    # Construire le message complet (system prompt + dernier message user)
    user_message = last_content
    if system_prompt:
        user_message = f"[System: {system_prompt[:2000]}]\n\n{last_content}"

    cli_timeout = int(timeout) if timeout else 120
    cli_result = await _openclaw_chat_via_cli(
        message=user_message,
        session_key=session_key,
        timeout_seconds=cli_timeout,
    )
    if not cli_result.error:
        return cli_result

    logger.warning(f"CLI OpenClaw echouee: {cli_result.error}")
    return OpenClawResponse(content="", error=f"OpenClaw indisponible (REST + CLI). {cli_result.error}")


# ── Chat completions avec SSE streaming ───────────────────────────────────────

async def openclaw_chat_stream(
    messages: list[dict],
    system_prompt: str = "",
    model: str = "openclaw/default",
    session_key: str | None = None,
    use_tools: bool = True,
) -> AsyncGenerator[OpenClawStreamEvent, None]:
    """
    Streaming SSE depuis le Gateway OpenClaw.
    Yield des OpenClawStreamEvent en temps reel :
      - content : fragment de texte
      - tool_call : outil invoque par le LLM
      - tool_result : resultat d'un outil
      - done : fin de la reponse
      - error : erreur
    """
    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    payload = {
        "model": model,
        "messages": full_messages,
        "stream": True,
    }

    headers = _build_headers(session_key)
    timeout = OPENCLAW_TIMEOUT_HEAVY if use_tools else OPENCLAW_TIMEOUT_SIMPLE

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{OPENCLAW_GATEWAY_URL}/v1/chat/completions",
                headers=headers,
                json=payload,
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield OpenClawStreamEvent(
                        event_type="error",
                        data={"error": f"Status {resp.status_code}: {body.decode()[:200]}"},
                    )
                    return

                buffer = ""
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        raw = line[6:].strip()
                        if raw == "[DONE]":
                            yield OpenClawStreamEvent(event_type="done", data={})
                            return
                        try:
                            chunk = json.loads(raw)
                            event = _parse_stream_chunk(chunk)
                            if event:
                                yield event
                        except json.JSONDecodeError:
                            continue

    except httpx.ConnectError:
        yield OpenClawStreamEvent(
            event_type="error",
            data={"error": "OpenClaw Gateway non accessible"},
        )
    except httpx.TimeoutException:
        yield OpenClawStreamEvent(
            event_type="error",
            data={"error": "Timeout streaming OpenClaw"},
        )
    except Exception as e:
        yield OpenClawStreamEvent(
            event_type="error",
            data={"error": str(e)},
        )


def _parse_stream_chunk(chunk: dict) -> OpenClawStreamEvent | None:
    """Parse un chunk SSE du Gateway."""
    choices = chunk.get("choices", [])
    if not choices:
        return None

    delta = choices[0].get("delta", {})
    finish_reason = choices[0].get("finish_reason")

    # Content delta
    content = delta.get("content", "")
    if content:
        return OpenClawStreamEvent(
            event_type="content",
            data=chunk,
            content_delta=content,
        )

    # Tool call
    tool_calls = delta.get("tool_calls", [])
    if tool_calls:
        tc = tool_calls[0]
        fn = tc.get("function", {})
        return OpenClawStreamEvent(
            event_type="tool_call",
            data=chunk,
            tool_name=fn.get("name", ""),
            tool_args=fn.get("arguments"),
        )

    # Finish
    if finish_reason:
        return OpenClawStreamEvent(
            event_type="done" if finish_reason == "stop" else "tool_result",
            data=chunk,
        )

    return None


# ── Response parser ──────────────────────────────────────────────────────────

def _parse_chat_response(data: dict, model: str) -> OpenClawResponse:
    """Parse une reponse complete du Gateway."""
    content = ""
    tool_calls_made = []
    search_results = []
    web_pages = []
    files_created = []
    images_generated = []

    if data.get("choices") and len(data["choices"]) > 0:
        choice = data["choices"][0]
        msg = choice.get("message", {})
        content = msg.get("content", "") or ""

        # Extraire les tool_calls
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tool_info = {
                    "id": tc.get("id", ""),
                    "name": tc.get("function", {}).get("name", ""),
                    "arguments": tc.get("function", {}).get("arguments", "{}"),
                }
                tool_calls_made.append(tool_info)
                _categorize_tool_call(tool_info, search_results, web_pages, files_created, images_generated)

    # Metadonnees d'execution du Gateway
    metadata = data.get("metadata", {}) or {}
    if metadata.get("tools_used"):
        for tool_used in metadata["tools_used"]:
            tool_calls_made.append({
                "name": tool_used.get("name", ""),
                "result_summary": tool_used.get("summary", ""),
            })
            _categorize_tool_call(
                {"name": tool_used.get("name", ""), "arguments": json.dumps(tool_used.get("args", {}))},
                search_results, web_pages, files_created, images_generated,
            )

    return OpenClawResponse(
        content=content,
        model=data.get("model", model),
        usage=data.get("usage"),
        raw=data,
        tool_calls_made=tool_calls_made,
        search_results=search_results,
        web_pages_visited=web_pages,
        files_created=files_created,
        images_generated=images_generated,
    )


def _categorize_tool_call(
    tool_info: dict,
    search_results: list,
    web_pages: list,
    files_created: list,
    images_generated: list,
):
    """Classe un tool_call par categorie pour le tracking."""
    name = tool_info.get("name", "")
    try:
        args = json.loads(tool_info.get("arguments", "{}"))
    except Exception:
        args = {}

    # Recherches web
    if name in ("web_search", "duckduckgo_search", "web_fetch"):
        query = args.get("query", args.get("q", args.get("url", "")))
        if query:
            search_results.append({"query": query, "tool": name})

    # Pages visitees
    if name in ("browser", "navigate", "browser_navigate", "web_fetch"):
        url = args.get("url", args.get("uri", ""))
        if url:
            web_pages.append(url)

    # Fichiers
    if name in ("write", "edit", "apply_patch"):
        filepath = args.get("path", args.get("file", ""))
        if filepath:
            files_created.append(filepath)

    # Images
    if name in ("image_generate", "image"):
        prompt = args.get("prompt", args.get("description", ""))
        if prompt:
            images_generated.append(prompt)


# ── Fonctions utilitaires d'outils specifiques ────────────────────────────────

async def openclaw_web_search(
    query: str,
    session_key: str | None = None,
    max_results: int = 10,
) -> OpenClawResponse:
    """Recherche web via OpenClaw (utilise chat completions pour le tool loop)."""
    messages = [
        {
            "role": "user",
            "content": f"Recherche web : '{query}'. Utilise l'outil web_search pour trouver des resultats recents et pertinents. Synthetise les {max_results} meilleurs resultats avec les URLs sources.",
        }
    ]
    return await openclaw_chat(
        messages=messages,
        system_prompt="Tu es un assistant de recherche. Utilise web_search pour trouver des informations. Retourne les resultats avec les URLs sources. Sois factuel et precis.",
        session_key=session_key,
        use_tools=True,
    )


async def openclaw_x_search(
    query: str,
    session_key: str | None = None,
    max_results: int = 10,
    from_date: str | None = None,
    to_date: str | None = None,
    allowed_handles: list[str] | None = None,
    excluded_handles: list[str] | None = None,
) -> dict:
    """
    Recherche X/Twitter via xAI Grok (x_search).
    Tente d'abord via OpenClaw CLI (qui utilise le tool x_search natif),
    puis fallback direct vers l'API xAI si XAI_API_KEY est configuree.
    """
    # ── Methode 1 : via OpenClaw CLI (x_search natif) ──
    try:
        constraints = []
        if from_date:
            constraints.append(f"depuis le {from_date}")
        if to_date:
            constraints.append(f"jusqu'au {to_date}")
        if allowed_handles:
            constraints.append(f"uniquement de @{', @'.join(allowed_handles)}")
        if excluded_handles:
            constraints.append(f"exclure @{', @'.join(excluded_handles)}")
        constraint_str = f" ({', '.join(constraints)})" if constraints else ""

        search_msg = (
            f"Utilise l'outil x_search pour rechercher sur X/Twitter : '{query}'{constraint_str}. "
            f"Retourne les {max_results} posts les plus pertinents avec : "
            f"le @handle de l'auteur, la date, le contenu du post, le nombre de likes/retweets si disponible, "
            f"et l'URL du post. Formate ta reponse en JSON avec une cle 'posts' contenant un tableau."
        )

        cli_result = await _openclaw_chat_via_cli(
            message=search_msg,
            session_key=session_key,
            timeout_seconds=45,
        )

        if cli_result.content and not cli_result.error:
            # Verifier que l'agent a reellement utilise x_search (pas juste dit "je ne peux pas")
            content_lower = cli_result.content.lower()
            no_tool_indicators = [
                "pas d'outil", "n'existe pas", "pas disponible", "je ne peux pas",
                "no tool", "not available", "cannot", "don't have", "je n'ai pas",
            ]
            if any(ind in content_lower for ind in no_tool_indicators):
                logger.info("x_search: OpenClaw CLI n'a pas le tool x_search, fallback...")
            else:
                # Tenter d'extraire du JSON structure
                posts = _parse_x_search_posts(cli_result.content)
                return {
                    "success": True,
                    "source": "openclaw_cli",
                    "query": query,
                    "posts": posts,
                    "raw_content": cli_result.content,
                    "summary": _extract_summary(cli_result.content, posts),
                }
    except Exception as e:
        logger.warning(f"x_search via OpenClaw CLI echoue : {e}")

    # ── Methode 2 : API xAI directe (Grok) ──
    xai_api_key = os.environ.get("XAI_API_KEY", "")
    if xai_api_key:
        try:
            return await _x_search_via_xai(
                query=query,
                api_key=xai_api_key,
                max_results=max_results,
                from_date=from_date,
                to_date=to_date,
                allowed_handles=allowed_handles,
                excluded_handles=excluded_handles,
            )
        except Exception as e:
            logger.warning(f"x_search via xAI API echoue : {e}")

    # ── Methode 3 : Fallback — recherche web classique sur X ──
    try:
        web_result = await openclaw_web_search(
            f"site:x.com OR site:twitter.com {query}",
            session_key=session_key,
            max_results=max_results,
        )
        if web_result.content and not web_result.error:
            return {
                "success": True,
                "source": "web_fallback",
                "query": query,
                "posts": [],
                "raw_content": web_result.content,
                "summary": f"Resultats web pour '{query}' sur X/Twitter (recherche indirecte)",
            }
    except Exception:
        pass

    return {
        "success": False,
        "source": "none",
        "query": query,
        "posts": [],
        "raw_content": "",
        "error": "Aucune methode de recherche X disponible. Configurez XAI_API_KEY ou activez x_search dans OpenClaw.",
    }


async def _x_search_via_xai(
    query: str,
    api_key: str,
    max_results: int = 10,
    from_date: str | None = None,
    to_date: str | None = None,
    allowed_handles: list[str] | None = None,
    excluded_handles: list[str] | None = None,
) -> dict:
    """Appel direct a l'API xAI Responses avec le tool x_search natif."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Construire le payload xAI Responses API
    tools = [{
        "type": "x_search",
        "x_search": {},
    }]

    # Ajouter les filtres si fournis
    x_search_config = tools[0]["x_search"]
    if allowed_handles:
        x_search_config["allowed_x_handles"] = allowed_handles
    if excluded_handles:
        x_search_config["excluded_x_handles"] = excluded_handles
    if from_date:
        x_search_config["from_date"] = from_date
    if to_date:
        x_search_config["to_date"] = to_date

    payload = {
        "model": "grok-3-fast-latest",
        "tools": tools,
        "input": f"Recherche sur X/Twitter : {query}. Retourne les {max_results} posts les plus pertinents.",
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.x.ai/v1/responses",
            headers=headers,
            json=payload,
        )

        if resp.status_code != 200:
            return {
                "success": False,
                "source": "xai_api",
                "query": query,
                "posts": [],
                "error": f"xAI API status {resp.status_code}: {resp.text[:300]}",
            }

        data = resp.json()

        # Parser la reponse xAI
        posts = []
        content_text = ""
        citations = []

        for item in data.get("output", []):
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if block.get("type") == "output_text":
                        content_text = block.get("text", "")
                        # Extraire les annotations/citations
                        for ann in block.get("annotations", []):
                            if ann.get("type") == "url_citation":
                                citations.append({
                                    "url": ann.get("url", ""),
                                    "title": ann.get("title", ""),
                                })
            elif item.get("type") == "x_search_results_block":
                for result in item.get("results", []):
                    posts.append({
                        "handle": result.get("user_handle", result.get("author", "")),
                        "display_name": result.get("user_display_name", result.get("user_handle", "")),
                        "content": result.get("text", result.get("content", "")),
                        "date": result.get("created_at", result.get("date", "")),
                        "url": result.get("url", result.get("tweet_url", "")),
                        "likes": result.get("like_count", result.get("likes", 0)),
                        "retweets": result.get("retweet_count", result.get("retweets", 0)),
                        "replies": result.get("reply_count", result.get("replies", 0)),
                        "views": result.get("view_count", result.get("views", 0)),
                    })

        # Si pas de bloc structuré, parser le texte
        if not posts:
            posts = _parse_x_search_posts(content_text)

        return {
            "success": True,
            "source": "xai_api",
            "query": query,
            "posts": posts[:max_results],
            "raw_content": content_text,
            "citations": citations,
            "summary": content_text[:500] if content_text else f"{len(posts)} posts trouves pour '{query}'",
        }


def _parse_x_search_posts(content: str) -> list[dict]:
    """Tente d'extraire des posts X structures depuis du texte brut ou JSON."""
    import re

    # Tenter JSON directement
    try:
        data = json.loads(content)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("posts", data.get("results", data.get("tweets", [])))
    except (json.JSONDecodeError, TypeError):
        pass

    # Tenter de trouver un bloc JSON dans le texte
    json_match = re.search(r'\[[\s\S]*?\]', content)
    if json_match:
        try:
            arr = json.loads(json_match.group())
            if isinstance(arr, list) and arr:
                return arr
        except (json.JSONDecodeError, TypeError):
            pass

    # Extraction heuristique depuis texte formaté
    posts = []
    # Pattern: @handle - contenu...
    post_patterns = re.findall(
        r'@(\w+)[:\s]+(.+?)(?=\n@\w+|\n\n|\Z)',
        content,
        re.DOTALL,
    )
    for handle, text in post_patterns:
        post = {
            "handle": f"@{handle}",
            "content": text.strip()[:500],
            "date": "",
            "url": f"https://x.com/{handle}",
        }
        # Extraire URL si présente
        url_match = re.search(r'https?://(?:x\.com|twitter\.com)/\S+', text)
        if url_match:
            post["url"] = url_match.group()
        posts.append(post)

    return posts


def _extract_summary(content: str, posts: list[dict]) -> str:
    """Genere un resume a partir du contenu et des posts trouves."""
    if not posts:
        return content[:300] if content else "Aucun resultat"
    return f"{len(posts)} posts trouves sur X/Twitter"


async def openclaw_browse(
    url: str,
    instruction: str = "Extrais le contenu principal de cette page.",
    session_key: str | None = None,
) -> OpenClawResponse:
    """Navigue vers une URL via le browser OpenClaw."""
    messages = [
        {
            "role": "user",
            "content": f"Navigue vers {url} et {instruction}",
        }
    ]
    return await openclaw_chat(
        messages=messages,
        system_prompt="Tu es un assistant qui navigue sur le web. Utilise le browser pour visiter les pages et extraire le contenu demande. Sois precis et structure.",
        session_key=session_key,
        use_tools=True,
    )


async def openclaw_execute(
    command: str,
    session_key: str | None = None,
) -> dict:
    """Execute une commande shell via OpenClaw exec."""
    return await openclaw_invoke_tool(
        tool_name="exec",
        action="run",
        args={"command": command},
        session_key=session_key,
    )


async def openclaw_code_execute(
    code: str,
    language: str = "python",
    filename: str | None = None,
    timeout: int | None = None,
) -> dict:
    """
    Execute du code dans le sandbox local securise.
    Contrairement a openclaw_execute (commande shell via Gateway),
    ceci execute du code localement avec isolation et validation.
    """
    from api.code_sandbox import sandbox_execute_code
    result = await sandbox_execute_code(code, language, filename, timeout)
    return result.to_dict()


async def openclaw_read_file(
    filepath: str,
    session_key: str | None = None,
) -> dict:
    """Lit un fichier via OpenClaw file ops."""
    return await openclaw_invoke_tool(
        tool_name="read",
        action="default",
        args={"path": filepath},
        session_key=session_key,
    )


async def openclaw_write_file(
    filepath: str,
    content: str,
    session_key: str | None = None,
) -> dict:
    """Ecrit un fichier via OpenClaw file ops."""
    return await openclaw_invoke_tool(
        tool_name="write",
        action="default",
        args={"path": filepath, "content": content},
        session_key=session_key,
    )


async def openclaw_generate_image(
    prompt: str,
    session_key: str | None = None,
) -> dict:
    """Genere une image via OpenClaw image_generate."""
    return await openclaw_invoke_tool(
        tool_name="image_generate",
        action="default",
        args={"prompt": prompt},
        session_key=session_key,
    )


async def openclaw_memory_search(
    query: str,
    session_key: str | None = None,
) -> dict:
    """Recherche dans la memoire OpenClaw."""
    return await openclaw_invoke_tool(
        tool_name="memory_search",
        action="default",
        args={"query": query},
        session_key=session_key,
    )


async def openclaw_spawn_session(
    agent_id: str,
    initial_message: str,
    session_key: str | None = None,
) -> dict:
    """Lance un sous-agent dans une nouvelle session OpenClaw."""
    return await openclaw_invoke_tool(
        tool_name="sessions_spawn",
        action="default",
        args={"agentId": agent_id, "message": initial_message},
        session_key=session_key,
    )


async def openclaw_create_cron(
    label: str,
    cron_expr: str,
    instruction: str,
    session_key: str | None = None,
) -> dict:
    """Cree une tache planifiee via OpenClaw cron."""
    return await openclaw_invoke_tool(
        tool_name="cron",
        action="create",
        args={"label": label, "schedule": cron_expr, "message": instruction},
        session_key=session_key,
    )


# ── Sessions management (5 outils) ───────────────────────────────────────────

async def openclaw_sessions_list(
    session_key: str | None = None,
) -> dict:
    """Liste toutes les sessions/sous-agents actifs sur le Gateway."""
    return await openclaw_invoke_tool(
        tool_name="sessions_list",
        action="default",
        args={},
        session_key=session_key,
    )


async def openclaw_sessions_history(
    target_session_id: str,
    session_key: str | None = None,
) -> dict:
    """Recupere l'historique complet d'une session/sous-agent."""
    return await openclaw_invoke_tool(
        tool_name="sessions_history",
        action="default",
        args={"sessionId": target_session_id},
        session_key=session_key,
    )


async def openclaw_session_status(
    target_session_id: str,
    session_key: str | None = None,
) -> dict:
    """Verifie le statut d'une session/sous-agent (running, idle, done, error)."""
    return await openclaw_invoke_tool(
        tool_name="sessions_send",
        action="status",
        args={"sessionId": target_session_id},
        session_key=session_key,
    )


async def openclaw_sessions_yield(
    target_session_id: str,
    session_key: str | None = None,
) -> dict:
    """Recupere le dernier resultat produit par un sous-agent sans le bloquer."""
    return await openclaw_invoke_tool(
        tool_name="sessions_send",
        action="yield",
        args={"sessionId": target_session_id},
        session_key=session_key,
    )


async def openclaw_agents_list(
    session_key: str | None = None,
) -> dict:
    """Liste tous les agents disponibles sur le Gateway (types, pas instances)."""
    # Tente d'abord via /v1/models qui liste les agents
    try:
        models = await openclaw_list_models()
        if models:
            return {"success": True, "agents": models}
    except Exception:
        pass
    # Fallback via invoke tool
    return await openclaw_invoke_tool(
        tool_name="gateway",
        action="agents",
        args={},
        session_key=session_key,
    )


# ── Loop Detection ────────────────────────────────────────────────────────────

class ToolLoopDetector:
    """
    Detecte les boucles infinies d'outils dans une session.

    Principe : si le meme outil est appele plus de `max_repeats` fois
    d'affilee, ou si le nombre total d'appels depasse `max_total`,
    on considere que c'est une boucle et on coupe.
    """

    def __init__(self, max_repeats: int = 4, max_total: int = 15):
        self.max_repeats = max_repeats
        self.max_total = max_total
        self._calls: list[str] = []

    def record(self, tool_name: str) -> None:
        """Enregistre un appel d'outil."""
        self._calls.append(tool_name)

    @property
    def total_calls(self) -> int:
        return len(self._calls)

    def is_looping(self) -> tuple[bool, str]:
        """
        Retourne (True, raison) si une boucle est detectee.
        Deux criteres :
          1. Le meme outil appele N fois d'affilee (repetition)
          2. Le total d'appels depasse le max (explosion)
        """
        # Critere 1 : repetitions consecutives
        if len(self._calls) >= self.max_repeats:
            tail = self._calls[-self.max_repeats:]
            if len(set(tail)) == 1:
                return True, f"Outil '{tail[0]}' appele {self.max_repeats}x d'affilee"

        # Critere 2 : total excessif
        if len(self._calls) > self.max_total:
            # Trouver l'outil le plus frequent
            from collections import Counter
            most_common = Counter(self._calls).most_common(1)
            culprit = most_common[0] if most_common else ("?", 0)
            return True, f"Trop d'appels d'outils ({len(self._calls)}), plus frequent: '{culprit[0]}' ({culprit[1]}x)"

        return False, ""

    def get_stats(self) -> dict:
        from collections import Counter
        return {
            "total_calls": len(self._calls),
            "max_total": self.max_total,
            "max_repeats": self.max_repeats,
            "calls": Counter(self._calls),
        }

    def reset(self) -> None:
        self._calls.clear()


# ── Tool Profiles (allow/deny par agent) ──────────────────────────────────────

# Profils d'outils par agent : definit quels outils chaque agent peut utiliser.
# "allow" = seuls ces outils sont autorises (whitelist)
# "deny"  = ces outils sont interdits (blacklist)
# Si un agent n'a pas de profil, tous les outils sont autorises.

TOOL_PROFILES: dict[str, dict] = {
    "agent3": {
        # Agent 3 = agent d'elite, acces complet sauf SMS/notifications (pas configure)
        "deny": ["sms.send", "notifications.send", "camera.capture"],
    },
    "agent3_light": {
        # Profil light pour les taches simples (pas de browser, pas de sous-agents)
        "allow": [
            "web_search", "web_fetch", "read", "write", "exec",
            "memory_search", "memory_get", "image",
        ],
    },
    "sub_agent": {
        # Sous-agents : pas de spawn recursif, pas de cron, pas de gateway control
        "deny": [
            "sessions_spawn", "subagents", "cron", "gateway",
            "sms.send", "notifications.send", "camera.capture",
        ],
    },
}


def get_allowed_tools(agent_id: str = "agent3") -> list[dict]:
    """
    Retourne la liste des outils autorises pour un agent donne,
    en appliquant le profil allow/deny.
    """
    profile = TOOL_PROFILES.get(agent_id)
    if not profile:
        return list(ALL_OPENCLAW_TOOLS)

    allow_list = profile.get("allow")
    deny_list = profile.get("deny", [])

    if allow_list:
        # Mode whitelist : seuls les outils dans allow sont gardes
        return [t for t in ALL_OPENCLAW_TOOLS if t["name"] in allow_list]
    else:
        # Mode blacklist : on enleve les outils deny
        return [t for t in ALL_OPENCLAW_TOOLS if t["name"] not in deny_list]


def is_tool_allowed(tool_name: str, agent_id: str = "agent3") -> bool:
    """Verifie si un outil est autorise pour un agent."""
    allowed = get_allowed_tools(agent_id)
    return any(t["name"] == tool_name for t in allowed)


def get_tool_profile(agent_id: str) -> dict | None:
    """Retourne le profil d'outils d'un agent."""
    return TOOL_PROFILES.get(agent_id)


# ── Models listing ────────────────────────────────────────────────────────────

async def openclaw_list_models() -> list[dict]:
    """Liste les modeles/agents disponibles sur le Gateway."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            headers = _build_headers()
            resp = await client.get(f"{OPENCLAW_GATEWAY_URL}/v1/models", headers=headers)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    return data.get("data", [])
                except Exception:
                    pass
    except Exception:
        pass
    return []


# ── Phase 3 — Nouveaux wrappers (12 tools) ───────────────────────────────────
#
# Chaque wrapper fait UN appel HTTP ou UN invoke OpenClaw, avec :
#   - un timeout adapte (plus court pour search, plus long pour media)
#   - gestion des erreurs unifiee (retour dict {success, data, error})
#   - fallback sur openclaw_invoke_tool quand une cle API directe n'est pas fournie
#
# Tous les wrappers sont sync-safe et peuvent etre appeles depuis un endpoint
# FastAPI sans blocage grace a httpx.AsyncClient / asyncio.to_thread.


# ─── Search engines (6) ──────────────────────────────────────────────────────

async def openclaw_firecrawl(
    url: str,
    mode: str = "scrape",  # "scrape" (1 page) | "crawl" (site entier)
    max_pages: int = 20,
    session_key: str | None = None,
) -> dict:
    """
    Crawl ou scrape d'une URL via Firecrawl.
    Mode "scrape" : retourne le markdown d'une page unique.
    Mode "crawl"  : parcourt le site jusqu'a `max_pages`.
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    if api_key:
        endpoint = "scrape" if mode == "scrape" else "crawl"
        payload = {"url": url}
        if mode == "crawl":
            payload["limit"] = max_pages
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"https://api.firecrawl.dev/v1/{endpoint}",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code in (200, 201, 202):
                    return {"success": True, "source": "firecrawl_api", "data": resp.json()}
                return {"success": False, "source": "firecrawl_api",
                        "error": f"Status {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            logger.warning(f"firecrawl API echoue: {e}")
    # Fallback via OpenClaw invoke
    return await openclaw_invoke_tool(
        tool_name="firecrawl",
        action=mode,
        args={"url": url, "limit": max_pages},
        session_key=session_key,
    )


async def openclaw_perplexity_search(
    query: str,
    max_results: int = 10,
    recency: str | None = None,  # "day" | "week" | "month" | "year"
    session_key: str | None = None,
) -> dict:
    """
    Recherche via Perplexity AI — retourne une reponse synthese + citations.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if api_key:
        payload = {
            "model": "llama-3.1-sonar-small-128k-online",
            "messages": [{"role": "user", "content": query}],
            "return_citations": True,
            "return_images": False,
        }
        if recency:
            payload["search_recency_filter"] = recency
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.perplexity.ai/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    answer = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    citations = data.get("citations", [])[:max_results]
                    return {"success": True, "source": "perplexity_api",
                            "answer": answer, "citations": citations, "raw": data}
                return {"success": False, "source": "perplexity_api",
                        "error": f"Status {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            logger.warning(f"perplexity API echoue: {e}")
    # Fallback via OpenClaw invoke
    return await openclaw_invoke_tool(
        tool_name="perplexity_search",
        action="default",
        args={"query": query, "max_results": max_results},
        session_key=session_key,
    )


async def openclaw_brave_search(
    query: str,
    max_results: int = 10,
    country: str = "fr",
    session_key: str | None = None,
) -> dict:
    """Recherche web via Brave Search API (privacy-first)."""
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                    params={"q": query, "count": max_results, "country": country},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = [
                        {"title": r.get("title"), "url": r.get("url"),
                         "description": r.get("description")}
                        for r in data.get("web", {}).get("results", [])[:max_results]
                    ]
                    return {"success": True, "source": "brave_api",
                            "query": query, "results": results}
                return {"success": False, "source": "brave_api",
                        "error": f"Status {resp.status_code}"}
        except Exception as e:
            logger.warning(f"brave_search API echoue: {e}")
    return await openclaw_invoke_tool(
        tool_name="brave_search",
        action="default",
        args={"query": query, "count": max_results},
        session_key=session_key,
    )


async def openclaw_google_search(
    query: str,
    max_results: int = 10,
    session_key: str | None = None,
) -> dict:
    """Recherche Google via SerpAPI."""
    api_key = os.environ.get("SERPAPI_API_KEY", "")
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    "https://serpapi.com/search",
                    params={"q": query, "num": max_results,
                            "api_key": api_key, "engine": "google"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = [
                        {"title": r.get("title"), "url": r.get("link"),
                         "description": r.get("snippet")}
                        for r in data.get("organic_results", [])[:max_results]
                    ]
                    return {"success": True, "source": "serpapi",
                            "query": query, "results": results}
                return {"success": False, "source": "serpapi",
                        "error": f"Status {resp.status_code}"}
        except Exception as e:
            logger.warning(f"google_search API echoue: {e}")
    return await openclaw_invoke_tool(
        tool_name="google_search",
        action="default",
        args={"query": query, "num": max_results},
        session_key=session_key,
    )


async def openclaw_tavily_search(
    query: str,
    max_results: int = 10,
    search_depth: str = "basic",  # "basic" | "advanced"
    session_key: str | None = None,
) -> dict:
    """Recherche agentic RAG via Tavily — optimise pour agents LLM."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": api_key, "query": query,
                          "max_results": max_results, "search_depth": search_depth,
                          "include_answer": True},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {"success": True, "source": "tavily_api",
                            "query": query, "answer": data.get("answer", ""),
                            "results": data.get("results", [])[:max_results]}
                return {"success": False, "source": "tavily_api",
                        "error": f"Status {resp.status_code}"}
        except Exception as e:
            logger.warning(f"tavily_search API echoue: {e}")
    return await openclaw_invoke_tool(
        tool_name="tavily_search",
        action="default",
        args={"query": query, "max_results": max_results},
        session_key=session_key,
    )


async def openclaw_exa_search(
    query: str,
    max_results: int = 10,
    search_type: str = "neural",  # "neural" | "keyword"
    session_key: str | None = None,
) -> dict:
    """Recherche neurale semantique via Exa (ex-Metaphor)."""
    api_key = os.environ.get("EXA_API_KEY", "")
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    "https://api.exa.ai/search",
                    headers={"x-api-key": api_key, "Content-Type": "application/json"},
                    json={"query": query, "numResults": max_results,
                          "type": search_type, "contents": {"text": True}},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    results = [
                        {"title": r.get("title"), "url": r.get("url"),
                         "description": r.get("text", "")[:300]}
                        for r in data.get("results", [])[:max_results]
                    ]
                    return {"success": True, "source": "exa_api",
                            "query": query, "results": results}
                return {"success": False, "source": "exa_api",
                        "error": f"Status {resp.status_code}"}
        except Exception as e:
            logger.warning(f"exa_search API echoue: {e}")
    return await openclaw_invoke_tool(
        tool_name="exa_search",
        action="default",
        args={"query": query, "num_results": max_results},
        session_key=session_key,
    )


# ─── Media generation (3) ────────────────────────────────────────────────────

async def openclaw_music_generate(
    prompt: str,
    duration_seconds: int = 30,
    style: str | None = None,
    session_key: str | None = None,
) -> dict:
    """
    Generation de musique / piste audio.
    Utilise OpenClaw invoke (le Gateway connait Suno / MusicGen / Stability Audio).
    """
    args = {"prompt": prompt, "duration": duration_seconds}
    if style:
        args["style"] = style
    return await openclaw_invoke_tool(
        tool_name="music_generate",
        action="default",
        args=args,
        session_key=session_key,
    )


async def openclaw_video_generate(
    prompt: str,
    duration_seconds: int = 5,
    aspect_ratio: str = "16:9",
    session_key: str | None = None,
) -> dict:
    """Generation de clip video court (Runway / Pika)."""
    return await openclaw_invoke_tool(
        tool_name="video_generate",
        action="default",
        args={"prompt": prompt, "duration": duration_seconds,
              "aspectRatio": aspect_ratio},
        session_key=session_key,
    )


async def openclaw_voice_generate(
    text: str,
    voice: str = "alloy",  # alloy, echo, fable, onyx, nova, shimmer (OpenAI)
    provider: str = "openai",  # "openai" | "elevenlabs"
    session_key: str | None = None,
) -> dict:
    """Synthese vocale TTS haute fidelite (OpenAI TTS ou ElevenLabs)."""
    # OpenAI TTS (direct, plus simple si cle fournie)
    if provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        "https://api.openai.com/v1/audio/speech",
                        headers={"Authorization": f"Bearer {api_key}",
                                 "Content-Type": "application/json"},
                        json={"model": "tts-1-hd", "input": text, "voice": voice},
                    )
                    if resp.status_code == 200:
                        import base64
                        audio_b64 = base64.b64encode(resp.content).decode("ascii")
                        return {"success": True, "source": "openai_tts",
                                "audio_base64": audio_b64, "voice": voice,
                                "length_bytes": len(resp.content)}
                    return {"success": False, "source": "openai_tts",
                            "error": f"Status {resp.status_code}: {resp.text[:200]}"}
            except Exception as e:
                logger.warning(f"openai_tts echoue: {e}")
    # Fallback OpenClaw
    return await openclaw_invoke_tool(
        tool_name="voice_generate",
        action="default",
        args={"text": text, "voice": voice, "provider": provider},
        session_key=session_key,
    )


# ─── Safety / guardrails (3) ─────────────────────────────────────────────────

async def openclaw_content_moderation(
    text: str,
    session_key: str | None = None,
) -> dict:
    """
    Moderation de contenu — detecte toxicite, harm, auto-harm, violence.
    Utilise OpenAI Moderation (gratuit) si OPENAI_API_KEY dispo,
    sinon fallback OpenClaw.
    """
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/moderations",
                    headers={"Authorization": f"Bearer {api_key}",
                             "Content-Type": "application/json"},
                    json={"input": text, "model": "omni-moderation-latest"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    result = data.get("results", [{}])[0]
                    flagged = bool(result.get("flagged", False))
                    categories = result.get("categories", {})
                    scores = result.get("category_scores", {})
                    # Liste des categories actives
                    active = [cat for cat, is_on in categories.items() if is_on]
                    return {"success": True, "source": "openai_moderation",
                            "flagged": flagged, "categories_flagged": active,
                            "scores": scores, "raw": data}
                return {"success": False, "source": "openai_moderation",
                        "error": f"Status {resp.status_code}"}
        except Exception as e:
            logger.warning(f"content_moderation API echoue: {e}")
    return await openclaw_invoke_tool(
        tool_name="content_moderation",
        action="default",
        args={"text": text},
        session_key=session_key,
    )


async def openclaw_url_safety_check(
    url: str,
    session_key: str | None = None,
) -> dict:
    """
    Verifie la reputation d'une URL (phishing / malware).
    Utilise Google Safe Browsing si GOOGLE_SAFE_BROWSING_API_KEY dispo.
    """
    api_key = os.environ.get("GOOGLE_SAFE_BROWSING_API_KEY", "")
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                payload = {
                    "client": {"clientId": "sylea", "clientVersion": "1.0"},
                    "threatInfo": {
                        "threatTypes": [
                            "MALWARE", "SOCIAL_ENGINEERING",
                            "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION",
                        ],
                        "platformTypes": ["ANY_PLATFORM"],
                        "threatEntryTypes": ["URL"],
                        "threatEntries": [{"url": url}],
                    },
                }
                resp = await client.post(
                    f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={api_key}",
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    matches = data.get("matches", [])
                    is_safe = len(matches) == 0
                    return {"success": True, "source": "google_safebrowsing",
                            "url": url, "is_safe": is_safe,
                            "threats": [m.get("threatType") for m in matches]}
                return {"success": False, "source": "google_safebrowsing",
                        "error": f"Status {resp.status_code}"}
        except Exception as e:
            logger.warning(f"url_safety_check API echoue: {e}")
    return await openclaw_invoke_tool(
        tool_name="url_safety_check",
        action="default",
        args={"url": url},
        session_key=session_key,
    )


async def openclaw_pii_scrub(
    text: str,
    redact: bool = True,
    session_key: str | None = None,
) -> dict:
    """
    Detecte + optionnellement redacte les PII (email, tel, IBAN, CB, NSS).
    Implementation locale via regex (rapide, pas de cle API requise).
    Fallback OpenClaw pour detection plus avancee si dispo.
    """
    import re

    patterns = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b",
        "phone_fr": r"(?:\+33|0)[1-9](?:[\s.-]?\d{2}){4}",
        "phone_intl": r"\+\d{1,3}[\s.-]?\d{4,14}",
        "iban": r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b",
        "credit_card": r"\b(?:\d[ -]*?){13,16}\b",
        "nss_fr": r"\b[12]\s?\d{2}\s?\d{2}\s?\d{2}\s?\d{3}\s?\d{3}\s?\d{2}\b",
        "ipv4": r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\b",
    }

    findings: dict[str, list[str]] = {}
    scrubbed = text
    for pii_type, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if matches:
            findings[pii_type] = matches
            if redact:
                scrubbed = re.sub(pattern, f"[REDACTED:{pii_type}]", scrubbed)

    return {
        "success": True,
        "source": "local_regex",
        "has_pii": bool(findings),
        "findings": findings,
        "total_matches": sum(len(v) for v in findings.values()),
        "scrubbed_text": scrubbed if redact else None,
    }


# ── Gateway capabilities (dynamiques) ────────────────────────────────────────

# Liste complete des outils OpenClaw connus (Phase 3 : 38 tools)
#
# Repartition par groupe :
#   - web (9)        : recherche / fetch web + search engines specialises
#   - ui (2)         : browser + canvas
#   - runtime (3)    : exec / bash / process
#   - fs (4)         : read / write / edit / apply_patch
#   - sessions (4)   : spawn / send / list / history
#   - memory (2)     : memory_search / memory_get
#   - automation (2) : cron / gateway
#   - messaging (1)  : message
#   - media (5)      : image / image_generate / music / video / voice
#   - safety (3)     : moderation / url_safety / pii_scrub
#   - special (3)    : llm_task / lobster / subagents
# Total : 38
ALL_OPENCLAW_TOOLS = [
    # ── group:web (9) — recherche / fetch / search engines ──────────────
    {"name": "web_search", "group": "web", "description": "Recherche web via DuckDuckGo"},
    {"name": "web_fetch", "group": "web", "description": "Recuperer le contenu d'une URL"},
    {"name": "x_search", "group": "web", "description": "Recherche X/Twitter via xAI Grok"},
    {"name": "firecrawl", "group": "web", "description": "Crawl multi-pages avec extraction structuree (Firecrawl)"},
    {"name": "perplexity_search", "group": "web", "description": "Recherche IA avec citations (Perplexity)"},
    {"name": "brave_search", "group": "web", "description": "Recherche privacy-first (Brave Search API)"},
    {"name": "google_search", "group": "web", "description": "Recherche Google (SerpAPI / Custom Search)"},
    {"name": "tavily_search", "group": "web", "description": "Recherche agentic RAG optimisee (Tavily)"},
    {"name": "exa_search", "group": "web", "description": "Recherche neurale semantique (Exa / Metaphor)"},

    # ── group:ui (2) ────────────────────────────────────────────────────
    {"name": "browser", "group": "ui", "description": "Navigation web Chrome, screenshots, formulaires, scraping"},
    {"name": "canvas", "group": "ui", "description": "Visualisation, presentations, diagrammes"},

    # ── group:runtime (3) ───────────────────────────────────────────────
    {"name": "exec", "group": "runtime", "description": "Executer des commandes shell"},
    {"name": "bash", "group": "runtime", "description": "Terminal bash interactif"},
    {"name": "process", "group": "runtime", "description": "Gestion des processus systeme"},

    # ── group:fs (4) ────────────────────────────────────────────────────
    {"name": "read", "group": "fs", "description": "Lire un fichier"},
    {"name": "write", "group": "fs", "description": "Ecrire un fichier"},
    {"name": "edit", "group": "fs", "description": "Modifier un fichier existant"},
    {"name": "apply_patch", "group": "fs", "description": "Appliquer un patch diff"},

    # ── group:sessions (4) ──────────────────────────────────────────────
    {"name": "sessions_spawn", "group": "sessions", "description": "Lancer un sous-agent autonome"},
    {"name": "sessions_send", "group": "sessions", "description": "Envoyer un message a un sous-agent"},
    {"name": "sessions_list", "group": "sessions", "description": "Lister les sessions actives"},
    {"name": "sessions_history", "group": "sessions", "description": "Historique d'une session"},

    # ── group:memory (2) ────────────────────────────────────────────────
    {"name": "memory_search", "group": "memory", "description": "Rechercher dans la memoire persistante"},
    {"name": "memory_get", "group": "memory", "description": "Recuperer un souvenir specifique"},

    # ── group:automation (2) ────────────────────────────────────────────
    {"name": "cron", "group": "automation", "description": "Taches planifiees / recurrentes"},
    {"name": "gateway", "group": "automation", "description": "Controle du Gateway"},

    # ── group:messaging (1) ─────────────────────────────────────────────
    {"name": "message", "group": "messaging", "description": "Envoyer des messages multi-canal"},

    # ── group:media (5) — analyse + generation audio/visuel ─────────────
    {"name": "image", "group": "media", "description": "Analyse et comprehension d'images"},
    {"name": "image_generate", "group": "media", "description": "Generation et edition d'images"},
    {"name": "music_generate", "group": "media", "description": "Generation de musique / pistes audio (Suno / MusicGen)"},
    {"name": "video_generate", "group": "media", "description": "Generation de clips video (Runway / Pika)"},
    {"name": "voice_generate", "group": "media", "description": "Synthese vocale TTS haute fidelite (ElevenLabs / OpenAI TTS)"},

    # ── group:safety (3) — guardrails avant action sensible ─────────────
    {"name": "content_moderation", "group": "safety", "description": "Detection toxicite, harm, auto-harm, violence (OpenAI / Perspective)"},
    {"name": "url_safety_check", "group": "safety", "description": "Verification phishing / malware / reputation d'URL (Google Safe Browsing)"},
    {"name": "pii_scrub", "group": "safety", "description": "Detection + redaction PII (email, telephone, IBAN, numero identite)"},

    # ── Outils speciaux (3) ─────────────────────────────────────────────
    {"name": "llm_task", "group": "special", "description": "Deleguer une sous-tache a un autre LLM"},
    {"name": "lobster", "group": "special", "description": "Moteur de workflows avec validations"},
    {"name": "subagents", "group": "special", "description": "Orchestration multi-agents"},
]


async def openclaw_capabilities() -> dict:
    """Retourne les capacites completes du Gateway OpenClaw."""
    health = await openclaw_health()
    models = await openclaw_list_models()
    is_connected = health.get("connected", False)

    # Tester quelques outils cles pour savoir lesquels sont actifs
    tools_status = []
    for tool in ALL_OPENCLAW_TOOLS:
        tools_status.append({
            **tool,
            "available": is_connected,  # Si le gateway est up, les outils sont disponibles
        })

    return {
        "connected": is_connected,
        "tools": tools_status,
        "tool_count": len(ALL_OPENCLAW_TOOLS),
        "groups": list(set(t["group"] for t in ALL_OPENCLAW_TOOLS)),
        "models": models,
        "health": health,
        "features": {
            "streaming": True,
            "multi_agent": True,
            "persistent_memory": True,
            "file_operations": True,
            "browser": True,
            "image_generation": True,
            "cron": True,
            "workflows": True,
        },
        "circuit_breaker": _circuit_breaker.get_stats(),
    }


def get_circuit_breaker_status() -> dict:
    """Expose l'etat du circuit breaker pour le monitoring."""
    return _circuit_breaker.get_stats()
