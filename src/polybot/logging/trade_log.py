"""Append-only JSONL trade log."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from polybot.config import LoggingConfig
from polybot.models import ResolutionRecord, TradeRecord

logger = logging.getLogger(__name__)


class TradeLog:
    """Writes one TradeRecord per line to a JSONL file."""

    def __init__(self, config: LoggingConfig) -> None:
        self._config = config
        self._log_dir = Path(config.log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._file = None
        self._current_date: str = ""

    def _ensure_file(self) -> None:
        """Open/rotate log file based on current UTC date."""
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        if today != self._current_date:
            if self._file:
                self._file.close()
            path = self._log_dir / f"trades_{today}.jsonl"
            self._file = open(path, "a")
            self._current_date = today
            logger.info("Logging trades to %s", path)

    def write(self, record: TradeRecord) -> None:
        """Append a trade record to the JSONL log."""
        if not self._config.jsonl_enabled:
            return
        self._ensure_file()
        line = record.model_dump_json()
        self._file.write(line + "\n")
        self._file.flush()

    def write_resolution(self, record: ResolutionRecord) -> None:
        """Append a resolution record to a separate JSONL log."""
        if not self._config.jsonl_enabled:
            return
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        path = self._log_dir / f"resolutions_{today}.jsonl"
        with open(path, "a") as f:
            f.write(record.model_dump_json() + "\n")
        logger.info(
            "Resolution logged: %s winner=%s pnl=%.4f",
            record.slug, record.winner, record.total_pnl,
        )

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
