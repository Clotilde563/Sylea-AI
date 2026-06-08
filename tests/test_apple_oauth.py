"""Tests pour api.auth.apple_oauth (Sign in with Apple)."""

from __future__ import annotations

import time

import pytest


# ─── Génération du client_secret JWT (ES256) ─────────────────────────────────

@pytest.fixture
def fake_p8_key():
    """Génère une clé EC P-256 valide pour signer un JWT ES256 (tests)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    return pem


def test_build_client_secret_requires_env(monkeypatch):
    from api.auth.apple_oauth import build_client_secret
    monkeypatch.delenv("APPLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("APPLE_TEAM_ID", raising=False)
    monkeypatch.delenv("APPLE_KEY_ID", raising=False)
    with pytest.raises(RuntimeError, match="non configuré"):
        build_client_secret()


def test_build_client_secret_signs_jwt(monkeypatch, fake_p8_key):
    from api.auth.apple_oauth import APPLE_ISSUER, build_client_secret
    monkeypatch.setenv("APPLE_CLIENT_ID", "com.sylea.ai")
    monkeypatch.setenv("APPLE_TEAM_ID", "TEAM12345A")
    monkeypatch.setenv("APPLE_KEY_ID", "KEY9876543")
    monkeypatch.setenv("APPLE_PRIVATE_KEY", fake_p8_key)

    token = build_client_secret()
    assert token.count(".") == 2  # JWT format header.payload.signature

    # Vérifier les claims sans valider la signature
    from jose import jwt
    claims = jwt.get_unverified_claims(token)
    assert claims["iss"] == "TEAM12345A"
    assert claims["aud"] == APPLE_ISSUER
    assert claims["sub"] == "com.sylea.ai"
    assert claims["exp"] > claims["iat"]
    assert claims["exp"] - claims["iat"] <= 30 * 60  # TTL max 30 min


def test_build_client_secret_header_has_kid(monkeypatch, fake_p8_key):
    from api.auth.apple_oauth import build_client_secret
    monkeypatch.setenv("APPLE_CLIENT_ID", "com.sylea.ai")
    monkeypatch.setenv("APPLE_TEAM_ID", "TEAM12345A")
    monkeypatch.setenv("APPLE_KEY_ID", "KEY9876543")
    monkeypatch.setenv("APPLE_PRIVATE_KEY", fake_p8_key)

    token = build_client_secret()
    from jose import jwt
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "ES256"
    assert header["kid"] == "KEY9876543"


def test_build_client_secret_handles_escaped_newlines(monkeypatch, fake_p8_key):
    """L'env var peut contenir \\n littéraux (depuis docker run --env)."""
    from api.auth.apple_oauth import build_client_secret
    monkeypatch.setenv("APPLE_CLIENT_ID", "com.sylea.ai")
    monkeypatch.setenv("APPLE_TEAM_ID", "TEAM12345A")
    monkeypatch.setenv("APPLE_KEY_ID", "KEY9876543")
    # Remplace les vrais newlines par \n littéraux
    escaped = fake_p8_key.replace("\n", "\\n")
    monkeypatch.setenv("APPLE_PRIVATE_KEY", escaped)

    # Ne doit pas crasher
    token = build_client_secret()
    assert token.count(".") == 2


# ─── URL d'autorisation ───────────────────────────────────────────────────────

def test_build_authorize_url(monkeypatch):
    from api.auth.apple_oauth import build_authorize_url
    monkeypatch.setenv("APPLE_CLIENT_ID", "com.sylea.ai")

    url = build_authorize_url(
        redirect_uri="https://api.sylea.ai/api/auth/oauth/apple/callback",
        state="random_nonce_abc",
    )
    assert url.startswith("https://appleid.apple.com/auth/authorize?")
    assert "client_id=com.sylea.ai" in url
    assert "response_type=code+id_token" in url
    assert "response_mode=form_post" in url
    assert "state=random_nonce_abc" in url
    assert "scope=name+email" in url


def test_build_authorize_url_missing_client_id(monkeypatch):
    from api.auth.apple_oauth import build_authorize_url
    monkeypatch.delenv("APPLE_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError, match="APPLE_CLIENT_ID"):
        build_authorize_url(redirect_uri="x", state="y")


# ─── Diagnostic ──────────────────────────────────────────────────────────────

def test_get_apple_oauth_config_unconfigured(monkeypatch):
    from api.auth.apple_oauth import get_apple_oauth_config
    for var in ("APPLE_CLIENT_ID", "APPLE_TEAM_ID", "APPLE_KEY_ID", "APPLE_PRIVATE_KEY"):
        monkeypatch.delenv(var, raising=False)
    cfg = get_apple_oauth_config()
    assert cfg["configured"] is False
    assert cfg["client_id_present"] is False


def test_get_apple_oauth_config_full(monkeypatch, fake_p8_key):
    from api.auth.apple_oauth import get_apple_oauth_config
    monkeypatch.setenv("APPLE_CLIENT_ID", "com.sylea.ai")
    monkeypatch.setenv("APPLE_TEAM_ID", "TEAM12345A")
    monkeypatch.setenv("APPLE_KEY_ID", "KEY9876543")
    monkeypatch.setenv("APPLE_PRIVATE_KEY", fake_p8_key)
    cfg = get_apple_oauth_config()
    assert cfg["configured"] is True


# ─── Verify id_token (mock JWKS) ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_id_token_invalid_format():
    from api.auth.apple_oauth import verify_id_token
    with pytest.raises(ValueError, match="malformé"):
        await verify_id_token("not.a.valid.jwt", expected_audience="com.sylea.ai")


@pytest.mark.asyncio
async def test_verify_id_token_invalid_kid(monkeypatch, fake_p8_key):
    """Si on signe avec une kid inconnue d'Apple → erreur."""
    from jose import jwt
    from api.auth.apple_oauth import verify_id_token, APPLE_ISSUER
    import api.auth.apple_oauth as ao

    # Reset JWKS cache
    ao._jwks_cache = {"keys": []}
    ao._jwks_cached_at = time.time()

    token = jwt.encode(
        {
            "iss": APPLE_ISSUER,
            "aud": "com.sylea.ai",
            "sub": "001234.abcdef.0001",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "email": "user@example.com",
            "email_verified": "true",
        },
        fake_p8_key,
        algorithm="ES256",
        headers={"kid": "UNKNOWN_KID"},
    )

    with pytest.raises(ValueError, match="kid"):
        await verify_id_token(token, expected_audience="com.sylea.ai")


@pytest.mark.asyncio
async def test_verify_id_token_audience_mismatch(monkeypatch, fake_p8_key):
    """Si l'audience du JWT ne matche pas notre client_id."""
    from jose import jwt
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    from api.auth.apple_oauth import verify_id_token, APPLE_ISSUER
    import api.auth.apple_oauth as ao

    # Construire un JWKS contenant la clé PUBLIQUE correspondant à fake_p8_key
    from cryptography.hazmat.primitives.asymmetric import ec as _ec
    key = serialization.load_pem_private_key(fake_p8_key.encode(), password=None)
    public_numbers = key.public_key().public_numbers()
    import base64
    def b64url(n: int) -> str:
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).decode().rstrip("=")
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "kid": "TESTKID01",
        "use": "sig",
        "alg": "ES256",
        "x": b64url(public_numbers.x),
        "y": b64url(public_numbers.y),
    }
    ao._jwks_cache = {"keys": [jwk]}
    ao._jwks_cached_at = time.time()

    # Token avec mauvaise audience
    token = jwt.encode(
        {
            "iss": APPLE_ISSUER,
            "aud": "different.audience",
            "sub": "001234.abcdef.0001",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
        },
        fake_p8_key,
        algorithm="ES256",
        headers={"kid": "TESTKID01"},
    )

    with pytest.raises(ValueError):
        await verify_id_token(token, expected_audience="com.sylea.ai")


@pytest.mark.asyncio
async def test_verify_id_token_valid(monkeypatch, fake_p8_key):
    """Token valide : signature OK, audience OK, pas expiré."""
    from jose import jwt
    from cryptography.hazmat.primitives import serialization
    from api.auth.apple_oauth import verify_id_token, APPLE_ISSUER
    import api.auth.apple_oauth as ao

    # JWKS fictive contenant notre clé publique
    key = serialization.load_pem_private_key(fake_p8_key.encode(), password=None)
    public_numbers = key.public_key().public_numbers()
    import base64
    def b64url(n: int) -> str:
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).decode().rstrip("=")
    jwk = {
        "kty": "EC",
        "crv": "P-256",
        "kid": "TESTKID02",
        "use": "sig",
        "alg": "ES256",
        "x": b64url(public_numbers.x),
        "y": b64url(public_numbers.y),
    }
    ao._jwks_cache = {"keys": [jwk]}
    ao._jwks_cached_at = time.time()

    token = jwt.encode(
        {
            "iss": APPLE_ISSUER,
            "aud": "com.sylea.ai",
            "sub": "001234.abcdef.0001",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "email": "user@example.com",
            "email_verified": "true",
            "is_private_email": "false",
        },
        fake_p8_key,
        algorithm="ES256",
        headers={"kid": "TESTKID02"},
    )

    user = await verify_id_token(token, expected_audience="com.sylea.ai")
    assert user.sub == "001234.abcdef.0001"
    assert user.email == "user@example.com"
    assert user.email_verified is True
    assert user.is_private_email is False


@pytest.mark.asyncio
async def test_verify_id_token_private_email(monkeypatch, fake_p8_key):
    """Test : is_private_email=true détecté correctement."""
    from jose import jwt
    from cryptography.hazmat.primitives import serialization
    from api.auth.apple_oauth import verify_id_token, APPLE_ISSUER
    import api.auth.apple_oauth as ao

    key = serialization.load_pem_private_key(fake_p8_key.encode(), password=None)
    public_numbers = key.public_key().public_numbers()
    import base64
    def b64url(n: int) -> str:
        b = n.to_bytes((n.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(b).decode().rstrip("=")
    jwk = {
        "kty": "EC", "crv": "P-256", "kid": "TESTKID03",
        "use": "sig", "alg": "ES256",
        "x": b64url(public_numbers.x), "y": b64url(public_numbers.y),
    }
    ao._jwks_cache = {"keys": [jwk]}
    ao._jwks_cached_at = time.time()

    token = jwt.encode(
        {
            "iss": APPLE_ISSUER,
            "aud": "com.sylea.ai",
            "sub": "002345.private.relay",
            "iat": int(time.time()),
            "exp": int(time.time()) + 600,
            "email": "xxx@privaterelay.appleid.com",
            "is_private_email": "true",
        },
        fake_p8_key,
        algorithm="ES256",
        headers={"kid": "TESTKID03"},
    )

    user = await verify_id_token(token, expected_audience="com.sylea.ai")
    assert user.is_private_email is True
