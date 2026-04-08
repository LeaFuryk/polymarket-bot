"""Stateless technical indicator functions computed from candle data."""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from polybot_data.domain.models import Candle


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


def trend_consistency(closes: Sequence[float], window: int = 10) -> float | None:
    """mean(sign(log_ret)) over last `window` candles. Range [-1, 1]."""
    if len(closes) < window + 1:
        return None
    recent = closes[-(window + 1) :]
    signs = []
    for i in range(1, len(recent)):
        if recent[i - 1] <= 0:
            continue
        lr = math.log(recent[i] / recent[i - 1])
        signs.append(1.0 if lr > 0 else -1.0 if lr < 0 else 0.0)
    if not signs:
        return None
    return sum(signs) / len(signs)


def range_position(candles: Sequence[Candle], last_price: float, window: int = 40) -> float | None:
    """(last_price - session_low) / (session_high - session_low) over last `window` candles."""
    if not candles:
        return None
    recent = candles[-window:]
    session_high = max(c.high for c in recent)
    session_low = min(c.low for c in recent)
    rng = session_high - session_low
    if rng == 0:
        return 0.5
    return max(0.0, min(1.0, (last_price - session_low) / rng))


def ma_crossover(closes: Sequence[float]) -> tuple[float, float, str] | None:
    """MA5 vs MA12 crossover. Returns (ma5, ma12, 'BULLISH'|'BEARISH') or None."""
    if len(closes) < 12:
        return None
    ma5 = sum(closes[-5:]) / 5
    ma12 = sum(closes[-12:]) / 12
    signal = "BULLISH" if ma5 > ma12 else "BEARISH"
    return (ma5, ma12, signal)


def trend_score(candles: Sequence[Candle], window: int = 12) -> float | None:
    """Weighted directional score. Range [-1, 1]. Needs 12+ candles."""
    if len(candles) < window:
        return None
    recent = candles[-window:]
    up_count = sum(1 for c in recent if c.close >= c.open)
    up_ratio = up_count / len(recent)
    candle_sig = (up_ratio - 0.5) * 2

    closes = [c.close for c in candles]
    ma5 = sum(closes[-5:]) / 5
    ma12 = sum(closes[-12:]) / 12
    price_now = closes[-1]

    ema_sig = max(-1.0, min(1.0, (ma5 - ma12) / 100))
    price_sig = max(-1.0, min(1.0, (price_now - ma12) / 150))

    score = max(-1.0, min(1.0, 0.4 * ema_sig + 0.35 * price_sig + 0.25 * candle_sig))
    return score


def velocity_conflict(
    last_price: float | None,
    candle_open: float | None,
    candles: Sequence[Candle],
) -> tuple[str, float]:
    """Detect conflict between BTC magnitude and recent velocity.
    Returns (label, severity). Label: NONE/MODERATE/STRONG. Severity: 0.0-1.0.
    """
    if last_price is None or candle_open is None or len(candles) < 3:
        return ("NONE", 0.0)
    magnitude = last_price - candle_open
    if abs(magnitude) < 5:
        return ("NONE", 0.0)
    mag_dir = 1.0 if magnitude > 0 else -1.0
    recent = candles[-3:]
    vel = recent[-1].close - recent[0].open
    if abs(vel) < 2:
        return ("NONE", 0.0)
    vel_dir = 1.0 if vel > 0 else -1.0
    if mag_dir == vel_dir:
        return ("NONE", 0.0)
    severity = min(1.0, abs(vel) / abs(magnitude))
    if severity >= 0.7:
        return ("STRONG", severity)
    elif severity >= 0.4:
        return ("MODERATE", severity)
    return ("NONE", severity)


def reversal_regime(candles: Sequence[Candle]) -> tuple[str, float]:
    """Detect reversal regime from candle direction patterns.
    Returns (label, score). Label: DIRECTIONAL/MODERATE/HIGH. Score: 0.0-1.0.
    """
    if len(candles) < 4:
        return ("DIRECTIONAL", 0.0)
    recent = candles[-12:] if len(candles) >= 12 else candles
    directions = [1 if c.close >= c.open else -1 for c in recent]
    reversals = sum(1 for i in range(1, len(directions)) if directions[i] != directions[i - 1])
    max_reversals = len(directions) - 1
    reversal_rate = reversals / max_reversals if max_reversals > 0 else 0.0
    intensities = []
    for c in recent:
        rng = c.high - c.low
        body = abs(c.close - c.open)
        if rng > 0:
            intensities.append(1.0 - body / rng)
    avg_intensity = sum(intensities) / len(intensities) if intensities else 0.0
    score = max(0.0, min(1.0, 0.5 * reversal_rate + 0.5 * avg_intensity))
    if score >= 0.6:
        return ("HIGH", score)
    elif score >= 0.35:
        return ("MODERATE", score)
    return ("DIRECTIONAL", score)
