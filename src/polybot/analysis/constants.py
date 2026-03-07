"""Constants for the analysis package."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Replay engine
# ---------------------------------------------------------------------------

RECOVERY_WINDOW_SECONDS: int = 30
"""Seconds after a cancelled/unfilled order to check for price recovery."""

TTL_COUNTERFACTUAL_VALUES: list[int] = [5, 8, 10]
"""TTL values to test in counterfactual analysis for missed orders."""

DEFAULT_TTL_SECONDS: int = 3
"""Default TTL for limit order simulation in replay."""

# ---------------------------------------------------------------------------
# Rendering — color thresholds
# ---------------------------------------------------------------------------

FILL_RATE_GREEN: float = 0.7
"""Fill rate >= this renders green."""

FILL_RATE_YELLOW: float = 0.4
"""Fill rate >= this renders yellow (below green)."""

AGG_FILL_RATE_GREEN: float = 0.5
"""Aggregate fill rate >= this renders green."""

AGG_FILL_RATE_YELLOW: float = 0.3
"""Aggregate fill rate >= this renders yellow."""

ENTRY_GAP_GREEN: float = 0.05
"""Entry gap < this renders green."""

ENTRY_GAP_YELLOW: float = 0.15
"""Entry gap < this renders yellow."""

RECOVERY_RATE_GREEN: float = 0.5
"""Post-cancel recovery rate >= this renders green."""

SIDE_ACCURACY_GREEN: float = 0.6
"""Side accuracy >= this renders green."""

SIDE_ACCURACY_YELLOW: float = 0.45
"""Side accuracy >= this renders yellow."""

# ---------------------------------------------------------------------------
# Validate — analysis buckets
# ---------------------------------------------------------------------------

VALIDATE_CONFIDENCE_LOW: int = 50
"""Confidence threshold below which a decision is 'low confidence'."""

VALIDATE_CONFIDENCE_MODERATE: int = 100
"""Confidence count threshold separating moderate from good coverage."""

PERCENTILE_BUCKETS: list[int] = [10, 25, 50, 75, 90, 95]
"""Percentile values for BTC move distribution analysis."""

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

ANNUALIZATION_FACTOR: int = 1440
"""Cycles per day used for Sharpe ratio annualization."""

# ---------------------------------------------------------------------------
# Deep analysis — recommendation thresholds
# ---------------------------------------------------------------------------

DEEP_ENTRY_EXPENSIVE_THRESHOLD: float = 0.65
"""Avg fill price above this triggers 'expensive entries' recommendation."""

DEEP_SIDE_ACCURACY_WARN: float = 0.55
"""Side win rate below this triggers 'poor side accuracy' recommendation."""

DEEP_FLIP_WARN: int = 2
"""Number of flips above this triggers 'excessive flipping' recommendation."""

DEEP_MISSED_HIGH_MOVE_THRESHOLD: float = 50.0
"""BTC move ($) above which a missed candle is 'high-move missed'."""
