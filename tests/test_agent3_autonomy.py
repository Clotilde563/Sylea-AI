"""
Tests pour l'autonomie Agent 3 :
  - Politique de confirmation mode default vs bypass
  - Niveaux de risque harmonises (EMAIL = high)
  - Handler COMPUTER_USE present dans le flow d'actions
  - Type PermissionMode frontend restreint a 'default' | 'bypass'
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


# ── Risk levels et destructive actions ──────────────────────────────────────

class TestRiskLevels:
    def test_email_is_high_risk(self):
        from api.routers.agent3_openclaw import ActionValidator
        assert ActionValidator.RISK_LEVELS["EMAIL"] == "high"

    def test_gmail_send_is_high_risk(self):
        from api.routers.agent3_openclaw import ActionValidator
        assert ActionValidator.RISK_LEVELS["GMAIL_SEND"] == "high"

    def test_computer_use_is_high_risk(self):
        from api.routers.agent3_openclaw import ActionValidator
        assert ActionValidator.RISK_LEVELS["COMPUTER_USE"] == "high"

    def test_search_stays_low_risk(self):
        from api.routers.agent3_openclaw import ActionValidator
        assert ActionValidator.RISK_LEVELS["SEARCH"] == "low"


class TestDestructiveActions:
    def test_email_is_destructive(self):
        from api.routers.agent3_openclaw import ActionValidator
        assert ActionValidator.is_destructive("EMAIL") is True

    def test_computer_use_is_destructive(self):
        from api.routers.agent3_openclaw import ActionValidator
        assert ActionValidator.is_destructive("COMPUTER_USE") is True

    def test_search_is_not_destructive(self):
        from api.routers.agent3_openclaw import ActionValidator
        assert ActionValidator.is_destructive("SEARCH") is False

    def test_unknown_is_not_destructive(self):
        from api.routers.agent3_openclaw import ActionValidator
        assert ActionValidator.is_destructive("FOO_BAR") is False


# ── requires_confirmation logic ──────────────────────────────────────────────

class TestRequiresConfirmation:
    def test_bypass_never_confirms(self):
        from api.routers.agent3_openclaw import ActionValidator
        # Mode bypass : aucune action ne requiert confirmation, meme destructive.
        assert ActionValidator.requires_confirmation(
            "EMAIL", "bypass", {"confirm_destructive": True}
        ) is False
        assert ActionValidator.requires_confirmation(
            "COMPUTER_USE", "bypass", {"confirm_destructive": True}
        ) is False

    def test_default_confirms_destructive(self):
        from api.routers.agent3_openclaw import ActionValidator
        # Mode default + pref True + destructive -> True
        assert ActionValidator.requires_confirmation(
            "EMAIL", "default", {"confirm_destructive": True}
        ) is True
        assert ActionValidator.requires_confirmation(
            "COMPUTER_USE", "default", {"confirm_destructive": True}
        ) is True

    def test_default_skips_non_destructive(self):
        from api.routers.agent3_openclaw import ActionValidator
        # Mode default + action non-destructive -> pas de confirmation
        assert ActionValidator.requires_confirmation(
            "SEARCH", "default", {"confirm_destructive": True}
        ) is False

    def test_pref_false_disables_confirmation_in_default(self):
        from api.routers.agent3_openclaw import ActionValidator
        # Meme en mode default, si l'utilisateur a mis confirm_destructive=False
        # dans ses prefs, on execute sans confirmer.
        assert ActionValidator.requires_confirmation(
            "EMAIL", "default", {"confirm_destructive": False}
        ) is False


# ── Default preferences ──────────────────────────────────────────────────────

class TestDefaultPrefs:
    def test_default_confirm_destructive_is_true(self):
        """Par defaut, l'agent doit demander confirmation (securite avant autonomie)."""
        from pathlib import Path as _Path
        from sylea.core.storage.database import DatabaseManager
        from api.routers.agent3_openclaw import _get_user_preferences

        db = DatabaseManager(db_path=_Path(":memory:"))
        # User inexistant -> prefs par defaut
        prefs = _get_user_preferences(db, "nouveau_user_test_autonomy")
        assert prefs.get("confirm_destructive") is True


# ── COMPUTER_USE dans les required fields ────────────────────────────────────

class TestComputerUseValidation:
    def test_computer_use_requires_prompt(self):
        from api.routers.agent3_openclaw import ActionValidator
        result = ActionValidator.validate("COMPUTER_USE", {})
        assert result["valid"] is False
        assert any("prompt" in e.lower() for e in result["errors"])

    def test_computer_use_valid_with_prompt(self):
        from api.routers.agent3_openclaw import ActionValidator
        result = ActionValidator.validate(
            "COMPUTER_USE", {"prompt": "Ouvre wikipedia et cherche Ada Lovelace"}
        )
        assert result["valid"] is True
        assert result["risk"] == "high"
        # Un warning "haut risque" est attendu
        assert any("haut risque" in w.lower() or "risque" in w.lower() for w in result["warnings"])


# ── Handler COMPUTER_USE present dans le flow chat/stream ────────────────────

class TestComputerUseHandler:
    """Verifie que le code source contient bien le handler pour COMPUTER_USE."""

    def test_computer_use_handler_exists_in_source(self):
        src = Path(__file__).resolve().parent.parent / "api" / "routers" / "agent3_openclaw.py"
        content = src.read_text(encoding="utf-8")
        # Doit y avoir un bloc 'elif action_type == "COMPUTER_USE":' dans le flow d'actions
        assert 'elif action_type == "COMPUTER_USE"' in content

    def test_computer_use_handler_calls_get_session(self):
        src = Path(__file__).resolve().parent.parent / "api" / "routers" / "agent3_openclaw.py"
        content = src.read_text(encoding="utf-8")
        # Le handler doit instancier une session via get_session
        # (on cherche get_session appele pres de notre handler COMPUTER_USE)
        match = re.search(
            r'elif action_type == "COMPUTER_USE".*?get_session',
            content, re.DOTALL,
        )
        assert match is not None, "Le handler COMPUTER_USE doit appeler get_session()"

    def test_computer_use_handler_respects_missing_api_key(self):
        src = Path(__file__).resolve().parent.parent / "api" / "routers" / "agent3_openclaw.py"
        content = src.read_text(encoding="utf-8")
        match = re.search(
            r'elif action_type == "COMPUTER_USE".*?ANTHROPIC_API_KEY',
            content, re.DOTALL,
        )
        assert match is not None, "Le handler COMPUTER_USE doit verifier ANTHROPIC_API_KEY"


# ── Frontend PermissionMode type restreint ───────────────────────────────────

class TestFrontendPermissionMode:
    def test_permission_mode_type_has_only_default_and_bypass(self):
        ts = Path(__file__).resolve().parent.parent / "frontend" / "src" / "components" / "Agent3PlanMode.tsx"
        content = ts.read_text(encoding="utf-8")
        # Chercher la declaration de type PermissionMode
        m = re.search(r"export type PermissionMode\s*=\s*(.+)", content)
        assert m is not None
        type_def = m.group(1).split("\n")[0]
        # Doit contenir 'default' et 'bypass', pas 'plan' ni 'auto_safe'
        assert "'default'" in type_def
        assert "'bypass'" in type_def
        assert "'plan'" not in type_def
        assert "'auto_safe'" not in type_def

    def test_client_ts_policy_type_restricted(self):
        ts = Path(__file__).resolve().parent.parent / "frontend" / "src" / "api" / "client.ts"
        content = ts.read_text(encoding="utf-8")
        # Cherche la signature browserAgentSetPolicy
        m = re.search(
            r"browserAgentSetPolicy:\s*\(policy:\s*\{\s*mode\?\s*:\s*([^\n}]+)",
            content,
        )
        assert m is not None
        type_str = m.group(1)
        assert "'default'" in type_str
        assert "'bypass'" in type_str
        assert "'plan'" not in type_str
        assert "'auto_safe'" not in type_str


# ── Confirmation event dans le stream ────────────────────────────────────────

class TestConfirmationEvent:
    def test_chat_stream_emits_confirmation_needed_for_destructive(self):
        src = Path(__file__).resolve().parent.parent / "api" / "routers" / "agent3_openclaw.py"
        content = src.read_text(encoding="utf-8")
        # Verifier que le stream emet bien un event confirmation_needed
        assert '_sse_event("confirmation_needed"' in content

    def test_chat_stream_skips_unconfirmed_destructive(self):
        src = Path(__file__).resolve().parent.parent / "api" / "routers" / "agent3_openclaw.py"
        content = src.read_text(encoding="utf-8")
        # Verifier qu'on check _confirmed avant d'executer
        assert '_requires_confirmation' in content or '_confirmed' in content


# ── Skills registry : trading et pine_script retires ─────────────────────────

class TestSkillsRegistryCleanup:
    def test_trading_skill_not_auto_discovered(self):
        # Le registre ne doit plus charger TradingAnalysisSkill ni PineScriptSkill
        # au demarrage (ils sont commentes dans auto_discover).
        from api.agent3_skills import get_skill_registry
        # Reset du singleton pour test propre
        import api.agent3_skills.registry as reg_module
        reg_module._registry = None
        reg = get_skill_registry()
        names = {s.name for s in reg.list_all()}
        assert "trading_analysis" not in names
        assert "pine_script" not in names

    def test_web_search_and_document_still_discovered(self):
        from api.agent3_skills import get_skill_registry
        import api.agent3_skills.registry as reg_module
        reg_module._registry = None
        reg = get_skill_registry()
        names = {s.name for s in reg.list_all()}
        assert "web_search" in names
        assert "document" in names
