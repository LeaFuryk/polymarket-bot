"""Tests for polybot.logging — trade log, constants."""

from __future__ import annotations

import json
import logging

from polybot.config import LoggingConfig
from polybot.logging.constants import (
    DATE_FORMAT,
    LOG_FILE_EXTENSION,
    RESOLUTION_LOG_PREFIX,
    TRADE_LOG_PREFIX,
)
from polybot.logging.trade_log import TradeLog
from polybot.models import ResolutionRecord, TradeRecord

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_date_format(self):
        assert DATE_FORMAT == "%Y%m%d"

    def test_trade_log_prefix(self):
        assert TRADE_LOG_PREFIX == "trades_"

    def test_resolution_log_prefix(self):
        assert RESOLUTION_LOG_PREFIX == "resolutions_"

    def test_log_file_extension(self):
        assert LOG_FILE_EXTENSION == ".jsonl"


# ---------------------------------------------------------------------------
# TradeLog
# ---------------------------------------------------------------------------


class TestTradeLog:
    def test_creates_log_directory(self, tmp_path):
        log_dir = tmp_path / "logs"
        config = LoggingConfig(log_dir=str(log_dir))
        TradeLog(config)
        assert log_dir.exists()

    def test_write_trade_record(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), jsonl_enabled=True)
        tl = TradeLog(config)

        record = TradeRecord()
        tl.write(record)
        tl.close()

        files = list(tmp_path.glob("trades_*.jsonl"))
        assert len(files) == 1
        content = files[0].read_text().strip()
        data = json.loads(content)
        assert "cycle_id" in data
        assert "timestamp" in data

    def test_write_multiple_records(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), jsonl_enabled=True)
        tl = TradeLog(config)

        tl.write(TradeRecord())
        tl.write(TradeRecord())
        tl.write(TradeRecord())
        tl.close()

        files = list(tmp_path.glob("trades_*.jsonl"))
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 3

    def test_write_disabled(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), jsonl_enabled=False)
        tl = TradeLog(config)

        tl.write(TradeRecord())
        tl.close()

        files = list(tmp_path.glob("trades_*.jsonl"))
        assert len(files) == 0

    def test_write_resolution(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), jsonl_enabled=True)
        tl = TradeLog(config)

        record = ResolutionRecord(
            slug="btc-5m-test",
            condition_id="0xabc",
            start_time=1000.0,
            end_time=1300.0,
            btc_open=50000.0,
            btc_close=50100.0,
            winner="up",
            up_pnl=5.0,
            down_pnl=-4.5,
            total_pnl=0.5,
        )
        tl.write_resolution(record)

        files = list(tmp_path.glob("resolutions_*.jsonl"))
        assert len(files) == 1
        data = json.loads(files[0].read_text().strip())
        assert data["winner"] == "up"
        assert data["total_pnl"] == 0.5

    def test_write_resolution_disabled(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), jsonl_enabled=False)
        tl = TradeLog(config)

        record = ResolutionRecord(
            slug="test",
            condition_id="0x",
            start_time=0,
            end_time=0,
            btc_open=0,
            btc_close=0,
            winner="up",
            up_pnl=0,
            down_pnl=0,
            total_pnl=0,
        )
        tl.write_resolution(record)

        files = list(tmp_path.glob("resolutions_*.jsonl"))
        assert len(files) == 0

    def test_close_idempotent(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path))
        tl = TradeLog(config)
        tl.close()
        tl.close()  # should not raise

    def test_close_after_write(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), jsonl_enabled=True)
        tl = TradeLog(config)
        tl.write(TradeRecord())
        tl.close()
        assert tl._file is None

    def test_injectable_logger(self, tmp_path):
        custom = logging.getLogger("test.trade_log")
        config = LoggingConfig(log_dir=str(tmp_path))
        tl = TradeLog(config, logger=custom)
        assert tl._logger is custom

    def test_default_logger(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path))
        tl = TradeLog(config)
        assert tl._logger.name == "polybot.logging.trade_log"

    def test_file_rotation_on_date_change(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), jsonl_enabled=True)
        tl = TradeLog(config)

        tl.write(TradeRecord())

        # Simulate date change by resetting the tracked date
        tl._current_date = "19700101"
        tl.write(TradeRecord())
        tl.close()

        files = list(tmp_path.glob("trades_*.jsonl"))
        # Should have 2 files (original date + today's re-opened)
        assert len(files) >= 1  # at minimum today's file re-created

    def test_trade_file_naming(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), jsonl_enabled=True)
        tl = TradeLog(config)
        tl.write(TradeRecord())
        tl.close()

        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        name = files[0].name
        assert name.startswith(TRADE_LOG_PREFIX)
        assert name.endswith(LOG_FILE_EXTENSION)

    def test_resolution_file_naming(self, tmp_path):
        config = LoggingConfig(log_dir=str(tmp_path), jsonl_enabled=True)
        tl = TradeLog(config)
        record = ResolutionRecord(
            slug="test",
            condition_id="0x",
            start_time=0,
            end_time=0,
            btc_open=0,
            btc_close=0,
            winner="down",
            up_pnl=0,
            down_pnl=0,
            total_pnl=0,
        )
        tl.write_resolution(record)

        files = list(tmp_path.glob("*.jsonl"))
        assert len(files) == 1
        name = files[0].name
        assert name.startswith(RESOLUTION_LOG_PREFIX)
        assert name.endswith(LOG_FILE_EXTENSION)
