"""Fakeout-based threshold computation.

Analyzes recent candle outcomes to determine optimal BTC move threshold
and max entry price. Two strategies:

1. **Fakeout-based** (preferred): uses peak wrong-direction moves to set
   threshold above typical fakeout noise.
2. **V-shaped fallback**: simple formula when peak data is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass

from polybot.adaptive_entry.constants import (
    ADAPTIVE_CAP_MAX,
    ADAPTIVE_CAP_MIN,
    BTC_THRESHOLD_MIN,
    CONTRARIAN_LOWER,
    DEFAULT_BTC_THRESHOLD,
    DEFAULT_MAX_ENTRY,
    ENTRY_BUFFER,
    FAKEOUT_P75_MULTIPLIER,
    FAKEOUT_WINDOW,
    MAX_ENTRY_CAP,
    MOMENTUM_UPPER,
    V_SHAPE_MAX_THRESHOLD,
    V_SHAPE_SLOPE,
)
from polybot.adaptive_entry.models import CandleOutcome


@dataclass
class ThresholdResult:
    """Output of threshold computation."""

    btc_threshold: float
    max_entry_price: float
    signal_type: str  # MOMENTUM / CONTRARIAN / UNCERTAIN
    using_fakeout: bool
    fakeout_p75: float
    fakeout_max: float
    fakeout_median: float
    adaptive_cap: float


def compute_thresholds(
    history: list[CandleOutcome],
    window: int,
) -> ThresholdResult:
    """Compute adaptive thresholds from rolling candle history.

    Args:
        history: Full candle history (will be sliced to last ``window``).
        window: Number of candles to use for statistics.

    Returns:
        ThresholdResult with all computed values.
    """
    recent = history[-window:]

    if len(recent) < window:
        return ThresholdResult(
            btc_threshold=DEFAULT_BTC_THRESHOLD,
            max_entry_price=DEFAULT_MAX_ENTRY,
            signal_type="UNCERTAIN",
            using_fakeout=False,
            fakeout_p75=0.0,
            fakeout_max=0.0,
            fakeout_median=0.0,
            adaptive_cap=ADAPTIVE_CAP_MIN,
        )

    # Reversal rate
    reversals = sum(1 for c in recent if c.reversed)
    reversal_rate = reversals / len(recent)

    # Fakeout magnitudes from shorter window
    fakeout_window = history[-FAKEOUT_WINDOW:]
    fakeout_magnitudes = []
    for c in fakeout_window:
        if c.peak_up_move > 0 or c.peak_down_move > 0:
            if c.winner == "up":
                fakeout_magnitudes.append(c.peak_down_move)
            else:
                fakeout_magnitudes.append(c.peak_up_move)

    if fakeout_magnitudes:
        sorted_fakeouts = sorted(fakeout_magnitudes)
        n = len(sorted_fakeouts)
        p75_idx = int(n * 0.75)
        p50_idx = int(n * 0.50)
        fakeout_p75 = sorted_fakeouts[min(p75_idx, n - 1)]
        fakeout_median = sorted_fakeouts[min(p50_idx, n - 1)]
        fakeout_max = sorted_fakeouts[-1]
        using_fakeout = True

        adaptive_cap = max(ADAPTIVE_CAP_MIN, min(ADAPTIVE_CAP_MAX, fakeout_p75 * FAKEOUT_P75_MULTIPLIER))
        btc_threshold = max(BTC_THRESHOLD_MIN, min(adaptive_cap, fakeout_median))
    else:
        using_fakeout = False
        fakeout_p75 = 0.0
        fakeout_median = 0.0
        fakeout_max = 0.0
        adaptive_cap = ADAPTIVE_CAP_MIN

        deviation = abs(reversal_rate - 0.5)
        btc_threshold = max(
            BTC_THRESHOLD_MIN, min(V_SHAPE_MAX_THRESHOLD, V_SHAPE_MAX_THRESHOLD - deviation * V_SHAPE_SLOPE)
        )

    # Signal type
    if reversal_rate > CONTRARIAN_LOWER:
        signal_type = "CONTRARIAN"
    elif reversal_rate < MOMENTUM_UPPER:
        signal_type = "MOMENTUM"
    else:
        signal_type = "UNCERTAIN"

    # Max entry price from avg winner ask
    winner_asks = [c.winner_ask_at_20 for c in recent if c.winner_ask_at_20 > 0]
    if winner_asks:
        avg_winner_ask = sum(winner_asks) / len(winner_asks)
        max_entry_price = min(avg_winner_ask + ENTRY_BUFFER, MAX_ENTRY_CAP)
    else:
        max_entry_price = DEFAULT_MAX_ENTRY

    return ThresholdResult(
        btc_threshold=btc_threshold,
        max_entry_price=max_entry_price,
        signal_type=signal_type,
        using_fakeout=using_fakeout,
        fakeout_p75=fakeout_p75,
        fakeout_max=fakeout_max,
        fakeout_median=fakeout_median,
        adaptive_cap=adaptive_cap,
    )
