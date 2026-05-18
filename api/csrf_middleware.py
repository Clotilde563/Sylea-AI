"""
CSRF protection — Syléa.AI (sécurité niveau pro).

Implémentation : Double-Submit Cookie pattern (variant Signed Token).
  - Au premier GET, on génère un token CSRF signé HMAC + on le pose dans
    un cookie non-HttpOnly `sylea_csrf` (lisible côté JS).
  - Le frontend lit ce cookie et l'envoie en header `X-CSRF-Token` sur
    chaque POST/PUT/PATCH/DELETE.
  - Le middleware vérifie que header == cookie ET que la signature HMAC
    est valide (sinon, un attaquant pourrait forger un cookie côté client).

Pourquoi pas un session-token côté serveur ?
  - Stateless : pas de table CSRF en DB. Le token est self-contained.
  - Compatible avec API stateless JWT (notre cas).
  - Pas de RTT supplémentaire (un GET initial suffit).

Endpoints exemptés :
  - Authentification (login/signup) : pas encore de session → CSRF ne
    s'applique pas. Protection assurée par le rate-limiter IP + l'auth.
  - WebSocket (handshake initial fait via header Authorization).
  - Health checks, statics.

Configuration :
  - SYLEA_CSRF_SECRET : clé HMAC. Si absente, dérivée de JWT_SECRET_KEY.
  - SYLEA_DISABLE_CSRF=true : désactive (tests, dev). En prod, FORCER ON.
  - SYLEA_CSRF_COOKIE_SECURE=true : pose le cookie en Secure (HTTPS only).
  - SYLEA_CSRF_COOKIE_SAMESITE=strict|lax|none : défaut `lax`.

Tokens :
  - Format : `<random_24_bytes_b64>.<hmac_sha256_b64>`
  - HMAC sur le random pour empêcher la forge côté client.
  - TTL implicite via expiration cookie (8h par défaut).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("sylea.csrf")


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

CSRF_COOKIE_NAME = "sylea_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_COOKIE_MAX_AGE_S = 8 * 3600  # 8h — re-généré au prochain GET sinon

# Méthodes considérées comme "unsafe" → CSRF requis
_UNSAFE_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Endpoints exemptés (pas de session à protéger ou auth déjà robuste)
_EXEMPT_PATH_PREFIXES: tuple[str, ...] = (
    # Auth : login/signup s'appuient sur le rate-limiter IP + JWT issued
    "/api/auth/login",
    "/api/auth/signup",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
    "/api/auth/verify-code",
    "/api/auth/oauth/",       # OAuth Google/GitHub callbacks
    "/api/auth/callback",
    # Webhooks Stripe — signature dédiée, pas de CSRF
    "/api/stripe/webhook",
    # WebSocket handshake — token JWT en query string
    "/ws/",
    # Health / static
    "/api/health",
    "/static/",
)


# ─────────────────────────────────────────────────────────────────────────────
# Clé HMAC
# ─────────────────────────────────────────────────────────────────────────────

def _get_csrf_secret() -> bytes:
    """Récupère la clé HMAC depuis l'env. Dérive de JWT_SECRET_KEY en fallback.

    On NE log JAMAIS le secret. Si tout est manquant en dev, on dérive d'une
    clé statique de DEV (refusée en prod via _check_prod_secret).
    """
    explicit = os.environ.get("SYLEA_CSRF_SECRET")
    if explicit:
        return explicit.encode("utf-8")

    jwt_secret = os.environ.get("JWT_SECRET_KEY")
    if jwt_secret:
        # Dérivation HKDF-like simplifiée : SHA256(jwt_secret + tag)
        return hashlib.sha256(
            jwt_secret.encode("utf-8") + b"|sylea-csrf-derivation-v1"
        ).digest()

    # Dev uniquement : clé fixe pour cohérence entre reloads
    logger.warning("[csrf] Aucun JWT_SECRET_KEY/SYLEA_CSRF_SECRET — "
                   "fallback clé DEV (NE JAMAIS utiliser en prod).")
    return hashlib.sha256(b"sylea-csrf-dev-fallback-DO-NOT-USE-IN-PROD").digest()


def _check_prod_secret() -> None:
    """Crash au boot si on est en prod (DATABASE_URL PG) sans secret réel."""
    db_url = os.environ.get("DATABASE_URL", "")
    is_pg_prod = db_url.startswith(("postgres://", "postgresql://", "postgresql+"))
    if not is_pg_prod:
        return
    if not (os.environ.get("SYLEA_CSRF_SECRET") or os.environ.get("JWT_SECRET_KEY")):
        raise RuntimeError(
            "Production détectée (PostgreSQL) sans SYLEA_CSRF_SECRET ni "
            "JWT_SECRET_KEY. Définir au moins l'un des deux."
        )


_check_prod_secret()
_CSRF_SECRET = _get_csrf_secret()


# ─────────────────────────────────────────────────────────────────────────────
# Génération / vérification de token
# ─────────────────────────────────────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    """Base64 URL-safe sans padding (compatible cookie)."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    """Decode b64 URL-safe, ré-injecte le padding."""
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def generate_csrf_token() -> str:
    """Génère un token CSRF signé HMAC : `<random>.<hmac>`."""
    random_part = secrets.token_bytes(24)
    sig = hmac.new(_CSRF_SECRET, random_part, hashlib.sha256).digest()
    return f"{_b64url(random_part)}.{_b64url(sig)}"


def verify_csrf_token(token: str) -> bool:
    """Vérifie qu'un token a été signé par notre clé HMAC.

    `hmac.compare_digest` pour éviter les timing attacks.
    """
    if not token or "." not in token:
        return False
    try:
        random_b64, sig_b64 = token.split(".", 1)
        random_part = _b64url_decode(random_b64)
        sig = _b64url_decode(sig_b64)
        if len(random_part) != 24 or len(sig) != 32:
            return False
        expected = hmac.new(_CSRF_SECRET, random_part, hashlib.sha256).digest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def is_path_exempt(path: str, extra_exempt: Iterable[str] = ()) -> bool:
    """True si le chemin est dans la liste d'exemption CSRF."""
    for prefix in _EXEMPT_PATH_PREFIXES:
        if path.startswith(prefix):
            return True
    for prefix in extra_exempt:
        if path.startswith(prefix):
            return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────────────────────

class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie + signed token pour POST/PUT/PATCH/DELETE.

    Comportement :
      - GET safe : si pas de cookie CSRF, on en pose un nouveau (rotation
        à chaque GET vs persistance ? on garde fixe sur la durée du cookie
        pour ne pas casser les onglets multiples).
      - POST/PUT/etc : on exige le header X-CSRF-Token === cookie sylea_csrf,
        ET que la signature soit valide. Sinon 403.

    Exempte :
      - Endpoints d'auth (login/signup) : aucune session à protéger.
      - WebSocket : géré ailleurs.
    """

    def __init__(self, app: ASGIApp, extra_exempt: Iterable[str] = ()):
        super().__init__(app)
        self._extra_exempt = tuple(extra_exempt)
        self._disabled = os.environ.get(
            "SYLEA_DISABLE_CSRF", ""
        ).strip().lower() in ("1", "true", "yes", "on")
        self._cookie_secure = os.environ.get(
            "SYLEA_CSRF_COOKIE_SECURE", ""
        ).strip().lower() in ("1", "true", "yes", "on")
        self._cookie_samesite = (
            os.environ.get("SYLEA_CSRF_COOKIE_SAMESITE", "lax").strip().lower()
        )
        if self._cookie_samesite not in ("strict", "lax", "none"):
            self._cookie_samesite = "lax"

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if self._disabled:
            response = await call_next(request)
            return response

        path = request.url.path
        method = request.method.upper()

        # Exemption : on émet quand même un cookie au GET pour faciliter
        # le frontend, mais on ne valide pas.
        if is_path_exempt(path, self._extra_exempt):
            response = await call_next(request)
            self._ensure_cookie(request, response)
            return response

        # POST/PUT/PATCH/DELETE : validation stricte
        if method in _UNSAFE_METHODS:
            cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
            header_token = request.headers.get(CSRF_HEADER_NAME)

            if not cookie_token or not header_token:
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Protection CSRF : cookie ou header manquant.",
                        "code": "csrf_missing",
                    },
                )

            # Double-submit : cookie et header DOIVENT correspondre
            if not hmac.compare_digest(cookie_token, header_token):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Protection CSRF : cookie et header divergent.",
                        "code": "csrf_mismatch",
                    },
                )

            # Signature : empêche un attaquant de forger un cookie+header
            if not verify_csrf_token(cookie_token):
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Protection CSRF : signature invalide.",
                        "code": "csrf_invalid_signature",
                    },
                )

        # Méthode safe (GET/HEAD/OPTIONS) ou POST valide : on continue
        response = await call_next(request)
        self._ensure_cookie(request, response)
        return response

    def _ensure_cookie(self, request: Request, response) -> None:
        """Pose le cookie CSRF si absent (1er GET typiquement)."""
        existing = request.cookies.get(CSRF_COOKIE_NAME)
        if existing and verify_csrf_token(existing):
            # Cookie déjà présent et valide : on ne le rotate pas (sinon
            # tous les onglets ouverts perdent leur token simultanément)
            return

        new_token = generate_csrf_token()
        # Cookie non-HttpOnly : le frontend DOIT pouvoir le lire en JS
        # pour le renvoyer dans le header X-CSRF-Token (double-submit pattern).
        response.set_cookie(
            key=CSRF_COOKIE_NAME,
            value=new_token,
            max_age=CSRF_COOKIE_MAX_AGE_S,
            httponly=False,
            secure=self._cookie_secure,
            samesite=self._cookie_samesite,
            path="/",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helper pour les tests / endpoints qui exposent un token (rare)
# ─────────────────────────────────────────────────────────────────────────────

def get_csrf_cookie_for_response(response, secure: bool = False) -> str:
    """Génère et pose un cookie CSRF, retourne le token (pour tests)."""
    token = generate_csrf_token()
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=CSRF_COOKIE_MAX_AGE_S,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return token
