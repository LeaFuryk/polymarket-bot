"""Tests for ReversalRegimeIndicator — cross-candle reversal pattern detection."""

from __future__ import annotations

import pytest

from polybot.indicators.catalog.reversal_regime import ReversalRegimeIndicator
from polybot.indicators.context import IndicatorContext
from polybot.models.core import MarketSnapshot
from polybot.shared_state.candle_microstructure import CandleMicrostructure

CANDLE_OPEN = 65000.0


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


def _make_ctx(
    history: list[CandleMicrostructure],
    *,
    moves: list[float] | None = None,
) -> IndicatorContext:
    """Build an IndicatorContext with microstructure_history and optional live data."""
    btc_price_history = [CANDLE_OPEN + m for m in moves] if moves else []
    return IndicatorContext(
        snapshot=MarketSnapshot(
            condition_id="test",
            btc_price_history=btc_price_history,
        ),
        candle_open_btc=CANDLE_OPEN if moves else None,
        microstructure_history=tuple(history),
    )


class TestReversalRegimeIndicator:
    def test_returns_none_with_insufficient_history(self):
        indicator = ReversalRegimeIndicator()
        assert indicator.compute(_make_ctx([])) is None
        assert indicator.compute(_make_ctx([_micro()])) is None

    def test_directional_regime(self):
        """Low reversal intensity + zero crossings = DIRECTIONAL."""
        indicator = ReversalRegimeIndicator()
        history = [_micro(reversal_intensity=0.1, zero_crossings=0) for _ in range(3)]
        result = indicator.compute(_make_ctx(history))
        assert result is not None
        assert "DIRECTIONAL" in result.label
        assert result.value < 0.35

    def test_high_reversal_regime(self):
        """High reversal intensity + many crossings = HIGH_REVERSAL."""
        indicator = ReversalRegimeIndicator()
        history = [_micro(reversal_intensity=0.8, zero_crossings=5) for _ in range(3)]
        result = indicator.compute(_make_ctx(history))
        assert result is not None
        assert "HIGH_REVERSAL" in result.label
        assert result.value >= 0.6

    def test_moderate_reversal_regime(self):
        """Moderate values = MODERATE_REVERSAL."""
        indicator = ReversalRegimeIndicator()
        history = [_micro(reversal_intensity=0.5, zero_crossings=2) for _ in range(3)]
        result = indicator.compute(_make_ctx(history))
        assert result is not None
        assert "MODERATE_REVERSAL" in result.label
        assert 0.35 <= result.value < 0.6

    def test_score_clamped_to_0_1(self):
        """Score should never exceed 1.0."""
        indicator = ReversalRegimeIndicator()
        history = [_micro(reversal_intensity=1.0, zero_crossings=10) for _ in range(3)]
        result = indicator.compute(_make_ctx(history))
        assert result is not None
        assert 0.0 <= result.value <= 1.0

    def test_cross_candle_only_when_no_live_data(self):
        """Without live BTC data, score comes from cross-candle only."""
        indicator = ReversalRegimeIndicator()
        history = [_micro(reversal_intensity=0.6, zero_crossings=3) for _ in range(2)]
        result = indicator.compute(_make_ctx(history))
        assert result is not None
        # cross_candle_score = 0.5 * 0.6 + 0.5 * min(3/4, 1) = 0.3 + 0.375 = 0.675
        assert result.value == pytest.approx(0.675, abs=0.01)

    def test_live_data_blended(self):
        """Live BTC price data is blended at 40% weight."""
        indicator = ReversalRegimeIndicator()
        history = [_micro(reversal_intensity=0.0, zero_crossings=0) for _ in range(2)]
        # Live data with lots of crossings — moves oscillate around zero
        moves = [10.0, -10.0, 10.0, -10.0, 10.0, -10.0, 10.0, -10.0, 10.0, -10.0]
        result = indicator.compute(_make_ctx(history, moves=moves))
        assert result is not None
        # Cross-candle is 0.0, live has crossings + high intensity, blended at 40%
        assert result.value > 0.0

    def test_live_data_ignored_when_too_short(self):
        """Live data < 10 snapshots is ignored."""
        indicator = ReversalRegimeIndicator()
        history = [_micro(reversal_intensity=0.5, zero_crossings=2) for _ in range(2)]
        short_moves = [10.0, 20.0, 30.0]
        result_with = indicator.compute(_make_ctx(history, moves=short_moves))
        result_without = indicator.compute(_make_ctx(history))
        assert result_with is not None
        assert result_without is not None
        assert result_with.value == result_without.value

    def test_exactly_two_candles(self):
        """Minimum viable history (2 candles) works."""
        indicator = ReversalRegimeIndicator()
        history = [_micro(reversal_intensity=0.4, zero_crossings=1) for _ in range(2)]
        result = indicator.compute(_make_ctx(history))
        assert result is not None

    def test_mixed_candle_history(self):
        """Different candles with varying values produce weighted average."""
        indicator = ReversalRegimeIndicator()
        history = [
            _micro(reversal_intensity=0.0, zero_crossings=0),
            _micro(reversal_intensity=1.0, zero_crossings=8),
        ]
        result = indicator.compute(_make_ctx(history))
        assert result is not None
        # avg_intensity = 0.5, avg_crossings = 4.0 -> crossing_score = 1.0
        # cross_candle = 0.5 * 0.5 + 0.5 * 1.0 = 0.75
        assert result.value == pytest.approx(0.75, abs=0.01)
        assert "HIGH_REVERSAL" in result.label
