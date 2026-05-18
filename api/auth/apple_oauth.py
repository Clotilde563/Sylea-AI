"""
Sign in with Apple — Syléa.AI.

Implémentation du flux OAuth 2.0 / OIDC d'Apple pour authentifier les
utilisateurs avec leur Apple ID.

Spécificités vs Google/GitHub :
  - Le `client_secret` n'est PAS une string statique : c'est un JWT signé en
    ES256 (ECDSA P-256) avec la clé privée Apple (.p8). On le génère à la
    volée pour chaque échange (durée de vie max 6 mois autorisée par Apple,
    on régénère par défaut à 30 min pour limiter l'exposition).
  - Apple ne renvoie le nom/prénom de l'utilisateur **qu'au PREMIER login**.
    Le frontend doit nous transmettre `user.name.firstName` / `lastName`
    extraits du form POST initial. Au 2e login, seul `id_token` arrive.
  - L'`id_token` est un JWT signé ES256 par Apple. On vérifie la signature
    via les clés publiques JWKS de https://appleid.apple.com/auth/keys.
  - Le `email` peut être un alias `xxx@privaterelay.appleid.com` si
    l'utilisateur a coché "Hide my email" (le user peut révoquer le relais).

Configuration env :
  APPLE_CLIENT_ID         = com.sylea.ai             # Bundle ID ou Services ID
  APPLE_TEAM_ID           = 10 chars Apple Developer Team ID
  APPLE_KEY_ID            = 10 chars Key ID (du AuthKey_XXXXXXXXXX.p8)
  APPLE_PRIVATE_KEY       = -----BEGIN PRIVATE KEY-----\n...\n-----END...-----
                            (contenu complet du .p8, newlines en \n)
  APPLE_REDIRECT_URI      = https://api.sylea.ai/api/auth/oauth/apple/callback

Documentation Apple :
  - https://developer.apple.com/documentation/sign_in_with_apple
  - https://developer.apple.com/documentation/signinwithapplerestapi/generate_and_validate_tokens
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("sylea.auth.apple")


# ─────────────────────────────────────────────────────────────────────────────
# Constantes Apple
# ─────────────────────────────────────────────────────────────────────────────

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
APPLE_AUTH_URL = "https://appleid.apple.com/auth/authorize"

# Durée de vie du client_secret JWT (max Apple = 6 mois ; on prend 30 min)
_CLIENT_SECRET_TTL_S = 30 * 60


# ─────────────────────────────────────────────────────────────────────────────
# Génération du client_secret JWT (signé ES256 avec la clé .p8)
# ─────────────────────────────────────────────────────────────────────────────

def _load_private_key():
    """Charge la clé privée P-256 depuis APPLE_PRIVATE_KEY."""
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError as e:
        raise RuntimeError(
            "cryptography requis pour signer le JWT Apple "
            "(pip install cryptography)."
        ) from e

    key_pem = os.environ.get("APPLE_PRIVATE_KEY", "")
    if not key_pem:
        raise RuntimeError(
            "APPLE_PRIVATE_KEY manquant — fournir le contenu du fichier "
            "AuthKey_XXXXXXXXXX.p8 (téléchargé sur developer.apple.com)."
        )

    # Le PEM peut contenir des \n littéraux (depuis l'env var)
    key_pem = key_pem.replace("\\n", "\n")

    return serialization.load_pem_private_key(
        key_pem.encode("utf-8"),
        password=None,
    )


def build_client_secret(
    client_id: str | None = None,
    team_id: str | None = None,
    key_id: str | None = None,
    ttl_s: int = _CLIENT_SECRET_TTL_S,
) -> str:
    """Génère un client_secret JWT signé ES256 valide pour Apple.

    Args:
        client_id: Services ID (web) ou Bundle ID (native). Défaut env APPLE_CLIENT_ID.
        team_id: 10 chars Apple Developer Team ID. Défaut env APPLE_TEAM_ID.
        key_id: 10 chars Key ID associé à la clé privée. Défaut env APPLE_KEY_ID.
        ttl_s: durée de vie en secondes (max 15777000 = 6 mois).

    Returns:
        JWT signé ES256 prêt pour le champ client_secret du token request.

    Raises:
        RuntimeError si env vars / lib manquantes.
    """
    try:
        from jose import jwt  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "python-jose requis pour générer le JWT Apple "
            "(déjà dans requirements.txt)."
        ) from e

    client_id = client_id or os.environ.get("APPLE_CLIENT_ID", "")
    team_id = team_id or os.environ.get("APPLE_TEAM_ID", "")
    key_id = key_id or os.environ.get("APPLE_KEY_ID", "")

    if not (client_id and team_id and key_id):
        raise RuntimeError(
            "Apple OAuth non configuré : APPLE_CLIENT_ID, APPLE_TEAM_ID, "
            "APPLE_KEY_ID requis."
        )

    now = int(time.time())
    payload = {
        "iss": team_id,                # Issuer = Apple Team ID
        "iat": now,                    # Issued at
        "exp": now + ttl_s,            # Expires
        "aud": APPLE_ISSUER,           # Audience = Apple
        "sub": client_id,              # Subject = notre client_id
    }
    headers = {
        "alg": "ES256",
        "kid": key_id,
    }

    private_key = _load_private_key()

    # python-jose accepte PEM PKCS8 ou la clé crypto Python directement
    from cryptography.hazmat.primitives import serialization
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    return jwt.encode(payload, pem, algorithm="ES256", headers=headers)


# ─────────────────────────────────────────────────────────────────────────────
# Cache JWKS (clés publiques Apple) — refresh quotidien
# ─────────────────────────────────────────────────────────────────────────────

_jwks_cache: dict[str, Any] | None = None
_jwks_cached_at: float = 0.0
_JWKS_TTL_S = 86400  # 24h


async def _fetch_apple_jwks() -> dict[str, Any]:
    """Récupère les clés publiques d'Apple (avec cache 24h)."""
    global _jwks_cache, _jwks_cached_at

    now = time.time()
    if _jwks_cache and (now - _jwks_cached_at) < _JWKS_TTL_S:
        return _jwks_cache

    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(APPLE_KEYS_URL)
        r.raise_for_status()
        _jwks_cache = r.json()
        _jwks_cached_at = now
    return _jwks_cache  # type: ignore[return-value]


def _find_apple_key(jwks: dict[str, Any], kid: str) -> dict[str, Any] | None:
    """Trouve la clé publique Apple correspondant au kid de l'id_token."""
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Vérification de l'id_token
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AppleUser:
    """Utilisateur extrait d'un id_token Apple validé."""
    sub: str                        # Identifiant unique Apple (= provider_id)
    email: str | None = None
    email_verified: bool = False
    is_private_email: bool = False  # True si @privaterelay.appleid.com
    name: str | None = None         # extrait du form POST initial (1er login uniquement)


async def verify_id_token(
    id_token: str,
    expected_audience: str | None = None,
) -> AppleUser:
    """Vérifie un id_token Apple : signature ES256 + claims.

    Args:
        id_token: JWT renvoyé par Apple dans la réponse token.
        expected_audience: client_id attendu (défaut env APPLE_CLIENT_ID).

    Returns:
        AppleUser avec sub + email si validation OK.

    Raises:
        ValueError si signature invalide, expiré, audience incorrecte.
    """
    try:
        from jose import jwt  # type: ignore
        from jose.exceptions import JWTError  # type: ignore
    except ImportError as e:
        raise RuntimeError("python-jose requis.") from e

    expected_audience = expected_audience or os.environ.get("APPLE_CLIENT_ID", "")
    if not expected_audience:
        raise RuntimeError("APPLE_CLIENT_ID manquant pour validation.")

    # 1) Lecture du header non vérifié pour récupérer kid
    try:
        unverified = jwt.get_unverified_header(id_token)
        kid = unverified.get("kid")
    except JWTError as e:
        raise ValueError(f"id_token malformé : {e}")

    if not kid:
        raise ValueError("id_token sans kid dans le header.")

    # 2) Récupération de la clé publique Apple correspondante
    jwks = await _fetch_apple_jwks()
    key = _find_apple_key(jwks, kid)
    if not key:
        raise ValueError(f"Clé publique Apple inconnue : kid={kid}")

    # 3) Vérification signature + claims standards
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["ES256"],
            audience=expected_audience,
            issuer=APPLE_ISSUER,
        )
    except JWTError as e:
        raise ValueError(f"id_token invalide : {e}")

    # 4) Extraction utilisateur
    sub = claims.get("sub", "")
    email = claims.get("email")
    if not sub:
        raise ValueError("id_token sans sub (subject).")

    email_verified_raw = claims.get("email_verified")
    # Apple renvoie parfois "true"/"false" string au lieu de bool
    if isinstance(email_verified_raw, str):
        email_verified = email_verified_raw.lower() == "true"
    else:
        email_verified = bool(email_verified_raw)

    is_private = bool(claims.get("is_private_email", False))
    if isinstance(claims.get("is_private_email"), str):
        is_private = claims["is_private_email"].lower() == "true"

    return AppleUser(
        sub=sub,
        email=email,
        email_verified=email_verified,
        is_private_email=is_private,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Échange code → tokens
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AppleTokens:
    """Tokens renvoyés par /auth/token Apple."""
    access_token: str
    id_token: str           # JWT contenant les claims utilisateur
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_in: int = 3600


async def exchange_code(
    code: str,
    redirect_uri: str,
    client_id: str | None = None,
) -> AppleTokens:
    """Échange un code d'autorisation contre des tokens Apple.

    Args:
        code: code retourné par Apple après auth utilisateur.
        redirect_uri: DOIT correspondre EXACTEMENT à celui configuré chez Apple.
        client_id: défaut env APPLE_CLIENT_ID.

    Returns:
        AppleTokens incluant id_token signé.
    """
    import httpx

    client_id = client_id or os.environ.get("APPLE_CLIENT_ID", "")
    if not client_id:
        raise RuntimeError("APPLE_CLIENT_ID manquant.")

    client_secret = build_client_secret(client_id=client_id)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            APPLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

    if resp.status_code != 200:
        try:
            err = resp.json()
        except Exception:
            err = {"error": resp.text[:200]}
        # Logger ERROR sans le code (qui n'est plus utile post-échange)
        logger.warning(
            "[apple] échange code échoué status=%d error=%s",
            resp.status_code, err.get("error"),
        )
        raise ValueError(f"Apple token exchange failed: {err.get('error', resp.status_code)}")

    data = resp.json()
    return AppleTokens(
        access_token=data.get("access_token", ""),
        id_token=data.get("id_token", ""),
        refresh_token=data.get("refresh_token"),
        token_type=data.get("token_type", "Bearer"),
        expires_in=int(data.get("expires_in", 3600)),
    )


# ─────────────────────────────────────────────────────────────────────────────
# URL d'autorisation (pour bouton "Sign in with Apple" frontend)
# ─────────────────────────────────────────────────────────────────────────────

def build_authorize_url(
    redirect_uri: str,
    state: str,
    scope: str = "name email",
    client_id: str | None = None,
    response_mode: str = "form_post",
) -> str:
    """Construit l'URL d'autorisation pour rediriger l'utilisateur vers Apple.

    Args:
        redirect_uri: doit MATCHER exactement celui configuré chez Apple.
        state: anti-CSRF nonce (à valider au retour).
        scope: "name email" pour récupérer le profil au premier login.
        response_mode: "form_post" est OBLIGATOIRE si scope inclut "name"
                       ou "email" (Apple impose POST pour transporter le
                       form-encoded user data au callback).

    Returns:
        URL complète vers appleid.apple.com/auth/authorize.
    """
    import urllib.parse

    client_id = client_id or os.environ.get("APPLE_CLIENT_ID", "")
    if not client_id:
        raise RuntimeError("APPLE_CLIENT_ID manquant.")

    params = {
        "response_type": "code id_token",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "response_mode": response_mode,
    }
    return f"{APPLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostic
# ─────────────────────────────────────────────────────────────────────────────

def get_apple_oauth_config() -> dict[str, Any]:
    """Diagnostic : drapeaux config Apple (sans secret)."""
    return {
        "client_id_present": bool(os.environ.get("APPLE_CLIENT_ID")),
        "team_id_present": bool(os.environ.get("APPLE_TEAM_ID")),
        "key_id_present": bool(os.environ.get("APPLE_KEY_ID")),
        "private_key_present": bool(os.environ.get("APPLE_PRIVATE_KEY")),
        "redirect_uri": os.environ.get("APPLE_REDIRECT_URI", ""),
        "configured": all(
            os.environ.get(k) for k in
            ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY")
        ),
    }
