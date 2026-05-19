"""JWT token and password hashing utilities."""

import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
from jose import JWTError, jwt

# ── Config ────────────────────────────────────────────────────────────────────

# Fichier ou on persiste le secret JWT en dev (evite la deconnexion auto
# a chaque restart uvicorn --reload). Ignore par .gitignore (data/).
_DEV_JWT_SECRET_FILE = Path("data") / ".jwt_secret_dev"


def _get_jwt_secret() -> str:
    """Retourne le secret JWT.

    - PROD (DATABASE_URL=postgresql://...) : SECRET REQUIS via JWT_SECRET_KEY.
      Crash au demarrage si absent (evite les tokens predictibles).
    - DEV (SQLite local) : utilise JWT_SECRET_KEY s'il est defini, sinon lit
      le secret persiste dans data/.jwt_secret_dev. Si le fichier n'existe pas
      encore, genere un secret aleatoire ET le persiste pour les restarts
      suivants. Comme ca uvicorn --reload ne deconnecte plus l'user a chaque
      modif de fichier .py.
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

    # Dev SQLite : lit le secret persiste ou en genere un nouveau (ET le sauve).
    # Comme ca uvicorn --reload ne genere pas un nouveau secret a chaque restart,
    # donc les tokens JWT emis restent valides (=> plus de deconnexion auto).
    try:
        if _DEV_JWT_SECRET_FILE.exists():
            content = _DEV_JWT_SECRET_FILE.read_text(encoding="utf-8").strip()
            if content and len(content) >= 32:
                return content
    except Exception:
        # Lecture impossible (permissions, IO error) -> on regenere en memoire
        pass

    # Genere et persiste
    new_secret = secrets.token_urlsafe(48)
    try:
        _DEV_JWT_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
        _DEV_JWT_SECRET_FILE.write_text(new_secret, encoding="utf-8")
        # Permissions restreintes (POSIX seulement, Windows ignore)
        try:
            os.chmod(_DEV_JWT_SECRET_FILE, 0o600)
        except Exception:
            pass
        print(
            f"[auth] JWT secret dev persiste dans {_DEV_JWT_SECRET_FILE} "
            "(ajoute JWT_SECRET_KEY dans .env pour override).",
        )
    except Exception as e:
        # Persistence impossible : on continue en RAM (secret regenere a chaque
        # restart, comme avant). Affiche un warning car ca cause des deconnexions.
        print(
            f"[auth] WARN : impossible de persister le secret JWT dev "
            f"({e}). Le secret sera regenere a chaque restart, "
            "ce qui deconnecte les utilisateurs. Ajoute JWT_SECRET_KEY dans .env.",
        )
    return new_secret


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
