"""Shared constants for the adaptive_entry package."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Default thresholds (used when insufficient history)
# ---------------------------------------------------------------------------
DEFAULT_BTC_THRESHOLD: float = 30.0  # $30 BTC move required
DEFAULT_MAX_ENTRY: float = 0.60  # $0.60 max ask price
MAX_ENTRY_CAP: float = 0.65  # Hard cap for max entry price
ENTRY_BUFFER: float = 0.10  # Buffer added to avg winner ask

# ---------------------------------------------------------------------------
# Retracement-based reversal detection
# ---------------------------------------------------------------------------
RETRACEMENT_THRESHOLD: float = 0.80  # 80% of peak must be retraced
MIN_PEAK_COMMIT: float = 25.0  # $25 minimum peak to evaluate retracement
VELOCITY_SAMPLE_SEC: int = 5  # sample interval for acceleration check
INITIAL_DIRECTION_MIN_MOVE: float = 5.0  # $ move to determine initial direction
NEAR_ZERO_GUARD: float = 5.0  # $ move below which reversal is inconclusive

# ---------------------------------------------------------------------------
# Fakeout threshold computation
# ---------------------------------------------------------------------------
FAKEOUT_WINDOW: int = 5  # last N candles for fakeout percentiles
FAKEOUT_P75_MULTIPLIER: float = 1.2  # adaptive_cap = P75 * 1.2
ADAPTIVE_CAP_MIN: float = 50.0  # $ min adaptive cap
ADAPTIVE_CAP_MAX: float = 100.0  # $ max adaptive cap
BTC_THRESHOLD_MIN: float = 20.0  # $ min BTC threshold

# ---------------------------------------------------------------------------
# Signal type boundaries (reversal rate thresholds)
# ---------------------------------------------------------------------------
MOMENTUM_UPPER: float = 0.40  # below → MOMENTUM
CONTRARIAN_LOWER: float = 0.60  # above → CONTRARIAN

# ---------------------------------------------------------------------------
# Regime boundaries
# ---------------------------------------------------------------------------
REGIME_CALM_UPPER: float = 0.20  # below → CALM
REGIME_MODERATE_UPPER: float = 0.40  # below → MODERATE, above → CHOPPY

# ---------------------------------------------------------------------------
# V-shaped fallback formula
# ---------------------------------------------------------------------------
V_SHAPE_MAX_THRESHOLD: float = 50.0
V_SHAPE_SLOPE: float = 60.0

# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
DATA_FILE_NAME: str = "adaptive_entry.jsonl"
HISTORY_MAX_FACTOR: int = 4  # keep window * N entries in file

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
BOOTSTRAP_FLAT_THRESHOLD: float = 1.0  # $ move below which a candle is too flat
BOOTSTRAP_CONSERVATIVE_REVERSED_ASK: float = 0.40
BOOTSTRAP_CONSERVATIVE_MOMENTUM_ASK: float = 0.55

# ---------------------------------------------------------------------------
# AI context
# ---------------------------------------------------------------------------
WILD_MARKET_FAKEOUT_FACTOR: float = 1.5  # fakeout_max > threshold * this → wild
