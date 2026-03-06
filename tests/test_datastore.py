"""Tests for the datastore package — constants, rows, DataStore, MarketHistoryStore."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pytest

from polybot.datastore.constants import (
    FLUSH_BATCH_SIZE,
    FLUSH_INTERVAL_SECONDS,
    JOURNAL_MODE,
    SYNCHRONOUS_MODE,
)
from polybot.datastore.market_history import MarketHistoryStore
from polybot.datastore.rows import DecisionRow, MarketSnapshotRow, SnapshotRow
from polybot.datastore.store import DataStore

# ---------------------------------------------------------------------------
# Constants tests
# ---------------------------------------------------------------------------


class TestConstants:
    def test_flush_interval_positive(self):
        assert FLUSH_INTERVAL_SECONDS > 0

    def test_flush_batch_positive(self):
        assert FLUSH_BATCH_SIZE > 0

    def test_journal_mode(self):
        assert JOURNAL_MODE == "WAL"

    def test_synchronous_mode(self):
        assert SYNCHRONOUS_MODE == "NORMAL"

    def test_all_constants_importable_from_package(self):
        from polybot.datastore import (
            FLUSH_BATCH_SIZE,
            FLUSH_INTERVAL_SECONDS,
            JOURNAL_MODE,
            SYNCHRONOUS_MODE,
        )

        assert FLUSH_INTERVAL_SECONDS > 0
        assert FLUSH_BATCH_SIZE > 0
        assert JOURNAL_MODE == "WAL"
        assert SYNCHRONOUS_MODE == "NORMAL"


# ---------------------------------------------------------------------------
# Row dataclass tests
# ---------------------------------------------------------------------------


class TestSnapshotRow:
    def test_defaults(self):
        row = SnapshotRow(candle_id=1, timestamp=time.time(), time_remaining=120.0)
        assert row.candle_id == 1
        assert row.up_best_bid is None
        assert row.btc_price == 0.0
        assert row.prefilter_passed is False
        assert row.indicators_json == "{}"

    def test_custom_values(self):
        row = SnapshotRow(
            candle_id=5,
            timestamp=1000.0,
            time_remaining=60.0,
            up_mid=0.45,
            down_mid=0.55,
            btc_price=85000.0,
            prefilter_passed=True,
            prefilter_reasons="momentum",
        )
        assert row.up_mid == 0.45
        assert row.btc_price == 85000.0
        assert row.prefilter_passed is True


class TestMarketSnapshotRow:
    def test_defaults(self):
        row = MarketSnapshotRow(candle_id=1, timestamp=time.time(), time_remaining=120.0)
        assert row.candle_id == 1
        assert row.streak == 0
        assert row.streak_direction == ""

    def test_no_prefilter_fields(self):
        """MarketSnapshotRow does not have prefilter fields."""
        assert not hasattr(MarketSnapshotRow(candle_id=1, timestamp=0, time_remaining=0), "prefilter_passed")


class TestDecisionRow:
    def test_defaults(self):
        row = DecisionRow(candle_id=1, timestamp=time.time(), cycle=1)
        assert row.action == "HOLD"
        assert row.token_side == "up"
        assert row.confidence == 0.0
        assert row.fill_price is None
        assert row.risk_blocked is False
        assert row.live_order_json == ""

    def test_custom_values(self):
        row = DecisionRow(
            candle_id=3,
            timestamp=1000.0,
            cycle=2,
            action="BUY",
            token_side="down",
            confidence=0.85,
            fill_price=0.42,
            ai_cost=0.003,
        )
        assert row.action == "BUY"
        assert row.token_side == "down"
        assert row.fill_price == 0.42


# ---------------------------------------------------------------------------
# DataStore tests
# ---------------------------------------------------------------------------


class TestDataStore:
    def test_open_creates_db(self, tmp_path: Path):
        db_path = tmp_path / "test.db"
        store = DataStore(db_path)
        store.open()
        assert db_path.exists()
        assert store._conn is not None

    def test_open_creates_parent_dirs(self, tmp_path: Path):
        db_path = tmp_path / "sub" / "dir" / "test.db"
        store = DataStore(db_path)
        store.open()
        assert db_path.exists()

    def test_injectable_logger(self, tmp_path: Path):
        custom_logger = logging.getLogger("test.datastore")
        store = DataStore(tmp_path / "test.db", logger=custom_logger)
        assert store._logger is custom_logger

    def test_begin_candle(self, tmp_path: Path):
        store = DataStore(tmp_path / "test.db")
        store.open()
        candle_id = store.begin_candle(
            condition_id="cond-001",
            slug="btc-updown-5m-001",
            title="Test Candle",
            start_time=1000.0,
            end_time=1300.0,
            btc_open=85000.0,
        )
        assert candle_id is not None
        assert candle_id > 0
        assert store.current_candle_id == candle_id

    def test_begin_candle_duplicate_returns_same_id(self, tmp_path: Path):
        store = DataStore(tmp_path / "test.db")
        store.open()
        id1 = store.begin_candle("cond-001", "slug-1", "title", 1000.0, 1300.0, 85000.0)
        id2 = store.begin_candle("cond-001", "slug-1", "title", 1000.0, 1300.0, 85000.0)
        assert id1 == id2

    def test_begin_candle_no_connection(self, tmp_path: Path):
        store = DataStore(tmp_path / "test.db")
        result = store.begin_candle("cond-001", "slug", "title", 0, 0, None)
        assert result is None

    def test_resolve_candle(self, tmp_path: Path):
        store = DataStore(tmp_path / "test.db")
        store.open()
        candle_id = store.begin_candle("cond-001", "slug-1", "title", 1000.0, 1300.0, 85000.0)
        store.resolve_candle(candle_id, btc_close=85100.0, winner="up", resolution_pnl=0.50)
        # Verify via raw SQL
        row = store._conn.execute(
            "SELECT winner, resolution_pnl FROM candles WHERE candle_id = ?", (candle_id,)
        ).fetchone()
        assert row[0] == "up"
        assert row[1] == pytest.approx(0.50)

    @pytest.mark.asyncio
    async def test_flush_snapshots(self, tmp_path: Path):
        store = DataStore(tmp_path / "test.db")
        store.open()
        candle_id = store.begin_candle("cond-001", "slug-1", "title", 1000.0, 1300.0, 85000.0)

        row = SnapshotRow(candle_id=candle_id, timestamp=time.time(), time_remaining=120.0, btc_price=85000.0)
        store.queue_snapshot(row)
        await store._flush()

        count = store._conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        assert count == 1

    @pytest.mark.asyncio
    async def test_flush_decisions(self, tmp_path: Path):
        store = DataStore(tmp_path / "test.db")
        store.open()
        candle_id = store.begin_candle("cond-001", "slug-1", "title", 1000.0, 1300.0, 85000.0)

        row = DecisionRow(candle_id=candle_id, timestamp=time.time(), cycle=1, action="BUY", confidence=0.80)
        store.queue_decision(row)
        await store._flush()

        count = store._conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0]
        assert count == 1

    @pytest.mark.asyncio
    async def test_flush_empty(self, tmp_path: Path):
        store = DataStore(tmp_path / "test.db")
        store.open()
        await store._flush()  # should not raise

    @pytest.mark.asyncio
    async def test_close_flushes(self, tmp_path: Path):
        store = DataStore(tmp_path / "test.db")
        store.open()
        candle_id = store.begin_candle("cond-001", "slug-1", "title", 1000.0, 1300.0, 85000.0)

        row = SnapshotRow(candle_id=candle_id, timestamp=time.time(), time_remaining=120.0)
        store.queue_snapshot(row)

        # Close should flush
        await store.close()

        # Reconnect to verify
        import sqlite3

        conn2 = sqlite3.connect(str(tmp_path / "test.db"))
        count = conn2.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        assert count == 1
        conn2.close()


# ---------------------------------------------------------------------------
# MarketHistoryStore tests
# ---------------------------------------------------------------------------


class TestMarketHistoryStore:
    def test_open_creates_db(self, tmp_path: Path):
        store = MarketHistoryStore(tmp_path / "market.db")
        store.open()
        assert (tmp_path / "market.db").exists()

    def test_injectable_logger(self, tmp_path: Path):
        custom_logger = logging.getLogger("test.market_history")
        store = MarketHistoryStore(tmp_path / "market.db", logger=custom_logger)
        assert store._logger is custom_logger

    def test_begin_candle(self, tmp_path: Path):
        store = MarketHistoryStore(tmp_path / "market.db", iteration="iter-1")
        store.open()
        candle_id = store.begin_candle(
            condition_id="cond-001",
            slug="btc-updown-5m-001",
            start_time=1000.0,
            end_time=1300.0,
            btc_open=85000.0,
        )
        assert candle_id is not None
        assert store.current_candle_id == candle_id

    def test_resolve_candle(self, tmp_path: Path):
        store = MarketHistoryStore(tmp_path / "market.db")
        store.open()
        candle_id = store.begin_candle("cond-001", "slug-1", 1000.0, 1300.0, 85000.0)
        store.resolve_candle(candle_id, btc_close=85100.0, winner="up")
        row = store._conn.execute("SELECT winner FROM market_candles WHERE candle_id = ?", (candle_id,)).fetchone()
        assert row[0] == "up"

    def test_begin_candle_no_connection(self, tmp_path: Path):
        store = MarketHistoryStore(tmp_path / "market.db")
        result = store.begin_candle("cond-001", "slug", 0, 0, None)
        assert result is None

    @pytest.mark.asyncio
    async def test_flush_snapshots(self, tmp_path: Path):
        store = MarketHistoryStore(tmp_path / "market.db")
        store.open()
        candle_id = store.begin_candle("cond-001", "slug-1", 1000.0, 1300.0, 85000.0)

        row = MarketSnapshotRow(candle_id=candle_id, timestamp=time.time(), time_remaining=120.0, btc_price=85000.0)
        store.queue_snapshot(row)
        await store._flush()

        count = store._conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
        assert count == 1

    @pytest.mark.asyncio
    async def test_close_flushes(self, tmp_path: Path):
        store = MarketHistoryStore(tmp_path / "market.db")
        store.open()
        candle_id = store.begin_candle("cond-001", "slug-1", 1000.0, 1300.0, 85000.0)

        row = MarketSnapshotRow(candle_id=candle_id, timestamp=time.time(), time_remaining=120.0)
        store.queue_snapshot(row)
        await store.close()

        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "market.db"))
        count = conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
        assert count == 1
        conn.close()


# ---------------------------------------------------------------------------
# Re-export tests
# ---------------------------------------------------------------------------


class TestReExports:
    def test_stores_importable(self):
        from polybot.datastore import DataStore, MarketHistoryStore

        assert DataStore is not None
        assert MarketHistoryStore is not None

    def test_rows_importable(self):
        from polybot.datastore import DecisionRow, MarketSnapshotRow, SnapshotRow

        assert SnapshotRow is not None
        assert DecisionRow is not None
        assert MarketSnapshotRow is not None

    def test_constants_importable(self):
        from polybot.datastore import FLUSH_BATCH_SIZE, FLUSH_INTERVAL_SECONDS

        assert FLUSH_INTERVAL_SECONDS > 0
        assert FLUSH_BATCH_SIZE > 0
