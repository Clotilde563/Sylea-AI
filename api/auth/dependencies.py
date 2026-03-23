"""Auth dependency for FastAPI routes."""

import sqlite3

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from api.auth.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_current_user(token: str | None = Depends(oauth2_scheme)) -> dict | None:
    """
    Extract and validate the current user from the JWT token.

    Returns None if no token is provided (allows unauthenticated access
    for backward compatibility during migration).
    """
    if token is None:
        return None

    user_id = decode_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expire",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"id": user_id}


async def require_auth(user: dict | None = Depends(get_current_user)) -> dict:
    """Strict auth dependency — raises 401 if no valid token."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
