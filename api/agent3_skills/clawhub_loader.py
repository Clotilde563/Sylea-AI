"""
ClawHub Skill Loader — Phase 4 Part A.

Charge dynamiquement les skills ClawHub (installees localement + bundled avec
OpenClaw) et les transforme en Anthropic tool schemas utilisables par la
boucle agentique d'Agent 3.

Architecture :
  [Disk: ~/.openclaw/skills/<slug>/SKILL.md]
  [Disk: ~/AppData/Roaming/npm/node_modules/openclaw/skills/<slug>/SKILL.md]
        |
        | scan + parse frontmatter YAML + body markdown
        v
  [ClawHubSkillMeta dataclass]
        |
        | build_tool_schema()
        v
  [Anthropic Tool Definition {name, description, input_schema}]
        |
        | load_all_tool_schemas() fusionne avec les tools natifs
        v
  [AgenticLoop tools=... ] -> LLM choisit et invoke

Chaque skill devient un tool nomme `skill_<slug>` avec un seul parametre
`instruction` en langage naturel. Le dispatcher (Part C/D) lit le SKILL.md
complet pour executer l'action reellement decrite.

Cache : scan + parse mis en cache avec invalidation par mtime sur les dossiers
racines. Force-refresh possible via `invalidate_cache()`.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import yaml  # type: ignore
    _HAS_YAML = True
except ImportError:  # pragma: no cover - pyyaml est dans requirements
    _HAS_YAML = False

logger = logging.getLogger("sylea.agent3.clawhub_loader")


# ─────────────────────────────────────────────────────────────────────────────
# Chemins de scan
# ─────────────────────────────────────────────────────────────────────────────

# Legacy path (pre-Phase 4.2) : tous les skills installes ici, partages entre users.
# Garde pour migration / fallback backward-compat.
LEGACY_USER_SKILLS_DIR = Path(os.path.expanduser("~/.openclaw/skills")).resolve()


def _sylea_users_root() -> Path:
    """Racine des donnees utilisateur Sylea. Overridable via SYLEA_USER_SKILLS_ROOT
    pour les tests. Par defaut : `~/.sylea/users/`.
    """
    override = os.environ.get("SYLEA_USER_SKILLS_ROOT", "").strip()
    if override:
        return Path(os.path.expanduser(override)).resolve()
    return Path(os.path.expanduser("~/.sylea/users")).resolve()


def _sanitize_auth_user_id(auth_user_id: Optional[str]) -> Optional[str]:
    """Normalise un auth_user_id pour usage en chemin filesystem.

    Returns None si invalid (None, vide, caracteres interdits). L'appelant doit
    traiter None comme "pas d'isolation user" -> fallback legacy.
    """
    if not auth_user_id:
        return None
    s = str(auth_user_id).strip()
    if not s:
        return None
    # Garde alnum + - + _ + . (couvre UUID, nanoid, sub OAuth, emails hashes)
    safe = re.sub(r"[^a-zA-Z0-9_.\-]", "_", s)
    # Evite path traversal
    safe = safe.replace("..", "_")
    if not safe or safe in (".", "_"):
        return None
    return safe[:128]  # hard cap pour eviter chemins demesures


_LEGACY_FALLBACK_ENABLED = os.environ.get(
    "SYLEA_ALLOW_LEGACY_SKILLS_FALLBACK", "1",
).strip().lower() in ("1", "true", "yes")
_legacy_fallback_warned = False


def get_user_skills_dir(auth_user_id: Optional[str] = None) -> Path:
    """Retourne le dossier des skills auto-installees pour un user donne.

    - Si `auth_user_id` est fourni (et valide) -> `~/.sylea/users/{id}/.openclaw/skills/`.
    - Sinon et fallback legacy active -> `USER_SKILLS_DIR` (module-level, partage, DEPRECIE).
    - Sinon (fallback desactive) -> dossier vide non persiste (bloque la fuite inter-users).

    Le sous-chemin `.openclaw/skills` est conserve pour que l'override `HOME`
    passe au clawhub CLI matche exactement : le binary installe dans
    `$HOME/.openclaw/skills/<slug>/` sans config additionnelle.

    Opt-out du legacy partage : exporter `SYLEA_ALLOW_LEGACY_SKILLS_FALLBACK=0`.

    Note : on lit `USER_SKILLS_DIR` via le module namespace pour que les
    tests (et les deploiements custom) puissent override ce dossier
    via `monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", ...)`.
    """
    safe_id = _sanitize_auth_user_id(auth_user_id)
    if safe_id is None:
        global _legacy_fallback_warned
        if not _legacy_fallback_warned:
            logger.warning(
                "ClawHub skills accessed without auth_user_id -> fallback legacy partage. "
                "Desactivable via SYLEA_ALLOW_LEGACY_SKILLS_FALLBACK=0."
            )
            _legacy_fallback_warned = True
        if not _LEGACY_FALLBACK_ENABLED:
            # Dossier sentinelle qui n'existe jamais -> aucune skill exposee.
            return (_sylea_users_root() / "_no_legacy_fallback").resolve()
        # Resolution via globals() pour supporter le monkeypatch tests.
        return globals().get("USER_SKILLS_DIR", LEGACY_USER_SKILLS_DIR)
    return (_sylea_users_root() / safe_id / ".openclaw" / "skills").resolve()


def get_user_home_override(auth_user_id: Optional[str] = None) -> Optional[Path]:
    """Retourne le repertoire a passer comme HOME/USERPROFILE au clawhub CLI.

    - Si auth_user_id valide -> `~/.sylea/users/{id}/` (parent de .openclaw).
    - Sinon -> None (pas d'override -> clawhub ecrit dans le HOME reel, legacy).
    """
    safe_id = _sanitize_auth_user_id(auth_user_id)
    if safe_id is None:
        return None
    return (_sylea_users_root() / safe_id).resolve()


def ensure_user_skills_dir(auth_user_id: Optional[str] = None) -> Path:
    """Cree le dossier des skills user (et ses parents) si absent, retourne le path."""
    p = get_user_skills_dir(auth_user_id)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.debug(f"ensure_user_skills_dir({auth_user_id}) failed: {e}")
    return p


# Alias backward-compat : code existant qui importait USER_SKILLS_DIR continue
# de marcher (mais pointe sur le legacy path partage).
USER_SKILLS_DIR = LEGACY_USER_SKILLS_DIR


# Skills bundled avec la CLI OpenClaw (npm global install).
# Windows : %APPDATA%/npm/node_modules/openclaw/skills
# Unix    : /usr/local/lib/node_modules/openclaw/skills ou /opt/homebrew/...
def _candidate_bundled_dirs() -> list[Path]:
    candidates = []
    # Windows
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "npm" / "node_modules" / "openclaw" / "skills")
    # Fallback expansion home
    candidates.append(
        Path(os.path.expanduser("~/AppData/Roaming/npm/node_modules/openclaw/skills"))
    )
    # macOS / Linux usual locations
    candidates.extend([
        Path("/usr/local/lib/node_modules/openclaw/skills"),
        Path("/opt/homebrew/lib/node_modules/openclaw/skills"),
        Path(os.path.expanduser("~/.nvm/versions")) / "node",  # scanned below
    ])
    # .agents/skills (older convention)
    candidates.append(Path(os.path.expanduser("~/.agents/skills")))
    # Dedup en resolvant les symlinks / chemins equivalents
    seen: set[str] = set()
    unique: list[Path] = []
    for c in candidates:
        if not (c.exists() and c.is_dir()):
            continue
        try:
            key = str(c.resolve()).lower()
        except OSError:
            key = str(c).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(c)
    return unique


BUNDLED_SKILLS_DIRS: list[Path] = _candidate_bundled_dirs()


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ClawHubSkillMeta:
    """Metadonnees d'une skill ClawHub extraites du SKILL.md."""

    slug: str                         # Nom du dossier (identifiant unique)
    name: str                         # Nom lisible depuis frontmatter.name
    description: str                  # Description courte depuis frontmatter
    path: Path                        # Dossier contenant SKILL.md
    is_bundled: bool = False          # True si skill bundled avec OpenClaw
    version: str = ""                 # frontmatter.version (souvent vide)
    author: str = ""                  # frontmatter.author (souvent vide)
    homepage: str = ""                # frontmatter.homepage
    emoji: str = ""                   # metadata.openclaw.emoji
    tags: list[str] = field(default_factory=list)
    required_bins: list[str] = field(default_factory=list)  # metadata.openclaw.requires.bins
    required_env: list[str] = field(default_factory=list)    # required_env OR metadata.openclaw.requires.env
    body_preview: str = ""            # 300 premiers chars du markdown (sans frontmatter)
    mtime: float = 0.0                # timestamp de derniere modif du SKILL.md

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "path": str(self.path),
            "is_bundled": self.is_bundled,
            "version": self.version,
            "author": self.author,
            "homepage": self.homepage,
            "emoji": self.emoji,
            "tags": self.tags,
            "required_bins": self.required_bins,
            "required_env": self.required_env,
            "body_preview": self.body_preview,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Parsing
# ─────────────────────────────────────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extrait le frontmatter YAML et retourne (meta_dict, body_markdown).

    Retourne ({}, content) si pas de frontmatter detectable.
    """
    m = _FRONTMATTER_RE.match(content)
    if not m:
        return {}, content
    fm_text = m.group(1)
    body = m.group(2)

    if _HAS_YAML:
        try:
            parsed = yaml.safe_load(fm_text)
            if isinstance(parsed, dict):
                return parsed, body
        except yaml.YAMLError as e:
            logger.debug(f"YAML parse failed, falling back to line parser: {e}")

    # Fallback : parseur ligne par ligne (name/description/homepage/version/author)
    meta: dict[str, Any] = {}
    for line in fm_text.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            key = key.strip().lower()
            val = val.strip().strip("\"'")
            if val:
                meta[key] = val
    return meta, body


def _extract_openclaw_metadata(frontmatter: dict[str, Any]) -> dict[str, Any]:
    """Navigue frontmatter.metadata.openclaw qui contient emoji, requires.bins, etc."""
    if not isinstance(frontmatter.get("metadata"), dict):
        return {}
    meta = frontmatter["metadata"]
    oc = meta.get("openclaw") if isinstance(meta, dict) else None
    if not isinstance(oc, dict):
        return {}
    return oc


def parse_skill_md(path: Path) -> Optional[ClawHubSkillMeta]:
    """Lit un fichier SKILL.md et retourne un ClawHubSkillMeta ou None si invalide.

    Args:
        path: Chemin vers SKILL.md (pas le dossier parent).
    """
    if not path.exists() or not path.is_file():
        return None

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        logger.warning(f"Cannot read {path}: {e}")
        return None

    fm, body = _parse_frontmatter(content)

    skill_dir = path.parent
    slug = skill_dir.name

    name = (fm.get("name") or slug) if isinstance(fm.get("name"), str) else slug
    description = fm.get("description") or ""
    if isinstance(description, list):
        description = " ".join(str(d) for d in description)
    elif not isinstance(description, str):
        description = str(description or "")

    # Nettoyage description : parfois multi-lignes avec \n, on reformate
    description = " ".join(description.split()).strip()

    # Fallback description : premier paragraphe du body apres le titre
    if not description and body:
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("```"):
                description = line[:300]
                break

    oc_meta = _extract_openclaw_metadata(fm)
    emoji = str(oc_meta.get("emoji", "")) if isinstance(oc_meta, dict) else ""

    required_bins: list[str] = []
    required_env: list[str] = []
    requires = oc_meta.get("requires") if isinstance(oc_meta, dict) else None
    if isinstance(requires, dict):
        bins = requires.get("bins")
        if isinstance(bins, list):
            required_bins = [str(b) for b in bins]
        elif isinstance(bins, str):
            required_bins = [bins]
        # env vars requises par le skill (credentials a injecter au runtime)
        env_list = requires.get("env") or requires.get("credentials")
        if isinstance(env_list, list):
            required_env = [str(e) for e in env_list if isinstance(e, str) and e.strip()]
        elif isinstance(env_list, str):
            required_env = [env_list]

    # Support format alternatif : top-level `required_env` dans le frontmatter.
    top_env = fm.get("required_env") or fm.get("credentials")
    if isinstance(top_env, list):
        for e in top_env:
            if isinstance(e, str) and e.strip() and e not in required_env:
                required_env.append(e)
    elif isinstance(top_env, str) and top_env not in required_env:
        required_env.append(top_env)

    tags: list[str] = []
    fm_tags = fm.get("tags")
    if isinstance(fm_tags, list):
        tags = [str(t) for t in fm_tags]
    elif isinstance(fm_tags, str):
        tags = [t.strip() for t in fm_tags.split(",") if t.strip()]

    homepage = str(fm.get("homepage") or "")
    version = str(fm.get("version") or "")
    author = str(fm.get("author") or "")

    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0

    # Preview du body (300 chars) — utile pour la confirmation UI
    body_preview = " ".join(body.split())[:300] if body else ""

    return ClawHubSkillMeta(
        slug=slug,
        name=str(name),
        description=description,
        path=skill_dir,
        version=version,
        author=author,
        homepage=homepage,
        emoji=emoji,
        tags=tags,
        required_bins=required_bins,
        required_env=required_env,
        body_preview=body_preview,
        mtime=mtime,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Scan
# ─────────────────────────────────────────────────────────────────────────────

def _iter_skill_md_in(base_dir: Path) -> list[Path]:
    """Retourne tous les chemins SKILL.md directement sous base_dir/*/SKILL.md."""
    if not base_dir.exists() or not base_dir.is_dir():
        return []
    results: list[Path] = []
    try:
        for entry in base_dir.iterdir():
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if skill_md.exists():
                results.append(skill_md)
    except OSError as e:
        logger.debug(f"Cannot iter {base_dir}: {e}")
    return results


def scan_all_skills(
    *,
    include_bundled: bool = True,
    include_user: bool = True,
    auth_user_id: Optional[str] = None,
) -> list[ClawHubSkillMeta]:
    """Scanne tous les chemins connus et retourne la liste des ClawHubSkillMeta.

    En cas de doublon (meme slug dans user + bundled), la version user prime.

    Args:
        auth_user_id: si fourni, scanne `~/.sylea/users/{id}/.openclaw/skills/`
            pour la section user. Sinon, scanne le dossier legacy
            `~/.openclaw/skills/` (partage).
    """
    seen_slugs: dict[str, ClawHubSkillMeta] = {}

    # 1) Skills utilisateur (prioritaires)
    user_dir = get_user_skills_dir(auth_user_id)
    if include_user and user_dir.exists():
        for skill_md in _iter_skill_md_in(user_dir):
            meta = parse_skill_md(skill_md)
            if meta is not None:
                meta.is_bundled = False
                seen_slugs[meta.slug] = meta

    # 1bis) Phase 14M : ClawHub CLI v2+ installe dans ~/.openclaw/workspace/skills/
    # au lieu de ~/.openclaw/skills/. On scanne aussi ce dossier pour rendre
    # les skills auto-installees via clawhub_install() visibles a l'agent.
    if include_user:
        try:
            workspace_user_dir = Path(os.path.expanduser("~/.openclaw/workspace/skills")).resolve()
            if workspace_user_dir.exists() and workspace_user_dir != user_dir:
                for skill_md in _iter_skill_md_in(workspace_user_dir):
                    meta = parse_skill_md(skill_md)
                    if meta is None:
                        continue
                    if meta.slug in seen_slugs:
                        continue  # priorite au repertoire principal
                    meta.is_bundled = False
                    seen_slugs[meta.slug] = meta
        except Exception as _ws_err:
            logger.debug(f"workspace/skills scan failed: {_ws_err}")

    # 2) Skills bundled (ne remplacent pas les user skills)
    if include_bundled:
        for base in BUNDLED_SKILLS_DIRS:
            for skill_md in _iter_skill_md_in(base):
                meta = parse_skill_md(skill_md)
                if meta is None:
                    continue
                if meta.slug in seen_slugs:
                    continue
                meta.is_bundled = True
                seen_slugs[meta.slug] = meta

    result = list(seen_slugs.values())
    result.sort(key=lambda m: m.slug)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Tool schema generation
# ─────────────────────────────────────────────────────────────────────────────

_TOOL_NAME_PREFIX = "skill_"
_SLUG_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_]")
_MAX_TOOL_NAME_LEN = 64
_MAX_DESCRIPTION_LEN = 1024


def tool_name_for_slug(slug: str) -> str:
    """Convertit un slug ClawHub (ex: 'apple-notes') en nom de tool Anthropic
    (ex: 'skill_apple_notes'). Contraintes Anthropic : [a-zA-Z0-9_-], max 64.
    """
    base = slug.replace("-", "_").replace(".", "_")
    base = _SLUG_SANITIZE_RE.sub("_", base)
    name = f"{_TOOL_NAME_PREFIX}{base}"
    return name[:_MAX_TOOL_NAME_LEN]


def slug_from_tool_name(tool_name: str) -> Optional[str]:
    """Inverse de tool_name_for_slug — retourne le slug si `tool_name` est
    un outil skill, None sinon. Note: les tirets d'origine ne sont pas
    recuperables. Un dispatcher doit utiliser le slug canonical du registre.
    """
    if not tool_name.startswith(_TOOL_NAME_PREFIX):
        return None
    return tool_name[len(_TOOL_NAME_PREFIX):]


def build_tool_schema(meta: ClawHubSkillMeta) -> dict[str, Any]:
    """Transforme un ClawHubSkillMeta en Anthropic tool definition.

    Le schema expose un seul parametre `instruction` (string) : le LLM passe
    l'intention en langage naturel, et le dispatcher (Part C/D) utilise le
    SKILL.md complet pour executer l'action reellement decrite.
    """
    emoji_prefix = f"{meta.emoji} " if meta.emoji else ""
    tag_suffix = ""
    if meta.is_bundled:
        tag_suffix = " [bundled]"
    if meta.required_bins:
        tag_suffix += f" [requires: {', '.join(meta.required_bins)}]"

    description = (
        f"{emoji_prefix}ClawHub skill '{meta.slug}'. {meta.description}{tag_suffix}"
    ).strip()
    description = description[:_MAX_DESCRIPTION_LEN]

    return {
        "name": tool_name_for_slug(meta.slug),
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": (
                        "Instruction en langage naturel decrivant ce que tu veux "
                        f"faire avec la skill '{meta.slug}'. Le dispatcher lira le "
                        "SKILL.md complet pour executer l'action appropriee."
                    ),
                },
                "parameters": {
                    "type": "object",
                    "description": (
                        "Parametres structures optionnels si la skill en exige "
                        "(ex: location pour weather, query pour search). Sinon "
                        "laisse vide et tout passe via `instruction`."
                    ),
                    "additionalProperties": True,
                },
            },
            "required": ["instruction"],
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Cache avec invalidation par mtime
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _CacheEntry:
    metas: list[ClawHubSkillMeta]
    schemas: list[dict[str, Any]]
    dir_mtimes: dict[str, float]
    ttl_until: float


class ClawHubSkillCache:
    """Cache thread-safe des skills scannees, invalide sur changement de mtime.

    Keyed par auth_user_id : chaque user a son propre cache entry, invalidable
    independamment. L'entry `None` correspond au legacy path partage.
    """

    def __init__(self, ttl_seconds: float = 60.0):
        self._lock = threading.RLock()
        # Map auth_user_id (ou None pour legacy) -> _CacheEntry
        self._entries: dict[Optional[str], _CacheEntry] = {}
        self._ttl = ttl_seconds

    def _snapshot_dir_mtimes(self, auth_user_id: Optional[str]) -> dict[str, float]:
        """Prend un snapshot des mtimes des dossiers racines pour detecter
        qu'un skill a ete installe/supprime/modifie.
        """
        mtimes: dict[str, float] = {}
        dirs_to_watch = [get_user_skills_dir(auth_user_id), *BUNDLED_SKILLS_DIRS]
        for d in dirs_to_watch:
            try:
                if d.exists():
                    mtimes[str(d)] = d.stat().st_mtime
            except OSError:
                continue
        return mtimes

    def _is_stale(self, auth_user_id: Optional[str]) -> bool:
        """True si le cache du user doit etre rafraichi."""
        key = _sanitize_auth_user_id(auth_user_id)
        entry = self._entries.get(key)
        if entry is None:
            return True
        now = time.time()
        if now >= entry.ttl_until:
            # TTL expire : verifier si les dossiers ont change
            current = self._snapshot_dir_mtimes(auth_user_id)
            if current != entry.dir_mtimes:
                return True
            # Pas de changement -> prolonger le cache
            entry.ttl_until = now + self._ttl
            return False
        return False

    def get_metas(
        self,
        *,
        include_bundled: bool = True,
        include_user: bool = True,
        force_refresh: bool = False,
        auth_user_id: Optional[str] = None,
    ) -> list[ClawHubSkillMeta]:
        with self._lock:
            key = _sanitize_auth_user_id(auth_user_id)
            entry = self._entries.get(key)
            if force_refresh or self._is_stale(auth_user_id) or entry is None:
                metas = scan_all_skills(
                    include_bundled=include_bundled,
                    include_user=include_user,
                    auth_user_id=auth_user_id,
                )
                schemas = [build_tool_schema(m) for m in metas]
                entry = _CacheEntry(
                    metas=metas,
                    schemas=schemas,
                    dir_mtimes=self._snapshot_dir_mtimes(auth_user_id),
                    ttl_until=time.time() + self._ttl,
                )
                self._entries[key] = entry
            # Filtres post-cache si demandes differents du scan initial
            result = entry.metas
            if not include_user:
                result = [m for m in result if m.is_bundled]
            if not include_bundled:
                result = [m for m in result if not m.is_bundled]
            return list(result)

    def get_schemas(
        self,
        *,
        enabled_slugs: Optional[set[str]] = None,
        include_bundled: bool = True,
        include_user: bool = True,
        force_refresh: bool = False,
        auth_user_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Retourne la liste des tool schemas. Si `enabled_slugs` est fourni,
        filtre pour ne garder que ces slugs.
        """
        metas = self.get_metas(
            include_bundled=include_bundled,
            include_user=include_user,
            force_refresh=force_refresh,
            auth_user_id=auth_user_id,
        )
        if enabled_slugs is not None:
            metas = [m for m in metas if m.slug in enabled_slugs]
        return [build_tool_schema(m) for m in metas]

    def get_meta(
        self, slug: str, *, auth_user_id: Optional[str] = None,
    ) -> Optional[ClawHubSkillMeta]:
        """Retourne le meta d'un slug (ou None) pour le user donne."""
        for m in self.get_metas(auth_user_id=auth_user_id):
            if m.slug == slug:
                return m
        return None

    def invalidate(self, *, auth_user_id: Optional[str] = None) -> None:
        """Force le rescan au prochain get() pour ce user.

        Si auth_user_id est explicitement None, invalide le cache legacy.
        Pour invalider TOUS les caches (ex: test reset), utilise invalidate_all().
        """
        with self._lock:
            key = _sanitize_auth_user_id(auth_user_id)
            self._entries.pop(key, None)

    def invalidate_all(self) -> None:
        """Invalide le cache pour tous les users (reset complet)."""
        with self._lock:
            self._entries.clear()


# Singleton global (peut etre reinitialise en test via _reset_cache())
_cache: Optional[ClawHubSkillCache] = None
_cache_lock = threading.Lock()


def get_cache() -> ClawHubSkillCache:
    """Retourne le singleton cache (lazy init)."""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                _cache = ClawHubSkillCache()
    return _cache


def invalidate_cache(*, auth_user_id: Optional[str] = None) -> None:
    """Force le rescan au prochain appel pour ce user.

    A appeler apres install/uninstall. Si auth_user_id est None, invalide
    uniquement le cache legacy (pas les caches per-user).
    """
    get_cache().invalidate(auth_user_id=auth_user_id)


def invalidate_all_caches() -> None:
    """Invalide le cache pour tous les users (reset)."""
    get_cache().invalidate_all()


def _reset_cache() -> None:
    """Utilitaire test : reset complet du singleton."""
    global _cache
    with _cache_lock:
        _cache = None


# ─────────────────────────────────────────────────────────────────────────────
# API publique de haut niveau
# ─────────────────────────────────────────────────────────────────────────────

def load_all_skills(
    *,
    include_bundled: bool = True,
    include_user: bool = True,
    force_refresh: bool = False,
    auth_user_id: Optional[str] = None,
) -> list[ClawHubSkillMeta]:
    """Retourne tous les ClawHubSkillMeta disponibles (cache)."""
    return get_cache().get_metas(
        include_bundled=include_bundled,
        include_user=include_user,
        force_refresh=force_refresh,
        auth_user_id=auth_user_id,
    )


def load_all_tool_schemas(
    *,
    enabled_slugs: Optional[set[str]] = None,
    include_bundled: bool = True,
    include_user: bool = True,
    force_refresh: bool = False,
    auth_user_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Retourne la liste des tool schemas Anthropic pour toutes les skills.

    Args:
        enabled_slugs: si fourni, filtre pour ne garder que ces slugs.
        include_bundled: inclure les skills bundled avec OpenClaw (~54).
        include_user: inclure les skills installees pour le user courant.
        force_refresh: bypass le cache.
        auth_user_id: isoler les skills user au dossier du user donne.
    """
    return get_cache().get_schemas(
        enabled_slugs=enabled_slugs,
        include_bundled=include_bundled,
        include_user=include_user,
        force_refresh=force_refresh,
        auth_user_id=auth_user_id,
    )


def get_skill_body(slug: str, *, auth_user_id: Optional[str] = None) -> Optional[str]:
    """Retourne le contenu markdown complet (sans frontmatter) d'une skill.

    Utile pour le dispatcher (Part C/D) qui doit donner au LLM les commandes
    shell / API calls decrites dans le SKILL.md pour executer la skill.
    """
    meta = get_cache().get_meta(slug, auth_user_id=auth_user_id)
    if meta is None:
        return None
    skill_md = meta.path / "SKILL.md"
    if not skill_md.exists():
        return None
    try:
        content = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    _, body = _parse_frontmatter(content)
    return body


def get_skill_full_content(slug: str, *, auth_user_id: Optional[str] = None) -> Optional[str]:
    """Retourne le SKILL.md complet (frontmatter + body)."""
    meta = get_cache().get_meta(slug, auth_user_id=auth_user_id)
    if meta is None:
        return None
    skill_md = meta.path / "SKILL.md"
    if not skill_md.exists():
        return None
    try:
        return skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


__all__ = [
    "ClawHubSkillMeta",
    "ClawHubSkillCache",
    "USER_SKILLS_DIR",
    "LEGACY_USER_SKILLS_DIR",
    "BUNDLED_SKILLS_DIRS",
    "get_user_skills_dir",
    "get_user_home_override",
    "ensure_user_skills_dir",
    "parse_skill_md",
    "scan_all_skills",
    "tool_name_for_slug",
    "slug_from_tool_name",
    "build_tool_schema",
    "get_cache",
    "invalidate_cache",
    "invalidate_all_caches",
    "load_all_skills",
    "load_all_tool_schemas",
    "get_skill_body",
    "get_skill_full_content",
]
