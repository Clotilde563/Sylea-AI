"""Tests Phase 4 Part A+B : ClawHub loader dynamique + fusion avec build_tool_schemas."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from api.agent3_skills import clawhub_loader
from api.agent3_skills.clawhub_loader import (
    ClawHubSkillMeta,
    _parse_frontmatter,
    build_tool_schema,
    parse_skill_md,
    scan_all_skills,
    slug_from_tool_name,
    tool_name_for_slug,
    load_all_tool_schemas,
    get_cache,
    invalidate_cache,
    _reset_cache,
    get_skill_body,
    get_skill_full_content,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_SKILL_MD_WITH_YAML = """---
name: sample-skill
description: "A test skill for unit tests. Use when: running pytest. NOT for: production."
homepage: https://example.com
metadata:
  {
    "openclaw":
      {
        "emoji": "🧪",
        "requires": { "bins": ["pytest", "python"] }
      }
  }
---

# Sample Skill

This is the body of the skill.

## How to use

```bash
pytest tests/
```
"""

SAMPLE_SKILL_MD_SIMPLE = """---
name: simple-skill
description: Simple skill with minimal frontmatter.
---

# Simple Skill

Just does one thing.
"""

SKILL_MD_NO_FRONTMATTER = """# Skill Without Frontmatter

This is just a markdown file.
"""

SKILL_MD_MALFORMED = """---
description: "Unclosed frontmatter
---
Body.
"""


@pytest.fixture
def tmp_skill_dir(tmp_path: Path) -> Path:
    """Cree un dossier skill temporaire avec SKILL.md valide."""
    sdir = tmp_path / "sample-skill"
    sdir.mkdir()
    (sdir / "SKILL.md").write_text(SAMPLE_SKILL_MD_WITH_YAML, encoding="utf-8")
    return sdir


@pytest.fixture
def tmp_skills_root(tmp_path: Path) -> Path:
    """Cree un dossier racine contenant plusieurs skills."""
    root = tmp_path / "skills"
    root.mkdir()
    # Skill 1 avec frontmatter YAML complet
    (root / "skill-one").mkdir()
    (root / "skill-one" / "SKILL.md").write_text(SAMPLE_SKILL_MD_WITH_YAML, encoding="utf-8")
    # Skill 2 avec frontmatter minimal
    (root / "skill-two").mkdir()
    (root / "skill-two" / "SKILL.md").write_text(SAMPLE_SKILL_MD_SIMPLE, encoding="utf-8")
    # Skill 3 sans SKILL.md (doit etre ignore)
    (root / "empty-skill").mkdir()
    (root / "empty-skill" / "README.md").write_text("# No SKILL.md here", encoding="utf-8")
    # Skill 4 sans frontmatter
    (root / "no-fm").mkdir()
    (root / "no-fm" / "SKILL.md").write_text(SKILL_MD_NO_FRONTMATTER, encoding="utf-8")
    return root


@pytest.fixture(autouse=True)
def reset_cache_each_test():
    """Assure un cache propre entre chaque test."""
    _reset_cache()
    yield
    _reset_cache()


# ──────────────────────────────────────────────────────────────────────────────
# Tests parsing
# ──────────────────────────────────────────────────────────────────────────────

class TestParseFrontmatter:
    def test_parse_full_yaml_frontmatter(self):
        meta, body = _parse_frontmatter(SAMPLE_SKILL_MD_WITH_YAML)
        assert meta["name"] == "sample-skill"
        assert "test skill" in meta["description"].lower()
        assert meta["homepage"] == "https://example.com"
        assert "Sample Skill" in body

    def test_parse_minimal_frontmatter(self):
        meta, body = _parse_frontmatter(SAMPLE_SKILL_MD_SIMPLE)
        assert meta["name"] == "simple-skill"
        assert "# Simple Skill" in body

    def test_parse_no_frontmatter(self):
        meta, body = _parse_frontmatter(SKILL_MD_NO_FRONTMATTER)
        assert meta == {}
        assert body == SKILL_MD_NO_FRONTMATTER

    def test_parse_malformed_falls_back_gracefully(self):
        meta, body = _parse_frontmatter(SKILL_MD_MALFORMED)
        # Ne doit pas crash — retourne un best effort
        assert isinstance(meta, dict)
        assert isinstance(body, str)


class TestParseSkillMd:
    def test_parse_full_skill(self, tmp_skill_dir):
        meta = parse_skill_md(tmp_skill_dir / "SKILL.md")
        assert meta is not None
        assert meta.slug == "sample-skill"
        assert meta.name == "sample-skill"
        assert "test skill" in meta.description.lower()
        assert meta.emoji == "🧪"
        assert set(meta.required_bins) == {"pytest", "python"}
        assert meta.homepage == "https://example.com"
        assert "body of the skill" in meta.body_preview.lower()
        assert meta.mtime > 0

    def test_parse_nonexistent_returns_none(self, tmp_path):
        assert parse_skill_md(tmp_path / "does-not-exist" / "SKILL.md") is None

    def test_parse_directory_returns_none(self, tmp_path):
        assert parse_skill_md(tmp_path) is None


# ──────────────────────────────────────────────────────────────────────────────
# Tests scan
# ──────────────────────────────────────────────────────────────────────────────

class TestScanAllSkills:
    def test_scan_isolated_root(self, tmp_skills_root, monkeypatch):
        # Rediriger USER et BUNDLED vers notre tmp
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_skills_root)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])

        metas = scan_all_skills()
        slugs = [m.slug for m in metas]
        assert "skill-one" in slugs
        assert "skill-two" in slugs
        # Skill sans SKILL.md ignore
        assert "empty-skill" not in slugs
        # Skill sans frontmatter : parse quand meme (slug = dossier, description fallback)
        assert "no-fm" in slugs

    def test_scan_user_priority_over_bundled(self, tmp_path, monkeypatch):
        user = tmp_path / "user_skills"
        bundled = tmp_path / "bundled_skills"
        user.mkdir()
        bundled.mkdir()
        (user / "shared").mkdir()
        (user / "shared" / "SKILL.md").write_text(
            "---\nname: from-user\ndescription: User version\n---\nUser body", encoding="utf-8",
        )
        (bundled / "shared").mkdir()
        (bundled / "shared" / "SKILL.md").write_text(
            "---\nname: from-bundled\ndescription: Bundled version\n---\nBundled body", encoding="utf-8",
        )
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", user)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [bundled])

        metas = scan_all_skills()
        shared = [m for m in metas if m.slug == "shared"]
        assert len(shared) == 1  # user wins
        assert shared[0].name == "from-user"
        assert shared[0].is_bundled is False

    def test_scan_empty_dirs(self, tmp_path, monkeypatch):
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_path / "nonexistent")
        monkeypatch.setattr(clawhub_loader, "WORKSPACE_USER_SKILLS_DIR", tmp_path / "nonexistent2")
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])
        assert scan_all_skills() == []


# ──────────────────────────────────────────────────────────────────────────────
# Tests tool schema generation
# ──────────────────────────────────────────────────────────────────────────────

class TestToolNameConversion:
    def test_simple_slug(self):
        assert tool_name_for_slug("weather") == "skill_weather"

    def test_hyphenated_slug(self):
        assert tool_name_for_slug("apple-notes") == "skill_apple_notes"

    def test_multi_hyphen(self):
        assert tool_name_for_slug("crypto-price-tracker") == "skill_crypto_price_tracker"

    def test_respects_max_length(self):
        long = "a" * 100
        assert len(tool_name_for_slug(long)) <= 64

    def test_slug_from_tool_name_roundtrip(self):
        assert slug_from_tool_name("skill_foo") == "foo"
        assert slug_from_tool_name("skill_apple_notes") == "apple_notes"
        assert slug_from_tool_name("weather") is None  # pas de prefix


class TestBuildToolSchema:
    def test_schema_has_required_anthropic_fields(self, tmp_skill_dir):
        meta = parse_skill_md(tmp_skill_dir / "SKILL.md")
        schema = build_tool_schema(meta)
        assert schema["name"] == "skill_sample_skill"
        assert "input_schema" in schema
        assert schema["input_schema"]["type"] == "object"
        assert "instruction" in schema["input_schema"]["properties"]
        assert "instruction" in schema["input_schema"]["required"]

    def test_description_includes_emoji_and_tags(self, tmp_skill_dir):
        meta = parse_skill_md(tmp_skill_dir / "SKILL.md")
        schema = build_tool_schema(meta)
        assert "🧪" in schema["description"]
        assert "sample-skill" in schema["description"]
        assert "pytest" in schema["description"]  # required_bins

    def test_description_includes_bundled_marker(self, tmp_skill_dir):
        meta = parse_skill_md(tmp_skill_dir / "SKILL.md")
        meta.is_bundled = True
        schema = build_tool_schema(meta)
        assert "[bundled]" in schema["description"]

    def test_description_truncated_at_1024_chars(self):
        meta = ClawHubSkillMeta(
            slug="x", name="x",
            description="X " * 1000,  # > 1024 chars
            path=Path("/tmp"),
        )
        schema = build_tool_schema(meta)
        assert len(schema["description"]) <= 1024


# ──────────────────────────────────────────────────────────────────────────────
# Tests cache
# ──────────────────────────────────────────────────────────────────────────────

class TestCache:
    def test_cache_reuses_results(self, tmp_skills_root, monkeypatch):
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_skills_root)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])
        cache = get_cache()

        call_count = {"n": 0}
        original = clawhub_loader.scan_all_skills

        def counting_scan(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(clawhub_loader, "scan_all_skills", counting_scan)

        _ = cache.get_metas()
        _ = cache.get_metas()
        _ = cache.get_metas()
        # Seul le premier appel doit avoir declenche scan
        assert call_count["n"] == 1

    def test_force_refresh_bypasses_cache(self, tmp_skills_root, monkeypatch):
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_skills_root)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])
        cache = get_cache()

        call_count = {"n": 0}
        original = clawhub_loader.scan_all_skills

        def counting_scan(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(clawhub_loader, "scan_all_skills", counting_scan)

        _ = cache.get_metas()
        _ = cache.get_metas(force_refresh=True)
        assert call_count["n"] == 2

    def test_invalidate_cache_forces_rescan(self, tmp_skills_root, monkeypatch):
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_skills_root)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])
        cache = get_cache()

        call_count = {"n": 0}
        original = clawhub_loader.scan_all_skills

        def counting_scan(*args, **kwargs):
            call_count["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(clawhub_loader, "scan_all_skills", counting_scan)

        _ = cache.get_metas()
        invalidate_cache()
        _ = cache.get_metas()
        assert call_count["n"] == 2

    def test_get_meta_by_slug(self, tmp_skills_root, monkeypatch):
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_skills_root)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])
        cache = get_cache()

        meta = cache.get_meta("skill-one")
        assert meta is not None
        assert meta.slug == "skill-one"
        assert cache.get_meta("nonexistent") is None


# ──────────────────────────────────────────────────────────────────────────────
# Tests body / full content
# ──────────────────────────────────────────────────────────────────────────────

class TestSkillContent:
    def test_get_skill_body_returns_markdown(self, tmp_skills_root, monkeypatch):
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_skills_root)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])
        body = get_skill_body("skill-one")
        assert body is not None
        assert "Sample Skill" in body
        # Frontmatter doit etre strippe
        assert "---" not in body.splitlines()[0:1]

    def test_get_skill_body_unknown_returns_none(self):
        assert get_skill_body("nonexistent-slug") is None

    def test_get_full_content_includes_frontmatter(self, tmp_skills_root, monkeypatch):
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_skills_root)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])
        full = get_skill_full_content("skill-one")
        assert full is not None
        assert full.startswith("---")
        assert "name: sample-skill" in full


# ──────────────────────────────────────────────────────────────────────────────
# Tests fusion avec build_tool_schemas
# ──────────────────────────────────────────────────────────────────────────────

class TestFusionBuildToolSchemas:
    def test_native_only_by_default(self):
        from api.agent3_native_tools import build_tool_schemas
        tools = build_tool_schemas()
        names = {t["name"] for t in tools}
        assert "search" in names
        assert "memory" in names
        assert not any(n.startswith("skill_") for n in names)
        assert not any(n.startswith("clawhub_") for n in names)

    def test_with_clawhub_skills_adds_tools(self, tmp_skills_root, monkeypatch):
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_skills_root)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])
        invalidate_cache()

        from api.agent3_native_tools import build_tool_schemas
        native = build_tool_schemas()
        with_skills = build_tool_schemas(include_clawhub_skills=True)
        # Tmp root a 3 skills parseables (skill-one, skill-two, no-fm)
        assert len(with_skills) >= len(native) + 2

    def test_enabled_slugs_filter(self, tmp_skills_root, monkeypatch):
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_skills_root)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])
        invalidate_cache()

        from api.agent3_native_tools import build_tool_schemas
        tools = build_tool_schemas(
            include_clawhub_skills=True,
            enabled_clawhub_slugs={"skill-one"},
        )
        skill_names = [t["name"] for t in tools if t["name"].startswith("skill_")]
        assert skill_names == ["skill_skill_one"]

    def test_with_meta_tools(self):
        from api.agent3_native_tools import build_tool_schemas
        with_meta = build_tool_schemas(include_clawhub_meta_tools=True)
        names = {t["name"] for t in with_meta}
        assert "clawhub_search" in names
        assert "clawhub_install" in names
        assert "clawhub_publish" in names

    def test_no_name_collisions(self, tmp_skills_root, monkeypatch):
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_skills_root)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])
        invalidate_cache()

        from api.agent3_native_tools import build_tool_schemas
        tools = build_tool_schemas(
            include_clawhub_skills=True,
            include_clawhub_meta_tools=True,
        )
        names = [t["name"] for t in tools]
        assert len(set(names)) == len(names), f"Duplicates: {[n for n in names if names.count(n) > 1]}"


# ──────────────────────────────────────────────────────────────────────────────
# Tests load_all_tool_schemas helper
# ──────────────────────────────────────────────────────────────────────────────

class TestLoadAllToolSchemas:
    def test_returns_list(self, tmp_skills_root, monkeypatch):
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", tmp_skills_root)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [])
        schemas = load_all_tool_schemas()
        assert isinstance(schemas, list)
        assert all(isinstance(s, dict) for s in schemas)
        assert all("name" in s and "input_schema" in s for s in schemas)

    def test_respects_bundled_filter(self, tmp_path, monkeypatch):
        user = tmp_path / "user"
        bundled = tmp_path / "bundled"
        user.mkdir()
        bundled.mkdir()
        (user / "user-only").mkdir()
        (user / "user-only" / "SKILL.md").write_text(
            "---\nname: user-only\ndescription: User\n---\nBody", encoding="utf-8",
        )
        (bundled / "bundled-only").mkdir()
        (bundled / "bundled-only" / "SKILL.md").write_text(
            "---\nname: bundled-only\ndescription: Bundled\n---\nBody", encoding="utf-8",
        )
        monkeypatch.setattr(clawhub_loader, "USER_SKILLS_DIR", user)
        monkeypatch.setattr(clawhub_loader, "BUNDLED_SKILLS_DIRS", [bundled])

        all_s = load_all_tool_schemas(force_refresh=True)
        all_slugs = [s["name"].replace("skill_", "") for s in all_s]
        assert "user_only" in all_slugs
        assert "bundled_only" in all_slugs

        only_user = load_all_tool_schemas(include_bundled=False, force_refresh=True)
        only_user_slugs = [s["name"].replace("skill_", "") for s in only_user]
        assert "user_only" in only_user_slugs
        assert "bundled_only" not in only_user_slugs
