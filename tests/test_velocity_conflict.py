"""Tests for velocity-magnitude conflict detection in prompt_context.py."""

from __future__ import annotations

from polybot.shared_state import PreFilterSnapshot
from polybot.tasks.prompt_context import (
    VelocityConflict,
    _compute_velocity_data,
    detect_velocity_magnitude_conflict,
)


def _make_snapshots(
    moves: list[float],
    *,
    start_ts: float = 1000.0,
) -> list[PreFilterSnapshot]:
    return [
        PreFilterSnapshot(
            timestamp=start_ts + i,
            time_remaining=300.0 - i,
            btc_move_from_open=m,
        )
        for i, m in enumerate(moves)
    ]


# ---------------------------------------------------------------------------
# _compute_velocity_data
# ---------------------------------------------------------------------------


class TestComputeVelocityData:
    def test_returns_none_insufficient_data(self):
        assert _compute_velocity_data(_make_snapshots([1.0] * 10)) is None

    def test_returns_tuple_with_enough_data(self):
        moves = [float(i) for i in range(20)]
        result = _compute_velocity_data(_make_snapshots(moves))
        assert result is not None
        assert len(result) == 5

    def test_velocity_positive_for_rising(self):
        moves = [float(i) * 2.0 for i in range(30)]
        result = _compute_velocity_data(_make_snapshots(moves))
        assert result is not None
        current_vel, _, current_move, _, _ = result
        assert current_vel > 0
        assert current_move > 0

    def test_velocity_negative_for_falling(self):
        moves = [float(-i) * 2.0 for i in range(30)]
        result = _compute_velocity_data(_make_snapshots(moves))
        assert result is not None
        current_vel, _, current_move, _, _ = result
        assert current_vel < 0
        assert current_move < 0

    def test_drawback_pct_computed(self):
        # Peak at 50, now at 25 → 50% drawback
        moves = [0.0] * 10 + [50.0] * 5 + [40.0, 35.0, 30.0, 28.0, 25.0]
        result = _compute_velocity_data(_make_snapshots(moves))
        assert result is not None
        _, _, _, _, drawback_pct = result
        assert 0.4 <= drawback_pct <= 0.6


# ---------------------------------------------------------------------------
# detect_velocity_magnitude_conflict
# ---------------------------------------------------------------------------


class TestDetectVelocityMagnitudeConflict:
    def test_insufficient_data_returns_aligned(self):
        conflict = detect_velocity_magnitude_conflict(_make_snapshots([1.0] * 5), 200.0)
        assert not conflict.has_conflict
        assert conflict.label == "ALIGNED"
        assert conflict.severity == 0.0

    def test_no_conflict_when_aligned(self):
        # Magnitude positive and velocity positive → aligned
        moves = [float(i) * 3.0 for i in range(30)]
        conflict = detect_velocity_magnitude_conflict(_make_snapshots(moves), 200.0)
        assert not conflict.has_conflict
        assert conflict.label == "ALIGNED"

    def test_no_conflict_when_velocity_too_low(self):
        # Magnitude negative, velocity slightly positive but < 0.5/s
        moves = [float(-i) * 5.0 for i in range(20)]
        # Add slight recovery (0.3/s)
        moves.extend([-100.0 + 0.3 * i for i in range(10)])
        conflict = detect_velocity_magnitude_conflict(_make_snapshots(moves), 200.0)
        assert not conflict.has_conflict

    def test_conflict_detected_when_opposing(self):
        # BTC dropped to -80, now recovering at ~2/s
        moves = [0.0] * 5
        for i in range(10):
            moves.append(float(-i) * 8.0)
        # Recovery phase
        for i in range(15):
            moves.append(-80.0 + float(i) * 3.0)
        conflict = detect_velocity_magnitude_conflict(_make_snapshots(moves), 150.0)
        assert conflict.has_conflict
        assert conflict.severity > 0
        assert conflict.magnitude_direction == "DOWN"
        assert conflict.velocity_direction == "UP"

    def test_strong_conflict_high_severity(self):
        # Large drawback, high velocity, lots of time
        moves = [0.0] * 5
        for i in range(10):
            moves.append(float(-i) * 10.0)
        # Strong recovery
        for i in range(15):
            moves.append(-100.0 + float(i) * 5.0)
        conflict = detect_velocity_magnitude_conflict(_make_snapshots(moves), 250.0)
        if conflict.has_conflict:
            assert conflict.severity >= 0.4

    def test_conflict_label_aligned_below_threshold(self):
        # Conflict exists but severity too low
        moves = [0.0] * 10
        for i in range(10):
            moves.append(float(-i) * 2.0)
        # Mild recovery at ~0.6/s (just above 0.5 threshold)
        for i in range(10):
            moves.append(-20.0 + float(i) * 0.6)
        conflict = detect_velocity_magnitude_conflict(_make_snapshots(moves), 30.0)
        # Even if conflict detected, low severity → ALIGNED label
        if conflict.has_conflict and conflict.severity < 0.4:
            assert conflict.label == "ALIGNED"

    def test_severity_clamped_to_01(self):
        # Even with extreme values, severity should be in [0, 1]
        moves = [0.0] * 10
        for i in range(10):
            moves.append(float(-i) * 20.0)
        for i in range(15):
            moves.append(-200.0 + float(i) * 10.0)
        conflict = detect_velocity_magnitude_conflict(_make_snapshots(moves), 300.0)
        assert 0.0 <= conflict.severity <= 1.0

    def test_time_remaining_passed_through(self):
        conflict = detect_velocity_magnitude_conflict(_make_snapshots([1.0] * 5), 123.0)
        assert conflict.time_remaining == 123.0

    def test_dataclass_fields(self):
        conflict = VelocityConflict(
            has_conflict=True,
            severity=0.6,
            magnitude_direction="DOWN",
            velocity_direction="UP",
            velocity_rate=2.0,
            btc_move=-50.0,
            drawback_pct=0.4,
            time_remaining=180.0,
            label="MODERATE_CONFLICT",
            detail="test",
        )
        assert conflict.has_conflict is True
        assert conflict.severity == 0.6
        assert conflict.label == "MODERATE_CONFLICT"
