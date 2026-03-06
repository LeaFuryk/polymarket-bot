"""Shared constants for the knowledge package."""

# ---------------------------------------------------------------------------
# PnL classification
# ---------------------------------------------------------------------------
PNL_THRESHOLD: float = 0.001  # Minimum |PnL| to count as win or loss

# ---------------------------------------------------------------------------
# Base knowledge cache
# ---------------------------------------------------------------------------
CACHE_TTL_SECONDS: float = 60.0

# ---------------------------------------------------------------------------
# Session history
# ---------------------------------------------------------------------------
SESSION_HISTORY_MAX_ROWS: int = 20

# ---------------------------------------------------------------------------
# Reflection API settings
# ---------------------------------------------------------------------------
REFLECTION_MAX_TOKENS: int = 4096
REFLECTION_TEMPERATURE: float = 0.2
MAX_NEW_OBSERVATIONS: int = 5
DEFAULT_OBSERVATION_EXPIRY: int = 30

# ---------------------------------------------------------------------------
# Feedback context thresholds
# ---------------------------------------------------------------------------
DRAWDOWN_ALERT_THRESHOLD: float = -5.0
RECENT_RESOLUTIONS_WINDOW: int = 10
EXPENSIVE_SIDE_THRESHOLD: float = 0.55
CHEAP_SIDE_THRESHOLD: float = 0.40
SIDE_ACCURACY_WARNING: float = 0.50
LOSING_STREAK_THRESHOLD: int = 3
MIN_TRAILING_TRADES: int = 5
MIN_SIDE_SAMPLES: int = 3
MIN_EXPENSIVE_SIDE_TRADES: int = 2

# ---------------------------------------------------------------------------
# Base knowledge files
# ---------------------------------------------------------------------------
BASE_KNOWLEDGE_FILES: list[str] = ["trading_patterns.md", "self_assessment.md"]
OBSERVATIONS_FILENAME: str = "observations.jsonl"
SESSION_HISTORY_FILENAME: str = "session_history.md"
FEATURE_CONFIG_FILENAME: str = "feature_config.json"
