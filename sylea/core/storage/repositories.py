"""
Repositories SQLite + PostgreSQL pour Syléa.AI.

Fournit les opérations CRUD pour :
- ProfilRepository  → ProfilUtilisateur
- DecisionRepository → Decision

Migration 2026-05-15 : detection automatique du backend via DATABASE_URL.
- SQLite (defaut) : execute directement sur sqlite3.Connection (perf)
- PostgreSQL : delegue a ProfilRepositoryAsync / DecisionRepositoryAsync
  via asyncio.run() (compat avec callers sync existants)
"""

import os
import sqlite3
from typing import List, Optional

from sylea.core.models.user import ProfilUtilisateur
from sylea.core.models.decision import Decision
from sylea.core.storage.database import DatabaseManager


def _is_pg() -> bool:
    """Detecte si l'app tourne en mode PostgreSQL via DATABASE_URL."""
    url = os.environ.get("DATABASE_URL", "")
    return url.startswith(("postgresql://", "postgresql+", "postgres://"))


def _run_async(coro):
    """Execute une coroutine depuis un contexte sync.

    Gere le cas ou on est deja dans un event loop (FastAPI request) via
    ThreadPoolExecutor pour eviter 'asyncio.run() cannot be called from
    a running event loop'.
    """
    import asyncio
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # Already in event loop : coroutine NE PAS recreer ici
        # Le ThreadPoolExecutor recoit la coroutine deja creee.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()


class ProfilRepository:
    """Accès aux données du profil utilisateur."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def sauvegarder(self, profil: ProfilUtilisateur, auth_user_id: str | None = None) -> None:
        """Insère ou met à jour le profil en base (PG-aware)."""
        if _is_pg():
            from sylea.core.storage.repositories_async import ProfilRepositoryAsync
            return _run_async(
                ProfilRepositoryAsync().sauvegarder_async(profil, auth_user_id=auth_user_id)
            )
        # Mode SQLite : path natif (perf, comportement actuel)
        data = profil.to_dict()
        if auth_user_id is not None:
            data["auth_user_id"] = auth_user_id
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        updates = ", ".join(
            f"{k} = :{k}" for k in data.keys() if k != "id"
        )
        sql = (
            f"INSERT INTO profil_utilisateur ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}"
        )
        with self._db.conn:
            self._db.conn.execute(sql, data)

    def charger(self, auth_user_id: str | None = None) -> Optional[ProfilUtilisateur]:
        """Charge le profil. Si auth_user_id fourni, filtre par auth_user_id (multi-user).
        Sinon, charge le premier profil (CLI / mode sans auth)."""
        if _is_pg():
            from sylea.core.storage.repositories_async import ProfilRepositoryAsync
            return _run_async(ProfilRepositoryAsync().charger_async(auth_user_id=auth_user_id))
        # Mode SQLite
        if auth_user_id is not None:
            row = self._db.conn.execute(
                "SELECT * FROM profil_utilisateur WHERE auth_user_id = ? LIMIT 1",
                (auth_user_id,),
            ).fetchone()
        else:
            row = self._db.conn.execute(
                "SELECT * FROM profil_utilisateur ORDER BY cree_le LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return ProfilUtilisateur.from_dict(dict(row))

    def existe(self, auth_user_id: str | None = None) -> bool:
        """Retourne True si un profil existe. Filtre par auth_user_id si fourni."""
        if _is_pg():
            from sylea.core.storage.repositories_async import ProfilRepositoryAsync
            return _run_async(ProfilRepositoryAsync().existe_async(auth_user_id=auth_user_id))
        # Mode SQLite
        if auth_user_id is not None:
            count = self._db.conn.execute(
                "SELECT COUNT(*) FROM profil_utilisateur WHERE auth_user_id = ?",
                (auth_user_id,),
            ).fetchone()[0]
        else:
            count = self._db.conn.execute(
                "SELECT COUNT(*) FROM profil_utilisateur"
            ).fetchone()[0]
        return count > 0

    def supprimer(self, user_id: str, auth_user_id: str | None = None) -> None:
        """Supprime le profil et toutes ses décisions associées."""
        if _is_pg():
            from sylea.core.storage.repositories_async import ProfilRepositoryAsync
            return _run_async(
                ProfilRepositoryAsync().supprimer_async(user_id, auth_user_id=auth_user_id)
            )
        # Mode SQLite
        with self._db.conn:
            self._db.conn.execute(
                "DELETE FROM decisions WHERE user_id = ?", (user_id,)
            )
            if auth_user_id is not None:
                self._db.conn.execute(
                    "DELETE FROM profil_utilisateur WHERE id = ? AND auth_user_id = ?",
                    (user_id, auth_user_id),
                )
            else:
                self._db.conn.execute(
                    "DELETE FROM profil_utilisateur WHERE id = ?", (user_id,)
                )


class DecisionRepository:
    """Accès aux données des décisions."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def sauvegarder(self, decision: Decision) -> None:
        """Insère ou met à jour une décision."""
        if _is_pg():
            from sylea.core.storage.repositories_async import DecisionRepositoryAsync
            return _run_async(DecisionRepositoryAsync().sauvegarder_async(decision))
        # Mode SQLite
        data = decision.to_dict()
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        updates = ", ".join(
            f"{k} = :{k}" for k in data.keys() if k != "id"
        )
        sql = (
            f"INSERT INTO decisions ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}"
        )
        with self._db.conn:
            self._db.conn.execute(sql, data)

    def lister_pour_utilisateur(
        self, user_id: str, limite: int = 20, auth_user_id: str | None = None,
    ) -> List[Decision]:
        """Retourne les dernières décisions d'un utilisateur, du plus récent au plus ancien."""
        if _is_pg():
            from sylea.core.storage.repositories_async import DecisionRepositoryAsync
            return _run_async(
                DecisionRepositoryAsync().lister_pour_utilisateur_async(
                    user_id, limite=limite, auth_user_id=auth_user_id,
                )
            )
        # Mode SQLite
        if auth_user_id is not None:
            rows = self._db.conn.execute(
                "SELECT d.* FROM decisions d "
                "JOIN profil_utilisateur p ON d.user_id = p.id "
                "WHERE d.user_id = ? AND p.auth_user_id = ? "
                "ORDER BY d.cree_le DESC LIMIT ?",
                (user_id, auth_user_id, limite),
            ).fetchall()
        else:
            rows = self._db.conn.execute(
                "SELECT * FROM decisions WHERE user_id = ? ORDER BY cree_le DESC LIMIT ?",
                (user_id, limite),
            ).fetchall()
        return [Decision.from_dict(dict(r)) for r in rows]

    def compter(self, user_id: str) -> int:
        """Retourne le nombre total de décisions enregistrées."""
        if _is_pg():
            from sylea.core.storage.repositories_async import DecisionRepositoryAsync
            return _run_async(DecisionRepositoryAsync().compter_async(user_id))
        # Mode SQLite
        return self._db.conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE user_id = ?", (user_id,)
        ).fetchone()[0]

    def obtenir_par_id(self, decision_id: str, user_id: str):
        """Charge une décision par son ID (vérifie le user_id)."""
        if _is_pg():
            from sylea.core.storage.repositories_async import DecisionRepositoryAsync
            return _run_async(
                DecisionRepositoryAsync().obtenir_par_id_async(decision_id, user_id)
            )
        # Mode SQLite
        row = self._db.conn.execute(
            "SELECT * FROM decisions WHERE id = ? AND user_id = ?",
            (decision_id, user_id),
        ).fetchone()
        if row is None:
            return None
        return Decision.from_dict(dict(row))

    def supprimer_par_id(self, decision_id: str, user_id: str) -> bool:
        """Supprime une décision par son ID (vérifie le user_id)."""
        if _is_pg():
            from sylea.core.storage.repositories_async import DecisionRepositoryAsync
            return _run_async(
                DecisionRepositoryAsync().supprimer_par_id_async(decision_id, user_id)
            )
        # Mode SQLite
        with self._db.conn:
            cursor = self._db.conn.execute(
                "DELETE FROM decisions WHERE id = ? AND user_id = ?",
                (decision_id, user_id),
            )
            return cursor.rowcount > 0

    def lister_pagine(
        self, user_id: str, page: int = 1, par_page: int = 10,
        tri: str = "recent", recherche: str | None = None,
    ) -> List[Decision]:
        """Liste paginee avec tri et recherche optionnelle."""
        if _is_pg():
            from sylea.core.storage.repositories_async import DecisionRepositoryAsync
            return _run_async(
                DecisionRepositoryAsync().lister_pagine_async(
                    user_id, page=page, par_page=par_page,
                    tri=tri, recherche=recherche,
                )
            )
        # Mode SQLite
        conditions = ["user_id = ?"]
        params: list = [user_id]
        if recherche:
            conditions.append("question LIKE ?")
            params.append(f"%{recherche}%")
        where = " AND ".join(conditions)

        order = {
            "recent": "cree_le DESC",
            "ancien": "cree_le ASC",
            "impact": "ABS(COALESCE(probabilite_apres, probabilite_avant) - probabilite_avant) DESC",
        }.get(tri, "cree_le DESC")

        offset = (max(1, page) - 1) * par_page
        params.extend([par_page, offset])
        rows = self._db.conn.execute(
            f"SELECT * FROM decisions WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [Decision.from_dict(dict(r)) for r in rows]

    def compter_filtre(self, user_id: str, recherche: str | None = None) -> int:
        """Compte les decisions avec filtre optionnel."""
        if _is_pg():
            from sylea.core.storage.repositories_async import DecisionRepositoryAsync
            return _run_async(
                DecisionRepositoryAsync().compter_filtre_async(user_id, recherche=recherche)
            )
        # Mode SQLite
        conditions = ["user_id = ?"]
        params: list = [user_id]
        if recherche:
            conditions.append("question LIKE ?")
            params.append(f"%{recherche}%")
        where = " AND ".join(conditions)
        return self._db.conn.execute(
            f"SELECT COUNT(*) FROM decisions WHERE {where}", params
        ).fetchone()[0]

    def effacer_decisions_utilisateur(self, user_id: str, auth_user_id: str | None = None) -> None:
        """Supprime toutes les décisions d’un utilisateur."""
        if _is_pg():
            from sylea.core.storage.repositories_async import DecisionRepositoryAsync
            return _run_async(
                DecisionRepositoryAsync().effacer_decisions_utilisateur_async(
                    user_id, auth_user_id=auth_user_id,
                )
            )
        # Mode SQLite
        with self._db.conn:
            if auth_user_id is not None:
                self._db.conn.execute(
                    "DELETE FROM decisions WHERE user_id IN "
                    "(SELECT d.user_id FROM decisions d "
                    "JOIN profil_utilisateur p ON d.user_id = p.id "
                    "WHERE d.user_id = ? AND p.auth_user_id = ?)",
                    (user_id, auth_user_id),
                )
            else:
                self._db.conn.execute("DELETE FROM decisions WHERE user_id = ?", (user_id,))
