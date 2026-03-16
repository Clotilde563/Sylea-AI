"""
Repositories SQLite pour Syléa.AI.

Fournit les opérations CRUD pour :
- ProfilRepository  → ProfilUtilisateur
- DecisionRepository → Decision
"""

import sqlite3
from typing import List, Optional

from sylea.core.models.user import ProfilUtilisateur
from sylea.core.models.decision import Decision
from sylea.core.storage.database import DatabaseManager


class ProfilRepository:
    """Accès aux données du profil utilisateur."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def sauvegarder(self, profil: ProfilUtilisateur) -> None:
        """Insère ou met à jour le profil en base."""
        data = profil.to_dict()
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

    def charger(self) -> Optional[ProfilUtilisateur]:
        """Charge le premier profil trouvé (Syléa ne gère qu'un seul profil local)."""
        row = self._db.conn.execute(
            "SELECT * FROM profil_utilisateur ORDER BY cree_le LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return ProfilUtilisateur.from_dict(dict(row))

    def existe(self) -> bool:
        """Retourne True si au moins un profil existe en base."""
        count = self._db.conn.execute(
            "SELECT COUNT(*) FROM profil_utilisateur"
        ).fetchone()[0]
        return count > 0

    def supprimer(self, user_id: str) -> None:
        """Supprime le profil et toutes ses décisions associées."""
        with self._db.conn:
            self._db.conn.execute(
                "DELETE FROM decisions WHERE user_id = ?", (user_id,)
            )
            self._db.conn.execute(
                "DELETE FROM profil_utilisateur WHERE id = ?", (user_id,)
            )


class DecisionRepository:
    """Accès aux données des décisions."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def sauvegarder(self, decision: Decision) -> None:
        """Insère ou met à jour une décision."""
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
        self, user_id: str, limite: int = 20
    ) -> List[Decision]:
        """Retourne les dernières décisions d'un utilisateur, du plus récent au plus ancien."""
        rows = self._db.conn.execute(
            "SELECT * FROM decisions WHERE user_id = ? ORDER BY cree_le DESC LIMIT ?",
            (user_id, limite),
        ).fetchall()
        return [Decision.from_dict(dict(r)) for r in rows]

    def compter(self, user_id: str) -> int:
        """Retourne le nombre total de décisions enregistrées."""
        return self._db.conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE user_id = ?", (user_id,)
        ).fetchone()[0]

    def supprimer_par_id(self, decision_id: str, user_id: str) -> bool:
        """Supprime une décision par son ID (vérifie le user_id)."""
        with self._db.conn:
            cursor = self._db.conn.execute(
                "DELETE FROM decisions WHERE id = ? AND user_id = ?",
                (decision_id, user_id),
            )
            return cursor.rowcount > 0

    def effacer_decisions_utilisateur(self, user_id: str) -> None:
        """Supprime toutes les décisions d’un utilisateur."""
        with self._db.conn:
            self._db.conn.execute("DELETE FROM decisions WHERE user_id = ?", (user_id,))
