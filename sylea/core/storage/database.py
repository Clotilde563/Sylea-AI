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
    objectif_probabilite_calculee REAL DEFAULT 0,
    probabilite_actuelle    REAL DEFAULT 0.0,
    auth_user_id            TEXT DEFAULT NULL,
    genre                   TEXT DEFAULT '',
    objectif_modifie_le     TEXT,
    phrase_personnalite     TEXT DEFAULT NULL,
    temps_initial_jours     INTEGER DEFAULT 0,
    temps_gagne_jours       REAL DEFAULT 0.0,
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
    temps_gagne_avant   REAL DEFAULT 0.0,
    temps_gagne_apres   REAL DEFAULT 0.0,
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
    audio_data TEXT DEFAULT '',
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

# Propositions emises par l'Agent 1 ou 2 lors d'une conversation, en attente
# de confirmation/refus utilisateur. Quand l'agent detecte un event/decision
# important (heritage, promotion, gain/perte majeure, etc.), il propose
# d'enregistrer un impact stats au lieu de le faire silencieusement.
_CREATE_AGENT_PROPOSALS = """
CREATE TABLE IF NOT EXISTS agent_proposals (
    id TEXT PRIMARY KEY,
    auth_user_id TEXT NOT NULL,
    agent_label TEXT NOT NULL,      -- 'agent1' ou 'agent2'
    type TEXT NOT NULL,             -- 'evenement' | 'decision_majeure' | 'info_profil_critique'
    description TEXT NOT NULL,
    impact_jours REAL DEFAULT 0,    -- positif = gain de temps, negatif = perte
    resume TEXT DEFAULT '',
    rationale TEXT DEFAULT '',
    target_so_hint TEXT DEFAULT '', -- nom du SO suggere par l'IA
    statut TEXT DEFAULT 'pending',  -- 'pending' | 'confirmed' | 'rejected'
    created_at TEXT NOT NULL,
    responded_at TEXT,
    decision_id TEXT                -- FK vers decisions si confirmed
);
"""

_CREATE_AGENT2_MESSAGES = """
CREATE TABLE IF NOT EXISTS agent2_messages (
    id TEXT PRIMARY KEY,
    auth_user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'text',
    created_at TEXT NOT NULL,
    audio_data TEXT DEFAULT '',
    FOREIGN KEY (auth_user_id) REFERENCES users(id)
);
"""

_CREATE_AGENT_REMINDERS = """
CREATE TABLE IF NOT EXISTS agent_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    agent_id TEXT DEFAULT 'agent2',
    reminder_time TEXT NOT NULL,
    reminder_date TEXT NOT NULL,
    message TEXT NOT NULL,
    completed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL
);
"""

_CREATE_AGENT3_MESSAGES = """
CREATE TABLE IF NOT EXISTS agent3_messages (
    id TEXT PRIMARY KEY,
    auth_user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'text',
    created_at TEXT NOT NULL,
    audio_data TEXT DEFAULT '',
    FOREIGN KEY (auth_user_id) REFERENCES users(id)
);
"""

_CREATE_USER_EMAIL_SETTINGS = """
CREATE TABLE IF NOT EXISTS user_email_settings (
    user_id TEXT PRIMARY KEY,
    smtp_email TEXT NOT NULL,
    smtp_password TEXT NOT NULL,
    smtp_host TEXT DEFAULT 'smtp.gmail.com',
    smtp_port INTEGER DEFAULT 465,
    display_name TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


_CREATE_WORKSPACE_SHARES = """
CREATE TABLE IF NOT EXISTS workspace_shares (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    owner_user_id TEXT NOT NULL,
    shared_with_user_id TEXT NOT NULL,
    permission TEXT DEFAULT 'read',
    created_at TEXT NOT NULL,
    UNIQUE(project_id, shared_with_user_id)
);
"""


# ── Phase 3 — Preferences de tools par utilisateur ──────────────────────────
# Chaque (user, tool_name) a une preference enabled 0/1. Absence d'entree =
# enabled par defaut (selon le TOOL_PROFILES de l'agent). Cette table ne
# remplace pas TOOL_PROFILES (qui est la whitelist systeme au niveau agent),
# elle permet a chaque utilisateur de desactiver un tool pour SON agent.
_CREATE_USER_TOOL_PREFERENCES = """
CREATE TABLE IF NOT EXISTS user_tool_preferences (
    user_id     TEXT NOT NULL,
    tool_name   TEXT NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (user_id, tool_name)
);
"""


class DatabaseManager:
    """Gestionnaire de connexion et de schema portable (SQLite + PostgreSQL).

    Migration 2026-05-15 : bascule automatique selon `DATABASE_URL` env var.
    - DATABASE_URL absent ou sqlite://... → sqlite3.Connection natif (perf max)
    - DATABASE_URL = postgresql://... → RawDBProxy wrap SQLAlchemy (compat PG)
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._path = db_path or get_database_path()
        self._conn = None  # sqlite3.Connection ou RawDBProxy

    # ── Connexion ────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Ouvre la connexion et cree le schema si necessaire.

        Detection automatique du backend via DATABASE_URL :
        - SQLite : optimisations PRAGMAs + sqlite3 natif (perf)
        - PostgreSQL : RawDBProxy via SQLAlchemy sync engine
        """
        import os
        database_url = os.environ.get("DATABASE_URL", "").strip()

        if database_url and database_url.startswith(
            ("postgresql://", "postgresql+", "postgres://"),
        ):
            # Mode PostgreSQL : RawDBProxy
            from sylea.core.storage.db_adapter import RawDBProxy
            self._conn = RawDBProxy.from_url(database_url)
            # Pas d'initialisation de schema en PG : Alembic gere
            return

        # Mode SQLite (defaut) : sqlite3 natif avec optimisations PRAGMAs
        # - WAL : 1 writer + N readers
        # - busy_timeout 5s : evite SQLITE_BUSY
        # - synchronous=NORMAL : perf 2-3x meilleure
        # - cache_size 64MB
        # - temp_store=MEMORY
        # - check_same_thread=False : partage multi-thread
        self._conn = sqlite3.connect(
            str(self._path),
            timeout=10.0,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA cache_size=-65536;")
        self._conn.execute("PRAGMA temp_store=MEMORY;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.execute("PRAGMA mmap_size=268435456;")
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
            self._conn.execute(_CREATE_AGENT_PROPOSALS)
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_proposals_user "
                "ON agent_proposals(auth_user_id, statut)"
            )
            self._conn.execute(_CREATE_AGENT2_MESSAGES)
            # ── Indexes critiques pour scale concurrent reads ──────────
            # Sans ces indexes, chaque query par user fait un FULL TABLE SCAN
            # ce qui devient ingérable à partir de ~10k rows.
            _CRITICAL_INDEXES = [
                # Isolation per-user : tous les SELECT/UPDATE par user_id
                "CREATE INDEX IF NOT EXISTS idx_profil_auth_user ON profil_utilisateur(auth_user_id)",
                "CREATE INDEX IF NOT EXISTS idx_decisions_user ON decisions(user_id)",
                "CREATE INDEX IF NOT EXISTS idx_decisions_user_cree ON decisions(user_id, cree_le DESC)",
                "CREATE INDEX IF NOT EXISTS idx_decisions_so ON decisions(sous_objectif_id)",
                "CREATE INDEX IF NOT EXISTS idx_bilans_user ON bilans_quotidiens(user_id, date DESC)",
                "CREATE INDEX IF NOT EXISTS idx_so_user ON sous_objectifs(user_id, ordre)",
                "CREATE INDEX IF NOT EXISTS idx_taches_user ON taches_quotidiennes(user_id, date DESC)",
                "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
                # Agent messages : queries par auth_user_id + created_at (quota daily)
                "CREATE INDEX IF NOT EXISTS idx_agent_msg_user_created ON agent_messages(auth_user_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_agent_msg_user_role ON agent_messages(auth_user_id, role)",
                "CREATE INDEX IF NOT EXISTS idx_agent2_msg_user_created ON agent2_messages(auth_user_id, created_at DESC)",
                "CREATE INDEX IF NOT EXISTS idx_agent2_msg_user_role ON agent2_messages(auth_user_id, role)",
                "CREATE INDEX IF NOT EXISTS idx_collected_info_user ON agent_collected_info(user_id, collected_at DESC)",
            ]
            for stmt in _CRITICAL_INDEXES:
                try:
                    self._conn.execute(stmt)
                except Exception:
                    pass  # table peut-etre absente, best-effort
            self._conn.execute(_CREATE_AGENT_REMINDERS)
            self._conn.execute(_CREATE_AGENT3_MESSAGES)
            self._conn.execute(_CREATE_USER_EMAIL_SETTINGS)
            self._conn.execute(_CREATE_WORKSPACE_SHARES)
            self._conn.execute(_CREATE_USER_TOOL_PREFERENCES)
            # Migrations legacy (colonnes maintenant dans CREATE TABLE, gardees pour anciennes DBs)
            for col_sql in [
                "ALTER TABLE profil_utilisateur ADD COLUMN auth_user_id TEXT DEFAULT NULL",
                "ALTER TABLE profil_utilisateur ADD COLUMN genre TEXT DEFAULT ''",
                "ALTER TABLE profil_utilisateur ADD COLUMN heures_objectif REAL DEFAULT 1.0",
                "ALTER TABLE profil_utilisateur ADD COLUMN objectif_modifie_le TEXT",
                "ALTER TABLE profil_utilisateur ADD COLUMN phrase_personnalite TEXT DEFAULT NULL",
                "ALTER TABLE profil_utilisateur ADD COLUMN objectif_probabilite_calculee REAL DEFAULT 0",
                "ALTER TABLE profil_utilisateur ADD COLUMN photo_url TEXT DEFAULT NULL",
            ]:
                try:
                    self._conn.execute(col_sql)
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
            # Migration : ajouter audio_data dans agent_messages
            try:
                self._conn.execute(
                    "ALTER TABLE agent_messages ADD COLUMN audio_data TEXT DEFAULT ''"
                )
            except Exception:
                pass  # Colonne deja existante
            # Index sur auth_user_id pour performance et cohérence multi-user
            # Note: SQLite ne supporte pas ALTER TABLE ADD FOREIGN KEY.
            # La contrainte est appliquée au niveau applicatif (repositories.py).
            try:
                self._conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_profil_auth_user_id ON profil_utilisateur(auth_user_id)"
                )
            except Exception:
                pass
            # Migration : ajouter temps_initial_jours et temps_gagne_jours dans profil_utilisateur
            for col_temps in [
                "ALTER TABLE profil_utilisateur ADD COLUMN temps_initial_jours INTEGER DEFAULT 0",
                "ALTER TABLE profil_utilisateur ADD COLUMN temps_gagne_jours REAL DEFAULT 0.0",
            ]:
                try:
                    self._conn.execute(col_temps)
                except Exception:
                    pass  # Colonne deja existante
            # Migration : ajouter temps_gagne_avant et temps_gagne_apres dans decisions
            for col_temps_dec in [
                "ALTER TABLE decisions ADD COLUMN temps_gagne_avant REAL DEFAULT 0.0",
                "ALTER TABLE decisions ADD COLUMN temps_gagne_apres REAL DEFAULT 0.0",
            ]:
                try:
                    self._conn.execute(col_temps_dec)
                except Exception:
                    pass  # Colonne deja existante
            # Legacy migrations for competences/diplomes/langues (now in CREATE TABLE)
            for col_sql2 in [
                "ALTER TABLE profil_utilisateur ADD COLUMN competences TEXT DEFAULT ''",
                "ALTER TABLE profil_utilisateur ADD COLUMN diplomes TEXT DEFAULT ''",
                "ALTER TABLE profil_utilisateur ADD COLUMN langues TEXT DEFAULT ''",
            ]:
                try:
                    self._conn.execute(col_sql2)
                except Exception:
                    pass
