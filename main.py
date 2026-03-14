#!/usr/bin/env python3
"""
SYLÉA.AI — Point d'entrée principal.

Mode automatique :
  • Si ANTHROPIC_API_KEY est configurée → mode IA complète (Claude)
  • Sinon → mode simulation locale (aucune API requise)

Usage :
    python main.py              # mode automatique
    python main.py --local      # force le mode simulation (sans API)
    python main.py --claude     # force le mode Claude (requiert clé API)
"""

import os
import sys

# Force UTF-8 so Rich box-drawing chars work on any Windows terminal
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _api_key_disponible() -> bool:
    """Vérifie si une clé API Anthropic valide est configurée."""
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass
    key = os.getenv("ANTHROPIC_API_KEY", "")
    return bool(key) and key != "sk-ant-votre-cle-api-ici"


def main() -> None:
    """Lance l'application en mode approprié selon la configuration."""
    args = sys.argv[1:]
    forcer_local = "--local" in args
    forcer_claude = "--claude" in args

    if forcer_claude or (not forcer_local and _api_key_disponible()):
        # Mode Claude : analyses enrichies par l'IA
        from sylea.interfaces.cli.app import AppSylea
        app = AppSylea()
        app.demarrer()
    else:
        # Mode simulation : 100% local, aucune API requise
        from sylea.interfaces.cli.main import ApplicationSylea
        app = ApplicationSylea()
        app.lancer()


if __name__ == "__main__":
    main()
