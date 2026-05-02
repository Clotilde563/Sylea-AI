"""
Agent 3 — Primitives stables re-exportees depuis les routers.

Ce module sert de facade entre le dispatcher (`api/agent3_native_dispatcher.py`)
et les helpers implementes dans les routers (`agent3_openclaw.py`, `integrations.py`).

Objectif : reduire le couplage implicite en remplacant les 15+ imports
dynamiques eparpilles dans le dispatcher (`from api.routers.agent3_openclaw
import ...` repete dans chaque handler) par un unique import depuis ce module.

Resolution lazy via `__getattr__` : chaque attribut est resolu a l'acces,
pas au chargement du module. Cela permet :
  - Evite les circular imports au chargement (routers chargent plus tard).
  - Les tests peuvent continuer a monkeypatch les modules sources
    (`monkeypatch.setattr(agent3_openclaw, "_send_email_smtp", fake)`) : le
    lookup dynamique verra la substitution au prochain appel.

Regles :
  - Ne contient AUCUNE logique metier propre.
  - Si un helper doit migrer de son router vers ce module plus tard, il faut
    le materialiser comme variable module-level (shadow le __getattr__).
"""

from __future__ import annotations

from typing import Any


# Mapping : nom de primitive -> (module source, attribut source).
# La resolution se fait a l'acces (pas a l'import), ce qui permet aux tests
# de monkeypatcher les modules sources sans avoir a connaitre ce module.
_PRIMITIVES: dict[str, tuple[str, str]] = {
    # Router Agent 3 OpenClaw (persistence, fallback, generation PDF, workspace).
    "_save_memory": ("api.routers.agent3_openclaw", "_save_memory"),
    "_log_clawhub_event": ("api.routers.agent3_openclaw", "_log_clawhub_event"),
    "_send_email_smtp": ("api.routers.agent3_openclaw", "_send_email_smtp"),
    "_save_file_create_fallback": ("api.routers.agent3_openclaw", "_save_file_create_fallback"),
    "_generate_pdf": ("api.routers.agent3_openclaw", "_generate_pdf"),
    "get_workspace_folder_name": ("api.routers.agent3_openclaw", "get_workspace_folder_name"),
    "WORKSPACE_BASE": ("api.routers.agent3_openclaw", "WORKSPACE_BASE"),
    # Router Integrations (OAuth Google).
    "_get_integration": ("api.routers.integrations", "_get_integration"),
    "_refresh_google_token": ("api.routers.integrations", "_refresh_google_token"),
}


def __getattr__(name: str) -> Any:
    """Resolution lazy : importe le module source et retourne son attribut.

    Levee `AttributeError` si le nom n'est pas dans le mapping, pour coller
    au contrat standard de Python (permet `hasattr`, `from X import *`, etc.).
    """
    if name in _PRIMITIVES:
        module_name, attr_name = _PRIMITIVES[name]
        import importlib
        module = importlib.import_module(module_name)
        return getattr(module, attr_name)
    raise AttributeError(f"module 'api.agent3_primitives' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(_PRIMITIVES.keys())


__all__ = list(_PRIMITIVES.keys())
