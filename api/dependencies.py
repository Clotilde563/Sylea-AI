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

from fastapi import Depends

from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
from sylea.core.engine.probability import MoteurProbabilite


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
