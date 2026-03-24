"""
Gestionnaire de base de données SQLite pour Syléa.AI.

Gère la connexion, la création du schéma et les opérations transactionnelles.
"""

import sqlite3
from pathlib import Path
from typing import Optional

from sylea.config.settings import get_database_path


_CREATE_PROFIL = """
CREATE TABLE IF NOT EXISTS profil_utilisateur (
    id                      TEXT PRIMARY KEY,
    nom                     TEXT NOT NULL,
    age                     INTEGER NOT NULL,
    profession              TEXT NOT NULL,
    ville                   TEXT NOT NULL,
    situation_familiale     TEXT NOT NULL,
    revenu_annuel           REAL NOT NULL,
    patrimoine_estime       REAL NOT NULL,
    charges_mensuelles      REAL NOT NULL,
    objectif_financier      REAL,
    heures_travail          REAL DEFAULT 8.0,
    heures_sommeil          REAL DEFAULT 7.0,
    heures_loisirs          REAL DEFAULT 2.0,
    heures_transport        REAL DEFAULT 1.0,
    heures_objectif         REAL DEFAULT 1.0,
    niveau_sante            INTEGER DEFAULT 7,
    niveau_stress           INTEGER DEFAULT 5,
    niveau_energie          INTEGER DEFAULT 7,
    niveau_bonheur          INTEGER DEFAULT 7,
    competences             TEXT DEFAULT '',
    diplomes                TEXT DEFAULT '',
    langues                 TEXT DEFAULT '',
    objectif_description    TEXT,
    objectif_categorie      TEXT,
    objectif_deadline       TEXT,
    objectif_probabilite_base REAL DEFAULT 0.0,
    probabilite_actuelle    REAL DEFAULT 0.0,
    cree_le                 TEXT NOT NULL,
    mis_a_jour_le           TEXT NOT NULL
);
"""

_CREATE_DECISIONS = """
CREATE TABLE IF NOT EXISTS decisions (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    question            TEXT NOT NULL,
    options_json        TEXT NOT NULL,
    probabilite_avant   REAL NOT NULL,
    option_choisie_id   TEXT,
    probabilite_apres   REAL,
    action_agent_json   TEXT,
    cree_le             TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES profil_utilisateur(id)
);
"""

_CREATE_BILANS = """
CREATE TABLE IF NOT EXISTS bilans_quotidiens (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    date                TEXT NOT NULL,
    niveau_sante        INTEGER DEFAULT 7,
    niveau_stress       INTEGER DEFAULT 5,
    niveau_energie      INTEGER DEFAULT 7,
    niveau_bonheur      INTEGER DEFAULT 7,
    heures_travail      REAL DEFAULT 8.0,
    heures_sommeil      REAL DEFAULT 7.0,
    heures_loisirs      REAL DEFAULT 2.0,
    heures_transport    REAL DEFAULT 1.0,
    heures_objectif     REAL DEFAULT 1.0,
    description         TEXT DEFAULT '',
    cree_le             TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES profil_utilisateur(id),
    UNIQUE(user_id, date)
);
"""

_CREATE_SOUS_OBJECTIFS = """
CREATE TABLE IF NOT EXISTS sous_objectifs (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    titre               TEXT NOT NULL,
    description         TEXT DEFAULT '',
    progression         REAL DEFAULT 0.0,
    ordre               INTEGER DEFAULT 0,
    cree_le             TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES profil_utilisateur(id)
);
"""

_CREATE_TACHES = """
CREATE TABLE IF NOT EXISTS taches_quotidiennes (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    date                TEXT NOT NULL,
    taches_json         TEXT NOT NULL,
    deadline            TEXT NOT NULL,
    statut              TEXT DEFAULT 'en_cours',
    cree_le             TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES profil_utilisateur(id),
    UNIQUE(user_id, date)
);
"""

_CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id                  TEXT PRIMARY KEY,
    email               TEXT UNIQUE NOT NULL,
    hashed_password     TEXT,
    provider            TEXT DEFAULT 'local',
    provider_id         TEXT,
    created_at          TEXT NOT NULL
);
"""

_CREATE_AGENT_MESSAGES = """
CREATE TABLE IF NOT EXISTS agent_messages (
    id TEXT PRIMARY KEY,
    auth_user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    type TEXT DEFAULT 'text',
    created_at TEXT NOT NULL,
    FOREIGN KEY (auth_user_id) REFERENCES users(id)
);
"""

_CREATE_AGENT_COLLECTED_INFO = """
CREATE TABLE IF NOT EXISTS agent_collected_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    field TEXT NOT NULL,
    value TEXT NOT NULL,
    collected_at TEXT NOT NULL
);
"""


class DatabaseManager:
    """Gestionnaire de connexion et de schéma SQLite."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = db_path or get_database_path()
        self._conn: Optional[sqlite3.Connection] = None

    # ── Connexion ────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Ouvre la connexion et crée le schéma si nécessaire."""
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._initialiser_schema()

    def disconnect(self) -> None:
        """Ferme la connexion proprement."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "DatabaseManager":
        self.connect()
        return self

    def __exit__(self, *_) -> None:
        self.disconnect()

    # ── Propriété ────────────────────────────────────────────────────────────

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Base de données non connectée. Appelez connect() d'abord.")
        return self._conn

    # ── Schéma ───────────────────────────────────────────────────────────────

    def _initialiser_schema(self) -> None:
        """Crée les tables si elles n'existent pas encore."""
        with self._conn:
            self._conn.execute(_CREATE_PROFIL)
            self._conn.execute(_CREATE_DECISIONS)
            self._conn.execute(_CREATE_BILANS)
            self._conn.execute(_CREATE_SOUS_OBJECTIFS)
            self._conn.execute(_CREATE_TACHES)
            self._conn.execute(_CREATE_USERS)
            self._conn.execute(_CREATE_AGENT_MESSAGES)
            self._conn.execute(_CREATE_AGENT_COLLECTED_INFO)
            # Migration : ajouter auth_user_id dans profil
            try:
                self._conn.execute(
                    "ALTER TABLE profil_utilisateur ADD COLUMN auth_user_id TEXT DEFAULT NULL"
                )
            except Exception:
                pass  # Colonne deja existante
            # Migration : ajouter genre si absent
            try:
                self._conn.execute(
                    "ALTER TABLE profil_utilisateur ADD COLUMN genre TEXT DEFAULT ''"
                )
            except Exception:
                pass  # Colonne deja existante
            # Migration : ajouter heures_objectif si la colonne est absente
            try:
                self._conn.execute(
                    "ALTER TABLE profil_utilisateur ADD COLUMN heures_objectif REAL DEFAULT 1.0"
                )
            except Exception:
                pass  # Colonne deja existante
            # Migration : ajouter objectif_modifie_le si absent
            try:
                self._conn.execute(
                    'ALTER TABLE profil_utilisateur ADD COLUMN objectif_modifie_le TEXT'
                )
            except Exception:
                pass  # Colonne deja existante
            # Migration : ajouter phrase_personnalite si absent
            try:
                self._conn.execute(
                    "ALTER TABLE profil_utilisateur ADD COLUMN phrase_personnalite TEXT DEFAULT NULL"
                )
            except Exception:
                pass  # Colonne deja existante
            # Migration : ajouter temps_estime dans sous_objectifs si absent
            try:
                self._conn.execute(
                    "ALTER TABLE sous_objectifs ADD COLUMN temps_estime REAL DEFAULT 0"
                )
            except Exception:
                pass  # Colonne deja existante
            # Migration : ajouter impact_temporel_jours dans decisions
            try:
                self._conn.execute(
                    "ALTER TABLE decisions ADD COLUMN impact_temporel_jours INTEGER DEFAULT NULL"
                )
            except Exception:
                pass  # Colonne deja existante
            # Migration : ajouter sous_objectif_id dans decisions
            try:
                self._conn.execute(
                    "ALTER TABLE decisions ADD COLUMN sous_objectif_id TEXT DEFAULT NULL"
                )
            except Exception:
                pass  # Colonne deja existante
            # Migration : ajouter impact_sous_objectif dans decisions
            try:
                self._conn.execute(
                    "ALTER TABLE decisions ADD COLUMN impact_sous_objectif REAL DEFAULT 0"
                )
            except Exception:
                pass  # Colonne deja existante
