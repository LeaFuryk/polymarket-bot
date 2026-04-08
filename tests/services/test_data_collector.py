"""Tests for DataCollector service."""

import math
import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from polybot_data.domain.collection import CandleRecord, Snapshot
from polybot_data.domain.models import (
    BtcTick,
    Candle,
    Market,
    MarketSnapshot,
    OrderBook,
    OrderBookLevel,
    PartialCandle,
)
from polybot_data.services.data_collector import RECORD_EVERY, DataCollector
from pyee.asyncio import AsyncIOEventEmitter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tick(price: float = 67800.0, timestamp: float | None = None) -> BtcTick:
    ts = timestamp if timestamp is not None else time.time()
    return BtcTick(price=price, bid=price - 2.0, ask=price + 2.0, timestamp=ts)


def _make_market() -> Market:
    return Market(
        condition_id="0xabc",
        up_token_id="up_123",
        down_token_id="down_456",
        slug="btc-updown-5m-123",
        question="Bitcoin up or down?",
        end_time=time.time() + 200,
        volume=5000.0,
    )


def _make_orderbook() -> OrderBook:
    return OrderBook(
        bids=(OrderBookLevel(0.55, 100), OrderBookLevel(0.54, 200)),
        asks=(OrderBookLevel(0.57, 150),),
        timestamp=time.time(),
    )


def _make_snapshot(market: Market) -> MarketSnapshot:
    return MarketSnapshot(
        market=market,
        up_book=_make_orderbook(),
        down_book=_make_orderbook(),
        last_trade_price=0.56,
        down_last_trade_price=0.44,
        volume=5000.0,
    )


def _make_partial(start_time: float | None = None) -> PartialCandle:
    st = start_time if start_time is not None else time.time() - 90
    return PartialCandle(
        open=67700.0,
        high=67850.0,
        low=67650.0,
        last_price=67800.0,
        start_time=st,
        end_time=st + 300,
        tick_count=5,
        last_tick_time=st + 80,
    )


def _make_collector(
    tick: BtcTick | None = None,
    market: Market | None = None,
    partial: PartialCandle | None = None,
) -> tuple[DataCollector, AsyncMock]:
    """Build a DataCollector with mocked dependencies. Returns (collector, store_mock)."""
    p = partial or _make_partial()

    candle_source = MagicMock()
    type(candle_source).latest_tick = PropertyMock(return_value=tick)
    type(candle_source).partial = PropertyMock(return_value=p)

    # Market slug must match the candle_id derived from partial's start_time
    boundary = int(p.start_time - (p.start_time % 300))
    mkt = market or Market(
        condition_id="0xabc",
        up_token_id="up_123",
        down_token_id="down_456",
        slug=f"btc-updown-5m-{boundary}",
        question="Bitcoin up or down?",
        end_time=p.end_time,
        volume=5000.0,
    )
    market_feed = AsyncMock()
    market_feed.discover_market = AsyncMock(return_value=mkt)
    market_feed.get_snapshot = AsyncMock(return_value=_make_snapshot(mkt))

    store = AsyncMock()
    store.write_snapshot = AsyncMock()
    store.write_candle = AsyncMock()

    events = AsyncIOEventEmitter()
    collector = DataCollector(candle_source, market_feed, store, events=events, broadcast_fn=None)
    collector._recording = True  # tests assume recording is active
    collector._tick_counter = RECORD_EVERY - 1  # next fetch will record
    return collector, store


# ---------------------------------------------------------------------------
# _fetch_and_dispatch tests
# ---------------------------------------------------------------------------


class TestCollectOnce:
    async def test_writes_snapshot(self):
        collector, store = _make_collector(tick=_make_tick(), partial=_make_partial())
        await collector._fetch_and_dispatch()
        store.write_snapshot.assert_awaited_once()

    async def test_snapshot_has_correct_btc_price(self):
        collector, store = _make_collector(
            tick=_make_tick(price=68000.0),
            partial=_make_partial(),
        )
        await collector._fetch_and_dispatch()
        snap = store.write_snapshot.call_args[0][0]
        assert isinstance(snap, Snapshot)
        assert snap.btc_price == 68000.0

    async def test_snapshot_has_up_last_trade(self):
        collector, store = _make_collector(tick=_make_tick(), partial=_make_partial())
        await collector._fetch_and_dispatch()
        snap = store.write_snapshot.call_args[0][0]
        assert snap.up_last_trade == 0.56

    async def test_snapshot_has_tick_timestamp(self):
        tick = _make_tick(timestamp=12345.0)
        collector, store = _make_collector(tick=tick, partial=_make_partial())
        await collector._fetch_and_dispatch()
        snap = store.write_snapshot.call_args[0][0]
        assert snap.tick_timestamp == 12345.0

    async def test_no_write_without_tick(self):
        collector, store = _make_collector(tick=None)
        await collector._fetch_and_dispatch()
        store.write_snapshot.assert_not_awaited()

    async def test_no_write_without_market(self):
        collector, store = _make_collector(tick=_make_tick(), partial=_make_partial())
        collector._market_feed.discover_market = AsyncMock(return_value=None)
        await collector._fetch_and_dispatch()
        store.write_snapshot.assert_not_awaited()


# ---------------------------------------------------------------------------
# on_candle_close tests
# ---------------------------------------------------------------------------


class TestOnCandleClose:
    async def test_writes_candle_record(self):
        collector, store = _make_collector(tick=_make_tick())
        candle = Candle(
            open=67800.0,
            high=67900.0,
            low=67750.0,
            close=67850.0,
            volume=15.0,
            start_time=900.0,
            end_time=1200.0,
        )
        await collector._on_candle_close(candle)
        store.write_candle.assert_awaited_once()
        record = store.write_candle.call_args[0][0]
        assert isinstance(record, CandleRecord)

    async def test_outcome_up_when_close_gte_open(self):
        collector, store = _make_collector(tick=_make_tick())
        candle = Candle(
            open=67800.0,
            high=67900.0,
            low=67750.0,
            close=67800.0,
            volume=15.0,
            start_time=900.0,
            end_time=1200.0,
        )
        await collector._on_candle_close(candle)
        record = store.write_candle.call_args[0][0]
        assert record.outcome == "UP"

    async def test_outcome_down_when_close_lt_open(self):
        collector, store = _make_collector(tick=_make_tick())
        candle = Candle(
            open=67800.0,
            high=67850.0,
            low=67700.0,
            close=67750.0,
            volume=15.0,
            start_time=900.0,
            end_time=1200.0,
        )
        await collector._on_candle_close(candle)
        record = store.write_candle.call_args[0][0]
        assert record.outcome == "DOWN"

    async def test_final_ret_is_correct(self):
        collector, store = _make_collector(tick=_make_tick())
        candle = Candle(
            open=67800.0,
            high=67900.0,
            low=67750.0,
            close=67850.0,
            volume=15.0,
            start_time=900.0,
            end_time=1200.0,
        )
        await collector._on_candle_close(candle)
        record = store.write_candle.call_args[0][0]
        expected = math.log(67850.0 / 67800.0)
        assert record.final_ret == pytest.approx(expected)

    async def test_candle_id_contains_boundary(self):
        collector, store = _make_collector(tick=_make_tick())
        candle = Candle(
            open=67800.0,
            high=67900.0,
            low=67750.0,
            close=67850.0,
            volume=15.0,
            start_time=900.0,
            end_time=1200.0,
        )
        await collector._on_candle_close(candle)
        record = store.write_candle.call_args[0][0]
        assert record.candle_id == "btc-updown-5m-900"


# ---------------------------------------------------------------------------
# _verify_resolution tests
# ---------------------------------------------------------------------------


def _make_candle_record(
    candle_id: str = "btc-updown-5m-900",
    open_: float = 67800.0,
    close: float = 67850.0,
    outcome: str = "UP",
) -> CandleRecord:
    """Build a CandleRecord for verify_resolution tests."""
    final_ret = math.log(close / open_) if open_ > 0 else 0.0
    return CandleRecord(
        candle_id=candle_id,
        start_time=900.0,
        end_time=1200.0,
        open=open_,
        high=max(open_, close) + 50.0,
        low=min(open_, close) - 50.0,
        close=close,
        volume=15.0,
        outcome=outcome,
        final_ret=final_ret,
    )


def _make_resolution_collector(
    resolution: dict | None = None,
    broadcast_fn: AsyncMock | None = None,
) -> tuple[DataCollector, AsyncMock, AsyncMock]:
    """Build a DataCollector configured for _verify_resolution tests.

    Returns (collector, store_mock, market_feed_mock).
    """
    candle_source = MagicMock()
    type(candle_source).latest_tick = PropertyMock(return_value=_make_tick())
    type(candle_source).partial = PropertyMock(return_value=_make_partial())

    market_feed = AsyncMock()
    market_feed.discover_market = AsyncMock(return_value=_make_market())
    market_feed.get_snapshot = AsyncMock(return_value=_make_snapshot(_make_market()))
    market_feed.get_resolution = AsyncMock(return_value=resolution)

    store = AsyncMock()
    store.write_snapshot = AsyncMock()
    store.write_candle = AsyncMock()
    store.update_candle = AsyncMock()

    events = AsyncIOEventEmitter()
    collector = DataCollector(
        candle_source,
        market_feed,
        store,
        events=events,
        broadcast_fn=broadcast_fn,
    )
    return collector, store, market_feed


class TestResolutionQueueMatch:
    """When Polymarket resolution matches Chainlink, prices still updated but no broadcast."""

    async def test_always_updates_with_polymarket_prices(self):
        original = _make_candle_record(open_=67800.0, close=67850.0, outcome="UP")
        resolution = {"open": 67800.0, "close": 67850.0, "outcome": "UP"}
        collector, store, _ = _make_resolution_collector(resolution=resolution)
        collector._pending_resolutions.append(original)

        await collector._process_pending_resolutions()

        store.update_candle.assert_awaited_once()
        assert len(collector._pending_resolutions) == 0


class TestResolutionQueuePending:
    """When resolution not available, candle stays in queue."""

    async def test_stays_in_queue_when_resolution_none(self):
        original = _make_candle_record()
        collector, store, _ = _make_resolution_collector(resolution=None)
        collector._pending_resolutions.append(original)

        await collector._process_pending_resolutions()

        assert len(collector._pending_resolutions) == 1  # still pending


class TestResolutionQueueOutcomeDiffers:
    """When Polymarket outcome differs, update_candle is called."""

    async def test_update_called_when_outcome_differs(self):
        original = _make_candle_record(open_=67800.0, close=67850.0, outcome="UP")
        resolution = {"open": 67800.0, "close": 67750.0, "outcome": "DOWN"}
        collector, store, _ = _make_resolution_collector(resolution=resolution)
        collector._pending_resolutions.append(original)

        await collector._process_pending_resolutions()

        store.update_candle.assert_awaited_once()
        call_kwargs = store.update_candle.call_args[1]
        assert call_kwargs["candle_id"] == original.candle_id
        assert call_kwargs["open"] == pytest.approx(67800.0)
        assert call_kwargs["close"] == pytest.approx(67750.0)
        assert call_kwargs["outcome"] == "DOWN"
        assert len(collector._pending_resolutions) == 0


class TestResolutionQueueOpenDiffers:
    """When open price differs beyond tolerance, update is triggered."""

    async def test_update_called_when_open_differs(self):
        original = _make_candle_record(open_=67800.0, close=67850.0, outcome="UP")
        resolution = {"open": 67810.0, "close": 67850.0, "outcome": "UP"}
        collector, store, _ = _make_resolution_collector(resolution=resolution)
        collector._pending_resolutions.append(original)

        await collector._process_pending_resolutions()

        store.update_candle.assert_awaited_once()
        call_kwargs = store.update_candle.call_args[1]
        assert call_kwargs["open"] == pytest.approx(67810.0)


class TestResolutionQueueBroadcast:
    """Test candle_correction broadcast behavior."""

    async def test_broadcasts_correction_on_mismatch(self):
        broadcast_fn = AsyncMock()
        original = _make_candle_record(open_=67800.0, close=67850.0, outcome="UP")
        resolution = {"open": 67800.0, "close": 67750.0, "outcome": "DOWN"}
        collector, store, _ = _make_resolution_collector(resolution=resolution, broadcast_fn=broadcast_fn)
        collector._pending_resolutions.append(original)

        await collector._process_pending_resolutions()

        broadcast_fn.assert_awaited_once()
        msg = broadcast_fn.call_args[0][0]
        assert msg["type"] == "candle_correction"
        assert msg["outcome"] == "DOWN"

    async def test_no_broadcast_when_matches(self):
        broadcast_fn = AsyncMock()
        original = _make_candle_record(open_=67800.0, close=67850.0, outcome="UP")
        resolution = {"open": 67800.0, "close": 67850.0, "outcome": "UP"}
        collector, store, _ = _make_resolution_collector(resolution=resolution, broadcast_fn=broadcast_fn)
        collector._pending_resolutions.append(original)

        await collector._process_pending_resolutions()

        broadcast_fn.assert_not_awaited()

    async def test_no_broadcast_when_no_broadcast_fn(self):
        original = _make_candle_record(open_=67800.0, close=67850.0, outcome="UP")
        resolution = {"open": 67800.0, "close": 67750.0, "outcome": "DOWN"}
        collector, store, _ = _make_resolution_collector(resolution=resolution)
        collector._pending_resolutions.append(original)

        await collector._process_pending_resolutions()
        store.update_candle.assert_awaited_once()


class TestResolutionQueueFinalRet:
    """Verify correct final_ret computation."""

    async def test_final_ret_computed(self):
        original = _make_candle_record(open_=67800.0, close=67850.0, outcome="UP")
        resolution = {"open": 67810.0, "close": 67900.0, "outcome": "UP"}
        collector, store, _ = _make_resolution_collector(resolution=resolution)
        collector._pending_resolutions.append(original)

        await collector._process_pending_resolutions()

        call_kwargs = store.update_candle.call_args[1]
        expected_ret = math.log(67900.0 / 67810.0)
        assert call_kwargs["final_ret"] == pytest.approx(expected_ret)

    async def test_final_ret_negative_for_down(self):
        original = _make_candle_record(open_=67800.0, close=67850.0, outcome="UP")
        resolution = {"open": 67800.0, "close": 67700.0, "outcome": "DOWN"}
        collector, store, _ = _make_resolution_collector(resolution=resolution)
        collector._pending_resolutions.append(original)

        await collector._process_pending_resolutions()

        call_kwargs = store.update_candle.call_args[1]
        assert call_kwargs["final_ret"] < 0


class TestResolutionQueueMultiple:
    """Test queue with multiple candles."""

    async def test_processes_multiple_candles(self):
        resolution = {"open": 67800.0, "close": 67850.0, "outcome": "UP"}
        collector, store, market_feed = _make_resolution_collector(resolution=None)
        # First candle resolved, second not yet
        market_feed.get_resolution = AsyncMock(side_effect=[resolution, None])

        c1 = _make_candle_record(candle_id="btc-updown-5m-900", open_=67800.0, close=67850.0, outcome="UP")
        c2 = _make_candle_record(candle_id="btc-updown-5m-1200", open_=67900.0, close=67950.0, outcome="UP")
        collector._pending_resolutions = [c1, c2]

        await collector._process_pending_resolutions()

        assert len(collector._pending_resolutions) == 1
        assert collector._pending_resolutions[0].candle_id == "btc-updown-5m-1200"
