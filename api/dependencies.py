"""
Injection de dépendances FastAPI — Syléa.AI.

Stratégie SQLite : connexion async par requête (thread-safe).
SQLite ne peut pas partager une connexion entre threads.
Solution : get_db() est un générateur ASYNC → s'exécute dans le thread
de la boucle d'événements asyncio. Les routes doivent être `async def`
pour rester dans ce même thread et éviter l'erreur SQLite.
"""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, Request

from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
from sylea.core.engine.probability import MoteurProbabilite
from api.auth.security import decode_token


async def get_db() -> AsyncGenerator[DatabaseManager, None]:
    """
    Crée une connexion SQLite dans le thread de la boucle asyncio.

    Générateur async : la connexion est créée et libérée dans le même
    thread (event loop), sans passer par un thread pool.
    Les routes async def partagent ce même thread → pas d'erreur SQLite.
    """
    db = DatabaseManager()
    db.connect()
    try:
        yield db
    finally:
        db.disconnect()


def get_profil_repo(db: DatabaseManager = Depends(get_db)) -> ProfilRepository:
    """Retourne un ProfilRepository lié à la connexion DB de la requête."""
    return ProfilRepository(db)


def get_decision_repo(db: DatabaseManager = Depends(get_db)) -> DecisionRepository:
    """Retourne un DecisionRepository lié à la connexion DB de la requête."""
    return DecisionRepository(db)


def get_moteur() -> MoteurProbabilite:
    """Retourne le moteur de probabilité (stateless, réutilisable)."""
    return MoteurProbabilite()


async def get_optional_user(request: Request) -> str | None:
    """Extract user_id from JWT Bearer token if present, return None otherwise.

    This allows endpoints to work both with and without authentication:
    - With auth: filters data by auth_user_id (multi-user web mode)
    - Without auth: loads first profil (CLI / single-user mode)

    SECURITE : on distingue 3 cas
      - Pas de header Authorization → None (anonyme legitime, ex: CLI mode)
      - Header avec token valide   → user_id decode
      - Header avec token invalide → HTTPException 401 (au lieu de None
        silencieux qui faisait passer pour anonyme un token forge/expire)
    """
    from fastapi import HTTPException
    auth = request.headers.get("Authorization", "")
    if not auth:
        return None
    if not auth.startswith("Bearer "):
        # Header present mais format invalide → 401 explicite
        raise HTTPException(
            status_code=401,
            detail="Authorization header doit etre au format 'Bearer <token>'",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth[7:].strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Token manquant apres 'Bearer '",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_token(token)
    if user_id is None:
        # Token present mais invalide/expire → 401 (ne PAS retourner None)
        raise HTTPException(
            status_code=401,
            detail="Token invalide ou expire",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_id


def get_agent():
    """
    Retourne l'agent Claude (optionnel — None si pas de clé API).

    On importe conditionnellement pour ne pas crasher en mode local.
    """
    try:
        from sylea.agent.claude_agent import AgentSylea
        return AgentSylea()
    except (ImportError, ValueError):
        return None
