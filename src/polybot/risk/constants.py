"""Constants for the risk package."""

from __future__ import annotations

DATE_FORMAT: str = "%Y-%m-%d"
"""Date format for daily counter resets."""

DEFAULT_FILL_PRICE: float = 0.5
"""Fallback fill price when best ask/bid is unavailable."""

CASH_BUFFER_FACTOR: float = 1.005
"""Multiplier for cash sufficiency check (0.5% buffer for fees)."""

SHORT_SELL_TOLERANCE: float = 1e-9
"""Float tolerance for short-sell prevention check."""

DEPTH_RATIO_LIMIT: float = 0.5
"""Maximum fraction of orderbook depth an order can consume."""
