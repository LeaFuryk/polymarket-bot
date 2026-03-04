"""Constants for the forensics package."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Feature B: TTL counterfactuals
# ---------------------------------------------------------------------------

DEFAULT_TTL_GRID: list[int] = [1, 3, 5, 10, 20, 30, 60]

# ---------------------------------------------------------------------------
# Feature D: Blocked order classification
# ---------------------------------------------------------------------------

RISK_CATEGORY_MAP: list[tuple[str, str]] = [
    ("kill switch", "kill_switch"),
    ("no token_id", "no_token_id"),
    ("no ask", "no_book"),
    ("no bid", "no_book"),
    ("no orderbook", "no_book"),
    ("exceeds max", "max_size"),
    ("wallet below min", "low_balance"),
    ("insufficient balance", "low_balance"),
    ("limit order timeout", "timeout"),
    ("no on-chain token balance", "no_token_balance"),
    ("execution error", "error"),
    ("dry run", "dry_run"),
]

TTL_RESCUE_WINDOW_S: float = 60.0
"""Max seconds after submit to check for price improvement (timeout rescue)."""

REPRICE_WINDOW_S: float = 10.0
"""Seconds after decision to check for repriceable conditions."""

REPRICE_BUY_MAX_ASK: float = 0.95
"""Maximum ask price considered reasonable for a BUY reprice rescue."""

REPRICE_SELL_MIN_BID: float = 0.05
"""Minimum bid price considered reasonable for a SELL reprice rescue."""

# ---------------------------------------------------------------------------
# Feature F: Decision context
# ---------------------------------------------------------------------------

ML_MODEL_PATH: str = "logs/ml_model.json"
"""Default path for ML model weights used in scoring."""

# ---------------------------------------------------------------------------
# Conversion factors
# ---------------------------------------------------------------------------

BPS_MULTIPLIER: int = 10_000
"""Basis-point conversion factor (1 bps = 1/10000)."""
