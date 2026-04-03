"""Tests for DataCollector service."""

import math
import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from polybot.domain.collection import CandleRecord, Snapshot
from polybot.domain.models import (
    BtcTick,
    Candle,
    Market,
    MarketSnapshot,
    OrderBook,
    OrderBookLevel,
    PartialCandle,
)
from polybot.services.data_collector import DataCollector
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
    candle_source = MagicMock()
    type(candle_source).latest_tick = PropertyMock(return_value=tick)
    type(candle_source).partial = PropertyMock(return_value=partial)

    mkt = market or _make_market()
    market_feed = AsyncMock()
    market_feed.discover_market = AsyncMock(return_value=mkt)
    market_feed.get_snapshot = AsyncMock(return_value=_make_snapshot(mkt))

    store = AsyncMock()
    store.write_snapshot = AsyncMock()
    store.write_candle = AsyncMock()

    events = AsyncIOEventEmitter()
    collector = DataCollector(candle_source, market_feed, store, events=events)
    collector._recording = True  # tests assume recording is active
    return collector, store


# ---------------------------------------------------------------------------
# collect_once tests
# ---------------------------------------------------------------------------


class TestCollectOnce:
    async def test_writes_snapshot(self):
        collector, store = _make_collector(tick=_make_tick(), partial=_make_partial())
        await collector.collect_once()
        store.write_snapshot.assert_awaited_once()

    async def test_snapshot_has_correct_btc_price(self):
        collector, store = _make_collector(
            tick=_make_tick(price=68000.0),
            partial=_make_partial(),
        )
        await collector.collect_once()
        snap = store.write_snapshot.call_args[0][0]
        assert isinstance(snap, Snapshot)
        assert snap.btc_price == 68000.0

    async def test_snapshot_has_up_last_trade(self):
        collector, store = _make_collector(tick=_make_tick(), partial=_make_partial())
        await collector.collect_once()
        snap = store.write_snapshot.call_args[0][0]
        assert snap.up_last_trade == 0.56

    async def test_snapshot_has_tick_timestamp(self):
        tick = _make_tick(timestamp=12345.0)
        collector, store = _make_collector(tick=tick, partial=_make_partial())
        await collector.collect_once()
        snap = store.write_snapshot.call_args[0][0]
        assert snap.tick_timestamp == 12345.0

    async def test_no_write_without_tick(self):
        collector, store = _make_collector(tick=None)
        await collector.collect_once()
        store.write_snapshot.assert_not_awaited()

    async def test_no_write_without_market(self):
        collector, store = _make_collector(tick=_make_tick(), partial=_make_partial())
        collector._market_feed.discover_market = AsyncMock(return_value=None)
        await collector.collect_once()
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
