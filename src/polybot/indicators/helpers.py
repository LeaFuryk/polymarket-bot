"""Shared helpers for indicator implementations."""

from __future__ import annotations

import statistics


def ema(values: list[float], period: int) -> float:
    """Exponential moving average of the last *period* values."""
    if len(values) < period:
        return statistics.mean(values)
    k = 2 / (period + 1)
    result = values[-period]
    for v in values[-period + 1 :]:
        result = v * k + result * (1 - k)
    return result


def compute_rr(ask: float) -> float:
    """Risk/reward ratio for binary options: entry at *ask* -> max profit = 1 - ask."""
    return (1.0 - ask) / ask if ask > 0 else 0.0
