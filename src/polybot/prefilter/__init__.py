"""Rules-based pre-filter — skip AI calls on obvious HOLD cycles.

Runs cheap, fast checks before calling Claude to determine if there's any
plausible trade setup. Saves 60-70% of AI API costs by filtering out cycles
where HOLD is the only sensible decision.
"""

from polybot.prefilter.filters import (
    ChoppyMarketFilter,
    NoStreakFilter,
    OpenPositionFilter,
    ThinBookFilter,
    TimeRemainingFilter,
    WideSpreadFilter,
)
from polybot.prefilter.prefilter import PreFilter, default_filters
from polybot.prefilter.protocol import MarketFilter
from polybot.prefilter.result import PreFilterResult
from polybot.prefilter.signals import (
    compute_best_entry,
    compute_btc_range_30m,
    compute_streak,
)

__all__ = [
    "ChoppyMarketFilter",
    "MarketFilter",
    "NoStreakFilter",
    "OpenPositionFilter",
    "PreFilter",
    "PreFilterResult",
    "ThinBookFilter",
    "TimeRemainingFilter",
    "WideSpreadFilter",
    "compute_best_entry",
    "compute_btc_range_30m",
    "compute_streak",
    "default_filters",
]
