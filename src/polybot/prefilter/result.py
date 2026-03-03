"""Pre-filter result container."""

from __future__ import annotations

from dataclasses import dataclass

from polybot.prefilter.constants import DEFAULT_BEST_ENTRY


@dataclass
class PreFilterResult:
    """Result of the rules-based pre-filter."""

    should_skip: bool
    reason: str
    # Computed signals passed to AI if not skipped (avoids recomputation)
    consecutive_streak: int = 0
    streak_direction: str = ""
    btc_range_30m: float = 0.0
    best_entry_price: float = DEFAULT_BEST_ENTRY
