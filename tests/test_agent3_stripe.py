"""
Tests Phase 13 — Stripe integration.

Tests unitaires purs (mock de stripe API, pas d'appel reseau).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from sylea.core.storage.database import DatabaseManager


@pytest.fixture
def db():
    d = DatabaseManager(db_path=Path(":memory:"))
    d.connect()
    return d


class TestStripeConfig:
    def test_not_configured_without_key(self, monkeypatch):
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        from api.agent3_stripe import is_configured
        assert is_configured() is False

    def test_configured_with_key(self, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_fake123")
        from api.agent3_stripe import is_configured
        assert is_configured() is True


class TestCheckoutNotConfigured:
    @pytest.mark.asyncio
    async def test_no_key_graceful(self, db, monkeypatch):
        monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
        from api.agent3_stripe import create_checkout_session
        r = await create_checkout_session(db, "u1", "u@x.com", "pro")
        assert r["ok"] is False
        assert "Stripe" in r["error"]

    @pytest.mark.asyncio
    async def test_invalid_plan(self, db, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        from api.agent3_stripe import create_checkout_session
        r = await create_checkout_session(db, "u1", "u@x.com", "free")
        assert r["ok"] is False


class TestEnsureColumns:
    def test_adds_stripe_columns(self, db):
        from api.agent3_stripe import ensure_stripe_columns
        ensure_stripe_columns(db)
        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(user_plans)").fetchall()]
        assert "stripe_customer_id" in cols
        assert "stripe_subscription_id" in cols

    def test_idempotent(self, db):
        from api.agent3_stripe import ensure_stripe_columns
        ensure_stripe_columns(db)
        ensure_stripe_columns(db)  # 2e fois ne doit pas crash
        cols = [r[1] for r in db.conn.execute("PRAGMA table_info(user_plans)").fetchall()]
        assert cols.count("stripe_customer_id") == 1


class TestWebhookHandler:
    def test_no_secret_rejects(self, db, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
        with patch("api.agent3_stripe._get_stripe") as mock_stripe_getter:
            mock_stripe_getter.return_value = MagicMock()
            from api.agent3_stripe import handle_webhook
            r = handle_webhook(db, b"{}", "t=123,v1=abc")
            assert r["ok"] is False
            assert "WEBHOOK_SECRET" in r.get("error", "")

    def test_checkout_completed_upgrades_plan(self, db, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")

        # Seed user
        db.conn.execute(
            "INSERT INTO users (id, email, hashed_password, created_at) VALUES (?,?,?,?)",
            ("u_stripe", "s@x.com", "pw", "2026-04-24"),
        )
        db.conn.commit()

        from api.agent3_quotas import get_user_plan
        # Avant : free
        assert get_user_plan(db, "u_stripe")["name"] == "free"

        # Mock l'event
        fake_event = {
            "type": "checkout.session.completed",
            "data": {"object": {
                "subscription": "sub_abc",
                "metadata": {"sylea_user_id": "u_stripe", "sylea_plan": "pro"},
            }},
        }

        with patch("api.agent3_stripe._get_stripe") as mock_stripe_getter:
            mock_stripe = MagicMock()
            mock_stripe.Webhook.construct_event.return_value = fake_event
            mock_stripe_getter.return_value = mock_stripe

            from api.agent3_stripe import handle_webhook
            r = handle_webhook(db, b'{"type":"checkout.session.completed"}', "t=x,v1=y")
            assert r["ok"] is True

        # Apres : pro
        assert get_user_plan(db, "u_stripe")["name"] == "pro"

    def test_subscription_deleted_downgrades(self, db, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")

        from api.agent3_quotas import set_user_plan, get_user_plan
        set_user_plan(db, "u_canc", "pro")
        assert get_user_plan(db, "u_canc")["name"] == "pro"

        fake_event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"metadata": {"sylea_user_id": "u_canc"}}},
        }
        with patch("api.agent3_stripe._get_stripe") as mock_stripe_getter:
            mock_stripe = MagicMock()
            mock_stripe.Webhook.construct_event.return_value = fake_event
            mock_stripe_getter.return_value = mock_stripe

            from api.agent3_stripe import handle_webhook
            r = handle_webhook(db, b"{}", "t=x,v1=y")
            assert r["ok"] is True

        assert get_user_plan(db, "u_canc")["name"] == "free"

    def test_invalid_signature_rejected(self, db, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")

        with patch("api.agent3_stripe._get_stripe") as mock_stripe_getter:
            mock_stripe = MagicMock()
            mock_stripe.Webhook.construct_event.side_effect = Exception("invalid signature")
            mock_stripe_getter.return_value = mock_stripe

            from api.agent3_stripe import handle_webhook
            r = handle_webhook(db, b"{}", "t=x,v1=bad")
            assert r["ok"] is False
            assert "signature" in r.get("error", "").lower()

    def test_unknown_event_ignored(self, db, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")

        fake_event = {"type": "customer.created", "data": {"object": {}}}
        with patch("api.agent3_stripe._get_stripe") as mock_stripe_getter:
            mock_stripe = MagicMock()
            mock_stripe.Webhook.construct_event.return_value = fake_event
            mock_stripe_getter.return_value = mock_stripe

            from api.agent3_stripe import handle_webhook
            r = handle_webhook(db, b"{}", "t=x")
            assert r["ok"] is True
            assert r["action"] == "ignored"


class TestCheckoutSessionMocked:
    @pytest.mark.asyncio
    async def test_create_checkout_happy_path(self, db, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.setenv("STRIPE_PRICE_PRO", "price_abc")

        mock_session = MagicMock()
        mock_session.id = "cs_123"
        mock_session.url = "https://checkout.stripe.com/c/pay/cs_123"
        mock_customer = MagicMock()
        mock_customer.id = "cus_abc"

        with patch("api.agent3_stripe._get_stripe") as mock_stripe_getter:
            mock_stripe = MagicMock()
            mock_stripe.Customer.create.return_value = mock_customer
            mock_stripe.checkout.Session.create.return_value = mock_session
            mock_stripe_getter.return_value = mock_stripe

            from api.agent3_stripe import create_checkout_session
            r = await create_checkout_session(db, "u_chk", "u@x.com", "pro")
            assert r["ok"] is True
            assert r["url"].startswith("https://")
            assert r["session_id"] == "cs_123"

    @pytest.mark.asyncio
    async def test_create_checkout_no_price_env(self, db, monkeypatch):
        monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
        monkeypatch.delenv("STRIPE_PRICE_PRO", raising=False)

        with patch("api.agent3_stripe._get_stripe") as mock_stripe_getter:
            mock_stripe_getter.return_value = MagicMock()
            from api.agent3_stripe import create_checkout_session
            r = await create_checkout_session(db, "u", "u@x.com", "pro")
            assert r["ok"] is False
            assert "Price" in r["error"]
