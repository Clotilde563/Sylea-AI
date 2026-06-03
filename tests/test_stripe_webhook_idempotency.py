"""Idempotence du webhook Stripe (2026-06).

Stripe re-livre le MEME event (event.id stable) en cas de retry apres timeout.
On verifie qu'un event deja traite n'est pas re-applique :
  1. test_idempotency_helpers : la persistance (table stripe_processed_events)
     marche — un id marque est ensuite detecte comme deja traite (mono event-loop
     pour eviter les soucis de reuse d'engine async cross-loop).
  2. test_handle_webhook_dedup : end-to-end, la 2e livraison identique renvoie
     action='duplicate_ignored' et NE re-declenche PAS le handler metier.
"""

import asyncio
import uuid

from api import agent3_stripe


def test_idempotency_helpers(shared_db):
    """La table de dedup persiste et detecte correctement les doublons."""
    async def _scenario():
        eid = f"evt_{uuid.uuid4().hex}"
        # Pas encore traite
        assert await agent3_stripe._is_stripe_event_processed_async(eid) is False
        # On marque
        await agent3_stripe._mark_stripe_event_processed_async(eid, "checkout.session.completed")
        # Maintenant detecte comme traite
        assert await agent3_stripe._is_stripe_event_processed_async(eid) is True
        # Re-marquer est un no-op silencieux (pas de crash sur violation PK)
        await agent3_stripe._mark_stripe_event_processed_async(eid, "checkout.session.completed")
        assert await agent3_stripe._is_stripe_event_processed_async(eid) is True

    asyncio.run(_scenario())


class _FakeWebhook:
    _event: dict = {}

    @classmethod
    def construct_event(cls, payload, sig, secret):
        return cls._event


class _FakeStripe:
    Webhook = _FakeWebhook


def test_handle_webhook_dedup(shared_db, monkeypatch):
    """2e livraison du meme event.id -> ignoree, handler metier appele 1x."""
    monkeypatch.setattr(agent3_stripe, "_get_stripe", lambda: _FakeStripe)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")

    calls: list = []

    async def _fake_set_plan(user_id, plan, *a, **k):
        calls.append((user_id, plan))

    monkeypatch.setattr("api.agent3_quotas.set_user_plan_async", _fake_set_plan)

    event_id = f"evt_test_{uuid.uuid4().hex}"
    _FakeStripe.Webhook._event = {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "metadata": {"sylea_user_id": "u-idem", "sylea_plan": "advanced"},
                "subscription": None,
            }
        },
    }

    # 1re livraison : traitee
    r1 = agent3_stripe.handle_webhook(db=shared_db, payload=b"{}", sig_header="sig")
    assert r1.get("ok") is True
    assert r1.get("action") != "duplicate_ignored"

    # 2e livraison identique : ignoree (idempotence)
    r2 = agent3_stripe.handle_webhook(db=shared_db, payload=b"{}", sig_header="sig")
    assert r2.get("ok") is True
    assert r2.get("action") == "duplicate_ignored"

    # Le handler metier n'a tourne qu'une fois
    assert len(calls) == 1, f"set_user_plan_async attendu 1x, obtenu {len(calls)}: {calls}"
