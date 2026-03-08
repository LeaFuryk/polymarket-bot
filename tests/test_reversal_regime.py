"""Tests for compute_reversal_regime() in prompt_context.py."""

from __future__ import annotations

import pytest

from polybot.shared_state import PreFilterSnapshot
from polybot.shared_state.candle_microstructure import CandleMicrostructure
from polybot.tasks.prompt_context import compute_reversal_regime


def _micro(
    reversal_intensity: float = 0.0,
    zero_crossings: int = 0,
    btc_range: float = 100.0,
    btc_final_move: float = 50.0,
) -> CandleMicrostructure:
    return CandleMicrostructure(
        timestamp=0.0,
        reversal_intensity=reversal_intensity,
        zero_crossings=zero_crossings,
        btc_range=btc_range,
        btc_final_move=btc_final_move,
    )


def _prefilter_snapshots(moves: list[float]) -> list[PreFilterSnapshot]:
    """Create minimal PreFilterSnapshot objects with given btc_move_from_open values."""
    return [
        PreFilterSnapshot(
            timestamp=float(i),
            time_remaining=300.0 - i,
            btc_move_from_open=m,
            up_spread_pct=0.02,
            down_spread_pct=0.02,
        )
        for i, m in enumerate(moves)
    ]


class TestComputeReversalRegime:
    def test_returns_none_with_insufficient_history(self):
        assert compute_reversal_regime([]) is None
        assert compute_reversal_regime([_micro()]) is None

    def test_directional_regime(self):
        """Low reversal intensity + zero crossings = DIRECTIONAL."""
        history = [_micro(reversal_intensity=0.1, zero_crossings=0) for _ in range(3)]
        result = compute_reversal_regime(history)
        assert result is not None
        score, label = result
        assert label == "DIRECTIONAL"
        assert score < 0.35

    def test_high_reversal_regime(self):
        """High reversal intensity + many crossings = HIGH_REVERSAL."""
        history = [_micro(reversal_intensity=0.8, zero_crossings=5) for _ in range(3)]
        result = compute_reversal_regime(history)
        assert result is not None
        score, label = result
        assert label == "HIGH_REVERSAL"
        assert score >= 0.6

    def test_moderate_reversal_regime(self):
        """Moderate values = MODERATE_REVERSAL."""
        history = [_micro(reversal_intensity=0.5, zero_crossings=2) for _ in range(3)]
        result = compute_reversal_regime(history)
        assert result is not None
        score, label = result
        assert label == "MODERATE_REVERSAL"
        assert 0.35 <= score < 0.6

    def test_score_clamped_to_0_1(self):
        """Score should never exceed 1.0."""
        history = [_micro(reversal_intensity=1.0, zero_crossings=10) for _ in range(3)]
        result = compute_reversal_regime(history)
        assert result is not None
        score, _ = result
        assert 0.0 <= score <= 1.0

    def test_cross_candle_only_when_no_live_data(self):
        """Without live prefilter data, score comes from cross-candle only."""
        history = [_micro(reversal_intensity=0.6, zero_crossings=3) for _ in range(2)]
        result = compute_reversal_regime(history, current_prefilter_history=None)
        assert result is not None
        score, _ = result
        # cross_candle_score = 0.5 * 0.6 + 0.5 * min(3/4, 1) = 0.3 + 0.375 = 0.675
        assert score == pytest.approx(0.675, abs=0.01)

    def test_live_data_blended(self):
        """Live prefilter data is blended at 40% weight."""
        history = [_micro(reversal_intensity=0.0, zero_crossings=0) for _ in range(2)]
        # Live data with lots of crossings — moves oscillate around zero
        moves = [10, -10, 10, -10, 10, -10, 10, -10, 10, -10]
        prefilter = _prefilter_snapshots(moves)
        result = compute_reversal_regime(history, current_prefilter_history=prefilter)
        assert result is not None
        score, _ = result
        # Cross-candle is 0.0, live has crossings + high intensity, blended at 40%
        assert score > 0.0

    def test_live_data_ignored_when_too_short(self):
        """Live data < 10 snapshots is ignored."""
        history = [_micro(reversal_intensity=0.5, zero_crossings=2) for _ in range(2)]
        short_prefilter = _prefilter_snapshots([10, 20, 30])
        result_with = compute_reversal_regime(history, current_prefilter_history=short_prefilter)
        result_without = compute_reversal_regime(history, current_prefilter_history=None)
        assert result_with is not None
        assert result_without is not None
        assert result_with[0] == result_without[0]

    def test_exactly_two_candles(self):
        """Minimum viable history (2 candles) works."""
        history = [_micro(reversal_intensity=0.4, zero_crossings=1) for _ in range(2)]
        result = compute_reversal_regime(history)
        assert result is not None

    def test_mixed_candle_history(self):
        """Different candles with varying values produce weighted average."""
        history = [
            _micro(reversal_intensity=0.0, zero_crossings=0),
            _micro(reversal_intensity=1.0, zero_crossings=8),
        ]
        result = compute_reversal_regime(history)
        assert result is not None
        score, label = result
        # avg_intensity = 0.5, avg_crossings = 4.0 → crossing_score = 1.0
        # cross_candle = 0.5 * 0.5 + 0.5 * 1.0 = 0.75
        assert score == pytest.approx(0.75, abs=0.01)
        assert label == "HIGH_REVERSAL"
