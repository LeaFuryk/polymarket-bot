"""Shared constants for the ml_scorer package."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Feature definitions (fixed order — must match normalization scales)
# ---------------------------------------------------------------------------
FEATURE_NAMES: list[str] = [
    "streak_signed",  # positive=up streak, negative=down streak
    "streak_magnitude",  # $ move during streak
    "btc_vs_open",  # current BTC - candle open
    "volatility_30m",  # avg candle range
    "volume_ratio",  # recent/prior volume
    "up_midpoint",  # UP token midpoint (market-implied prob)
    "down_midpoint",  # DOWN token midpoint
    "book_imbalance",  # UP bid_depth / ask_depth
    "flat_ratio",  # fraction of flat candles
    "reversal_rate",  # rolling reversal rate from adaptive entry (0-1)
    "btc_velocity",  # current BTC velocity in $/s
    "velocity_conflict",  # velocity-magnitude conflict severity (0-1)
]

NUM_FEATURES: int = len(FEATURE_NAMES)

# ---------------------------------------------------------------------------
# Normalization scales — fixed per-feature divisors to prevent extreme
# gradients.  Based on expected value ranges, not learned statistics.
# ---------------------------------------------------------------------------
NORMALIZATION_SCALES: list[float] = [
    5.0,  # streak_signed: typically -6 to +6
    200.0,  # streak_magnitude: typically -$500 to +$500
    100.0,  # btc_vs_open: typically -$200 to +$200
    100.0,  # volatility_30m: typically $10 to $300
    1.0,  # volume_ratio: typically 0.3 to 3.0 (already scaled)
    1.0,  # up_midpoint: 0 to 1
    1.0,  # down_midpoint: 0 to 1
    2.0,  # book_imbalance: typically 0.3 to 3.0
    1.0,  # flat_ratio: 0 to 1
    1.0,  # reversal_rate: 0 to 1 (already scaled)
    5.0,  # btc_velocity: typically -$5/s to +$5/s
    1.0,  # velocity_conflict: 0 to 1 (already scaled)
]

# ---------------------------------------------------------------------------
# Confidence thresholds — probability boundaries for classification
# ---------------------------------------------------------------------------
STRONG_UP_THRESHOLD: float = 0.65
LEAN_UP_THRESHOLD: float = 0.55
LEAN_DOWN_THRESHOLD: float = 0.45
STRONG_DOWN_THRESHOLD: float = 0.35

# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
DEFAULT_LEARNING_RATE: float = 0.01
MIN_TRAINING_SAMPLES: int = 10  # minimum before trusting predictions

# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------
FLAT_CANDLE_THRESHOLD: float = 5.0  # $ move below which a candle is "flat"
VOLATILITY_WINDOW: int = 6  # candles for 30-min volatility
VOLUME_WINDOW: int = 6  # candles for volume ratio (split 3/3)
