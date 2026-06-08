"""
Security headers middleware — Syléa.AI (sécurité niveau pro).

Ajoute les headers HTTP de sécurité standards sur toutes les réponses :

  - Strict-Transport-Security (HSTS) : force HTTPS pendant 1 an + preload
  - Content-Security-Policy (CSP) : whitelist stricte de sources autorisées
  - X-Content-Type-Options : nosniff (empêche MIME confusion)
  - X-Frame-Options : DENY (anti clickjacking, complète frame-ancestors CSP)
  - Referrer-Policy : strict-origin-when-cross-origin (limite leak via Referer)
  - Permissions-Policy : désactive géoloc/caméra/micro sauf consent explicite
  - Cross-Origin-Opener-Policy : same-origin (anti Spectre)
  - Cross-Origin-Resource-Policy : same-site

CSP est la défense la plus puissante contre les XSS reflétés/stockés.
Configuration permissive en dev (eval autorisé pour Vite HMR), stricte en prod.

Variables d'env :
  SYLEA_SECURITY_HEADERS_MODE     : strict (prod) | dev (relâché) — défaut auto
  SYLEA_CSP_REPORT_URI            : URL pour reporter les violations CSP
  SYLEA_CSP_EXTRA_SCRIPT_SRC      : domaines additionnels pour script-src
  SYLEA_CSP_EXTRA_CONNECT_SRC     : domaines additionnels pour connect-src
  SYLEA_DISABLE_SECURITY_HEADERS  : true pour désactiver (tests uniquement)
"""

from __future__ import annotations

import logging
import os
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("sylea.security_headers")


# ─────────────────────────────────────────────────────────────────────────────
# Détection prod vs dev
# ─────────────────────────────────────────────────────────────────────────────

def _is_production() -> bool:
    """Heuristique prod : DATABASE_URL pointe vers PostgreSQL."""
    db_url = os.environ.get("DATABASE_URL", "")
    return db_url.startswith(("postgres://", "postgresql://", "postgresql+"))


def _get_mode() -> str:
    """strict (prod) ou dev (autorise eval pour Vite HMR)."""
    explicit = os.environ.get("SYLEA_SECURITY_HEADERS_MODE", "").strip().lower()
    if explicit in ("strict", "dev"):
        return explicit
    return "strict" if _is_production() else "dev"


# ─────────────────────────────────────────────────────────────────────────────
# Construction de la CSP
# ─────────────────────────────────────────────────────────────────────────────

# Sources de base (toujours autorisées)
_DEFAULT_SCRIPT_SRC = ["'self'"]
_DEFAULT_STYLE_SRC = ["'self'", "'unsafe-inline'"]  # styles inline OK (CSS-in-JS)
_DEFAULT_IMG_SRC = ["'self'", "data:", "blob:", "https:"]
_DEFAULT_FONT_SRC = ["'self'", "data:"]
_DEFAULT_CONNECT_SRC = [
    "'self'",
    # APIs Anthropic/OpenAI (Claude, GPT, TTS)
    "https://api.anthropic.com",
    "https://api.openai.com",
    # Stripe (paiements)
    "https://api.stripe.com",
    "https://checkout.stripe.com",
    # Open-Meteo (météo publique)
    "https://api.open-meteo.com",
    # Backend dev (CORS local pour Tauri/Vite)
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "ws://localhost:8000",
    "ws://127.0.0.1:8000",
]
_DEFAULT_FRAME_SRC = [
    "'self'",
    "https://js.stripe.com",
    "https://checkout.stripe.com",
]


def _split_extra(env_name: str) -> list[str]:
    """Parse une liste d'URLs séparées par virgule depuis l'env."""
    raw = os.environ.get(env_name, "")
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _build_csp(mode: str) -> str:
    """Construit la chaîne CSP complète selon le mode."""
    script_src = list(_DEFAULT_SCRIPT_SRC)
    style_src = list(_DEFAULT_STYLE_SRC)
    img_src = list(_DEFAULT_IMG_SRC)
    font_src = list(_DEFAULT_FONT_SRC)
    connect_src = list(_DEFAULT_CONNECT_SRC)
    frame_src = list(_DEFAULT_FRAME_SRC)

    # Mode dev : autorise 'unsafe-eval' pour Vite HMR + ws://localhost
    if mode == "dev":
        script_src.append("'unsafe-eval'")
        script_src.append("'unsafe-inline'")  # Vite injecte des scripts inline

    # Extra sources depuis l'env (pour Stripe.js, etc.)
    script_src.extend(_split_extra("SYLEA_CSP_EXTRA_SCRIPT_SRC"))
    connect_src.extend(_split_extra("SYLEA_CSP_EXTRA_CONNECT_SRC"))

    # Stripe charge ses scripts depuis js.stripe.com
    if "https://js.stripe.com" not in script_src:
        script_src.append("https://js.stripe.com")

    directives = [
        f"default-src 'self'",
        f"script-src {' '.join(script_src)}",
        f"style-src {' '.join(style_src)}",
        f"img-src {' '.join(img_src)}",
        f"font-src {' '.join(font_src)}",
        f"connect-src {' '.join(connect_src)}",
        f"frame-src {' '.join(frame_src)}",
        # Anti-clickjacking (complète X-Frame-Options pour navigateurs modernes)
        f"frame-ancestors 'none'",
        # Empêche l'application d'être chargée depuis un sous-domaine inattendu
        f"base-uri 'self'",
        # Formulaires : soumettre uniquement sur same-origin
        f"form-action 'self'",
        # Empêche les plugins (Flash) — héritage mais sans risque
        f"object-src 'none'",
        # Upgrade-insecure-requests : force HTTPS pour les sous-ressources
    ]

    if mode == "strict":
        directives.append("upgrade-insecure-requests")

    # Reporting (optionnel)
    report_uri = os.environ.get("SYLEA_CSP_REPORT_URI", "").strip()
    if report_uri:
        directives.append(f"report-uri {report_uri}")

    return "; ".join(directives)


# ─────────────────────────────────────────────────────────────────────────────
# Permissions-Policy
# ─────────────────────────────────────────────────────────────────────────────

def _build_permissions_policy() -> str:
    """Désactive toutes les API sensibles sauf si explicitement demandées.

    Note : `microphone=(self)` parce que la saisie vocale (SpeechRecognition
    de Chrome) fonctionne avec le micro local. `geolocation=(self)` pour le
    widget météo qui demande la position approximative.
    """
    return ", ".join([
        "accelerometer=()",
        "ambient-light-sensor=()",
        "autoplay=(self)",
        "battery=()",
        "camera=()",
        # Saisie vocale (SpeechRecognition) nécessite le micro
        "microphone=(self)",
        # Geoloc widget météo
        "geolocation=(self)",
        "gyroscope=()",
        "magnetometer=()",
        "midi=()",
        "payment=(self)",       # Stripe Checkout en popup
        "picture-in-picture=()",
        "publickey-credentials-get=()",
        "screen-wake-lock=()",
        "sync-xhr=()",
        "usb=()",
        "xr-spatial-tracking=()",
    ])


# ─────────────────────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────────────────────

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Pose les headers de sécurité standard sur toutes les réponses."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self._disabled = os.environ.get(
            "SYLEA_DISABLE_SECURITY_HEADERS", ""
        ).strip().lower() in ("1", "true", "yes", "on")
        self._mode = _get_mode()
        self._csp = _build_csp(self._mode)
        self._permissions_policy = _build_permissions_policy()
        logger.info("[security_headers] mode=%s CSP=%d chars",
                    self._mode, len(self._csp))

    async def dispatch(self, request, call_next):  # type: ignore[override]
        response = await call_next(request)

        if self._disabled:
            return response

        # HSTS : force HTTPS pendant 1 an. `preload` permet l'inclusion dans
        # la liste Chrome HSTS preload (https://hstspreload.org).
        # Mode dev : on n'active PAS HSTS (sinon localhost bloque en dev).
        if self._mode == "strict":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        # Content-Security-Policy — défense principale anti-XSS
        response.headers["Content-Security-Policy"] = self._csp

        # Anti MIME sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Anti clickjacking (complète frame-ancestors CSP)
        response.headers["X-Frame-Options"] = "DENY"

        # Referer : ne pas leak l'URL complète aux third parties
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions-Policy (anciennement Feature-Policy)
        response.headers["Permissions-Policy"] = self._permissions_policy

        # COOP/CORP : isolent l'app des autres origines (anti Spectre)
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"

        # X-XSS-Protection : déprécié, mais reste utile pour IE/vieux WebKit
        response.headers["X-XSS-Protection"] = "0"

        return response


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostic
# ─────────────────────────────────────────────────────────────────────────────

def get_security_headers_config() -> dict:
    """Diagnostic /api/health/security."""
    mode = _get_mode()
    return {
        "mode": mode,
        "csp_length": len(_build_csp(mode)),
        "hsts_enabled": mode == "strict",
        "disabled": os.environ.get(
            "SYLEA_DISABLE_SECURITY_HEADERS", ""
        ).strip().lower() in ("1", "true", "yes", "on"),
    }
