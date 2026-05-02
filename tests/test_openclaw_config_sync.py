"""Tests pour api/openclaw_config_sync.py — sync Vault -> openclaw.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sylea.core.storage.database import DatabaseManager


@pytest.fixture
def db():
    d = DatabaseManager(db_path=Path(":memory:"))
    d.connect()
    return d


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Cree un openclaw.json minimal et override le path."""
    cfg = tmp_path / "openclaw.json"
    cfg.write_text(json.dumps({
        "gateway": {"port": 18789},
        "plugins": {"entries": {"duckduckgo": {"enabled": True}}},
    }, indent=2), encoding="utf-8")
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(cfg))
    monkeypatch.setenv("SYLEA_CREDENTIALS_MASTER_KEY", "test-key-not-for-prod-123456789")
    from api import credentials as cred_mod
    cred_mod._fernet_instance = None
    return cfg


class TestSyncBasic:
    def test_no_user_id(self, db, tmp_config):
        from api.openclaw_config_sync import sync_user_credentials_to_openclaw
        r = sync_user_credentials_to_openclaw(db, "")
        assert r["ok"] is False

    def test_config_missing(self, db, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(tmp_path / "nope.json"))
        from api.openclaw_config_sync import sync_user_credentials_to_openclaw
        r = sync_user_credentials_to_openclaw(db, "u1")
        assert r["ok"] is False
        assert "absent" in r["error"]

    def test_sync_no_credentials(self, db, tmp_config):
        from api.openclaw_config_sync import sync_user_credentials_to_openclaw
        r = sync_user_credentials_to_openclaw(db, "u1")
        assert r["ok"] is True
        # Pas de cle en vault -> tous skipped, pas de changes
        assert r["changes"] == []
        assert len(r["skipped_providers"]) > 0


class TestSyncWithCredentials:
    def test_sync_perplexity(self, db, tmp_config):
        from api.credentials import save_credential
        from api.openclaw_config_sync import sync_user_credentials_to_openclaw

        save_credential(db, "u1", "perplexity", "api_key", "pplx-test-abc123xyz")
        r = sync_user_credentials_to_openclaw(db, "u1")

        assert r["ok"] is True
        assert "perplexity" in r["synced_providers"]
        assert any(c["provider"] == "perplexity" for c in r["changes"])

        # Verifie le contenu ecrit dans le fichier
        with open(tmp_config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg["plugins"]["entries"]["perplexity"]["config"]["webSearch"]["apiKey"] == "pplx-test-abc123xyz"
        assert cfg["plugins"]["entries"]["perplexity"]["enabled"] is True

    def test_sync_multiple_providers(self, db, tmp_config):
        from api.credentials import save_credential
        from api.openclaw_config_sync import sync_user_credentials_to_openclaw

        save_credential(db, "u1", "perplexity", "api_key", "pplx-1")
        save_credential(db, "u1", "brave", "api_key", "BSA-2")
        save_credential(db, "u1", "tavily", "api_key", "tvly-3")

        r = sync_user_credentials_to_openclaw(db, "u1")
        assert r["ok"] is True
        assert len(r["changes"]) == 3

        with open(tmp_config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg["plugins"]["entries"]["perplexity"]["config"]["webSearch"]["apiKey"] == "pplx-1"
        assert cfg["plugins"]["entries"]["brave-web-search"]["config"]["apiKey"] == "BSA-2"
        assert cfg["plugins"]["entries"]["tavily"]["config"]["apiKey"] == "tvly-3"

    def test_dry_run_no_write(self, db, tmp_config):
        from api.credentials import save_credential
        from api.openclaw_config_sync import sync_user_credentials_to_openclaw

        save_credential(db, "u1", "perplexity", "api_key", "pplx-dry")
        # Capture contenu avant
        before = tmp_config.read_text(encoding="utf-8")
        r = sync_user_credentials_to_openclaw(db, "u1", dry_run=True)
        assert r["ok"] is True
        assert r["dry_run"] is True
        assert len(r["changes"]) == 1
        # Fichier pas modifie
        assert tmp_config.read_text(encoding="utf-8") == before

    def test_update_existing(self, db, tmp_config):
        from api.credentials import save_credential
        from api.openclaw_config_sync import sync_user_credentials_to_openclaw

        save_credential(db, "u1", "perplexity", "api_key", "pplx-v1")
        sync_user_credentials_to_openclaw(db, "u1")

        # Update la cle
        save_credential(db, "u1", "perplexity", "api_key", "pplx-v2-updated")
        r = sync_user_credentials_to_openclaw(db, "u1")
        assert any(c["action"] == "updated" for c in r["changes"])

        with open(tmp_config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg["plugins"]["entries"]["perplexity"]["config"]["webSearch"]["apiKey"] == "pplx-v2-updated"

    def test_remove_missing(self, db, tmp_config):
        from api.credentials import save_credential, delete_credential
        from api.openclaw_config_sync import sync_user_credentials_to_openclaw

        save_credential(db, "u1", "perplexity", "api_key", "pplx-will-be-deleted")
        sync_user_credentials_to_openclaw(db, "u1")
        delete_credential(db, "u1", "perplexity", "api_key")

        r = sync_user_credentials_to_openclaw(db, "u1", remove_missing=True)
        assert any(c["action"] == "removed" for c in r["changes"])

        with open(tmp_config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        assert cfg["plugins"]["entries"]["perplexity"]["enabled"] is False
        assert cfg["plugins"]["entries"]["perplexity"]["config"]["webSearch"]["apiKey"] == ""


class TestConfigPath:
    def test_env_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(tmp_path / "custom.json"))
        from api.openclaw_config_sync import get_openclaw_config_path
        p = get_openclaw_config_path()
        assert str(p).endswith("custom.json")

    def test_default_path(self, monkeypatch):
        monkeypatch.delenv("OPENCLAW_CONFIG_PATH", raising=False)
        from api.openclaw_config_sync import get_openclaw_config_path
        p = get_openclaw_config_path()
        assert ".openclaw" in str(p)
        assert p.name == "openclaw.json"


class TestBackup:
    def test_backup_created(self, db, tmp_config):
        from api.credentials import save_credential
        from api.openclaw_config_sync import sync_user_credentials_to_openclaw

        save_credential(db, "u1", "brave", "api_key", "BSA-backup-test")
        sync_user_credentials_to_openclaw(db, "u1")

        backup = tmp_config.with_suffix(".json.bak")
        assert backup.exists()


class TestReload:
    def test_reload_gracefully_handles_no_gateway(self, monkeypatch):
        monkeypatch.setenv("OPENCLAW_GATEWAY_URL", "http://localhost:1")  # port mort
        from api.openclaw_config_sync import reload_openclaw_gateway
        r = reload_openclaw_gateway()
        # Doit retourner not_supported (pas de crash)
        assert r["action"] in ("not_supported", "error")
