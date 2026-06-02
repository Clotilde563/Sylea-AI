"""
Injection de dépendances FastAPI — Syléa.AI.

Stratégie SQLite : connexion async par requête (thread-safe).
SQLite ne peut pas partager une connexion entre threads.
Solution : get_db() est un générateur ASYNC → s'exécute dans le thread
de la boucle d'événements asyncio. Les routes doivent être `async def`
pour rester dans ce même thread et éviter l'erreur SQLite.
"""

from __future__ import annotations

import time
from typing import AsyncGenerator

from fastapi import Depends, Request

from sylea.core.storage.database import DatabaseManager
from sylea.core.storage.repositories import ProfilRepository, DecisionRepository
from sylea.core.engine.probability import MoteurProbabilite
from api.auth.security import decode_token, decode_token_payload


# ── Cache etat securite du compte (anti-DB-hammer) ───────────────────────────
# get_optional_user tourne sur quasiment chaque requete authentifiee. Pour
# eviter un SELECT users a chaque appel, on cache (disabled, invalidated_before)
# pendant _SEC_CACHE_TTL secondes. Compromis : un compte fraichement banni /
# deconnecte garde l'acces au plus 30s (vs 7 jours auparavant — le JWT n'avait
# aucune revocation).
_sec_cache: dict[str, tuple[bool, "float | None", float]] = {}  # uid -> (disabled, invalidated_before_epoch, cached_at)
_SEC_CACHE_TTL = 30.0  # secondes


async def _get_user_security_state(user_id: str) -> tuple[bool, "float | None"]:
    """Retourne (disabled, tokens_invalidated_before_epoch) pour cet user.

    - disabled : True si users.disabled_at non-NULL.
    - tokens_invalidated_before_epoch : timestamp epoch (float) avant lequel
      tout token est revoque, ou None si jamais de logout.

    Cache TTL 30s. NULL-safe : colonnes manquantes (DB pre-migration) ou DB
    indispo -> (False, None) (fail-open sur infra, on ne bloque pas l'auth
    pour un probleme de schema/DB).
    """
    now = time.time()
    cached = _sec_cache.get(user_id)
    if cached is not None and (now - cached[2]) < _SEC_CACHE_TTL:
        return cached[0], cached[1]

    disabled = False
    invalidated_before: float | None = None
    try:
        from sqlalchemy import text as _sa_text
        from api.database import get_session_factory
        from datetime import datetime, timezone
        factory = get_session_factory()
        async with factory() as session:
            # On tente disabled_at + tokens_invalidated_before. Si la 2e colonne
            # n'existe pas (DB pre-migration), on retombe sur disabled_at seul.
            try:
                res = await session.execute(
                    _sa_text(
                        "SELECT disabled_at, tokens_invalidated_before "
                        "FROM users WHERE id = :uid LIMIT 1"
                    ),
                    {"uid": user_id},
                )
                row = res.first()
            except Exception:
                res = await session.execute(
                    _sa_text("SELECT disabled_at FROM users WHERE id = :uid LIMIT 1"),
                    {"uid": user_id},
                )
                r2 = res.first()
                row = (r2[0], None) if r2 is not None else None

            if row is not None:
                if row[0]:
                    disabled = True
                tib = row[1] if len(row) > 1 else None
                if tib:
                    try:
                        dt = datetime.fromisoformat(str(tib).replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        invalidated_before = dt.timestamp()
                    except Exception:
                        invalidated_before = None
    except Exception:
        disabled = False
        invalidated_before = None

    _sec_cache[user_id] = (disabled, invalidated_before, now)
    # Anti-OOM : purge les entrees expirees si le cache grossit trop
    # (1 entree/user a vie sinon). Borne large, eviction rare.
    if len(_sec_cache) > 50_000:
        _expired = [k for k, v in _sec_cache.items() if (now - v[2]) >= _SEC_CACHE_TTL]
        for k in _expired:
            _sec_cache.pop(k, None)
    return disabled, invalidated_before


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
    payload = decode_token_payload(token)
    if payload is None or not payload.get("sub"):
        # Token present mais invalide/expire → 401 (ne PAS retourner None)
        raise HTTPException(
            status_code=401,
            detail="Token invalide ou expire",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = payload["sub"]

    # SECURITE (P0/P1 2026-06) : 1 SELECT (cache 30s) pour 2 checks :
    #   - compte desactive (disabled_at) → 403
    #   - token revoque (iat < tokens_invalidated_before, pose par /logout) → 401
    disabled, invalidated_before = await _get_user_security_state(user_id)
    if disabled:
        raise HTTPException(
            status_code=403,
            detail="Compte desactive. Contactez le support.",
        )
    if invalidated_before is not None:
        iat = payload.get("iat")
        # iat absent (vieux token pre-migration) → on considere revoque si un
        # logout a eu lieu (fail-closed cote securite, l'user se reconnecte).
        if iat is None or float(iat) < invalidated_before:
            raise HTTPException(
                status_code=401,
                detail="Session expiree. Reconnecte-toi.",
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
