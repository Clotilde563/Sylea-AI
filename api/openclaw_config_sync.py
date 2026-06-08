"""
Sync des credentials Sylea Vault -> OpenClaw Gateway config file.

**Contexte :** OpenClaw Gateway lit les cles API tierces (Perplexity, Brave,
Tavily, Exa, Firecrawl, xAI) depuis 3 sources :
  1. Config file `~/.openclaw/openclaw.json`
     -> `plugins.entries.<provider>.config.webSearch.apiKey`
  2. Env vars du process (PERPLEXITY_API_KEY, BRAVE_API_KEY, etc.)
  3. Fallback (OPENROUTER_API_KEY pour perplexity)

Il ne lit **PAS** les cles depuis le payload HTTP ni un header custom. Donc
pour centraliser les cles dans le Credential Vault Sylea (multi-user-ready),
la seule voie sans forker OpenClaw est de **synchroniser** les cles Vault
vers le fichier `openclaw.json` a chaque changement.

**Modele mono-user (local dev) :**
- Un seul user Sylea = un seul set de cles dans openclaw.json
- Sync automatique au demarrage + a chaque modification Vault

**Limite multi-user :** cette approche ecrase les cles entre users. Pour
multi-tenant commercial, il faudrait soit :
  - Une instance Gateway par user (overhead reseau/port)
  - Forker OpenClaw pour accepter les cles en payload/header
  - Router via un proxy Sylea qui injecte selon le user authentifie

**Fonctions exposees :**
  - `sync_user_credentials_to_openclaw(db, user_id)` : extract + write
  - `get_openclaw_config_path()` : chemin du fichier config
  - `reload_openclaw_gateway()` : redemarre Gateway (optionnel, best-effort)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("sylea.openclaw_sync")


# ─────────────────────────────────────────────────────────────────────────────
# Mapping Sylea provider -> OpenClaw config path
# ─────────────────────────────────────────────────────────────────────────────
#
# Chaque entree decrit comment injecter une cle du Credential Vault Sylea
# dans la structure `openclaw.json`. Le path est une liste de cles imbriquees
# qui sera navigue (cree si absent) pour y mettre la cle.
#
# La cle Vault Sylea est `(provider_slug, field="api_key")`. Si absent,
# l'entree n'est pas touchee (on ne supprime pas les cles existantes a moins
# de remove_missing=True).

_SYNC_MAP: dict[str, dict[str, Any]] = {
    "perplexity": {
        "path": ["plugins", "entries", "perplexity", "config", "webSearch", "apiKey"],
        "enable_path": ["plugins", "entries", "perplexity", "enabled"],
    },
    "brave": {
        "path": ["plugins", "entries", "brave-web-search", "config", "apiKey"],
        "enable_path": ["plugins", "entries", "brave-web-search", "enabled"],
    },
    "tavily": {
        "path": ["plugins", "entries", "tavily", "config", "apiKey"],
        "enable_path": ["plugins", "entries", "tavily", "enabled"],
    },
    "exa": {
        "path": ["plugins", "entries", "exa", "config", "apiKey"],
        "enable_path": ["plugins", "entries", "exa", "enabled"],
    },
    "firecrawl": {
        "path": ["plugins", "entries", "firecrawl", "config", "apiKey"],
        "enable_path": ["plugins", "entries", "firecrawl", "enabled"],
    },
    "xai": {
        "path": ["plugins", "entries", "xai", "config", "apiKey"],
        "enable_path": ["plugins", "entries", "xai", "enabled"],
    },
    "openrouter": {
        "path": ["plugins", "entries", "openrouter", "config", "apiKey"],
        "enable_path": ["plugins", "entries", "openrouter", "enabled"],
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Config file path resolution
# ─────────────────────────────────────────────────────────────────────────────

def get_openclaw_config_path() -> Path:
    """Retourne le path de `openclaw.json`. Override via env `OPENCLAW_CONFIG_PATH`."""
    override = os.environ.get("OPENCLAW_CONFIG_PATH", "").strip()
    if override:
        return Path(override)
    # Default Windows/Mac/Linux : ~/.openclaw/openclaw.json
    return Path.home() / ".openclaw" / "openclaw.json"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers : set/get nested dict paths
# ─────────────────────────────────────────────────────────────────────────────

def _set_nested(d: dict, path: list[str], value: Any) -> None:
    """Set `d[path[0]][path[1]]...[path[-1]] = value`, creating dicts as needed."""
    cur = d
    for key in path[:-1]:
        if key not in cur or not isinstance(cur[key], dict):
            cur[key] = {}
        cur = cur[key]
    cur[path[-1]] = value


def _get_nested(d: dict, path: list[str]) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


# ─────────────────────────────────────────────────────────────────────────────
# Main sync function
# ─────────────────────────────────────────────────────────────────────────────

async def sync_user_credentials_to_openclaw(
    db: Any,
    user_id: str,
    *,
    config_path: Path | None = None,
    remove_missing: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Synchronise les cles du Vault Sylea vers le config OpenClaw.

    Args:
        db : DatabaseManager
        user_id : user dont on lit les cles du Vault
        config_path : override du path (defaut = ~/.openclaw/openclaw.json)
        remove_missing : si True, efface les cles OpenClaw dont Sylea n'a plus
            la valeur. Si False (default), on ajoute/update seulement.
        dry_run : si True, calcule le diff sans ecrire.

    Retourne :
        {
            "ok": bool,
            "synced_providers": [...],
            "skipped_providers": [...],
            "config_path": str,
            "changes": [...],
            "error": str (si ok=False)
        }
    """
    if not user_id:
        return {"ok": False, "error": "user_id requis"}

    path = config_path or get_openclaw_config_path()
    if not path.exists():
        return {"ok": False, "error": f"openclaw.json absent : {path}"}

    # Lecture config actuelle
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        return {"ok": False, "error": f"lecture config failed : {e}"}

    # Lecture Vault Sylea (async/PG)
    try:
        from api.credentials import get_credential_async
    except Exception as e:
        return {"ok": False, "error": f"credentials module absent : {e}"}

    synced: list[str] = []
    skipped: list[str] = []
    changes: list[dict[str, Any]] = []

    for provider_slug, mapping in _SYNC_MAP.items():
        try:
            api_key = await get_credential_async(user_id, provider_slug, "api_key", context="openclaw_sync")
        except Exception as e:
            logger.debug(f"sync: get_credential_async({provider_slug}) failed : {e}")
            api_key = None

        existing = _get_nested(config, mapping["path"])

        if api_key:
            if existing != api_key:
                # Ajout/update
                _set_nested(config, mapping["path"], api_key)
                # Active le plugin si pas deja
                if _get_nested(config, mapping["enable_path"]) is not True:
                    _set_nested(config, mapping["enable_path"], True)
                changes.append({
                    "provider": provider_slug,
                    "action": "updated" if existing else "added",
                    "masked": api_key[:4] + "..." + api_key[-4:] if len(api_key) > 10 else "***",
                })
            synced.append(provider_slug)
        else:
            if remove_missing and existing is not None:
                # Supprime la cle et desactive le plugin
                _set_nested(config, mapping["path"], "")
                _set_nested(config, mapping["enable_path"], False)
                changes.append({"provider": provider_slug, "action": "removed"})
            skipped.append(provider_slug)

    # Ecriture atomique (si pas dry_run)
    if not dry_run and changes:
        try:
            # Backup
            backup_path = path.with_suffix(".json.bak")
            shutil.copy2(path, backup_path)

            # Write atomic : tmp -> rename
            tmp_fd, tmp_path = tempfile.mkstemp(
                suffix=".json.tmp", dir=str(path.parent), text=True
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
                # Windows : need to remove dest first
                if path.exists():
                    os.replace(tmp_path, str(path))
                else:
                    os.rename(tmp_path, str(path))
            except Exception:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
                raise
        except Exception as e:
            return {"ok": False, "error": f"ecriture failed : {e}"}

    return {
        "ok": True,
        "synced_providers": synced,
        "skipped_providers": skipped,
        "config_path": str(path),
        "changes": changes,
        "dry_run": dry_run,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Optionnel : reload Gateway
# ─────────────────────────────────────────────────────────────────────────────

def reload_openclaw_gateway() -> dict[str, Any]:
    """Tente de faire reload les plugins du Gateway sans le redemarrer.

    Best-effort : si endpoint /reload n'existe pas, on ne peut pas forcer.
    L'alternative est de redemarrer le process Gateway, mais ca depasse le
    perimetre de Sylea (le process est lance manuellement par l'user).

    Retourne :
        {"ok": bool, "action": str, "hint": str}
    """
    try:
        import httpx
        url = os.environ.get("OPENCLAW_GATEWAY_URL", "http://localhost:18789")
        token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        # Tente /reload (non-standard, best-effort)
        with httpx.Client(timeout=5.0) as client:
            for endpoint in ("/reload", "/plugins/reload", "/config/reload"):
                try:
                    resp = client.post(f"{url}{endpoint}", headers=headers)
                    if resp.status_code < 400:
                        return {"ok": True, "action": f"reloaded via {endpoint}"}
                except Exception:
                    continue
    except Exception as e:
        return {"ok": False, "action": "error", "hint": str(e)}

    return {
        "ok": False,
        "action": "not_supported",
        "hint": (
            "OpenClaw Gateway ne supporte pas le reload live. "
            "Redemarrer manuellement : `node openclaw gateway --port 18789`. "
            "Les nouvelles cles seront picked up au prochain demarrage."
        ),
    }


__all__ = [
    "sync_user_credentials_to_openclaw",
    "get_openclaw_config_path",
    "reload_openclaw_gateway",
]
