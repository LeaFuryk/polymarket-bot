"""Tests for tasks/decision_guards.py — pure decision guard functions."""

from __future__ import annotations

from polybot.models import Action, OrderType, TokenSide, TradingDecision
from polybot.tasks.decision_guards import (
    apply_anti_flip,
    apply_confidence_gate,
    apply_entry_price_cap,
    apply_position_sizing,
    apply_reversal_regime_scaling,
    apply_single_entry,
    apply_velocity_conflict_scaling,
    clamp_sell_size,
    compute_position_scale,
    force_exit_side,
    override_to_hold,
)
from polybot.tasks.prompt_context import VelocityConflict


def _buy(
    side: TokenSide = TokenSide.UP,
    size: float = 50.0,
    confidence: float = 0.75,
    reasoning: str = "test buy",
) -> TradingDecision:
    return TradingDecision(
        action=Action.BUY,
        order_type=OrderType.MARKET,
        size=size,
        confidence=confidence,
        reasoning=reasoning,
        market_view="",
        token_side=side,
    )


def _sell(side: TokenSide = TokenSide.UP, size: float = 30.0) -> TradingDecision:
    return TradingDecision(
        action=Action.SELL,
        order_type=OrderType.MARKET,
        size=size,
        confidence=0.5,
        reasoning="test sell",
        market_view="",
        token_side=side,
    )


def _hold() -> TradingDecision:
    return TradingDecision(
        action=Action.HOLD,
        order_type=OrderType.MARKET,
        size=0.0,
        confidence=0.5,
        reasoning="test hold",
        market_view="",
        token_side=TokenSide.UP,
    )


# ---------------------------------------------------------------------------
# override_to_hold
# ---------------------------------------------------------------------------


class TestOverrideToHold:
    def test_basic(self):
        d = _buy()
        result = override_to_hold(d, "blocked")
        assert result.action == Action.HOLD
        assert result.size == 0.0
        assert result.reasoning == "blocked"
        assert result.confidence == d.confidence

    def test_preserves_token_side(self):
        d = _buy(side=TokenSide.DOWN)
        result = override_to_hold(d, "x")
        assert result.token_side == TokenSide.DOWN


# ---------------------------------------------------------------------------
# clamp_sell_size
# ---------------------------------------------------------------------------


class TestClampSellSize:
    def test_no_op_for_buy(self):
        d = _buy()
        assert clamp_sell_size(d, 10.0) is d

    def test_no_op_when_size_fits(self):
        d = _sell(size=20.0)
        assert clamp_sell_size(d, 30.0) is d

    def test_clamps_to_held(self):
        d = _sell(size=50.0)
        result = clamp_sell_size(d, 30.0)
        assert result.size == 30.0
        assert result.action == Action.SELL

    def test_no_clamp_when_held_zero(self):
        d = _sell(size=50.0)
        assert clamp_sell_size(d, 0.0) is d


# ---------------------------------------------------------------------------
# force_exit_side
# ---------------------------------------------------------------------------


class TestForceExitSide:
    def test_no_op_when_no_forced_side(self):
        d = _sell()
        assert force_exit_side(d, None) is d

    def test_no_op_for_buy(self):
        d = _buy()
        assert force_exit_side(d, "down") is d

    def test_no_op_when_sides_match(self):
        d = _sell(side=TokenSide.UP)
        assert force_exit_side(d, "up") is d

    def test_forces_side(self):
        d = _sell(side=TokenSide.UP)
        result = force_exit_side(d, "down")
        assert result.token_side == TokenSide.DOWN
        assert result.action == Action.SELL


# ---------------------------------------------------------------------------
# apply_confidence_gate
# ---------------------------------------------------------------------------


class TestApplyConfidenceGate:
    def test_no_op_for_hold(self):
        d = _hold()
        assert apply_confidence_gate(d, 0.6) is d

    def test_no_op_above_threshold(self):
        d = _buy(confidence=0.8)
        assert apply_confidence_gate(d, 0.6) is d

    def test_blocks_below_threshold(self):
        d = _buy(confidence=0.4)
        result = apply_confidence_gate(d, 0.6)
        assert result.action == Action.HOLD
        assert "Overridden" in result.reasoning

    def test_exact_threshold_passes(self):
        d = _buy(confidence=0.6)
        assert apply_confidence_gate(d, 0.6) is d


# ---------------------------------------------------------------------------
# apply_entry_price_cap
# ---------------------------------------------------------------------------


class TestApplyEntryPriceCap:
    def test_no_op_for_sell(self):
        d = _sell()
        assert apply_entry_price_cap(d, 0.90) is d

    def test_no_op_below_cap(self):
        d = _buy()
        assert apply_entry_price_cap(d, 0.60) is d

    def test_blocks_above_cap(self):
        d = _buy()
        result = apply_entry_price_cap(d, 0.90)
        assert result.action == Action.HOLD
        assert "Entry price cap" in result.reasoning

    def test_custom_cap(self):
        d = _buy()
        assert apply_entry_price_cap(d, 0.75, cap=0.80) is d
        result = apply_entry_price_cap(d, 0.85, cap=0.80)
        assert result.action == Action.HOLD


# ---------------------------------------------------------------------------
# apply_anti_flip
# ---------------------------------------------------------------------------


class TestApplyAntiFlip:
    def test_no_op_for_hold(self):
        d = _hold()
        assert apply_anti_flip(d, {"UP"}) is d

    def test_no_op_when_no_sold(self):
        d = _buy(side=TokenSide.UP)
        assert apply_anti_flip(d, set()) is d

    def test_blocks_opposite_side(self):
        d = _buy(side=TokenSide.DOWN)
        result = apply_anti_flip(d, {"UP"}, slug="test-slug")
        assert result.action == Action.HOLD
        assert "Anti-flip" in result.reasoning

    def test_allows_same_side_reentry(self):
        d = _buy(side=TokenSide.UP)
        assert apply_anti_flip(d, {"UP"}) is d


# ---------------------------------------------------------------------------
# apply_single_entry
# ---------------------------------------------------------------------------


class TestApplySingleEntry:
    def test_no_op_when_not_bought(self):
        d = _buy(side=TokenSide.UP)
        assert apply_single_entry(d, set()) is d

    def test_blocks_double_entry(self):
        d = _buy(side=TokenSide.UP)
        result = apply_single_entry(d, {"UP"}, slug="test-slug")
        assert result.action == Action.HOLD
        assert "Single-entry" in result.reasoning

    def test_no_op_for_sell(self):
        d = _sell()
        assert apply_single_entry(d, {"UP"}) is d


# ---------------------------------------------------------------------------
# compute_position_scale
# ---------------------------------------------------------------------------


class TestComputePositionScale:
    def test_high_rr_full_scale(self):
        scale, trend = compute_position_scale(1.5, 60.0, None, TokenSide.UP)
        assert scale == 1.0
        assert trend == 1.0

    def test_low_rr_reduces(self):
        scale, _ = compute_position_scale(0.2, 60.0, None, TokenSide.UP)
        assert scale == 0.75

    def test_small_btc_move_reduces(self):
        scale, _ = compute_position_scale(1.0, 5.0, None, TokenSide.UP)
        assert scale == 0.80

    def test_counter_trend_reduces(self):
        # UP buy in bearish trend (score < -0.3)
        scale, trend = compute_position_scale(1.0, 60.0, -0.5, TokenSide.UP)
        assert trend == 0.70
        assert scale < 1.0

    def test_strong_counter_trend(self):
        scale, trend = compute_position_scale(1.0, 60.0, -0.8, TokenSide.UP)
        assert trend == 0.50

    def test_trend_aligned_no_reduction(self):
        scale, trend = compute_position_scale(1.0, 60.0, 0.5, TokenSide.UP)
        assert trend == 1.0
        assert scale == 1.0


# ---------------------------------------------------------------------------
# apply_position_sizing
# ---------------------------------------------------------------------------


class TestApplyPositionSizing:
    def test_no_op_for_hold(self):
        d = _hold()
        assert apply_position_sizing(d, 0.5, 1.0) is d

    def test_scales_down(self):
        d = _buy(size=100.0)
        result = apply_position_sizing(d, 0.5, 1.0)
        assert result.size == 50.0

    def test_enforces_min_size(self):
        d = _buy(size=10.0)
        result = apply_position_sizing(d, 1.0, 1.0)
        assert result.size == 40  # default min

    def test_counter_trend_lower_min(self):
        d = _buy(size=10.0)
        result = apply_position_sizing(d, 1.0, 0.7)
        assert result.size == 20  # counter-trend min

    def test_no_op_at_full_scale(self):
        d = _buy(size=60.0)
        result = apply_position_sizing(d, 1.0, 1.0)
        assert result.size == 60.0


# ---------------------------------------------------------------------------
# apply_velocity_conflict_scaling
# ---------------------------------------------------------------------------


def _conflict(severity: float, mag_dir: str = "DOWN", vel_dir: str = "UP") -> VelocityConflict:
    return VelocityConflict(
        has_conflict=severity >= 0.4,
        severity=severity,
        magnitude_direction=mag_dir,
        velocity_direction=vel_dir,
        velocity_rate=2.0 if vel_dir == "UP" else -2.0,
        btc_move=-50.0 if mag_dir == "DOWN" else 50.0,
        drawback_pct=0.4,
        time_remaining=180.0,
        label="STRONG_CONFLICT" if severity >= 0.7 else "MODERATE_CONFLICT",
        detail="test",
    )


class TestApplyVelocityConflictScaling:
    def test_no_op_for_hold(self):
        d = _hold()
        assert apply_velocity_conflict_scaling(d, _conflict(0.8)) is d

    def test_no_op_for_sell(self):
        d = _sell()
        assert apply_velocity_conflict_scaling(d, _conflict(0.8)) is d

    def test_no_op_when_no_conflict(self):
        d = _buy(side=TokenSide.DOWN)
        no_conflict = _conflict(0.0, mag_dir="DOWN", vel_dir="DOWN")
        assert apply_velocity_conflict_scaling(d, no_conflict) is d

    def test_no_op_when_low_severity(self):
        d = _buy(side=TokenSide.DOWN)
        low = _conflict(0.3)
        assert apply_velocity_conflict_scaling(d, low) is d

    def test_no_op_when_buy_opposes_magnitude(self):
        """Buy UP when magnitude says DOWN → trading WITH velocity, no scaling."""
        d = _buy(side=TokenSide.UP)
        c = _conflict(0.8, mag_dir="DOWN", vel_dir="UP")
        assert apply_velocity_conflict_scaling(d, c) is d

    def test_moderate_conflict_scales_to_75pct(self):
        """Buy DOWN when magnitude says DOWN but velocity is UP → scale to 75%."""
        d = _buy(side=TokenSide.DOWN, size=100.0)
        c = _conflict(0.5, mag_dir="DOWN", vel_dir="UP")
        result = apply_velocity_conflict_scaling(d, c)
        assert result.size == 75.0
        assert result.action == Action.BUY

    def test_strong_conflict_scales_to_50pct(self):
        d = _buy(side=TokenSide.DOWN, size=100.0)
        c = _conflict(0.8, mag_dir="DOWN", vel_dir="UP")
        result = apply_velocity_conflict_scaling(d, c)
        assert result.size == 50.0

    def test_strong_conflict_boundary(self):
        d = _buy(side=TokenSide.DOWN, size=100.0)
        c = _conflict(0.7, mag_dir="DOWN", vel_dir="UP")
        result = apply_velocity_conflict_scaling(d, c)
        assert result.size == 50.0

    def test_up_side_conflict(self):
        """Buy UP when magnitude says UP but velocity is DOWN."""
        d = _buy(side=TokenSide.UP, size=80.0)
        c = _conflict(0.6, mag_dir="UP", vel_dir="DOWN")
        result = apply_velocity_conflict_scaling(d, c)
        assert result.size == 60.0  # 80 * 0.75

    def test_minimum_size_floor(self):
        d = _buy(side=TokenSide.DOWN, size=1.0)
        c = _conflict(0.8, mag_dir="DOWN", vel_dir="UP")
        result = apply_velocity_conflict_scaling(d, c)
        assert result.size >= 1.0


# ---------------------------------------------------------------------------
# apply_reversal_regime_scaling
# ---------------------------------------------------------------------------


class TestApplyReversalRegimeScaling:
    def test_no_op_for_hold(self):
        d = _hold()
        assert apply_reversal_regime_scaling(d, 0.8) is d

    def test_no_op_for_sell(self):
        d = _sell()
        assert apply_reversal_regime_scaling(d, 0.8) is d

    def test_no_op_below_threshold(self):
        d = _buy(size=100.0)
        assert apply_reversal_regime_scaling(d, 0.3) is d

    def test_moderate_scales_to_75pct(self):
        d = _buy(size=100.0)
        result = apply_reversal_regime_scaling(d, 0.45)
        assert result.size == 75.0
        assert result.action == Action.BUY

    def test_high_scales_to_50pct(self):
        d = _buy(size=100.0)
        result = apply_reversal_regime_scaling(d, 0.7)
        assert result.size == 50.0

    def test_boundary_0_35_scales(self):
        d = _buy(size=80.0)
        result = apply_reversal_regime_scaling(d, 0.35)
        assert result.size == 60.0  # 80 * 0.75

    def test_boundary_0_6_scales_to_50pct(self):
        d = _buy(size=100.0)
        result = apply_reversal_regime_scaling(d, 0.6)
        assert result.size == 50.0

    def test_minimum_size_floor(self):
        d = _buy(size=1.0)
        result = apply_reversal_regime_scaling(d, 0.8)
        assert result.size >= 1.0
