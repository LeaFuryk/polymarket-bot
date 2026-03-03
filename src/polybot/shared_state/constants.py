"""Default values for shared state fields.

Centralizes magic numbers and sentinel strings so they are easy to
find, audit, and override.
"""

from __future__ import annotations

# -- EntryContext defaults ----------------------------------------------------
DEFAULT_ML_UP_PROBABILITY: float = 0.5
DEFAULT_ML_CONFIDENCE: str = "neutral"

# -- CandleMicrostructure defaults -------------------------------------------
DEFAULT_AVG_IMBALANCE: float = 1.0  # bid/ask ratio (>1 = bid-heavy)

# -- PreFilterSnapshot defaults -----------------------------------------------
DEFAULT_BEST_ENTRY: float = 1.0  # worst-case entry (no fill opportunity)

# -- SharedState defaults -----------------------------------------------------
PREFILTER_HISTORY_MAXLEN: int = 300  # ~5 min at 1 snapshot/s
DEFAULT_SIGNAL_TYPE: str = "UNCERTAIN"  # MOMENTUM / UNCERTAIN / CONTRARIAN
DEFAULT_REGIME: str = "MODERATE"  # CALM / MODERATE / CHOPPY
