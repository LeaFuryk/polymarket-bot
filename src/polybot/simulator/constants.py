"""Constants for the simulator package."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Execution engine — slippage & pricing
# ---------------------------------------------------------------------------

THIN_BOOK_PENALTY_FACTOR: float = 3.0
"""Multiplier applied to base slippage when total liquidity is zero."""

BPS_DIVISOR: float = 10_000.0
"""Basis points to decimal conversion factor."""

FILL_PRICE_MIN: float = 0.001
"""Minimum fill price for prediction market tokens."""

FILL_PRICE_MAX: float = 0.999
"""Maximum fill price for prediction market tokens."""

# ---------------------------------------------------------------------------
# Portfolio — position management
# ---------------------------------------------------------------------------

DOWN_PRICE_FLOOR: float = 0.01
"""Minimum inferred down-token price when not provided."""

OVERSELL_TOLERANCE: float = 1e-9
"""Float tolerance for detecting sell-more-than-held."""

WINNING_TOKEN_PAYOUT: float = 1.0
"""Payout per share of the winning token at resolution."""

LOSING_TOKEN_PAYOUT: float = 0.0
"""Payout per share of the losing token at resolution."""
