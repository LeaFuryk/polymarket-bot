"""Tests for technical indicator functions."""

import pytest
from polybot.domain.models import Candle
from polybot.services.technicals import (
    atr_normalized,
    bollinger_pct_b,
    macd_histogram,
    rsi,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# 40 BTC closes for testing (realistic-ish prices, enough for MACD which needs 35+)
CLOSES = [
    67500,
    67520,
    67480,
    67550,
    67600,
    67580,
    67620,
    67650,
    67630,
    67700,
    67680,
    67720,
    67750,
    67730,
    67770,
    67800,
    67780,
    67820,
    67850,
    67830,
    67870,
    67900,
    67880,
    67920,
    67950,
    67930,
    67970,
    68000,
    67980,
    68020,
    68050,
    68030,
    68070,
    68100,
    68080,
    68120,
    68150,
    68130,
    68170,
    68200,
]


def _make_candles(closes: list[float], spread: float = 50.0) -> list[Candle]:
    """Create candles with synthetic high/low from closes."""
    candles = []
    for i, close in enumerate(closes):
        candles.append(
            Candle(
                open=close - 10,
                high=close + spread / 2,
                low=close - spread / 2,
                close=close,
                volume=10.0,
                start_time=i * 300.0,
                end_time=(i + 1) * 300.0,
            )
        )
    return candles


# ---------------------------------------------------------------------------
# RSI tests
# ---------------------------------------------------------------------------


class TestRSI:
    def test_insufficient_data(self):
        assert rsi([100, 101, 102]) is None
        assert rsi(list(range(14))) is None  # 14 closes = 13 deltas, need 14

    def test_sufficient_data(self):
        result = rsi(CLOSES)
        assert result is not None
        assert 0 <= result <= 100

    def test_all_gains_returns_100(self):
        closes = [100 + i for i in range(20)]  # monotonically rising
        result = rsi(closes)
        assert result == 100.0

    def test_all_losses_returns_0(self):
        closes = [200 - i for i in range(20)]  # monotonically falling
        result = rsi(closes)
        assert result == 0.0

    def test_flat_series_returns_50(self):
        closes = [100.0] * 20
        result = rsi(closes)
        assert result == 50.0

    def test_typical_range(self):
        result = rsi(CLOSES)
        # Trending up slightly, expect RSI > 50
        assert 40 < result < 90


# ---------------------------------------------------------------------------
# MACD tests
# ---------------------------------------------------------------------------


class TestMACD:
    def test_insufficient_data(self):
        assert macd_histogram(CLOSES[:25]) is None

    def test_sufficient_data(self):
        result = macd_histogram(CLOSES)
        assert result is not None

    def test_returns_float(self):
        result = macd_histogram(CLOSES)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# Bollinger %B tests
# ---------------------------------------------------------------------------


class TestBollingerPctB:
    def test_insufficient_data(self):
        assert bollinger_pct_b([100, 101]) is None
        assert bollinger_pct_b(list(range(19))) is None

    def test_sufficient_data(self):
        result = bollinger_pct_b(CLOSES)
        assert result is not None

    def test_at_middle_band(self):
        # Flat prices → close is at the mean → %B = 0.5
        flat = [100.0] * 20
        result = bollinger_pct_b(flat)
        assert result == pytest.approx(0.5)

    def test_range_is_reasonable(self):
        result = bollinger_pct_b(CLOSES)
        # Trending up, expect %B > 0.5 but within reasonable range
        assert -0.5 < result < 1.5


# ---------------------------------------------------------------------------
# ATR normalized tests
# ---------------------------------------------------------------------------


class TestATRNormalized:
    def test_insufficient_data(self):
        candles = _make_candles(CLOSES[:14])
        assert atr_normalized(candles) is None

    def test_sufficient_data(self):
        candles = _make_candles(CLOSES)
        result = atr_normalized(candles)
        assert result is not None
        assert result > 0

    def test_normalized_is_small(self):
        # With spread=50 and prices ~67k, normalized ATR should be tiny
        candles = _make_candles(CLOSES, spread=50.0)
        result = atr_normalized(candles)
        assert result < 0.01  # Less than 1%

    def test_higher_volatility_higher_atr(self):
        low_vol = _make_candles(CLOSES, spread=20.0)
        high_vol = _make_candles(CLOSES, spread=200.0)
        assert atr_normalized(high_vol) > atr_normalized(low_vol)
