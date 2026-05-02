"""
Tests pour l'isolation per-user des skills ClawHub (Phase 4.2).

Verifie :
  - `get_user_skills_dir(user_id)` -> chemin distinct par user
  - `scan_all_skills(auth_user_id=X)` -> ne voit que les skills de X (+ bundled)
  - `ClawHubSkillCache` maintient des entrees independantes par user
  - `invalidate_cache(auth_user_id=X)` n'affecte que le cache de X
  - `_run_clawhub` override HOME/USERPROFILE quand auth_user_id fourni
  - Migration script : dry-run + apply + idempotence
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from api.agent3_skills import clawhub_loader as cl


SKILL_MD_TEMPLATE = """---
name: {name}
description: {desc}
---

# {name}

Test skill used for isolation tests.
"""


def _write_skill(base_dir: Path, slug: str, *, desc: str = "test skill") -> Path:
    """Ecrit un SKILL.md minimal dans base_dir/<slug>/SKILL.md."""
    skill_dir = base_dir / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        SKILL_MD_TEMPLATE.format(name=slug, desc=desc),
        encoding="utf-8",
    )
    return skill_md


@pytest.fixture
def isolated_sylea_root(tmp_path, monkeypatch):
    """Redirige SYLEA_USER_SKILLS_ROOT vers un tmp_path et vide le cache."""
    root = tmp_path / "sylea_users"
    root.mkdir()
    monkeypatch.setenv("SYLEA_USER_SKILLS_ROOT", str(root))
    # Reset singleton cache
    cl._reset_cache()
    yield root
    cl._reset_cache()


# ──────────────────────────────────────────────────────────────────────────────
# Path helpers
# ──────────────────────────────────────────────────────────────────────────────


class TestUserSkillsDir:
    def test_legacy_path_when_no_user(self):
        """Sans auth_user_id, retourne le legacy dir partage."""
        p = cl.get_user_skills_dir(None)
        assert p == cl.LEGACY_USER_SKILLS_DIR

    def test_per_user_path_uses_sylea_root(self, isolated_sylea_root):
        """Avec auth_user_id, compose ~/.sylea/users/{id}/.openclaw/skills/."""
        p = cl.get_user_skills_dir("alice-123")
        assert p == (isolated_sylea_root / "alice-123" / ".openclaw" / "skills").resolve()

    def test_different_users_get_different_dirs(self, isolated_sylea_root):
        p_alice = cl.get_user_skills_dir("alice")
        p_bob = cl.get_user_skills_dir("bob")
        assert p_alice != p_bob
        assert p_alice.parent.parent.name == "alice"
        assert p_bob.parent.parent.name == "bob"

    def test_invalid_user_id_falls_back_to_legacy(self, isolated_sylea_root):
        """Empty / whitespace -> fallback legacy."""
        assert cl.get_user_skills_dir("") == cl.LEGACY_USER_SKILLS_DIR
        assert cl.get_user_skills_dir("   ") == cl.LEGACY_USER_SKILLS_DIR

    def test_path_traversal_sanitized(self, isolated_sylea_root):
        """../ dans user_id ne peut pas s'echapper du sylea root."""
        p = cl.get_user_skills_dir("../../etc")
        # Apres sanitisation : ".." -> "_" donc "__/__/etc" ou assimile
        # Important : le path resolu doit rester DANS isolated_sylea_root
        assert str(p).startswith(str(isolated_sylea_root))

    def test_home_override_for_clawhub_cli(self, isolated_sylea_root):
        """get_user_home_override retourne le parent de .openclaw (pour HOME env)."""
        home = cl.get_user_home_override("alice-42")
        assert home == (isolated_sylea_root / "alice-42").resolve()
        assert cl.get_user_home_override(None) is None
        assert cl.get_user_home_override("") is None

    def test_ensure_creates_dir(self, isolated_sylea_root):
        """ensure_user_skills_dir cree les parents si absents."""
        p = cl.ensure_user_skills_dir("newuser")
        assert p.exists() and p.is_dir()
        assert str(p).endswith(os.path.join("newuser", ".openclaw", "skills"))


# ──────────────────────────────────────────────────────────────────────────────
# Scan isolation : users ne voient pas les skills d'autres users
# ──────────────────────────────────────────────────────────────────────────────


class TestScanIsolation:
    def test_user_sees_only_their_skills(self, isolated_sylea_root, monkeypatch):
        # On desactive les bundled dirs pour simplifier l'assertion
        monkeypatch.setattr(cl, "BUNDLED_SKILLS_DIRS", [])

        alice_dir = cl.ensure_user_skills_dir("alice")
        bob_dir = cl.ensure_user_skills_dir("bob")

        _write_skill(alice_dir, "alice-only", desc="for alice")
        _write_skill(bob_dir, "bob-only", desc="for bob")
        _write_skill(alice_dir, "shared-slug", desc="alice version")

        alice_metas = cl.scan_all_skills(auth_user_id="alice")
        bob_metas = cl.scan_all_skills(auth_user_id="bob")

        alice_slugs = {m.slug for m in alice_metas}
        bob_slugs = {m.slug for m in bob_metas}

        assert "alice-only" in alice_slugs
        assert "shared-slug" in alice_slugs
        assert "bob-only" not in alice_slugs

        assert "bob-only" in bob_slugs
        assert "alice-only" not in bob_slugs
        assert "shared-slug" not in bob_slugs

    def test_legacy_path_when_no_user_id(self, isolated_sylea_root, monkeypatch, tmp_path):
        """Avec auth_user_id=None, on scanne le legacy dir (pas les user dirs)."""
        # Legacy redirige vers tmp pour eviter de pollue le vrai ~/.openclaw
        fake_legacy = tmp_path / "legacy_openclaw" / "skills"
        fake_legacy.mkdir(parents=True)
        monkeypatch.setattr(cl, "LEGACY_USER_SKILLS_DIR", fake_legacy)
        monkeypatch.setattr(cl, "USER_SKILLS_DIR", fake_legacy)
        monkeypatch.setattr(cl, "BUNDLED_SKILLS_DIRS", [])

        _write_skill(fake_legacy, "legacy-skill")

        alice_dir = cl.ensure_user_skills_dir("alice")
        _write_skill(alice_dir, "alice-skill")

        legacy_metas = cl.scan_all_skills(auth_user_id=None)
        legacy_slugs = {m.slug for m in legacy_metas}

        assert "legacy-skill" in legacy_slugs
        assert "alice-skill" not in legacy_slugs


# ──────────────────────────────────────────────────────────────────────────────
# Cache isolation : invalidate un user ne casse pas le cache des autres
# ──────────────────────────────────────────────────────────────────────────────


class TestCacheIsolation:
    def test_cache_keyed_per_user(self, isolated_sylea_root, monkeypatch):
        monkeypatch.setattr(cl, "BUNDLED_SKILLS_DIRS", [])

        alice_dir = cl.ensure_user_skills_dir("alice")
        bob_dir = cl.ensure_user_skills_dir("bob")

        _write_skill(alice_dir, "alice-v1")
        _write_skill(bob_dir, "bob-v1")

        # Premier load -> peuple le cache pour chaque user
        schemas_alice = cl.load_all_tool_schemas(auth_user_id="alice")
        schemas_bob = cl.load_all_tool_schemas(auth_user_id="bob")

        alice_tool_names = {s["name"] for s in schemas_alice}
        bob_tool_names = {s["name"] for s in schemas_bob}

        assert "skill_alice_v1" in alice_tool_names
        assert "skill_alice_v1" not in bob_tool_names
        assert "skill_bob_v1" in bob_tool_names
        assert "skill_bob_v1" not in alice_tool_names

    def test_invalidate_user_only_affects_that_user(
        self, isolated_sylea_root, monkeypatch,
    ):
        monkeypatch.setattr(cl, "BUNDLED_SKILLS_DIRS", [])

        alice_dir = cl.ensure_user_skills_dir("alice")
        bob_dir = cl.ensure_user_skills_dir("bob")
        _write_skill(alice_dir, "initial-alice")
        _write_skill(bob_dir, "initial-bob")

        # Peuple le cache pour Alice et Bob
        cl.load_all_tool_schemas(auth_user_id="alice")
        cl.load_all_tool_schemas(auth_user_id="bob")

        # Ajoute un nouveau skill a Alice SANS invalider
        _write_skill(alice_dir, "new-alice-skill")

        # Sans invalidate : cache toujours actif, nouveau skill invisible
        schemas_alice = cl.load_all_tool_schemas(auth_user_id="alice")
        alice_names = {s["name"] for s in schemas_alice}
        assert "skill_new_alice_skill" not in alice_names

        # Invalide UNIQUEMENT le cache d'Alice
        cl.invalidate_cache(auth_user_id="alice")

        # Alice voit le nouveau skill
        schemas_alice = cl.load_all_tool_schemas(auth_user_id="alice")
        alice_names = {s["name"] for s in schemas_alice}
        assert "skill_new_alice_skill" in alice_names

        # Bob n'est pas affecte (son cache reste intact, pas de rescan)
        # On verifie indirectement : un skill ajoute a Bob SANS invalider son
        # cache doit rester invisible.
        _write_skill(bob_dir, "new-bob-skill")
        schemas_bob = cl.load_all_tool_schemas(auth_user_id="bob")
        bob_names = {s["name"] for s in schemas_bob}
        assert "skill_new_bob_skill" not in bob_names

    def test_invalidate_all_clears_everyone(
        self, isolated_sylea_root, monkeypatch,
    ):
        monkeypatch.setattr(cl, "BUNDLED_SKILLS_DIRS", [])

        alice_dir = cl.ensure_user_skills_dir("alice")
        bob_dir = cl.ensure_user_skills_dir("bob")
        _write_skill(alice_dir, "alice-1")
        _write_skill(bob_dir, "bob-1")

        cl.load_all_tool_schemas(auth_user_id="alice")
        cl.load_all_tool_schemas(auth_user_id="bob")

        _write_skill(alice_dir, "alice-2")
        _write_skill(bob_dir, "bob-2")

        cl.invalidate_all_caches()

        schemas_alice = cl.load_all_tool_schemas(auth_user_id="alice")
        schemas_bob = cl.load_all_tool_schemas(auth_user_id="bob")
        assert "skill_alice_2" in {s["name"] for s in schemas_alice}
        assert "skill_bob_2" in {s["name"] for s in schemas_bob}


# ──────────────────────────────────────────────────────────────────────────────
# build_tool_schemas propagation
# ──────────────────────────────────────────────────────────────────────────────


class TestBuildToolSchemasIsolation:
    def test_build_with_auth_user_id_forwards_to_loader(
        self, isolated_sylea_root, monkeypatch,
    ):
        from api.agent3_native_tools import build_tool_schemas

        monkeypatch.setattr(cl, "BUNDLED_SKILLS_DIRS", [])

        alice_dir = cl.ensure_user_skills_dir("alice")
        _write_skill(alice_dir, "alice-tool")
        bob_dir = cl.ensure_user_skills_dir("bob")
        _write_skill(bob_dir, "bob-tool")

        # Alice n'a aucun action natif, juste ses skills
        schemas_alice = build_tool_schemas(
            enabled_actions=set(),
            include_clawhub_skills=True,
            include_clawhub_meta_tools=False,
            auth_user_id="alice",
        )
        alice_names = {s["name"] for s in schemas_alice}

        schemas_bob = build_tool_schemas(
            enabled_actions=set(),
            include_clawhub_skills=True,
            include_clawhub_meta_tools=False,
            auth_user_id="bob",
        )
        bob_names = {s["name"] for s in schemas_bob}

        assert "skill_alice_tool" in alice_names
        assert "skill_bob_tool" not in alice_names
        assert "skill_bob_tool" in bob_names
        assert "skill_alice_tool" not in bob_names


# ──────────────────────────────────────────────────────────────────────────────
# _run_clawhub : HOME override quand auth_user_id fourni
# ──────────────────────────────────────────────────────────────────────────────


class TestRunClawhubHomeOverride:
    def test_home_env_set_when_user_provided(self, isolated_sylea_root, monkeypatch):
        """_run_clawhub doit injecter HOME / USERPROFILE quand auth_user_id fourni."""
        import asyncio

        captured_env: dict = {}

        # Monkey-patch subprocess.run dans le module pour capturer l'env
        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env") or {})

            class _R:
                stdout = b"ok"
                stderr = b""
                returncode = 0
            return _R()

        from api.agent3_skills import clawhub_meta_tools as cmt
        monkeypatch.setattr(cmt.subprocess, "run", fake_run)

        asyncio.get_event_loop().run_until_complete(
            cmt._run_clawhub(["search", "test"], timeout=5, auth_user_id="alice-42")
        )

        expected_home = str((isolated_sylea_root / "alice-42").resolve())
        assert captured_env.get("HOME") == expected_home
        assert captured_env.get("USERPROFILE") == expected_home
        assert captured_env.get("SYLEA_AUTH_USER_ID") == "alice-42"

    def test_no_override_when_no_user(self, isolated_sylea_root, monkeypatch):
        """Sans auth_user_id, HOME n'est pas touche (legacy behavior)."""
        import asyncio

        captured_env: dict = {}
        orig_home = os.environ.get("HOME", "")
        orig_userprofile = os.environ.get("USERPROFILE", "")

        def fake_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env") or {})

            class _R:
                stdout = b"ok"
                stderr = b""
                returncode = 0
            return _R()

        from api.agent3_skills import clawhub_meta_tools as cmt
        monkeypatch.setattr(cmt.subprocess, "run", fake_run)

        asyncio.get_event_loop().run_until_complete(
            cmt._run_clawhub(["search", "test"], timeout=5, auth_user_id=None)
        )

        # HOME et USERPROFILE ne sont pas touches
        assert captured_env.get("HOME", orig_home) == orig_home
        assert captured_env.get("USERPROFILE", orig_userprofile) == orig_userprofile
        # Pas de marker Sylea
        assert "SYLEA_AUTH_USER_ID" not in captured_env


# ──────────────────────────────────────────────────────────────────────────────
# Migration script
# ──────────────────────────────────────────────────────────────────────────────


class TestMigration:
    def test_dry_run_does_not_copy(self, isolated_sylea_root, monkeypatch, tmp_path):
        from api.agent3_skills.migrate_user_isolation import migrate

        fake_legacy = tmp_path / "legacy"
        fake_legacy.mkdir()
        monkeypatch.setattr(cl, "LEGACY_USER_SKILLS_DIR", fake_legacy)
        monkeypatch.setattr(cl, "USER_SKILLS_DIR", fake_legacy)

        _write_skill(fake_legacy, "old-skill")

        result = migrate(auth_user_id="alice", apply=False, verbose=False)
        assert result["planned"] == ["old-skill"]
        assert result["copied"] == []
        # Cible n'existe pas encore
        target = cl.get_user_skills_dir("alice")
        assert not (target / "old-skill").exists()

    def test_apply_copies_skills(self, isolated_sylea_root, monkeypatch, tmp_path):
        from api.agent3_skills.migrate_user_isolation import migrate

        fake_legacy = tmp_path / "legacy"
        fake_legacy.mkdir()
        monkeypatch.setattr(cl, "LEGACY_USER_SKILLS_DIR", fake_legacy)
        monkeypatch.setattr(cl, "USER_SKILLS_DIR", fake_legacy)

        _write_skill(fake_legacy, "to-migrate")
        _write_skill(fake_legacy, "also-migrate")

        result = migrate(auth_user_id="alice", apply=True, verbose=False)
        assert set(result["copied"]) == {"to-migrate", "also-migrate"}

        target = cl.get_user_skills_dir("alice")
        assert (target / "to-migrate" / "SKILL.md").exists()
        assert (target / "also-migrate" / "SKILL.md").exists()

    def test_idempotent_second_run_skips(
        self, isolated_sylea_root, monkeypatch, tmp_path,
    ):
        from api.agent3_skills.migrate_user_isolation import migrate

        fake_legacy = tmp_path / "legacy"
        fake_legacy.mkdir()
        monkeypatch.setattr(cl, "LEGACY_USER_SKILLS_DIR", fake_legacy)
        monkeypatch.setattr(cl, "USER_SKILLS_DIR", fake_legacy)

        _write_skill(fake_legacy, "shared-slug")

        r1 = migrate(auth_user_id="alice", apply=True, verbose=False)
        assert r1["copied"] == ["shared-slug"]

        r2 = migrate(auth_user_id="alice", apply=True, verbose=False)
        assert r2["copied"] == []
        assert r2["skipped"] == ["shared-slug"]

    def test_slugs_filter(self, isolated_sylea_root, monkeypatch, tmp_path):
        from api.agent3_skills.migrate_user_isolation import migrate

        fake_legacy = tmp_path / "legacy"
        fake_legacy.mkdir()
        monkeypatch.setattr(cl, "LEGACY_USER_SKILLS_DIR", fake_legacy)
        monkeypatch.setattr(cl, "USER_SKILLS_DIR", fake_legacy)

        _write_skill(fake_legacy, "wanted")
        _write_skill(fake_legacy, "not-wanted")

        result = migrate(
            auth_user_id="alice",
            apply=True,
            slugs_filter=["wanted"],
            verbose=False,
        )
        assert result["copied"] == ["wanted"]
        target = cl.get_user_skills_dir("alice")
        assert (target / "wanted").exists()
        assert not (target / "not-wanted").exists()

    def test_cleanup_legacy_requires_confirm(
        self, isolated_sylea_root, monkeypatch, tmp_path,
    ):
        from api.agent3_skills.migrate_user_isolation import migrate

        fake_legacy = tmp_path / "legacy"
        fake_legacy.mkdir()
        monkeypatch.setattr(cl, "LEGACY_USER_SKILLS_DIR", fake_legacy)
        monkeypatch.setattr(cl, "USER_SKILLS_DIR", fake_legacy)

        _write_skill(fake_legacy, "slug-x")

        # cleanup_legacy=True mais confirm_cleanup=False -> on NE supprime PAS
        result = migrate(
            auth_user_id="alice",
            apply=True,
            cleanup_legacy=True,
            confirm_cleanup=False,
            verbose=False,
        )
        assert result["copied"] == ["slug-x"]
        assert result["removed_legacy"] is False
        assert (fake_legacy / "slug-x").exists()

        # Avec confirm_cleanup=True, le legacy est supprime
        # D'abord on re-migre (idempotent : skipped), puis cleanup.
        result = migrate(
            auth_user_id="alice",
            apply=True,
            cleanup_legacy=True,
            confirm_cleanup=True,
            verbose=False,
        )
        assert result["removed_legacy"] is True
        assert not (fake_legacy / "slug-x").exists()
