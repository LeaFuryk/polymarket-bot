"""Tests for SqliteStore adapter."""

from pathlib import Path

import pytest
from polybot_data.adapters.sqlite_store import SqliteStore
from polybot_data.domain.collection import CandleRecord, Snapshot
from polybot_data.ports.data_store import DataStore


@pytest.fixture
async def store(tmp_path: Path):
    """Yield an initialised SqliteStore, cleaned up after test."""
    db_path = str(tmp_path / "test.db")
    s = SqliteStore(db_path)
    await s.init()
    yield s
    await s.close()


def _make_snapshot(candle_id: str = "btc-updown-5m-900", timestamp: float = 1000.0) -> Snapshot:
    return Snapshot(
        timestamp=timestamp,
        tick_timestamp=timestamp - 0.5,
        candle_id=candle_id,
        elapsed_pct=0.33,
        btc_price=67800.0,
        btc_bid=67798.0,
        btc_ask=67802.0,
        up_bids=((0.55, 100.0), (0.54, 200.0)),
        up_asks=((0.57, 150.0),),
        down_bids=((0.43, 80.0),),
        down_asks=((0.45, 120.0), (0.46, 90.0)),
        up_last_trade=0.56,
        down_last_trade=0.44,
        market_volume=5000.0,
    )


def _make_candle_record(candle_id: str = "btc-updown-5m-900") -> CandleRecord:
    return CandleRecord(
        candle_id=candle_id,
        start_time=900.0,
        end_time=1200.0,
        open=67800.0,
        high=67900.0,
        low=67750.0,
        close=67850.0,
        volume=15.0,
        outcome="UP",
        final_ret=0.0007,
    )


class TestProtocolConformance:
    def test_is_data_store(self):
        assert isinstance(SqliteStore("dummy.db"), DataStore)


class TestCandleRoundTrip:
    async def test_write_and_read(self, store: SqliteStore):
        record = _make_candle_record()
        await store.write_candle(record)
        loaded = await store.get_candle("btc-updown-5m-900")
        assert loaded is not None
        assert loaded.candle_id == record.candle_id
        assert loaded.open == pytest.approx(record.open)
        assert loaded.close == pytest.approx(record.close)
        assert loaded.outcome == record.outcome
        assert loaded.final_ret == pytest.approx(record.final_ret)

    async def test_get_nonexistent_returns_none(self, store: SqliteStore):
        result = await store.get_candle("does-not-exist")
        assert result is None

    async def test_duplicate_write_ignored(self, store: SqliteStore):
        """Second write with same candle_id is silently ignored — first wins."""
        rec1 = _make_candle_record()
        await store.write_candle(rec1)

        rec2 = CandleRecord(
            candle_id=rec1.candle_id,
            start_time=900.0,
            end_time=1200.0,
            open=67800.0,
            high=67900.0,
            low=67750.0,
            close=67700.0,
            volume=15.0,
            outcome="DOWN",
            final_ret=-0.0015,
        )
        await store.write_candle(rec2)
        loaded = await store.get_candle(rec1.candle_id)
        assert loaded is not None
        assert loaded.outcome == "UP"  # first write wins


class TestSnapshotRoundTrip:
    async def test_write_and_read_by_candle_id(self, store: SqliteStore):
        snap1 = _make_snapshot(timestamp=1000.0)
        snap2 = _make_snapshot(timestamp=1005.0)
        snap_other = _make_snapshot(candle_id="other-candle", timestamp=1002.0)

        await store.write_snapshot(snap1)
        await store.write_snapshot(snap2)
        await store.write_snapshot(snap_other)

        results = await store.get_snapshots("btc-updown-5m-900")
        assert len(results) == 2
        # Ordered by timestamp
        assert results[0].timestamp < results[1].timestamp

    async def test_preserves_scalar_fields(self, store: SqliteStore):
        snap = _make_snapshot()
        await store.write_snapshot(snap)
        loaded = (await store.get_snapshots(snap.candle_id))[0]

        assert loaded.btc_price == pytest.approx(snap.btc_price)
        assert loaded.btc_bid == pytest.approx(snap.btc_bid)
        assert loaded.btc_ask == pytest.approx(snap.btc_ask)
        assert loaded.tick_timestamp == pytest.approx(snap.tick_timestamp)
        assert loaded.elapsed_pct == pytest.approx(snap.elapsed_pct)
        assert loaded.up_last_trade == pytest.approx(snap.up_last_trade)
        assert loaded.down_last_trade == pytest.approx(snap.down_last_trade)
        assert loaded.market_volume == pytest.approx(snap.market_volume)

    async def test_preserves_orderbook_data(self, store: SqliteStore):
        snap = _make_snapshot()
        await store.write_snapshot(snap)
        loaded = (await store.get_snapshots(snap.candle_id))[0]

        assert loaded.up_bids == snap.up_bids
        assert loaded.up_asks == snap.up_asks
        assert loaded.down_bids == snap.down_bids
        assert loaded.down_asks == snap.down_asks

    async def test_null_last_trade(self, store: SqliteStore):
        snap = Snapshot(
            timestamp=1000.0,
            tick_timestamp=999.5,
            candle_id="btc-updown-5m-900",
            elapsed_pct=0.33,
            btc_price=67800.0,
            btc_bid=67798.0,
            btc_ask=67802.0,
            up_bids=(),
            up_asks=(),
            down_bids=(),
            down_asks=(),
            up_last_trade=None,
            down_last_trade=None,
            market_volume=0.0,
        )
        await store.write_snapshot(snap)
        loaded = (await store.get_snapshots(snap.candle_id))[0]
        assert loaded.up_last_trade is None
        assert loaded.down_last_trade is None


# ---------------------------------------------------------------------------
# update_candle tests
# ---------------------------------------------------------------------------


class TestUpdateCandle:
    async def test_updates_existing_candle(self, store: SqliteStore):
        """update_candle modifies open, close, outcome, final_ret for an existing row."""
        original = _make_candle_record()
        await store.write_candle(original)

        await store.update_candle(
            candle_id=original.candle_id,
            open=67750.0,
            close=67700.0,
            outcome="DOWN",
            final_ret=-0.0007,
        )

        loaded = await store.get_candle(original.candle_id)
        assert loaded is not None
        assert loaded.open == pytest.approx(67750.0)
        assert loaded.close == pytest.approx(67700.0)
        assert loaded.outcome == "DOWN"
        assert loaded.final_ret == pytest.approx(-0.0007)

    async def test_update_preserves_untouched_columns(self, store: SqliteStore):
        """Columns not in the UPDATE SET clause stay unchanged."""
        original = _make_candle_record()
        await store.write_candle(original)

        await store.update_candle(
            candle_id=original.candle_id,
            open=99999.0,
            close=99999.0,
            outcome="DOWN",
            final_ret=0.0,
        )

        loaded = await store.get_candle(original.candle_id)
        assert loaded is not None
        # These columns should remain from the original insert
        assert loaded.start_time == pytest.approx(original.start_time)
        assert loaded.end_time == pytest.approx(original.end_time)
        assert loaded.high == pytest.approx(original.high)
        assert loaded.low == pytest.approx(original.low)
        assert loaded.volume == pytest.approx(original.volume)

    async def test_update_nonexistent_candle_is_noop(self, store: SqliteStore):
        """UPDATE on a missing candle_id affects zero rows and does not raise."""
        # Should not raise any exception
        await store.update_candle(
            candle_id="does-not-exist",
            open=100.0,
            close=200.0,
            outcome="UP",
            final_ret=0.5,
        )

        # Confirm nothing was created
        loaded = await store.get_candle("does-not-exist")
        assert loaded is None

    async def test_update_persists_after_reread(self, store: SqliteStore):
        """Verify the update is durable — read back multiple times."""
        original = _make_candle_record()
        await store.write_candle(original)

        await store.update_candle(
            candle_id=original.candle_id,
            open=68000.0,
            close=68100.0,
            outcome="UP",
            final_ret=0.00147,
        )

        # First read
        loaded1 = await store.get_candle(original.candle_id)
        assert loaded1 is not None
        assert loaded1.open == pytest.approx(68000.0)
        assert loaded1.close == pytest.approx(68100.0)

        # Second read — same values
        loaded2 = await store.get_candle(original.candle_id)
        assert loaded2 is not None
        assert loaded2.open == pytest.approx(68000.0)
        assert loaded2.close == pytest.approx(68100.0)
        assert loaded2.outcome == "UP"
        assert loaded2.final_ret == pytest.approx(0.00147)
