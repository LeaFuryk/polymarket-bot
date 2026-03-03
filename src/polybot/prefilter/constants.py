"""Default thresholds for pre-filter checks."""

from __future__ import annotations

# Time gate
MIN_TIME_REMAINING: float = 45.0  # seconds before candle close

# Spread gate
MAX_SPREAD_PCT: float = 0.08  # 8% — skip if both sides wider

# Book depth gate
MIN_BOOK_DEPTH: float = 50.0  # USD — skip if both sides thinner

# Choppy market gate
CHOPPY_RANGE_THRESHOLD: float = 50.0  # BTC $ range over last 30 min
CHOPPY_MAX_ENTRY: float = 0.28  # best entry price ceiling in choppy conditions

# No-streak gate
NO_STREAK_MAX_ENTRY: float = 0.50  # best entry ceiling when streak < 2
MIN_STREAK_FOR_TRADE: int = 0  # minimum consecutive candles in same direction

# Signal helpers
BTC_RANGE_CANDLE_WINDOW: int = 6  # ~30 minutes at 5-min candles
DEFAULT_BEST_ENTRY: float = 1.0  # worst-case (most expensive) entry
