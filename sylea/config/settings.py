"""
Configuration globale de Syléa.AI.
Charge les variables d'environnement depuis le fichier .env.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Charger le fichier .env s'il existe
_BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(_BASE_DIR / ".env", override=True)


def get_database_path() -> Path:
    """Retourne le chemin absolu vers la base de données SQLite."""
    raw = os.getenv("DATABASE_PATH", "data/sylea.db")
    path = Path(raw)
    if not path.is_absolute():
        path = _BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def is_debug() -> bool:
    """Retourne True si le mode debug est activé."""
    return os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")


# Constantes de l'application
APP_NAME = "SYLÉA.AI"
APP_VERSION = "1.0.0"
APP_TAGLINE = "Votre assistant de vie augmenté"

# Limites de probabilité
PROB_MIN = 0.01  # % minimum affichable
PROB_MAX = 99.9  # % maximum affichable

# Limites des évaluations
SCORE_MIN = 1
SCORE_MAX = 10

# Claude model
CLAUDE_MODEL = "claude-sonnet-4-6"


def get_api_key() -> str:
    """Retourne la clé API Anthropic."""
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError(
            "ANTHROPIC_API_KEY manquante. Créez un fichier .env avec votre clé API."
        )
    return key
