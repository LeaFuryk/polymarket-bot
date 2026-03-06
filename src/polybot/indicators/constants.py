"""Shared constants for the indicators package."""

# ---------------------------------------------------------------------------
# Numerical guards
# ---------------------------------------------------------------------------
NEAR_ZERO: float = 1e-9  # Used to guard against division by zero

# ---------------------------------------------------------------------------
# Token volatility level thresholds
# ---------------------------------------------------------------------------
TOKEN_VOL_HIGH: float = 0.02
TOKEN_VOL_MODERATE: float = 0.005

# ---------------------------------------------------------------------------
# BTC volatility level thresholds (in USD)
# ---------------------------------------------------------------------------
BTC_VOL_HIGH: float = 200.0
BTC_VOL_MODERATE: float = 50.0

# ---------------------------------------------------------------------------
# Orderbook imbalance thresholds (bid/ask depth ratio)
# ---------------------------------------------------------------------------
IMBALANCE_STRONG_BUY: float = 1.5
IMBALANCE_SLIGHT_BUY: float = 1.1
IMBALANCE_SLIGHT_SELL: float = 0.9
IMBALANCE_STRONG_SELL: float = 0.67

# ---------------------------------------------------------------------------
# Spread level thresholds (fraction)
# ---------------------------------------------------------------------------
SPREAD_VERY_WIDE: float = 0.05
SPREAD_WIDE: float = 0.02
SPREAD_NORMAL: float = 0.005

# ---------------------------------------------------------------------------
# Cross-book flow thresholds
# ---------------------------------------------------------------------------
CROSS_BOOK_HEAVY_THRESHOLD: float = 0.65
CROSS_BOOK_BALANCED_THRESHOLD: float = 0.05

# ---------------------------------------------------------------------------
# Token price divergence thresholds
# ---------------------------------------------------------------------------
DIVERGENCE_SIGNIFICANT: float = 0.03
DIVERGENCE_MINOR: float = 0.01

# ---------------------------------------------------------------------------
# Market trend EMA signal scaling
# ---------------------------------------------------------------------------
EMA_DIFF_SCALE: float = 100.0  # $100 BTC move = full EMA signal
PRICE_DIFF_SCALE: float = 150.0  # $150 BTC move = full price signal
TREND_STRONG_THRESHOLD: float = 0.5
TREND_MILD_THRESHOLD: float = 0.2

# ---------------------------------------------------------------------------
# BTC candle momentum thresholds
# ---------------------------------------------------------------------------
CANDLE_BULLISH_RATIO: float = 0.67
CANDLE_BEARISH_RATIO: float = 0.33

# ---------------------------------------------------------------------------
# Consecutive streak thresholds
# ---------------------------------------------------------------------------
STREAK_STRONG: int = 4
STREAK_MODERATE: int = 3
STREAK_MILD: int = 2

# ---------------------------------------------------------------------------
# Streak magnitude thresholds (in USD)
# ---------------------------------------------------------------------------
MAGNITUDE_EXHAUSTION: float = 200.0
MAGNITUDE_STRONG: float = 100.0
MAGNITUDE_MODERATE: float = 50.0

# ---------------------------------------------------------------------------
# 30-min volatility regime thresholds (avg range in USD)
# ---------------------------------------------------------------------------
VOL30_HIGH: float = 150.0
VOL30_MODERATE: float = 80.0
VOL30_LOW: float = 30.0

# ---------------------------------------------------------------------------
# Chainlink divergence thresholds (in USD)
# ---------------------------------------------------------------------------
CHAINLINK_HIGH_DIV: float = 50.0
CHAINLINK_MODERATE_DIV: float = 20.0
CHAINLINK_MINOR_DIV: float = 5.0

# ---------------------------------------------------------------------------
# Best entry analysis thresholds
# ---------------------------------------------------------------------------
ENTRY_SIGNIFICANT_DIFF: float = 0.05
ENTRY_SLIGHT_DIFF: float = 0.02

# ---------------------------------------------------------------------------
# Volume trend thresholds
# ---------------------------------------------------------------------------
VOLUME_INCREASING: float = 1.3
VOLUME_SLIGHTLY_INCREASING: float = 1.1
VOLUME_SLIGHTLY_DECREASING: float = 0.9
VOLUME_DECREASING: float = 0.7

# ---------------------------------------------------------------------------
# Confidence calibration
# ---------------------------------------------------------------------------
CALIBRATION_TOLERANCE: float = 0.01

# ---------------------------------------------------------------------------
# Mean reversion z-score thresholds
# ---------------------------------------------------------------------------
Z_OVEREXTENDED: float = 2.0
Z_STRETCHED: float = 1.0

# ---------------------------------------------------------------------------
# Default flat market threshold (in USD)
# ---------------------------------------------------------------------------
DEFAULT_FLAT_THRESHOLD: float = 5.0
