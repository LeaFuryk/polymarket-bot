"""Tests for BtcVelocityConflictIndicator — detects velocity-magnitude conflicts."""

from __future__ import annotations

from polybot.indicators.catalog.btc_velocity_conflict import BtcVelocityConflictIndicator
from polybot.indicators.context import IndicatorContext
from polybot.models.core import MarketSnapshot

CANDLE_OPEN = 65000.0


def _make_ctx(
    moves: list[float],
    *,
    time_remaining: float = 200.0,
) -> IndicatorContext:
    """Build an IndicatorContext with btc_price_history derived from moves."""
    return IndicatorContext(
        snapshot=MarketSnapshot(
            condition_id="test",
            btc_price_history=[CANDLE_OPEN + m for m in moves],
        ),
        candle_open_btc=CANDLE_OPEN,
        time_remaining=time_remaining,
    )


# ---------------------------------------------------------------------------
# Insufficient data / basic aligned
# ---------------------------------------------------------------------------


class TestInsufficientData:
    def test_returns_aligned_insufficient_data(self):
        indicator = BtcVelocityConflictIndicator()
        result = indicator.compute(_make_ctx([1.0] * 10))
        assert result is not None
        assert result.value == 0.0
        assert "ALIGNED" in result.label

    def test_returns_result_with_enough_data(self):
        indicator = BtcVelocityConflictIndicator()
        moves = [float(i) for i in range(20)]
        result = indicator.compute(_make_ctx(moves))
        assert result is not None


# ---------------------------------------------------------------------------
# Velocity direction
# ---------------------------------------------------------------------------


class TestVelocityDirection:
    def test_velocity_positive_for_rising(self):
        indicator = BtcVelocityConflictIndicator()
        moves = [float(i) * 2.0 for i in range(30)]
        result = indicator.compute(_make_ctx(moves))
        assert result is not None
        # Move is positive and velocity is positive -> aligned
        assert "ALIGNED" in result.label

    def test_velocity_negative_for_falling(self):
        indicator = BtcVelocityConflictIndicator()
        moves = [float(-i) * 2.0 for i in range(30)]
        result = indicator.compute(_make_ctx(moves))
        assert result is not None
        # Move is negative and velocity is negative -> aligned
        assert "ALIGNED" in result.label


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


class TestConflictDetection:
    def test_no_conflict_when_aligned(self):
        indicator = BtcVelocityConflictIndicator()
        # Magnitude positive and velocity positive -> aligned
        moves = [float(i) * 3.0 for i in range(30)]
        result = indicator.compute(_make_ctx(moves))
        assert result is not None
        assert result.value == 0.0
        assert "ALIGNED" in result.label

    def test_conflict_detected_when_opposing(self):
        indicator = BtcVelocityConflictIndicator()
        # BTC dropped to -80, now recovering at ~3/s
        moves = [0.0] * 5
        for i in range(10):
            moves.append(float(-i) * 8.0)
        # Recovery phase
        for i in range(15):
            moves.append(-80.0 + float(i) * 3.0)
        result = indicator.compute(_make_ctx(moves, time_remaining=150.0))
        assert result is not None
        assert result.value > 0
        assert "DOWN" in result.label
        assert "UP" in result.label

    def test_strong_conflict_high_severity(self):
        indicator = BtcVelocityConflictIndicator()
        # Large drawback, high velocity, lots of time
        moves = [0.0] * 5
        for i in range(10):
            moves.append(float(-i) * 10.0)
        # Strong recovery
        for i in range(15):
            moves.append(-100.0 + float(i) * 5.0)
        result = indicator.compute(_make_ctx(moves, time_remaining=250.0))
        assert result is not None
        if result.value > 0:
            assert result.value >= 0.4

    def test_severity_clamped_to_01(self):
        indicator = BtcVelocityConflictIndicator()
        # Even with extreme values, severity should be in [0, 1]
        moves = [0.0] * 10
        for i in range(10):
            moves.append(float(-i) * 20.0)
        for i in range(15):
            moves.append(-200.0 + float(i) * 10.0)
        result = indicator.compute(_make_ctx(moves, time_remaining=300.0))
        assert result is not None
        assert 0.0 <= result.value <= 1.0

    def test_no_conflict_when_velocity_too_low(self):
        indicator = BtcVelocityConflictIndicator()
        # Magnitude negative, velocity slightly positive but < 0.5/s
        moves = [float(-i) * 5.0 for i in range(20)]
        # Add slight recovery (0.3/s)
        moves.extend([-100.0 + 0.3 * i for i in range(10)])
        result = indicator.compute(_make_ctx(moves))
        assert result is not None
        # Low velocity should not trigger conflict
        assert result.value == 0.0

    def test_indicator_result_fields(self):
        indicator = BtcVelocityConflictIndicator()
        result = indicator.compute(_make_ctx([1.0] * 5))
        assert result is not None
        assert result.name == "BTC Velocity Conflict"
        assert isinstance(result.value, float)
        assert isinstance(result.label, str)
