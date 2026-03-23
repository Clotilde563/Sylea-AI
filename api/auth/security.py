"""JWT token and password hashing utilities."""

import os
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

# ── Config ────────────────────────────────────────────────────────────────────

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "sylea-dev-secret-change-in-production")
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
