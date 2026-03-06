"""Shared constants for the datastore package."""

# ---------------------------------------------------------------------------
# Batch insert thresholds
# ---------------------------------------------------------------------------
FLUSH_INTERVAL_SECONDS: float = 5.0  # Max seconds between flushes
FLUSH_BATCH_SIZE: int = 50  # Max rows before forcing a flush

# ---------------------------------------------------------------------------
# SQLite pragma settings
# ---------------------------------------------------------------------------
JOURNAL_MODE: str = "WAL"
SYNCHRONOUS_MODE: str = "NORMAL"
