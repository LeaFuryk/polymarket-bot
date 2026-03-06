"""Append-only JSONL trade log."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from polybot.config import LoggingConfig
from polybot.logging.constants import (
    DATE_FORMAT,
    LOG_FILE_EXTENSION,
    RESOLUTION_LOG_PREFIX,
    TRADE_LOG_PREFIX,
)
from polybot.models import ResolutionRecord, TradeRecord


class TradeLog:
    """Writes one TradeRecord per line to a JSONL file."""

    def __init__(
        self,
        config: LoggingConfig,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._logger = logger or logging.getLogger(__name__)
        self._log_dir = Path(config.log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._file = None
        self._current_date: str = ""

    def _ensure_file(self) -> None:
        """Open/rotate log file based on current UTC date."""
        today = datetime.now(UTC).strftime(DATE_FORMAT)
        if today != self._current_date:
            if self._file:
                self._file.close()
            path = self._log_dir / f"{TRADE_LOG_PREFIX}{today}{LOG_FILE_EXTENSION}"
            self._file = open(path, "a")  # noqa: SIM115
            self._current_date = today
            self._logger.info("Logging trades to %s", path)

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
        today = datetime.now(UTC).strftime(DATE_FORMAT)
        path = self._log_dir / f"{RESOLUTION_LOG_PREFIX}{today}{LOG_FILE_EXTENSION}"
        with open(path, "a") as f:
            f.write(record.model_dump_json() + "\n")
        self._logger.info(
            "Resolution logged: %s winner=%s pnl=%.4f",
            record.slug,
            record.winner,
            record.total_pnl,
        )

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
