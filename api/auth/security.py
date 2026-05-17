"""JWT token and password hashing utilities."""

import os
import secrets
import sys
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

# ── Config ────────────────────────────────────────────────────────────────────

def _get_jwt_secret() -> str:
    """Retourne le secret JWT.

    - PROD (DATABASE_URL=postgresql://...) : SECRET REQUIS via JWT_SECRET_KEY.
      Crash au demarrage si absent (evite les tokens predictibles).
    - DEV (SQLite local) : autogenere un secret aleatoire au demarrage si
      JWT_SECRET_KEY absent (sera regenere a chaque restart, OK en dev).
    """
    secret = os.environ.get("JWT_SECRET_KEY", "").strip()
    if secret:
        return secret

    # Pas de secret defini : check si on est en prod
    is_prod_pg = os.environ.get("DATABASE_URL", "").startswith(
        ("postgresql://", "postgresql+", "postgres://"),
    )
    if is_prod_pg:
        # CRITIQUE en prod : refuser de demarrer
        print(
            "[FATAL] JWT_SECRET_KEY non defini en mode PostgreSQL prod. "
            "Generer avec : python -c \"import secrets; "
            "print(secrets.token_urlsafe(64))\"",
            file=sys.stderr,
        )
        sys.exit(1)

    # Dev SQLite : auto-genere un secret aleatoire
    return secrets.token_urlsafe(48)


SECRET_KEY = _get_jwt_secret()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 jours


# ── Password ──────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a plain-text password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against its hash."""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(user_id: str, expires_delta: timedelta | None = None) -> str:
    """Create a JWT access token for the given user_id."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> str | None:
    """Decode a JWT token and return the user_id, or None if invalid."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        return None
