"""
ClawHub Skills — Interface avec le registre de skills OpenClaw pour Sylea.

Wrappe les commandes `openclaw skills` (search, install, list, info, check)
via subprocess, comme le reste du bridge OpenClaw.

Architecture :
  [Sylea API] -> [clawhub.py] -> [openclaw skills <cmd>] -> [ClawHub registry]
                                                          -> [~/.openclaw/skills/]

Le registre ClawHub contient 13,700+ skills communautaires installables.
Les skills installees sont chargees automatiquement par le Gateway OpenClaw.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("clawhub")


# ── Configuration ─────────────────────────────────────────────────────────────

SKILLS_DIR = os.path.join(os.path.expanduser("~"), ".openclaw", "skills")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class SkillInfo:
    """Information sur une skill ClawHub."""
    slug: str
    name: str
    description: str = ""
    version: str = ""
    author: str = ""
    installed: bool = False
    enabled: bool = True
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
        }
        if self.version:
            d["version"] = self.version
        if self.author:
            d["author"] = self.author
        d["installed"] = self.installed
        d["enabled"] = self.enabled
        if self.tags:
            d["tags"] = self.tags
        return d


@dataclass
class ClawHubResult:
    """Resultat d'une operation ClawHub."""
    success: bool
    data: list[dict] | dict | None = None
    error: str = ""
    raw_output: str = ""


# ── Execution CLI ─────────────────────────────────────────────────────────────

async def _run_openclaw_skills(args: list[str], timeout: int = 30) -> tuple[str, str, int]:
    """
    Execute `openclaw skills <args>` et retourne (stdout, stderr, returncode).
    Utilise asyncio.to_thread + subprocess.run pour Windows.
    """
    import subprocess as _sp

    is_windows = sys.platform == "win32"

    # Trouver l'executable openclaw
    openclaw_cmd = os.environ.get("OPENCLAW_CLI_PATH", "openclaw")
    openclaw_is_node = False
    mjs_path = ""

    if is_windows:
        npm_dir = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm")
        mjs_candidate = os.path.join(npm_dir, "node_modules", "openclaw", "openclaw.mjs")
        if os.path.exists(mjs_candidate):
            node_exe = shutil.which("node")
            if node_exe:
                openclaw_cmd = node_exe
                openclaw_is_node = True
                mjs_path = mjs_candidate
            else:
                cmd_path = os.path.join(npm_dir, "openclaw.cmd")
                if os.path.exists(cmd_path):
                    openclaw_cmd = cmd_path
        else:
            cmd_path = os.path.join(npm_dir, "openclaw.cmd")
            if os.path.exists(cmd_path):
                openclaw_cmd = cmd_path

    # Construire la commande
    if is_windows and openclaw_is_node:
        cmd_list = [openclaw_cmd, mjs_path, "skills"] + args
    else:
        cmd_list = [openclaw_cmd, "skills"] + args

    creation_flags = 0x08000000 if is_windows else 0  # CREATE_NO_WINDOW

    def _run():
        try:
            result = _sp.run(
                cmd_list,
                capture_output=True,
                timeout=timeout,
                creationflags=creation_flags,
            )
            return (
                result.stdout.decode("utf-8", errors="replace").strip(),
                result.stderr.decode("utf-8", errors="replace").strip(),
                result.returncode,
            )
        except _sp.TimeoutExpired:
            return "", "Timeout", -1
        except FileNotFoundError:
            return "", f"Executable introuvable: {openclaw_cmd}", -2
        except Exception as e:
            return "", f"Erreur: {type(e).__name__}: {str(e)[:200]}", -3

    return await asyncio.to_thread(_run)


def _parse_json_output(output: str) -> list[dict] | dict | None:
    """Tente de parser la sortie JSON du CLI."""
    if not output:
        return None
    # Chercher le premier { ou [
    for i, ch in enumerate(output):
        if ch in ('{', '['):
            try:
                return json.loads(output[i:])
            except json.JSONDecodeError:
                pass
    return None


def _parse_text_skills(output: str) -> list[dict]:
    """Parse la sortie texte du CLI quand ce n'est pas du JSON."""
    skills = []
    # Pattern typique : "skill-name - Description of the skill"
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-" * 5):
            continue
        # Essayer le format "slug - description"
        match = re.match(r'^([a-zA-Z0-9_-]+)\s*[-–—]\s*(.+)$', line)
        if match:
            skills.append({
                "slug": match.group(1).strip(),
                "name": match.group(1).strip(),
                "description": match.group(2).strip(),
            })
        # Essayer le format "  slug  description"
        elif re.match(r'^[a-zA-Z0-9_-]+\s+\S', line):
            parts = line.split(None, 1)
            if len(parts) == 2:
                skills.append({
                    "slug": parts[0],
                    "name": parts[0],
                    "description": parts[1],
                })
    return skills


# ── Fonctions publiques ───────────────────────────────────────────────────────

async def clawhub_search(query: str, limit: int = 20) -> ClawHubResult:
    """
    Recherche des skills sur le registre ClawHub.

    Args:
        query: Terme de recherche
        limit: Nombre max de resultats
    """
    stdout, stderr, rc = await _run_openclaw_skills(
        ["search", query, "--json"] if query else ["list", "--json"],
        timeout=30,
    )

    if rc != 0 and not stdout:
        # Fallback sans --json
        stdout2, stderr2, rc2 = await _run_openclaw_skills(
            ["search", query] if query else ["list"],
            timeout=30,
        )
        if stdout2:
            skills = _parse_text_skills(stdout2)
            return ClawHubResult(
                success=len(skills) > 0,
                data=skills[:limit],
                raw_output=stdout2,
            )
        return ClawHubResult(
            success=False,
            error=stderr or stderr2 or f"Erreur CLI (code {rc})",
            raw_output=stdout or stdout2,
        )

    # Parser le JSON
    parsed = _parse_json_output(stdout)
    if parsed and isinstance(parsed, list):
        return ClawHubResult(success=True, data=parsed[:limit], raw_output=stdout)
    elif parsed and isinstance(parsed, dict):
        items = parsed.get("skills", parsed.get("results", parsed.get("data", [])))
        if isinstance(items, list):
            return ClawHubResult(success=True, data=items[:limit], raw_output=stdout)
        return ClawHubResult(success=True, data=parsed, raw_output=stdout)

    # Fallback : parser le texte
    skills = _parse_text_skills(stdout)
    return ClawHubResult(
        success=len(skills) > 0 or rc == 0,
        data=skills[:limit] if skills else None,
        raw_output=stdout,
        error="" if skills or rc == 0 else "Aucun resultat",
    )


async def clawhub_install(slug: str) -> ClawHubResult:
    """
    Installe une skill depuis le registre ClawHub.

    Args:
        slug: Identifiant de la skill (ex: "web-scraper", "discord-bot")
    """
    # Validation du slug
    if not slug or not re.match(r'^[a-zA-Z0-9_-]+$', slug):
        return ClawHubResult(success=False, error=f"Slug invalide: {slug}")

    stdout, stderr, rc = await _run_openclaw_skills(
        ["install", slug],
        timeout=60,
    )

    if rc == 0:
        logger.info(f"Skill installee: {slug}")
        # Validate the installed skill
        info_result = await clawhub_skill_info(slug)
        skill_data = {"slug": slug, "action": "installed"}
        if info_result.success and isinstance(info_result.data, dict):
            skill_data["name"] = info_result.data.get("name", slug)
            skill_data["description"] = info_result.data.get("description", "")
        return ClawHubResult(
            success=True,
            data=skill_data,
            raw_output=stdout,
        )

    return ClawHubResult(
        success=False,
        error=stderr or f"Echec installation (code {rc})",
        raw_output=stdout,
    )


async def clawhub_list_installed() -> ClawHubResult:
    """Liste les skills installees localement."""

    # Methode 1 : via CLI
    stdout, stderr, rc = await _run_openclaw_skills(["list", "--json"], timeout=15)

    if rc == 0 and stdout:
        parsed = _parse_json_output(stdout)
        if parsed:
            return ClawHubResult(success=True, data=parsed, raw_output=stdout)

    # Methode 2 : via CLI sans --json
    stdout2, stderr2, rc2 = await _run_openclaw_skills(["list"], timeout=15)
    if stdout2:
        skills = _parse_text_skills(stdout2)
        if skills:
            return ClawHubResult(success=True, data=skills, raw_output=stdout2)

    # Methode 3 : scanner le dossier skills directement
    installed = _scan_local_skills()
    if installed:
        return ClawHubResult(success=True, data=installed)

    return ClawHubResult(
        success=True,
        data=[],
        error="" if rc == 0 or rc2 == 0 else (stderr or stderr2 or ""),
    )


async def clawhub_skill_info(slug: str) -> ClawHubResult:
    """Recupere les informations detaillees d'une skill."""
    if not slug:
        return ClawHubResult(success=False, error="Slug manquant")

    stdout, stderr, rc = await _run_openclaw_skills(["info", slug], timeout=15)

    if rc == 0 and stdout:
        parsed = _parse_json_output(stdout)
        if parsed:
            return ClawHubResult(success=True, data=parsed, raw_output=stdout)
        # Retourner le texte brut
        return ClawHubResult(success=True, data={"slug": slug, "info": stdout}, raw_output=stdout)

    # Essayer de lire le SKILL.md local (tous les chemins possibles)
    local_info = _read_local_skill(slug)
    if local_info:
        return ClawHubResult(success=True, data=local_info)

    # Chercher dans les skills bundled avec OpenClaw
    for base_dir in [
        os.path.join(os.path.expanduser("~"), ".agents", "skills"),
        os.path.join(
            os.path.expanduser("~"), "AppData", "Roaming", "npm",
            "node_modules", "openclaw", "skills",
        ),
    ]:
        skill_dir = os.path.join(base_dir, slug)
        if os.path.isdir(skill_dir):
            local_info = _read_local_skill(slug, skill_dir)
            if local_info:
                return ClawHubResult(success=True, data=local_info)

    return ClawHubResult(
        success=False,
        error=stderr or f"Skill '{slug}' introuvable",
        raw_output=stdout,
    )


async def clawhub_check() -> ClawHubResult:
    """Verifie quelles skills sont pretes vs manquent des prerequis."""
    stdout, stderr, rc = await _run_openclaw_skills(["check"], timeout=15)

    if rc == 0:
        return ClawHubResult(success=True, data={"status": stdout}, raw_output=stdout)

    return ClawHubResult(
        success=False,
        error=stderr or f"Erreur check (code {rc})",
        raw_output=stdout,
    )


async def clawhub_uninstall(slug: str) -> ClawHubResult:
    """Desinstalle une skill."""
    if not slug or not re.match(r'^[a-zA-Z0-9_-]+$', slug):
        return ClawHubResult(success=False, error=f"Slug invalide: {slug}")

    # Tenter via CLI
    stdout, stderr, rc = await _run_openclaw_skills(["uninstall", slug], timeout=30)
    if rc == 0:
        logger.info(f"Skill desinstallee: {slug}")
        return ClawHubResult(success=True, data={"slug": slug, "action": "uninstalled"}, raw_output=stdout)

    # Fallback : supprimer le dossier directement
    skill_dir = os.path.join(SKILLS_DIR, slug)
    if os.path.isdir(skill_dir):
        try:
            shutil.rmtree(skill_dir)
            logger.info(f"Skill supprimee manuellement: {slug}")
            return ClawHubResult(success=True, data={"slug": slug, "action": "removed_manually"})
        except Exception as e:
            return ClawHubResult(success=False, error=f"Erreur suppression: {e}")

    return ClawHubResult(
        success=False,
        error=stderr or f"Skill '{slug}' non trouvee",
        raw_output=stdout,
    )


# ── Helpers locaux ────────────────────────────────────────────────────────────

def _scan_local_skills() -> list[dict]:
    """Scanne le dossier ~/.openclaw/skills/ pour les skills installees."""
    skills = []

    # Dossier principal
    for base_dir in [
        SKILLS_DIR,
        os.path.join(os.path.expanduser("~"), ".agents", "skills"),
    ]:
        if not os.path.isdir(base_dir):
            continue
        for entry in os.listdir(base_dir):
            skill_dir = os.path.join(base_dir, entry)
            if os.path.isdir(skill_dir):
                info = _read_local_skill(entry, skill_dir)
                if info:
                    skills.append(info)

    # Skills bundled avec OpenClaw
    npm_skills = os.path.join(
        os.path.expanduser("~"), "AppData", "Roaming", "npm",
        "node_modules", "openclaw", "skills",
    )
    if os.path.isdir(npm_skills):
        for entry in os.listdir(npm_skills):
            skill_dir = os.path.join(npm_skills, entry)
            if os.path.isdir(skill_dir):
                info = _read_local_skill(entry, skill_dir)
                if info:
                    info["bundled"] = True
                    skills.append(info)

    return skills


def _read_local_skill(slug: str, skill_dir: str | None = None) -> dict | None:
    """Lit le SKILL.md d'une skill locale et extrait les metadonnees."""
    if skill_dir is None:
        skill_dir = os.path.join(SKILLS_DIR, slug)

    skill_md = os.path.join(skill_dir, "SKILL.md")
    if not os.path.exists(skill_md):
        # Essayer README.md comme fallback
        skill_md = os.path.join(skill_dir, "README.md")
        if not os.path.exists(skill_md):
            return None

    try:
        content = open(skill_md, "r", encoding="utf-8", errors="replace").read(20000)
    except Exception:
        return None

    info: dict = {
        "slug": slug,
        "name": slug,
        "installed": True,
        "path": skill_dir,
        # Raw SKILL.md / README.md content (truncated 20k chars max) — pour le rendu UI.
        "skill_md_content": content,
    }

    # Parser le frontmatter YAML
    fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if fm_match:
        fm = fm_match.group(1)
        for line in fm.splitlines():
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip().lower()
                val = val.strip().strip("\"'")
                if key == "name":
                    info["name"] = val
                elif key == "description":
                    info["description"] = val
                elif key == "version":
                    info["version"] = val
                elif key == "author":
                    info["author"] = val
                elif key == "tags":
                    info["tags"] = [t.strip() for t in val.split(",")]

    # Si pas de description dans le frontmatter, prendre la premiere ligne apres le titre
    if "description" not in info:
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("---") and len(line) > 10:
                info["description"] = line[:200]
                break

    return info
