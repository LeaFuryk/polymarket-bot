"""Tests for build_velocity_conflict_warning in context_builder.py."""

from __future__ import annotations

from polybot.tasks.context_builder import build_velocity_conflict_warning
from polybot.tasks.prompt_context import VelocityConflict


def _conflict(severity: float, **kwargs) -> VelocityConflict:
    defaults = dict(
        has_conflict=severity >= 0.3,
        severity=severity,
        magnitude_direction="DOWN",
        velocity_direction="UP",
        velocity_rate=2.0,
        btc_move=-50.0,
        drawback_pct=0.4,
        time_remaining=180.0,
        label="MODERATE_CONFLICT" if severity >= 0.4 else "ALIGNED",
        detail="test",
    )
    defaults.update(kwargs)
    return VelocityConflict(**defaults)


class TestBuildVelocityConflictWarning:
    def test_returns_none_below_threshold(self):
        assert build_velocity_conflict_warning(_conflict(0.0)) is None
        assert build_velocity_conflict_warning(_conflict(0.1)) is None
        assert build_velocity_conflict_warning(_conflict(0.29)) is None

    def test_returns_none_at_threshold_boundary(self):
        # Severity 0.3 is the exact boundary — should return a warning
        result = build_velocity_conflict_warning(_conflict(0.3))
        assert result is not None

    def test_moderate_conflict_text(self):
        result = build_velocity_conflict_warning(_conflict(0.5))
        assert result is not None
        assert "## Velocity-Magnitude Conflict" in result
        assert "auto-reduced to 75%" in result
        assert "DOWN" in result
        assert "UP" in result

    def test_strong_conflict_text(self):
        result = build_velocity_conflict_warning(_conflict(0.75, label="STRONG_CONFLICT"))
        assert result is not None
        assert "## VELOCITY-MAGNITUDE CONFLICT WARNING" in result
        assert "auto-reduced to 50%" in result
        assert "Still trade" in result

    def test_moderate_boundary(self):
        # 0.4 is moderate
        result = build_velocity_conflict_warning(_conflict(0.4))
        assert result is not None
        assert "auto-reduced to 75%" in result

    def test_strong_boundary(self):
        # 0.7 is strong
        result = build_velocity_conflict_warning(_conflict(0.7, label="STRONG_CONFLICT"))
        assert result is not None
        assert "auto-reduced to 50%" in result

    def test_includes_velocity_rate(self):
        result = build_velocity_conflict_warning(_conflict(0.5, velocity_rate=3.5))
        assert "$+3.5/s" in result

    def test_includes_btc_move(self):
        result = build_velocity_conflict_warning(_conflict(0.5, btc_move=-80.0))
        assert "-80" in result

    def test_includes_drawback_pct(self):
        result = build_velocity_conflict_warning(_conflict(0.5, drawback_pct=0.65))
        assert "65%" in result

    def test_includes_time_remaining(self):
        result = build_velocity_conflict_warning(_conflict(0.5, time_remaining=120.0))
        assert "120s" in result
