"""
ClawHub Meta-Tools — Phase 4 Part C.

Expose 3 meta-tools au LLM pour gerer dynamiquement son registre de skills :

  1. `clawhub_search`  — Chercher un skill dans le registre clawhub.com
  2. `clawhub_install` — Installer un skill localement (telechargement)
  3. `clawhub_publish` — Publier un skill genere par le LLM sur clawhub.com

L'idee est que quand l'Agent 3 se retrouve sans tool adapte pour une tache
precise, il peut :
  - D'abord chercher (`clawhub_search`) si un skill existe deja
  - Si oui, l'installer (`clawhub_install`) et l'utiliser au tour suivant
  - Si non, en creer un (`clawhub_publish`) qui sera reutilise a l'avenir

Ces meta-tools utilisent la CLI `clawhub` (v0.9.0+) via subprocess, et invalident
le cache du loader apres install/publish pour que le skill soit immediatement
disponible dans build_tool_schemas().
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("sylea.agent3.clawhub_meta_tools")


# ─────────────────────────────────────────────────────────────────────────────
# Tool schemas exposes a l'agent
# ─────────────────────────────────────────────────────────────────────────────

CLAWHUB_META_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "clawhub_search",
        "description": (
            "Cherche un skill sur le registre ClawHub (clawhub.com). Utilise "
            "CE TOOL AVANT de repondre 'je ne peux pas' : il y a probablement "
            "un skill qui peut accomplir la tache. Retourne la liste des "
            "correspondances avec slug, nom, description. Ensuite, utilise "
            "clawhub_install pour installer le skill le plus pertinent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Termes de recherche en langage naturel. Ex: "
                        "'postgres backups', 'slack notifications', "
                        "'ebay scraper'. Sois specifique."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Nombre max de resultats (defaut 10, max 30).",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "clawhub_install",
        "description": (
            "Installe un skill depuis le registre ClawHub dans ~/.openclaw/skills/. "
            "Le skill devient immediatement disponible comme tool `skill_<slug>` "
            "au prochain tour. ACTION POTENTIELLEMENT DESTRUCTIVE (telecharge "
            "du code tiers) — confirmation utilisateur recommandee en mode default."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": "Slug exact du skill (ex: 'weather', 'slack').",
                },
                "version": {
                    "type": "string",
                    "description": "Version semver specifique (optionnel, defaut: latest).",
                },
            },
            "required": ["slug"],
        },
    },
    {
        "name": "clawhub_publish",
        "description": (
            "Cree et publie un nouveau skill sur le registre ClawHub. A "
            "utiliser UNIQUEMENT quand clawhub_search n'a rien retourne de "
            "pertinent ET que la tache est generalisable (reutilisable par "
            "d'autres utilisateurs). Le LLM doit fournir un SKILL.md complet "
            "avec frontmatter YAML + instructions markdown claires. Requis : "
            "etre authentifie via 'clawhub login' au prealable."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "slug": {
                    "type": "string",
                    "description": (
                        "Slug unique kebab-case (ex: 'crypto-tracker'). "
                        "Doit etre descriptif et generique."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Nom lisible (ex: 'Crypto Tracker').",
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Description courte (1-2 phrases) expliquant quand "
                        "utiliser ce skill. Pattern recommande : "
                        "'Use when: X. NOT for: Y. [Requires: Z]'."
                    ),
                },
                "skill_content": {
                    "type": "string",
                    "description": (
                        "Contenu complet du SKILL.md (frontmatter YAML + body "
                        "markdown). Le frontmatter doit contenir au minimum "
                        "`name:`, `description:`. Body : instructions claires "
                        "avec blocs ```bash``` pour les commandes."
                    ),
                },
                "version": {
                    "type": "string",
                    "description": "Version semver (defaut: '0.1.0').",
                    "default": "0.1.0",
                },
                "changelog": {
                    "type": "string",
                    "description": "Note de version (optionnel).",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tags de categorisation (optionnel, max 5).",
                },
            },
            "required": ["slug", "name", "description", "skill_content"],
        },
    },
]

CLAWHUB_META_TOOL_NAMES: set[str] = {t["name"] for t in CLAWHUB_META_TOOL_SCHEMAS}


# ─────────────────────────────────────────────────────────────────────────────
# CLI wrapper (clawhub binary)
# ─────────────────────────────────────────────────────────────────────────────

def _find_clawhub_binary() -> str:
    """Localise l'executable clawhub (npm global). Retourne le chemin ou 'clawhub'
    si on doit se fier au PATH."""
    explicit = os.environ.get("CLAWHUB_CLI_PATH")
    if explicit and os.path.exists(explicit):
        return explicit

    # Windows : %APPDATA%\npm\clawhub.cmd
    if sys.platform == "win32":
        candidates = [
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm", "clawhub.cmd"),
            os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm", "clawhub.ps1"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c

    found = shutil.which("clawhub")
    return found or "clawhub"


async def _run_clawhub(
    args: list[str],
    *,
    timeout: int = 60,
    cwd: Optional[str] = None,
    env_extra: Optional[dict[str, str]] = None,
    auth_user_id: Optional[str] = None,
) -> tuple[str, str, int]:
    """Execute `clawhub <args>`. Retourne (stdout, stderr, returncode).

    Utilise asyncio.to_thread pour ne pas bloquer l'event loop.
    Sur Windows, CREATE_NO_WINDOW evite les flashs de console.

    Si `auth_user_id` est fourni :
      1. Override HOME / USERPROFILE / XDG_CONFIG_HOME pour que le CLI lise
         sa config depuis `~/.sylea/users/{id}/`.
      2. Auto-injecte les options globales `--workdir <user_home>` et
         `--dir .openclaw/skills` AVANT le sous-command pour que install/
         uninstall/update/publish ecrivent dans
         `~/.sylea/users/{id}/.openclaw/skills/<slug>/` (alignment avec le
         scan path de get_user_skills_dir()).

    NB sur le clawhub CLI v0.9 : les options `--workdir` et `--dir` sont
    GLOBALES (avant le sous-command), pas par-command. Donc on les insere
    en tete de `args`. On evite la duplication si l'appelant a deja passe ces
    options.
    """
    binary = _find_clawhub_binary()

    # Auto-prefix global options (--workdir + --dir) si auth_user_id et que
    # l'appelant n'a pas deja inject ses propres values. Les sous-commands
    # qui n'ont pas besoin de skills-dir (login, logout, whoami, search)
    # ignorent simplement ces flags ; aucun cout a les ajouter en preventif.
    final_args = list(args)
    if auth_user_id and "--workdir" not in args:
        try:
            from api.agent3_skills.clawhub_loader import get_user_home_override
            _user_home = get_user_home_override(auth_user_id)
            if _user_home is not None:
                # Inserer les options globales en tete (avant tout sous-command).
                # On respecte un eventuel `--no-input` deja present : on insert
                # nos options apres `--no-input` pour preserver la lisibilite.
                _prefix = ["--workdir", str(_user_home), "--dir", ".openclaw/skills"]
                if final_args and final_args[0] == "--no-input":
                    final_args = [final_args[0]] + _prefix + final_args[1:]
                else:
                    final_args = _prefix + final_args
        except Exception as _wd_err:
            logger.debug(f"workdir auto-prefix failed: {_wd_err}")

    cmd = [binary, *final_args]

    creationflags = 0x08000000 if sys.platform == "win32" else 0
    full_env = os.environ.copy()

    # Isolation user : override HOME pour que clawhub ecrive dans le dossier
    # dedie au user courant. On garde CLAWHUB_CLI_PATH / PATH intacts.
    if auth_user_id:
        try:
            from api.agent3_skills.clawhub_loader import (
                ensure_user_skills_dir, get_user_home_override,
            )
            # S'assure que le dossier ~/.sylea/users/{id}/.openclaw/skills/ existe
            ensure_user_skills_dir(auth_user_id)
            user_home = get_user_home_override(auth_user_id)
            if user_home is not None:
                home_str = str(user_home)
                # POSIX : HOME
                full_env["HOME"] = home_str
                # Windows : USERPROFILE (equivalent de HOME)
                full_env["USERPROFILE"] = home_str
                # XDG config fallback (si clawhub l'utilise un jour)
                full_env["XDG_CONFIG_HOME"] = str(user_home / ".config")
                # Marker pour debug / audit trail
                full_env["SYLEA_AUTH_USER_ID"] = str(auth_user_id)
                # Hygiene : retirer les vars CLAWHUB_* qui pourraient venir du
                # process parent et fuiter entre users (token, registry URL, etc.).
                # Laisser explicitement au CLI le soin de lire la config depuis
                # le HOME override.
                for k in list(full_env.keys()):
                    if k.startswith("CLAWHUB_") and k not in {"CLAWHUB_CLI_PATH"}:
                        full_env.pop(k, None)
        except Exception as e:
            logger.warning(f"HOME override failed for user {auth_user_id}: {e}")

    if env_extra:
        full_env.update(env_extra)

    def _run() -> tuple[str, str, int]:
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                cwd=cwd,
                env=full_env,
                creationflags=creationflags,
            )
            return (
                res.stdout.decode("utf-8", errors="replace").strip(),
                res.stderr.decode("utf-8", errors="replace").strip(),
                res.returncode,
            )
        except subprocess.TimeoutExpired:
            return "", f"Timeout apres {timeout}s", -1
        except FileNotFoundError:
            return "", f"Binaire clawhub introuvable ({binary})", -2
        except Exception as e:
            return "", f"Erreur {type(e).__name__}: {str(e)[:200]}", -3

    return await asyncio.to_thread(_run)


def _try_parse_json(text: str) -> Any:
    """Extrait le premier JSON parseable (objet ou tableau) d'un texte."""
    if not text:
        return None
    # Tentative directe
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Chercher la premiere accolade/crochet
    for i, ch in enumerate(text):
        if ch in "{[":
            # Tenter chaque longueur decroissante
            for j in range(len(text), i, -1):
                try:
                    return json.loads(text[i:j])
                except json.JSONDecodeError:
                    continue
            break
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Parser texte (fallback quand --json n'est pas supporte)
# ─────────────────────────────────────────────────────────────────────────────

_SLUG_DESC_RE = re.compile(r"^([a-z0-9][a-z0-9_-]{1,62})\s*[-–—:]\s*(.+)$")


def _parse_search_text(text: str) -> list[dict[str, str]]:
    """Parse la sortie humaine de `clawhub search` quand JSON indispo."""
    results = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _SLUG_DESC_RE.match(line.lower() if line[0].isupper() else line)
        if m:
            results.append({"slug": m.group(1), "description": m.group(2).strip()})
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Meta-tool implementations
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MetaToolResult:
    """Format de retour normalise utilisable par le dispatcher."""
    content: str
    is_error: bool = False
    raw: dict[str, Any] = None  # type: ignore[assignment]

    def to_dict(self) -> dict[str, Any]:
        return {"content": self.content, "is_error": self.is_error, "raw": self.raw or {}}


async def clawhub_meta_search(
    query: str, limit: int = 10, *, auth_user_id: Optional[str] = None,
) -> MetaToolResult:
    """`clawhub search <query>` -> liste de {slug, description, ...}.

    `auth_user_id` est forwarde au CLI (HOME override) pour que la config
    clawhub (login tokens, etc.) soit aussi per-user.
    """
    query = (query or "").strip()
    if not query:
        return MetaToolResult("Parametre 'query' manquant.", is_error=True, raw={})

    limit = max(1, min(30, int(limit or 10)))

    # Tentative JSON
    stdout, stderr, rc = await _run_clawhub(
        ["search", query, "--json"], timeout=30, auth_user_id=auth_user_id,
    )
    results: list[dict[str, Any]] = []
    if rc == 0 and stdout:
        parsed = _try_parse_json(stdout)
        if isinstance(parsed, list):
            results = parsed
        elif isinstance(parsed, dict):
            maybe = parsed.get("results") or parsed.get("skills") or parsed.get("data")
            if isinstance(maybe, list):
                results = maybe

    # Fallback : sortie texte
    if not results and rc != 0:
        stdout2, stderr2, rc2 = await _run_clawhub(
            ["search", query], timeout=30, auth_user_id=auth_user_id,
        )
        if rc2 == 0 and stdout2:
            results = _parse_search_text(stdout2)
            stdout = stdout or stdout2
        else:
            return MetaToolResult(
                f"Recherche ClawHub echouee: {stderr or stderr2 or 'code ' + str(rc)}",
                is_error=True,
                raw={"rc": rc, "stderr": stderr},
            )

    results = results[:limit]
    if not results:
        return MetaToolResult(
            f"Aucun skill trouve pour '{query}'. Envisage clawhub_publish pour "
            "en creer un si la tache est generalisable.",
            is_error=False,
            raw={"query": query, "count": 0},
        )

    # Format lisible pour le LLM
    lines = [f"**{len(results)} skill(s) trouve(s) pour '{query}' :**", ""]
    for i, r in enumerate(results, 1):
        slug = r.get("slug") or r.get("name") or "?"
        desc = r.get("description") or ""
        author = r.get("author") or r.get("owner") or ""
        version = r.get("version") or r.get("latestVersion") or ""
        meta_bits = []
        if author:
            meta_bits.append(f"@{author}")
        if version:
            meta_bits.append(f"v{version}")
        meta = f" ({', '.join(meta_bits)})" if meta_bits else ""
        lines.append(f"{i}. `{slug}`{meta} — {desc[:200]}")
    lines.append("")
    lines.append("Pour installer : utilise clawhub_install avec le slug.")
    return MetaToolResult("\n".join(lines), is_error=False, raw={"results": results, "query": query})


async def clawhub_meta_install(
    slug: str, version: Optional[str] = None, *, auth_user_id: Optional[str] = None,
) -> MetaToolResult:
    """`clawhub install <slug>` -> installation dans le dossier du user courant.

    Si `auth_user_id` est fourni, installe dans
    `~/.sylea/users/{id}/.openclaw/skills/<slug>/` (isolation user).
    Sinon, fallback legacy : `~/.openclaw/skills/<slug>/`.
    """
    slug = (slug or "").strip()
    if not slug or not re.match(r"^[a-z0-9][a-z0-9_-]{1,62}$", slug):
        return MetaToolResult(
            f"Slug invalide: '{slug}'. Format: kebab-case, 2-63 chars.",
            is_error=True, raw={},
        )

    # Note : `--workdir` + `--dir` sont auto-injectes par _run_clawhub() quand
    # auth_user_id est fourni (Phase 14F). On declare juste --no-input,
    # le sous-command, le slug et --force.
    # --no-input : evite tout prompt interactif.
    # --force : autorise l'installation de skills "suspicious" en mode non-
    # interactif (sinon clawhub bloque sur certains skills marques par le
    # registre). Comme l'auto-extension a deja choisi le skill via une
    # recherche fuzzy raisonnee, on accepte d'installer.
    args: list[str] = ["--no-input", "install", slug, "--force"]
    if version:
        version = version.strip()
        if not re.match(r"^[\w.\-+]{1,30}$", version):
            return MetaToolResult(
                f"Version invalide: '{version}'", is_error=True, raw={},
            )
        args += ["--version", version]

    stdout, stderr, rc = await _run_clawhub(args, timeout=120, auth_user_id=auth_user_id)
    if rc == 0:
        # Invalider le cache du user courant pour que le skill apparaisse au prochain tour
        try:
            from api.agent3_skills.clawhub_loader import invalidate_cache, get_cache
            invalidate_cache(auth_user_id=auth_user_id)
            # Verifier que le skill est bien charge (dans le cache user-scoped)
            new_meta = get_cache().get_meta(slug, auth_user_id=auth_user_id)
            installed_ok = new_meta is not None
        except Exception as e:
            logger.warning(f"Cache invalidation failed after install: {e}")
            installed_ok = True  # On reste optimiste
            new_meta = None

        if installed_ok:
            desc = new_meta.description[:200] if new_meta else ""
            return MetaToolResult(
                f"Skill '{slug}' installe avec succes. Il est maintenant "
                f"disponible comme tool `skill_{slug.replace('-', '_')}`.\n"
                f"Description: {desc}",
                is_error=False,
                raw={"slug": slug, "version": version, "path": str(new_meta.path) if new_meta else ""},
            )
        # Chemin informatif (per-user si applicable)
        try:
            from api.agent3_skills.clawhub_loader import get_user_skills_dir
            expected_dir = get_user_skills_dir(auth_user_id) / slug
        except Exception:
            expected_dir = Path(f"~/.openclaw/skills/{slug}")
        return MetaToolResult(
            f"Skill '{slug}' installe par la CLI mais introuvable au rescan.\n"
            f"Verifie {expected_dir}/SKILL.md.\n{stdout[:500]}",
            is_error=False,  # pas un echec complet
            raw={"slug": slug, "stdout": stdout[:500]},
        )

    # rc != 0 : echec
    err_msg = stderr or stdout or f"Code de retour {rc}"
    # Detection des erreurs typiques
    hint = ""
    if "not found" in err_msg.lower() or "no such" in err_msg.lower():
        hint = "\n[Hint] Le slug n'existe pas dans le registre. Utilise clawhub_search pour trouver le bon slug."
    elif "unauthorized" in err_msg.lower() or "401" in err_msg:
        hint = "\n[Hint] Authentification requise. L'utilisateur doit executer 'clawhub login' en terminal."
    elif "network" in err_msg.lower() or "timeout" in err_msg.lower():
        hint = "\n[Hint] Probleme reseau. Verifie la connexion internet."

    return MetaToolResult(
        f"Installation de '{slug}' echouee.\n{err_msg[:500]}{hint}",
        is_error=True,
        raw={"slug": slug, "rc": rc, "stderr": stderr[:500]},
    )


def _validate_skill_md(content: str) -> Optional[str]:
    """Valide basiquement un SKILL.md. Retourne None si OK, message d'erreur sinon."""
    if not content or len(content) < 50:
        return "SKILL.md trop court (< 50 chars)"
    if not content.lstrip().startswith("---"):
        return "SKILL.md doit commencer par un frontmatter YAML (---\\n...)"
    # Verifier qu'il y a un fermeture du frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not fm_match:
        return "Frontmatter YAML non ferme (attendu : '---' a l'ouverture et a la fermeture)"
    fm_text = fm_match.group(1)
    if "name:" not in fm_text:
        return "Frontmatter doit contenir 'name:'"
    if "description:" not in fm_text:
        return "Frontmatter doit contenir 'description:'"
    # Body doit exister
    body_start = fm_match.end()
    body = content[body_start:].strip()
    if len(body) < 20:
        return "Body markdown trop court (< 20 chars apres le frontmatter)"
    return None


async def clawhub_meta_publish(
    slug: str,
    name: str,
    description: str,
    skill_content: str,
    version: str = "0.1.0",
    changelog: Optional[str] = None,
    tags: Optional[list[str]] = None,
    *,
    auth_user_id: Optional[str] = None,
) -> MetaToolResult:
    """`clawhub publish <path>` -> publie un nouveau skill sur clawhub.com."""
    slug = (slug or "").strip()
    name = (name or "").strip()
    description = (description or "").strip()

    if not re.match(r"^[a-z0-9][a-z0-9_-]{1,62}$", slug):
        return MetaToolResult(
            f"Slug invalide: '{slug}'. Format: kebab-case lowercase 2-63 chars.",
            is_error=True, raw={},
        )
    if not name or len(name) > 100:
        return MetaToolResult("Nom invalide (1-100 chars requis).", is_error=True, raw={})
    if not description or len(description) < 10:
        return MetaToolResult("Description trop courte (>= 10 chars).", is_error=True, raw={})
    if not re.match(r"^\d+\.\d+\.\d+(-[\w.]+)?$", version):
        return MetaToolResult(f"Version invalide '{version}' (semver requis).", is_error=True, raw={})

    # Validation du SKILL.md
    val_err = _validate_skill_md(skill_content)
    if val_err:
        return MetaToolResult(
            f"SKILL.md invalide: {val_err}.\nRegle bien le frontmatter et le body "
            "avant de republier.",
            is_error=True, raw={"validation_error": val_err},
        )

    # Ecrire dans un dossier temporaire
    tmpdir = Path(tempfile.mkdtemp(prefix=f"clawhub_publish_{slug}_"))
    skill_dir = tmpdir / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"

    try:
        skill_md.write_text(skill_content, encoding="utf-8")
        logger.info(f"Skill temporaire ecrit: {skill_md}")

        args = [
            "--no-input",
            "publish", str(skill_dir),
            "--slug", slug,
            "--name", name,
            "--version", version,
        ]
        if changelog:
            args.extend(["--changelog", changelog[:500]])
        if tags:
            tag_str = ",".join(t.strip() for t in tags[:5] if t.strip())
            if tag_str:
                args.extend(["--tags", tag_str])

        stdout, stderr, rc = await _run_clawhub(args, timeout=120, auth_user_id=auth_user_id)

        if rc == 0:
            # Invalider le cache user (au cas ou le publish installe aussi localement)
            try:
                from api.agent3_skills.clawhub_loader import invalidate_cache
                invalidate_cache(auth_user_id=auth_user_id)
            except Exception:
                pass
            return MetaToolResult(
                f"Skill '{slug}' v{version} publie avec succes sur clawhub.com.\n"
                f"Il est maintenant installable via clawhub_install.\n"
                f"{stdout[:500]}",
                is_error=False,
                raw={"slug": slug, "version": version, "stdout": stdout[:500]},
            )

        err_msg = stderr or stdout or f"Code {rc}"
        hint = ""
        if "unauthorized" in err_msg.lower() or "401" in err_msg:
            hint = "\n[Hint] L'utilisateur doit se connecter via 'clawhub login' en terminal."
        elif "already exists" in err_msg.lower() or "conflict" in err_msg.lower():
            hint = (
                "\n[Hint] Ce slug/version existe deja. Incrementer la version "
                "(ex: 0.1.1) ou utiliser un slug different."
            )
        elif "validation" in err_msg.lower() or "invalid" in err_msg.lower():
            hint = "\n[Hint] Le contenu SKILL.md est rejete par le registre. Verifier le frontmatter."

        return MetaToolResult(
            f"Publication de '{slug}' v{version} echouee.\n{err_msg[:500]}{hint}",
            is_error=True,
            raw={"slug": slug, "rc": rc, "stderr": stderr[:500]},
        )
    finally:
        # Cleanup best-effort
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception as e:
            logger.debug(f"Cleanup tmpdir failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher central (utilise par Agent3ActionDispatcher en Part D)
# ─────────────────────────────────────────────────────────────────────────────

_RESERVED_CLAWHUB_KEYS = {"auth_user_id", "user_id", "owner_user_id"}


async def dispatch_clawhub_meta_tool(
    tool_name: str,
    tool_input: dict,
    *,
    auth_user_id: Optional[str] = None,
) -> dict:
    """Route un tool_use meta-tool ClawHub vers sa fonction. Ne leve jamais.

    `auth_user_id` est forwarde pour isoler les writes (install/publish) dans
    le dossier dedie au user. Sans user_id, fallback legacy partage.

    Defense en profondeur : les cles reservees (auth_user_id, user_id, ...)
    dans `tool_input` sont ignorees. Un LLM ne peut donc pas forger un
    install dans le dossier d'un autre user.
    """
    tool_input = dict(tool_input or {})
    for k in _RESERVED_CLAWHUB_KEYS:
        tool_input.pop(k, None)

    try:
        if tool_name == "clawhub_search":
            r = await clawhub_meta_search(
                query=str(tool_input.get("query", "")),
                limit=int(tool_input.get("limit", 10) or 10),
                auth_user_id=auth_user_id,
            )
        elif tool_name == "clawhub_install":
            r = await clawhub_meta_install(
                slug=str(tool_input.get("slug", "")),
                version=tool_input.get("version"),
                auth_user_id=auth_user_id,
            )
        elif tool_name == "clawhub_publish":
            tags_in = tool_input.get("tags")
            tags = [str(t) for t in tags_in] if isinstance(tags_in, list) else None
            r = await clawhub_meta_publish(
                slug=str(tool_input.get("slug", "")),
                name=str(tool_input.get("name", "")),
                description=str(tool_input.get("description", "")),
                skill_content=str(tool_input.get("skill_content", "")),
                version=str(tool_input.get("version") or "0.1.0"),
                changelog=tool_input.get("changelog"),
                tags=tags,
                auth_user_id=auth_user_id,
            )
        else:
            return {
                "content": f"Meta-tool inconnu : {tool_name}",
                "is_error": True,
                "raw": {"tool_name": tool_name},
            }
        return r.to_dict()
    except Exception as e:
        logger.exception(f"Meta-tool {tool_name} crashed: {e}")
        return {
            "content": f"Erreur technique sur {tool_name}: {str(e)[:300]}",
            "is_error": True,
            "raw": {"exception": type(e).__name__},
        }


__all__ = [
    "CLAWHUB_META_TOOL_SCHEMAS",
    "CLAWHUB_META_TOOL_NAMES",
    "MetaToolResult",
    "clawhub_meta_search",
    "clawhub_meta_install",
    "clawhub_meta_publish",
    "dispatch_clawhub_meta_tool",
    "_validate_skill_md",  # expose pour les tests
]
