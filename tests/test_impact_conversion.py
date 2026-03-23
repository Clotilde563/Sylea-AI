"""
Tests for jours_vers_probabilite: the impact_jours -> impact_probabilite conversion.

This formula is used in both evenement.py and claude_agent.py to convert
a time delta (days gained/lost) into a probability delta (percentage points).
"""

import pytest
from sylea.core.engine.probability import jours_vers_probabilite


# ── Helper: compute remaining days from probability ──────────────────────────

def _temps_restant(prob: float) -> int:
    """Reproduce the temps_j formula for test assertions."""
    prob = max(0.01, min(99.99, prob))
    return min(73000, max(1, round(900 * ((100 - prob) / prob) ** 0.675)))


# ── Positive impact (gaining days) increases probability ─────────────────────

class TestPositiveImpact:
    def test_small_gain(self):
        delta = jours_vers_probabilite(30.0, 10)
        assert delta > 0, "Gaining 10 days should increase probability"

    def test_moderate_gain(self):
        delta = jours_vers_probabilite(30.0, 100)
        assert delta > 0
        # 100 days should give a bigger boost than 10 days
        delta_small = jours_vers_probabilite(30.0, 10)
        assert delta > delta_small

    def test_large_gain(self):
        delta = jours_vers_probabilite(10.0, 500)
        assert delta > 0
        assert delta > jours_vers_probabilite(10.0, 100)


# ── Negative impact (losing days) decreases probability ──────────────────────

class TestNegativeImpact:
    def test_small_loss(self):
        delta = jours_vers_probabilite(30.0, -10)
        assert delta < 0, "Losing 10 days should decrease probability"

    def test_moderate_loss(self):
        delta = jours_vers_probabilite(30.0, -100)
        assert delta < 0
        # 100 days lost should be worse than 10 days lost
        delta_small = jours_vers_probabilite(30.0, -10)
        assert delta < delta_small

    def test_large_loss(self):
        delta = jours_vers_probabilite(50.0, -500)
        assert delta < 0


# ── Zero impact returns approximately 0 ──────────────────────────────────────

class TestZeroImpact:
    def test_zero_at_low_prob(self):
        delta = jours_vers_probabilite(10.0, 0)
        # Rounding in temps_j calculation can cause tiny residual
        assert abs(delta) < 0.02

    def test_zero_at_mid_prob(self):
        delta = jours_vers_probabilite(50.0, 0)
        assert abs(delta) < 0.02

    def test_zero_at_high_prob(self):
        delta = jours_vers_probabilite(90.0, 0)
        # At high prob, temps_j is small so rounding has more relative effect
        assert abs(delta) < 0.02


# ── Large impact: gaining almost all remaining time ──────────────────────────

class TestLargeImpact:
    def test_gain_most_remaining_time(self):
        """Gaining almost all remaining time should give a high probability boost."""
        prob = 20.0
        remaining = _temps_restant(prob)
        # Gain 90% of remaining time
        delta = jours_vers_probabilite(prob, remaining * 0.9)
        assert delta > 30, f"Gaining 90% of remaining time should boost prob significantly, got {delta}"

    def test_gain_all_remaining_time(self):
        """Gaining all remaining time should push prob close to 100%."""
        prob = 20.0
        remaining = _temps_restant(prob)
        delta = jours_vers_probabilite(prob, remaining)
        # After gaining all remaining time, temps_apres = max(1, 0) = 1
        # prob_apres should be very close to 100%
        new_prob = prob + delta
        assert new_prob > 95, f"Gaining all remaining time should bring prob near 100%, got {new_prob}"

    def test_gain_exceeding_remaining_time(self):
        """Gaining more than remaining time is capped at temps_apres=1."""
        prob = 30.0
        remaining = _temps_restant(prob)
        delta_exact = jours_vers_probabilite(prob, remaining)
        delta_excess = jours_vers_probabilite(prob, remaining + 1000)
        # Both should produce the same result since temps_apres is clamped to 1
        assert abs(delta_exact - delta_excess) < 0.01


# ── Consistency: round-trip conversion ───────────────────────────────────────

class TestConsistency:
    def test_roundtrip_positive(self):
        """Converting days->prob->days should give similar values."""
        prob = 40.0
        impact_days = 50
        delta_pct = jours_vers_probabilite(prob, impact_days)
        new_prob = prob + delta_pct

        # Now compute remaining time before and after
        temps_before = _temps_restant(prob)
        temps_after = _temps_restant(new_prob)
        recovered_days = temps_before - temps_after

        # Should be close to original impact_days (within rounding tolerance)
        assert abs(recovered_days - impact_days) <= 2, (
            f"Round-trip: {impact_days} days -> {delta_pct}% -> {recovered_days} days"
        )

    def test_roundtrip_negative(self):
        """Negative round-trip should also be consistent."""
        prob = 40.0
        impact_days = -30
        delta_pct = jours_vers_probabilite(prob, impact_days)
        new_prob = prob + delta_pct

        temps_before = _temps_restant(prob)
        temps_after = _temps_restant(new_prob)
        recovered_days = temps_before - temps_after

        assert abs(recovered_days - impact_days) <= 2, (
            f"Round-trip: {impact_days} days -> {delta_pct}% -> {recovered_days} days"
        )


# ── Edge cases: extreme probability values ───────────────────────────────────

class TestEdgeCases:
    def test_very_low_prob(self):
        """prob_actuelle = 0.01 (minimum)."""
        delta = jours_vers_probabilite(0.01, 100)
        assert delta > 0
        # At 0.01%, remaining time is huge, so 100 days is a tiny fraction
        # Delta should be small but positive
        assert delta < 1.0, f"At 0.01%, 100 days should be a tiny impact, got {delta}"

    def test_mid_prob(self):
        """prob_actuelle = 50 (middle)."""
        delta = jours_vers_probabilite(50.0, 100)
        assert delta > 0
        # At 50%, remaining time is ~900 days, so 100 days is significant
        assert delta > 1.0, f"At 50%, 100 days should be meaningful, got {delta}"

    def test_very_high_prob(self):
        """prob_actuelle = 99.99 (near maximum)."""
        remaining = _temps_restant(99.99)
        # At 99.99%, remaining time is very small (1-2 days)
        assert remaining <= 2

        # Gaining days when already at 99.99% should have minimal effect
        delta = jours_vers_probabilite(99.99, 1)
        # Already near max, delta should be tiny
        assert abs(delta) < 0.1

    def test_below_minimum_clamped(self):
        """prob_actuelle below 0.01 should be clamped to 0.01."""
        delta_neg = jours_vers_probabilite(-5.0, 100)
        delta_min = jours_vers_probabilite(0.01, 100)
        assert abs(delta_neg - delta_min) < 0.001

    def test_above_maximum_clamped(self):
        """prob_actuelle above 99.99 should be clamped to 99.99."""
        delta_over = jours_vers_probabilite(150.0, 1)
        delta_max = jours_vers_probabilite(99.99, 1)
        assert abs(delta_over - delta_max) < 0.001


# ── Monotonicity: more days gained = higher delta ────────────────────────────

class TestMonotonicity:
    @pytest.mark.parametrize("prob", [10.0, 30.0, 50.0, 70.0, 90.0])
    def test_increasing_days_increases_delta(self, prob):
        """More days gained should always produce a higher probability delta."""
        d1 = jours_vers_probabilite(prob, 10)
        d2 = jours_vers_probabilite(prob, 50)
        d3 = jours_vers_probabilite(prob, 200)
        assert d1 < d2 < d3, f"At prob={prob}: {d1} < {d2} < {d3} should hold"

    @pytest.mark.parametrize("prob", [10.0, 30.0, 50.0, 70.0, 90.0])
    def test_increasing_loss_decreases_delta(self, prob):
        """More days lost should always produce a lower (more negative) delta."""
        d1 = jours_vers_probabilite(prob, -10)
        d2 = jours_vers_probabilite(prob, -50)
        d3 = jours_vers_probabilite(prob, -200)
        assert d1 > d2 > d3, f"At prob={prob}: {d1} > {d2} > {d3} should hold"
