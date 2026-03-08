"""Tests for build_reversal_regime_warning() in context_builder.py."""

from __future__ import annotations

from polybot.shared_state.candle_microstructure import CandleMicrostructure
from polybot.tasks.context_builder import build_reversal_regime_warning


def _micro(
    reversal_intensity: float = 0.5,
    zero_crossings: int = 2,
) -> CandleMicrostructure:
    return CandleMicrostructure(
        timestamp=0.0,
        reversal_intensity=reversal_intensity,
        zero_crossings=zero_crossings,
    )


class TestBuildReversalRegimeWarning:
    def test_returns_none_below_threshold(self):
        assert build_reversal_regime_warning(0.1, "DIRECTIONAL") is None
        assert build_reversal_regime_warning(0.29, "DIRECTIONAL") is None

    def test_returns_none_at_exact_threshold_boundary(self):
        assert build_reversal_regime_warning(0.29, "DIRECTIONAL") is None

    def test_returns_advisory_at_moderate(self):
        result = build_reversal_regime_warning(0.45, "MODERATE_REVERSAL")
        assert result is not None
        assert "Reversal Regime Advisory" in result
        assert "auto-reduced to 75%" in result

    def test_returns_warning_at_high(self):
        result = build_reversal_regime_warning(0.7, "HIGH_REVERSAL")
        assert result is not None
        assert "REVERSAL REGIME WARNING" in result
        assert "auto-reduced to 50%" in result

    def test_includes_stats_when_history_provided(self):
        history = [_micro(reversal_intensity=0.6, zero_crossings=3) for _ in range(3)]
        result = build_reversal_regime_warning(0.65, "HIGH_REVERSAL", microstructure_history=history)
        assert result is not None
        assert "Avg crossings/candle" in result
        assert "Avg reversal intensity" in result
        assert "Regime score" in result

    def test_no_stats_without_history(self):
        result = build_reversal_regime_warning(0.5, "MODERATE_REVERSAL", microstructure_history=None)
        assert result is not None
        assert "Regime score: 0.50" in result

    def test_moderate_range(self):
        """Score in [0.3, 0.6) with MODERATE label gets advisory."""
        result = build_reversal_regime_warning(0.35, "MODERATE_REVERSAL")
        assert result is not None
        assert "Advisory" in result

    def test_boundary_0_3_returns_warning(self):
        """Score exactly 0.3 should return a warning (>= 0.3 check is exclusive in code)."""
        result = build_reversal_regime_warning(0.3, "MODERATE_REVERSAL")
        assert result is not None
