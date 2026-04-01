"""Stateless technical indicator functions computed from candle data."""

from __future__ import annotations

import statistics
from collections.abc import Sequence

from polybot.domain.models import Candle


def _ema(values: Sequence[float], period: int) -> list[float]:
    """Compute exponential moving average series."""
    if len(values) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    """RSI(14). Needs period+1 closes minimum."""
    if len(closes) < period + 1:
        return None

    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_gain == 0 and avg_loss == 0:
        return 50.0  # indeterminate — no movement
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd_histogram(closes: Sequence[float]) -> float | None:
    """MACD histogram (MACD line - signal line). Needs 35+ closes."""
    if len(closes) < 35:
        return None

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)

    # Align: ema12 starts at index 12, ema26 at index 26
    # We need the overlap region
    offset = 26 - 12  # = 14
    macd_line = [ema12[offset + i] - ema26[i] for i in range(len(ema26))]

    if len(macd_line) < 9:
        return None

    signal = _ema(macd_line, 9)
    if not signal:
        return None

    return macd_line[-1] - signal[-1]


def bollinger_pct_b(closes: Sequence[float], period: int = 20, num_std: float = 2.0) -> float | None:
    """Bollinger %B. 0 = lower band, 1 = upper band. Needs period closes."""
    if len(closes) < period:
        return None

    window = closes[-period:]
    mid = statistics.mean(window)
    std = statistics.pstdev(window)

    if std == 0:
        return 0.5

    upper = mid + num_std * std
    lower = mid - num_std * std
    band_width = upper - lower

    if band_width == 0:
        return 0.5

    return (closes[-1] - lower) / band_width


def atr_normalized(candles: Sequence[Candle], period: int = 14) -> float | None:
    """ATR(14) / close. Needs period+1 candles."""
    if len(candles) < period + 1:
        return None

    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        high = candles[i].high
        low = candles[i].low
        prev_c = candles[i - 1].close
        tr = max(high - low, abs(high - prev_c), abs(low - prev_c))
        true_ranges.append(tr)

    # Wilder's smoothing (same as RSI smoothing)
    atr = sum(true_ranges[:period]) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period

    last_close = candles[-1].close
    if last_close == 0:
        return None

    return atr / last_close
