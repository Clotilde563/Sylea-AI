"""Tests du coeur d'auth JWT — migration python-jose -> PyJWT (2026-06).

Verifie :
  - round-trip create_access_token / decode_token,
  - payload complet (sub + claims de revocation iat/exp/jti),
  - rejet des tokens invalides / expires / signes avec un mauvais secret,
  - INTEROPERABILITE : un token emis par python-jose (ancienne lib) reste
    decodable par PyJWT -> les sessions existantes ne sont PAS invalidees par
    la migration.
"""

from datetime import datetime, timedelta, timezone

from api.auth import security


def test_create_decode_roundtrip():
    token = security.create_access_token("user-123")
    assert isinstance(token, str)
    assert token.count(".") == 2  # header.payload.signature
    assert security.decode_token(token) == "user-123"


def test_payload_contains_revocation_claims():
    token = security.create_access_token("user-abc")
    payload = security.decode_token_payload(token)
    assert payload is not None
    assert payload["sub"] == "user-abc"
    # Claims poses par create_access_token (revocation P1)
    assert "iat" in payload
    assert "exp" in payload
    assert "jti" in payload


def test_invalid_tokens_return_none():
    assert security.decode_token("not.a.jwt") is None
    assert security.decode_token("") is None
    assert security.decode_token_payload("garbage") is None


def test_expired_token_rejected():
    token = security.create_access_token("u", expires_delta=timedelta(seconds=-10))
    assert security.decode_token(token) is None
    assert security.decode_token_payload(token) is None


def test_token_signed_with_wrong_secret_rejected():
    import jwt as pyjwt
    forged = pyjwt.encode(
        {"sub": "attacker", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "wrong-secret-key-0123456789abcdef0123456789abcdef",
        algorithm="HS256",
    )
    assert security.decode_token(forged) is None


def test_interop_with_legacy_python_jose_tokens():
    """Token emis par python-jose avec le MEME secret/algo -> doit rester
    decodable par PyJWT (pas de deconnexion lors du deploiement de la migration)."""
    from jose import jwt as jose_jwt
    legacy = jose_jwt.encode(
        {
            "sub": "legacy-user",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "iat": datetime.now(timezone.utc),
        },
        security.SECRET_KEY,
        algorithm=security.ALGORITHM,
    )
    assert security.decode_token(legacy) == "legacy-user"
    payload = security.decode_token_payload(legacy)
    assert payload is not None and payload["sub"] == "legacy-user"
