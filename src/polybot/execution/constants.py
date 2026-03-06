"""Constants for the execution package."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Polymarket CLOB signature & order defaults
# ---------------------------------------------------------------------------

SIGNATURE_TYPE: int = 2
"""POLY_GNOSIS_SAFE — Polymarket browser wallet proxy signature type."""

FEE_RATE_BPS: int = 0
"""Fee rate (basis points) passed to ``OrderArgs`` when creating orders."""

ORDER_EXPIRATION: int = 0
"""Order expiration passed to ``OrderArgs`` (0 = no expiry, rely on GTC + TTL cancel)."""

# ---------------------------------------------------------------------------
# Polymarket fee schedule
# ---------------------------------------------------------------------------

TAKER_FEE_BPS: int = 20
"""Polymarket taker fee in basis points (0.20%)."""

BPS_DIVISOR: int = 10_000
"""Divisor converting basis points to a decimal fraction."""

# ---------------------------------------------------------------------------
# Balance / unit conversion
# ---------------------------------------------------------------------------

USDC_DECIMALS: float = 1e6
"""Raw USDC and conditional-token balances use 6 decimal places."""

# ---------------------------------------------------------------------------
# Polling & timing
# ---------------------------------------------------------------------------

POLL_INTERVAL_SECONDS: float = 1.0
"""Seconds between each order-status poll during TTL window."""

POST_CANCEL_WAIT_SECONDS: float = 1.0
"""Seconds to wait after cancel before verifying fill status."""

# ---------------------------------------------------------------------------
# Stealth fill detection
# ---------------------------------------------------------------------------

STEALTH_FILL_TOLERANCE: float = 0.90
"""Minimum fraction of expected size for a balance delta to count as a fill.

A delta >= ``expected_size * STEALTH_FILL_TOLERANCE`` is treated as filled.
Default 0.90 allows 10% tolerance for on-chain rounding.
"""
