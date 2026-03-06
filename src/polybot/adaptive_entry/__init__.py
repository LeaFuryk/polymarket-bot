"""Adaptive entry threshold tracker — learns optimal BTC move threshold and max entry price.

Tracks rolling candle outcomes to calibrate entry thresholds based on
fakeout magnitudes, reversal patterns, and winner ask prices.
"""

from polybot.adaptive_entry.models import CandleOutcome
from polybot.adaptive_entry.reversal_detector import ReversalResult, detect_reversal
from polybot.adaptive_entry.threshold_calculator import ThresholdResult, compute_thresholds
from polybot.adaptive_entry.tracker import AdaptiveEntryTracker

__all__ = [
    # Core
    "AdaptiveEntryTracker",
    # Models
    "CandleOutcome",
    "ReversalResult",
    "ThresholdResult",
    # Functions
    "detect_reversal",
    "compute_thresholds",
]
