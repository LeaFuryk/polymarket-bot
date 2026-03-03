"""Pure-function signal computations used by filters.

These are stateless helpers that compute market signals from raw data.
Extracted so filters and the composite can share them without coupling.
"""

from __future__ import annotations

from polybot.models import BtcCandle, MarketSnapshot
from polybot.prefilter.constants import BTC_RANGE_CANDLE_WINDOW, DEFAULT_BEST_ENTRY


def compute_streak(candles: list[BtcCandle]) -> tuple[int, str]:
    """Count consecutive same-direction candles from the most recent."""
    if not candles:
        return 0, ""
    streak = 1
    direction = candles[-1].direction
    for c in reversed(candles[:-1]):
        if c.direction == direction:
            streak += 1
        else:
            break
    return streak, direction


def compute_btc_range_30m(candles: list[BtcCandle]) -> float:
    """Compute BTC price range over the last ~30 minutes."""
    if len(candles) < 2:
        return 0.0
    recent = candles[-BTC_RANGE_CANDLE_WINDOW:]
    highs = [c.high for c in recent]
    lows = [c.low for c in recent]
    return max(highs) - min(lows)


def compute_best_entry(snapshot: MarketSnapshot) -> float:
    """Find the cheapest entry price across both tokens.

    Lower price = better risk/reward for binary options.
    """
    prices = []
    up_ask = snapshot.orderbook.best_ask
    down_ask = snapshot.down_orderbook.best_ask
    if up_ask is not None:
        prices.append(up_ask)
    if down_ask is not None:
        prices.append(down_ask)
    return min(prices) if prices else DEFAULT_BEST_ENTRY
