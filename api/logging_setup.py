"""
Structured logging + request_id propagation — Syléa.AI.

Remplace les `print()` éparpillés par des logs JSON structurés que les
agrégateurs (Datadog, Loki, ELK, CloudWatch Logs Insights) peuvent indexer.

Apports :
  - Format JSON : `{"ts": "...", "level": "INFO", "message": "...", "request_id": "...", "user_id": "..."}`
  - **request_id** : UUID4 attaché à chaque requête HTTP, propagé dans
    TOUS les logs émis pendant le traitement (via contextvars).
  - **user_id** + tier : injectés si auth présente.
  - Stack traces formatées.
  - Compatible avec OpenTelemetry traceparent → tracing distribué.

Activation :
  - SYLEA_LOG_FORMAT=json (défaut prod si DATABASE_URL=PG) | text (dev)
  - SYLEA_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR (défaut INFO)
  - SYLEA_LOG_REQUEST_ID_HEADER=X-Request-Id (header pour forward un ID existant)

Usage :
    from api.logging_setup import configure_logging, get_logger

    configure_logging()  # appel unique au boot
    logger = get_logger(__name__)
    logger.info("user logged in", extra={"user_id": user.id, "ip": ip})

    # Ou avec contexte de requête (auto-injecté par le middleware) :
    logger.info("dilemma analysis started")  # request_id + user_id ajoutés
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import sys
import time
import traceback
import uuid
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


# ─────────────────────────────────────────────────────────────────────────────
# Context vars (thread/task-local pour propagation transparente)
# ─────────────────────────────────────────────────────────────────────────────

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "user_id", default=None
)
_user_tier: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "user_tier", default=None
)


def get_request_id() -> str | None:
    """Retourne le request_id de la requête courante (None hors requête)."""
    return _request_id.get()


def set_request_id(rid: str) -> None:
    _request_id.set(rid)


def set_user_context(user_id: str | None, tier: str | None = None) -> None:
    """À appeler après auth pour enrichir les logs avec l'identité utilisateur."""
    if user_id:
        _user_id.set(user_id)
    if tier:
        _user_tier.set(tier)


def clear_context() -> None:
    """Reset tout le contexte (fin de requête)."""
    _request_id.set(None)
    _user_id.set(None)
    _user_tier.set(None)


# ─────────────────────────────────────────────────────────────────────────────
# Formatter JSON
# ─────────────────────────────────────────────────────────────────────────────

# Champs ajoutés automatiquement à chaque log (depuis contextvars)
_AUTO_FIELDS = ("request_id", "user_id", "user_tier")

# Champs internes de LogRecord à ne pas dupliquer dans le JSON
_LOG_RECORD_INTERNAL = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName",
    "taskName",  # Python 3.12+
})


class JsonFormatter(logging.Formatter):
    """Format JSON Loki/Datadog/CloudWatch compatible."""

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Contexte automatique (request_id, user_id, tier)
        rid = _request_id.get()
        if rid:
            payload["request_id"] = rid
        uid = _user_id.get()
        if uid:
            payload["user_id"] = uid
        tier = _user_tier.get()
        if tier:
            payload["user_tier"] = tier

        # Source code locator (utile en debug)
        payload["src"] = f"{record.module}:{record.funcName}:{record.lineno}"

        # Extra fields passés par l'appelant (`logger.info("...", extra={...})`)
        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_INTERNAL or key.startswith("_"):
                continue
            if key in payload:
                continue
            try:
                json.dumps(value)  # serializable ?
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        # Exception traceback
        if record.exc_info:
            payload["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "stack": traceback.format_exception(*record.exc_info),
            }

        return json.dumps(payload, ensure_ascii=False, default=str)


# ─────────────────────────────────────────────────────────────────────────────
# Formatter texte (dev)
# ─────────────────────────────────────────────────────────────────────────────

class HumanReadableFormatter(logging.Formatter):
    """Format texte lisible pour dev local."""

    _COLORS = {
        "DEBUG": "\033[36m",     # cyan
        "INFO": "\033[32m",      # green
        "WARNING": "\033[33m",   # yellow
        "ERROR": "\033[31m",     # red
        "CRITICAL": "\033[35m",  # magenta
    }
    _RESET = "\033[0m"

    def __init__(self, use_color: bool = True):
        super().__init__()
        self._color = use_color and sys.stdout.isatty()

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        ts = time.strftime("%H:%M:%S", time.localtime(record.created))
        level = record.levelname
        if self._color:
            color = self._COLORS.get(level, "")
            level_str = f"{color}{level:<8}{self._RESET}"
        else:
            level_str = f"{level:<8}"

        rid = _request_id.get()
        rid_str = f"[{rid[:8]}]" if rid else ""

        return f"{ts} {level_str} {record.name:<30} {rid_str} {record.getMessage()}"


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

def _detect_log_format() -> str:
    """JSON si prod (PG), text si dev."""
    explicit = os.environ.get("SYLEA_LOG_FORMAT", "").strip().lower()
    if explicit in ("json", "text"):
        return explicit
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url.startswith(("postgres://", "postgresql://", "postgresql+")):
        return "json"
    return "text"


def configure_logging(level: str | None = None, fmt: str | None = None) -> None:
    """Configure le root logger une seule fois.

    Args:
        level: SYLEA_LOG_LEVEL ou DEBUG/INFO/WARNING/ERROR/CRITICAL.
        fmt: SYLEA_LOG_FORMAT ou json/text.
    """
    level_name = (level or os.environ.get("SYLEA_LOG_LEVEL") or "INFO").upper()
    level_int = getattr(logging, level_name, logging.INFO)

    format_choice = (fmt or _detect_log_format()).lower()
    if format_choice == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = HumanReadableFormatter(use_color=True)

    # Reset handlers existants (sinon, en dev, on a parfois des doublons)
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(level_int)
    root.addHandler(handler)
    root.setLevel(level_int)

    # Réduire le bruit des libs tierces
    for noisy in ("httpx", "httpcore", "uvicorn.access", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Wrapper pour cohérence d'import. Équivalent `logging.getLogger(name)`."""
    return logging.getLogger(name)


# ─────────────────────────────────────────────────────────────────────────────
# Middleware FastAPI : génère/propage le request_id
# ─────────────────────────────────────────────────────────────────────────────

class RequestContextMiddleware(BaseHTTPMiddleware):
    """Génère un `request_id` par requête, le pose dans contextvars + header.

    - Si le client envoie déjà un `X-Request-Id` (header config via env),
      on le réutilise (utile pour tracing distribué : frontend → backend).
    - Sinon, on génère un UUID4.
    - À la fin de la requête : on le renvoie en réponse pour que le client
      puisse le logger côté lui (debug end-to-end).
    """

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self._header_name = os.environ.get(
            "SYLEA_LOG_REQUEST_ID_HEADER", "X-Request-Id"
        )

    async def dispatch(self, request, call_next):  # type: ignore[override]
        # 1) Récupère ou génère
        incoming = request.headers.get(self._header_name)
        rid = incoming if incoming and len(incoming) <= 128 else str(uuid.uuid4())

        # 2) Pose dans contextvars
        token = _request_id.set(rid)

        # 3) Traite la requête
        try:
            response = await call_next(request)
        finally:
            # 4) Nettoie le contexte pour ne pas leaker sur des tâches background
            _request_id.reset(token)
            _user_id.set(None)
            _user_tier.set(None)

        # 5) Renvoie l'ID au client
        response.headers[self._header_name] = rid
        return response


# ─────────────────────────────────────────────────────────────────────────────
# Helpers pour mesurer la latence d'une opération
# ─────────────────────────────────────────────────────────────────────────────

class TimedOperation:
    """Context manager qui logge la durée d'une opération.

    Usage :
        with TimedOperation("dilemma_analysis", logger):
            result = analyze(...)
        # → log "dilemma_analysis completed" + extra={"duration_ms": ...}
    """

    def __init__(self, name: str, logger: logging.Logger, **extra):
        self.name = name
        self.logger = logger
        self.extra = extra
        self._t0: float = 0.0

    def __enter__(self) -> "TimedOperation":
        self._t0 = time.perf_counter()
        self.logger.debug(f"{self.name} started", extra=self.extra)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        duration_ms = round((time.perf_counter() - self._t0) * 1000, 2)
        payload = {**self.extra, "duration_ms": duration_ms}
        if exc_type is None:
            self.logger.info(f"{self.name} completed", extra=payload)
        else:
            payload["error"] = str(exc)
            self.logger.error(f"{self.name} failed", extra=payload, exc_info=True)
        return False  # ne pas avaler l'exception
