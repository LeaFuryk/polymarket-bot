"""Constants for the logging package."""

from __future__ import annotations

DATE_FORMAT: str = "%Y%m%d"
"""Date format for log file rotation (e.g., '20260306')."""

TRADE_LOG_PREFIX: str = "trades_"
"""File name prefix for trade JSONL logs."""

RESOLUTION_LOG_PREFIX: str = "resolutions_"
"""File name prefix for resolution JSONL logs."""

LOG_FILE_EXTENSION: str = ".jsonl"
"""File extension for all JSONL log files."""
