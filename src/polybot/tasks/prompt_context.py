"""Pure functions that build AI prompt context sections.

Retained functions are still used by context_builder and decision_guards.
Indicator-based computations have been moved to the indicator catalog.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# VelocityConflict dataclass — retained for context_builder compatibility
# ---------------------------------------------------------------------------


@dataclass
class VelocityConflict:
    """Result of detecting a conflict between BTC magnitude and velocity."""

    has_conflict: bool
    severity: float  # 0.0 - 1.0
    magnitude_direction: str  # "UP" or "DOWN"
    velocity_direction: str  # "UP" or "DOWN"
    velocity_rate: float  # $/s
    btc_move: float  # current move from open
    drawback_pct: float  # how much of peak has been given back (0-1)
    time_remaining: float
    label: str  # "STRONG_CONFLICT", "MODERATE_CONFLICT", or "ALIGNED"
    detail: str  # human-readable explanation
