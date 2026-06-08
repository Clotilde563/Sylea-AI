"""
Repositories async (PG-compatible) pour Syléa.AI — Migration 2026-05-15.

Versions async des Repositories CLI sync existants. Utilisent SQLAlchemy text()
async via api.database.get_session_factory(), compat SQLite + PostgreSQL.

Les versions sync (repositories.py) restent pour le CLI standalone (main.py --local).
Les endpoints API en production PG doivent utiliser ces versions async.

API symetrique a repositories.py :
  - ProfilRepositoryAsync.sauvegarder_async(...)
  - ProfilRepositoryAsync.charger_async(...)
  - ProfilRepositoryAsync.existe_async(...)
  - ProfilRepositoryAsync.supprimer_async(...)
  - DecisionRepositoryAsync.sauvegarder_async(...)
  - DecisionRepositoryAsync.lister_pour_utilisateur_async(...)
  - DecisionRepositoryAsync.compter_async(...)
  - DecisionRepositoryAsync.obtenir_par_id_async(...)
  - DecisionRepositoryAsync.supprimer_par_id_async(...)
  - DecisionRepositoryAsync.lister_pagine_async(...)
  - DecisionRepositoryAsync.compter_filtre_async(...)
  - DecisionRepositoryAsync.effacer_decisions_utilisateur_async(...)
"""

from __future__ import annotations

from typing import List, Optional

from sylea.core.models.user import ProfilUtilisateur
from sylea.core.models.decision import Decision


class ProfilRepositoryAsync:
    """Accès aux données du profil utilisateur (async, PG-compatible)."""

    async def sauvegarder_async(
        self, profil: ProfilUtilisateur, auth_user_id: str | None = None,
    ) -> None:
        """Upsert portable (SELECT puis UPDATE/INSERT) — compat SQLite + PG."""
        from sqlalchemy import text
        from api.database import get_session_factory
        data = profil.to_dict()
        if auth_user_id is not None:
            data["auth_user_id"] = auth_user_id

        factory = get_session_factory()
        async with factory() as session:
            try:
                # Verifier si le profil existe deja
                result = await session.execute(
                    text("SELECT id FROM profil_utilisateur WHERE id = :id"),
                    {"id": data["id"]},
                )
                existing = result.first()
                if existing:
                    # UPDATE (tous les champs sauf id)
                    updates = ", ".join(
                        f"{k} = :{k}" for k in data.keys() if k != "id"
                    )
                    await session.execute(
                        text(
                            f"UPDATE profil_utilisateur SET {updates} "
                            "WHERE id = :id"
                        ),
                        data,
                    )
                else:
                    # INSERT
                    cols = ", ".join(data.keys())
                    placeholders = ", ".join(f":{k}" for k in data.keys())
                    await session.execute(
                        text(
                            f"INSERT INTO profil_utilisateur ({cols}) "
                            f"VALUES ({placeholders})"
                        ),
                        data,
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def charger_async(
        self, auth_user_id: str | None = None,
    ) -> Optional[ProfilUtilisateur]:
        """Charge le profil (filtre par auth_user_id si fourni)."""
        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()
        async with factory() as session:
            if auth_user_id is not None:
                result = await session.execute(
                    text(
                        "SELECT * FROM profil_utilisateur "
                        "WHERE auth_user_id = :uid LIMIT 1"
                    ),
                    {"uid": auth_user_id},
                )
            else:
                result = await session.execute(
                    text(
                        "SELECT * FROM profil_utilisateur ORDER BY cree_le LIMIT 1"
                    )
                )
            row = result.mappings().first()
        if row is None:
            return None
        return ProfilUtilisateur.from_dict(dict(row))

    async def existe_async(self, auth_user_id: str | None = None) -> bool:
        """Retourne True si un profil existe."""
        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()
        async with factory() as session:
            if auth_user_id is not None:
                result = await session.execute(
                    text(
                        "SELECT COUNT(*) FROM profil_utilisateur "
                        "WHERE auth_user_id = :uid"
                    ),
                    {"uid": auth_user_id},
                )
            else:
                result = await session.execute(
                    text("SELECT COUNT(*) FROM profil_utilisateur")
                )
            count = int(result.scalar() or 0)
        return count > 0

    async def supprimer_async(
        self, user_id: str, auth_user_id: str | None = None,
    ) -> None:
        """Supprime le profil et toutes ses decisions associees (transaction)."""
        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()
        async with factory() as session:
            try:
                await session.execute(
                    text("DELETE FROM decisions WHERE user_id = :uid"),
                    {"uid": user_id},
                )
                if auth_user_id is not None:
                    await session.execute(
                        text(
                            "DELETE FROM profil_utilisateur "
                            "WHERE id = :id AND auth_user_id = :auid"
                        ),
                        {"id": user_id, "auid": auth_user_id},
                    )
                else:
                    await session.execute(
                        text("DELETE FROM profil_utilisateur WHERE id = :id"),
                        {"id": user_id},
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise


class DecisionRepositoryAsync:
    """Accès aux données des decisions (async, PG-compatible)."""

    async def sauvegarder_async(self, decision: Decision) -> None:
        """Upsert portable (SELECT puis UPDATE/INSERT)."""
        from sqlalchemy import text
        from api.database import get_session_factory
        data = decision.to_dict()
        factory = get_session_factory()
        async with factory() as session:
            try:
                result = await session.execute(
                    text("SELECT id FROM decisions WHERE id = :id"),
                    {"id": data["id"]},
                )
                existing = result.first()
                if existing:
                    updates = ", ".join(
                        f"{k} = :{k}" for k in data.keys() if k != "id"
                    )
                    await session.execute(
                        text(f"UPDATE decisions SET {updates} WHERE id = :id"),
                        data,
                    )
                else:
                    cols = ", ".join(data.keys())
                    placeholders = ", ".join(f":{k}" for k in data.keys())
                    await session.execute(
                        text(
                            f"INSERT INTO decisions ({cols}) "
                            f"VALUES ({placeholders})"
                        ),
                        data,
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def lister_pour_utilisateur_async(
        self, user_id: str, limite: int = 20,
        auth_user_id: str | None = None,
    ) -> List[Decision]:
        """Retourne les dernieres decisions d'un utilisateur."""
        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()
        async with factory() as session:
            if auth_user_id is not None:
                result = await session.execute(
                    text(
                        "SELECT d.* FROM decisions d "
                        "JOIN profil_utilisateur p ON d.user_id = p.id "
                        "WHERE d.user_id = :uid AND p.auth_user_id = :auid "
                        "ORDER BY d.cree_le DESC LIMIT :lim"
                    ),
                    {"uid": user_id, "auid": auth_user_id, "lim": limite},
                )
            else:
                result = await session.execute(
                    text(
                        "SELECT * FROM decisions WHERE user_id = :uid "
                        "ORDER BY cree_le DESC LIMIT :lim"
                    ),
                    {"uid": user_id, "lim": limite},
                )
            rows = result.mappings().all()
        return [Decision.from_dict(dict(r)) for r in rows]

    async def compter_async(self, user_id: str) -> int:
        """Retourne le nombre total de decisions."""
        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT COUNT(*) FROM decisions WHERE user_id = :uid"
                ),
                {"uid": user_id},
            )
            return int(result.scalar() or 0)

    async def obtenir_par_id_async(
        self, decision_id: str, user_id: str,
    ) -> Optional[Decision]:
        """Charge une decision par son ID (verifie le user_id)."""
        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT * FROM decisions "
                    "WHERE id = :did AND user_id = :uid"
                ),
                {"did": decision_id, "uid": user_id},
            )
            row = result.mappings().first()
        if row is None:
            return None
        return Decision.from_dict(dict(row))

    async def supprimer_par_id_async(
        self, decision_id: str, user_id: str,
    ) -> bool:
        """Supprime une decision par son ID (verifie le user_id)."""
        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()
        async with factory() as session:
            try:
                result = await session.execute(
                    text(
                        "DELETE FROM decisions "
                        "WHERE id = :did AND user_id = :uid"
                    ),
                    {"did": decision_id, "uid": user_id},
                )
                await session.commit()
                return (result.rowcount or 0) > 0
            except Exception:
                await session.rollback()
                raise

    async def lister_pagine_async(
        self, user_id: str, page: int = 1, par_page: int = 10,
        tri: str = "recent", recherche: str | None = None,
    ) -> List[Decision]:
        """Liste paginee avec tri et recherche optionnelle."""
        from sqlalchemy import text
        from api.database import get_session_factory
        # Whitelist du tri pour eviter l'injection SQL
        order_map = {
            "recent": "cree_le DESC",
            "ancien": "cree_le ASC",
            "impact": (
                "ABS(COALESCE(probabilite_apres, probabilite_avant) "
                "- probabilite_avant) DESC"
            ),
        }
        order = order_map.get(tri, "cree_le DESC")
        offset = (max(1, page) - 1) * par_page

        conditions = ["user_id = :uid"]
        params = {"uid": user_id, "lim": par_page, "off": offset}
        if recherche:
            conditions.append("question LIKE :search")
            params["search"] = f"%{recherche}%"
        where = " AND ".join(conditions)

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                text(
                    f"SELECT * FROM decisions WHERE {where} "
                    f"ORDER BY {order} LIMIT :lim OFFSET :off"
                ),
                params,
            )
            rows = result.mappings().all()
        return [Decision.from_dict(dict(r)) for r in rows]

    async def compter_filtre_async(
        self, user_id: str, recherche: str | None = None,
    ) -> int:
        """Compte les decisions avec filtre optionnel."""
        from sqlalchemy import text
        from api.database import get_session_factory
        conditions = ["user_id = :uid"]
        params = {"uid": user_id}
        if recherche:
            conditions.append("question LIKE :search")
            params["search"] = f"%{recherche}%"
        where = " AND ".join(conditions)

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                text(f"SELECT COUNT(*) FROM decisions WHERE {where}"),
                params,
            )
            return int(result.scalar() or 0)

    async def effacer_decisions_utilisateur_async(
        self, user_id: str, auth_user_id: str | None = None,
    ) -> None:
        """Supprime toutes les decisions d'un utilisateur."""
        from sqlalchemy import text
        from api.database import get_session_factory
        factory = get_session_factory()
        async with factory() as session:
            try:
                if auth_user_id is not None:
                    await session.execute(
                        text(
                            "DELETE FROM decisions WHERE user_id IN "
                            "(SELECT d.user_id FROM decisions d "
                            "JOIN profil_utilisateur p ON d.user_id = p.id "
                            "WHERE d.user_id = :uid AND p.auth_user_id = :auid)"
                        ),
                        {"uid": user_id, "auid": auth_user_id},
                    )
                else:
                    await session.execute(
                        text(
                            "DELETE FROM decisions WHERE user_id = :uid"
                        ),
                        {"uid": user_id},
                    )
                await session.commit()
            except Exception:
                await session.rollback()
                raise


__all__ = ["ProfilRepositoryAsync", "DecisionRepositoryAsync"]
