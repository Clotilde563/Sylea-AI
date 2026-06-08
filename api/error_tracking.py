"""
Error tracking — Syléa.AI (intégration Sentry).

Initialise Sentry SDK avec la config standard production :
  - PII scrubbing automatique (emails, IDs)
  - Sampling configurable (traces + profiles)
  - Integration FastAPI + SQLAlchemy + httpx
  - Tags depuis env (env, release, region)
  - Filtering : on n'envoie pas les 4xx classiques (auth, rate limit)

Activation :
  SENTRY_DSN=https://...@sentry.io/...
  SENTRY_ENVIRONMENT=production|staging|preview
  SENTRY_RELEASE=git-sha-de-la-release
  SENTRY_TRACES_SAMPLE_RATE=0.1  (10% des traces)
  SENTRY_PROFILES_SAMPLE_RATE=0.0  (profiling off par défaut)

Sans `SENTRY_DSN`, le module est no-op (tests + dev local OK).
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("sylea.error_tracking")


# ─────────────────────────────────────────────────────────────────────────────
# Filtering : événements à NE PAS envoyer à Sentry
# ─────────────────────────────────────────────────────────────────────────────

# Codes HTTP qu'on ne veut PAS voir dans Sentry (bruit)
_IGNORED_HTTP_STATUSES = frozenset({401, 403, 404, 422, 429})


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """Hook Sentry : filtre les events avant envoi.

    Retourne None pour skip l'event, ou l'event modifié.
    """
    # Skip les exceptions HTTP de bas niveau (4xx auth/rate-limit)
    exc_info = hint.get("exc_info")
    if exc_info:
        exc = exc_info[1]
        status = getattr(exc, "status_code", None)
        if status in _IGNORED_HTTP_STATUSES:
            return None

    # Scrubbing PII supplémentaire (au cas où l'utilisateur enverrait des
    # données sensibles dans des messages d'erreur)
    if "request" in event:
        req = event["request"]
        # On supprime les query params et body — uniquement headers + URL
        req.pop("query_string", None)
        req.pop("data", None)
        # On scrub Authorization / Cookie
        headers = req.get("headers", {}) or {}
        for k in list(headers.keys()):
            if k.lower() in ("authorization", "cookie", "x-api-key"):
                headers[k] = "[REDACTED]"

    # On préserve le request_id pour pouvoir corréler avec les logs
    from api.logging_setup import get_request_id
    rid = get_request_id()
    if rid:
        event.setdefault("tags", {})["request_id"] = rid

    return event


# ─────────────────────────────────────────────────────────────────────────────
# Init
# ─────────────────────────────────────────────────────────────────────────────

_initialized = False


def init_sentry() -> bool:
    """Initialise Sentry si SENTRY_DSN est défini. No-op sinon.

    Returns:
        True si initialisé, False sinon (dev/test sans DSN).
    """
    global _initialized
    if _initialized:
        return True

    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        logger.info("[sentry] SENTRY_DSN non défini — error tracking désactivé.")
        return False

    try:
        import sentry_sdk  # type: ignore
        from sentry_sdk.integrations.fastapi import FastApiIntegration  # type: ignore
        from sentry_sdk.integrations.starlette import StarletteIntegration  # type: ignore
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration  # type: ignore
        from sentry_sdk.integrations.httpx import HttpxIntegration  # type: ignore
        from sentry_sdk.integrations.logging import LoggingIntegration  # type: ignore
    except ImportError:
        logger.warning(
            "[sentry] sentry-sdk absent (pip install sentry-sdk[fastapi]). "
            "Error tracking désactivé."
        )
        return False

    env = os.environ.get("SENTRY_ENVIRONMENT", "production")
    release = os.environ.get("SENTRY_RELEASE", "unknown")
    try:
        traces_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
    except ValueError:
        traces_rate = 0.1
    try:
        profiles_rate = float(os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.0"))
    except ValueError:
        profiles_rate = 0.0

    sentry_sdk.init(
        dsn=dsn,
        environment=env,
        release=release,
        traces_sample_rate=traces_rate,
        profiles_sample_rate=profiles_rate,
        send_default_pii=False,  # Pas d'envoi de PII auto (RGPD)
        attach_stacktrace=True,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
            SqlalchemyIntegration(),
            HttpxIntegration(),
            LoggingIntegration(
                level=logging.INFO,        # breadcrumbs depuis INFO
                event_level=logging.ERROR,  # events Sentry depuis ERROR
            ),
        ],
        before_send=_before_send,
    )

    _initialized = True
    logger.info(
        "[sentry] initialisé (env=%s, release=%s, traces=%s, profiles=%s)",
        env, release, traces_rate, profiles_rate,
    )
    return True


def is_initialized() -> bool:
    return _initialized


def capture_exception(exc: Exception | None = None, **extra) -> None:
    """Envoie manuellement une exception à Sentry (no-op si non init)."""
    if not _initialized:
        return
    try:
        import sentry_sdk  # type: ignore
        with sentry_sdk.push_scope() as scope:
            for k, v in extra.items():
                scope.set_extra(k, v)
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass  # ne jamais crasher dans le tracking d'erreurs


def capture_message(message: str, level: str = "info", **extra) -> None:
    """Envoie un message custom à Sentry."""
    if not _initialized:
        return
    try:
        import sentry_sdk  # type: ignore
        with sentry_sdk.push_scope() as scope:
            for k, v in extra.items():
                scope.set_extra(k, v)
            sentry_sdk.capture_message(message, level=level)
    except Exception:
        pass


def set_user(user_id: str, tier: str | None = None, email_hash: str | None = None) -> None:
    """Attache l'utilisateur courant au scope Sentry (pour error grouping).

    Note : on n'envoie JAMAIS l'email en clair (RGPD). Si besoin, hasher.
    """
    if not _initialized:
        return
    try:
        import sentry_sdk  # type: ignore
        data: dict[str, str] = {"id": user_id}
        if tier:
            data["tier"] = tier
        if email_hash:
            data["email_hash"] = email_hash
        sentry_sdk.set_user(data)
    except Exception:
        pass


def get_config() -> dict[str, Any]:
    """Diagnostic /api/health/sentry."""
    return {
        "initialized": _initialized,
        "dsn_present": bool(os.environ.get("SENTRY_DSN")),
        "environment": os.environ.get("SENTRY_ENVIRONMENT", "unknown"),
        "release": os.environ.get("SENTRY_RELEASE", "unknown"),
        "traces_sample_rate": os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"),
    }
