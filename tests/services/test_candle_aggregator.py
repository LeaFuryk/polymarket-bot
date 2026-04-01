"""Tests for CandleAggregator."""

import math
import time
from unittest.mock import AsyncMock

import pytest
from polybot.domain.models import BtcTick, Candle, PartialCandle
from polybot.services.candle_aggregator import CandleAggregator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tick(price=67800.0, timestamp=None) -> BtcTick:
    return BtcTick(
        price=price,
        bid=price - 2.0,
        ask=price + 2.0,
        timestamp=time.time() if timestamp is None else timestamp,
    )


def _make_aggregator(interval=300, history_size=20, backfill_candles=None) -> CandleAggregator:
    price_stream = AsyncMock()
    volume_feed = AsyncMock()
    volume_feed.get_volume = AsyncMock(return_value=10.0)
    volume_feed.get_candles = AsyncMock(return_value=backfill_candles or [])
    return CandleAggregator(price_stream, volume_feed, interval=interval, history_size=history_size)


# ---------------------------------------------------------------------------
# PartialCandle tests
# ---------------------------------------------------------------------------


class TestPartialCandle:
    def test_update_high(self):
        candle = PartialCandle(
            open=100.0,
            high=100.0,
            low=100.0,
            last_price=100.0,
            start_time=0,
            end_time=300,
        )
        candle.update(_make_tick(price=105.0))
        assert candle.high == 105.0
        assert candle.low == 100.0

    def test_update_low(self):
        candle = PartialCandle(
            open=100.0,
            high=100.0,
            low=100.0,
            last_price=100.0,
            start_time=0,
            end_time=300,
        )
        candle.update(_make_tick(price=95.0))
        assert candle.low == 95.0
        assert candle.high == 100.0

    def test_update_last_price(self):
        candle = PartialCandle(
            open=100.0,
            high=100.0,
            low=100.0,
            last_price=100.0,
            start_time=0,
            end_time=300,
        )
        candle.update(_make_tick(price=99.0))
        assert candle.last_price == 99.0

    def test_tick_count_increments(self):
        candle = PartialCandle(
            open=100.0,
            high=100.0,
            low=100.0,
            last_price=100.0,
            start_time=0,
            end_time=300,
        )
        candle.update(_make_tick(price=101.0))
        candle.update(_make_tick(price=102.0))
        assert candle.tick_count == 2


# ---------------------------------------------------------------------------
# CandleAggregator tests
# ---------------------------------------------------------------------------


class TestProcessTick:
    async def test_first_tick_creates_partial(self):
        agg = _make_aggregator()
        tick = _make_tick(price=67800.0, timestamp=1000.0)
        await agg._process_tick(tick)

        assert agg.partial is not None
        assert agg.partial.open == 67800.0
        assert agg.latest_tick == tick

    async def test_tick_in_same_candle_updates_partial(self):
        agg = _make_aggregator(interval=300)
        await agg._process_tick(_make_tick(price=100.0, timestamp=1000.0))
        await agg._process_tick(_make_tick(price=105.0, timestamp=1010.0))
        await agg._process_tick(_make_tick(price=95.0, timestamp=1020.0))

        assert agg.partial.open == 100.0
        assert agg.partial.high == 105.0
        assert agg.partial.low == 95.0
        assert agg.partial.last_price == 95.0
        assert agg.partial.tick_count == 3

    async def test_first_candle_discarded_on_startup(self):
        agg = _make_aggregator(interval=10)

        # First candle (incomplete startup) — discarded
        await agg._process_tick(_make_tick(price=100.0, timestamp=5.0))
        await agg._process_tick(_make_tick(price=110.0, timestamp=10.0))  # boundary

        assert len(agg.closed_candles()) == 0

    async def test_second_candle_kept(self):
        agg = _make_aggregator(interval=10)

        # Candle 0: startup candle — discarded
        await agg._process_tick(_make_tick(price=100.0, timestamp=0.0))
        # Candle 1: first complete candle — kept
        await agg._process_tick(_make_tick(price=105.0, timestamp=10.0))
        await agg._process_tick(_make_tick(price=108.0, timestamp=15.0))
        # Candle 2: triggers close of candle 1
        await agg._process_tick(_make_tick(price=110.0, timestamp=20.0))

        closed = agg.closed_candles()
        assert len(closed) == 1
        assert closed[0].open == 105.0
        assert closed[0].close == 108.0

    async def test_closed_candle_has_volume_from_feed(self):
        agg = _make_aggregator(interval=10)
        agg._volume_feed.get_volume = AsyncMock(return_value=18.42)

        # Startup candle — discarded
        await agg._process_tick(_make_tick(price=100.0, timestamp=0.0))
        # First complete candle
        await agg._process_tick(_make_tick(price=105.0, timestamp=10.0))
        # Close it
        await agg._process_tick(_make_tick(price=110.0, timestamp=20.0))

        closed = agg.closed_candles()
        assert closed[0].volume == pytest.approx(18.42)

    async def test_history_limited_to_size(self):
        agg = _make_aggregator(interval=10, history_size=3)

        # 7 boundaries → 1 discarded + 6 closed, capped at 3
        for i in range(8):
            await agg._process_tick(_make_tick(price=100.0 + i, timestamp=i * 10.0))

        assert len(agg.closed_candles()) <= 3


class TestBackfill:
    def _make_backfill_candles(self, count: int) -> list[Candle]:
        return [
            Candle(
                open=67800.0 + i * 10,
                high=67850.0 + i * 10,
                low=67750.0 + i * 10,
                close=67820.0 + i * 10,
                volume=15.0,
                start_time=i * 300.0,
                end_time=(i + 1) * 300.0,
            )
            for i in range(count)
        ]

    async def test_backfill_on_first_discard(self):
        backfill = self._make_backfill_candles(21)  # 20 closed + 1 in-progress (excluded)
        agg = _make_aggregator(interval=10, history_size=20, backfill_candles=backfill)

        # Startup candle — triggers discard + backfill
        await agg._process_tick(_make_tick(price=100.0, timestamp=5.0))
        await agg._process_tick(_make_tick(price=110.0, timestamp=10.0))

        # Should have 20 backfilled candles (last one excluded)
        assert len(agg.closed_candles()) == 20

    async def test_backfill_not_called_twice(self):
        backfill = self._make_backfill_candles(5)
        agg = _make_aggregator(interval=10, backfill_candles=backfill)

        # First discard → backfill
        await agg._process_tick(_make_tick(price=100.0, timestamp=5.0))
        await agg._process_tick(_make_tick(price=110.0, timestamp=10.0))

        # Second boundary → normal close, no second backfill
        await agg._process_tick(_make_tick(price=120.0, timestamp=20.0))

        assert agg._volume_feed.get_candles.await_count == 1

    async def test_backfill_empty_is_safe(self):
        agg = _make_aggregator(interval=10)  # default: get_candles returns []

        await agg._process_tick(_make_tick(price=100.0, timestamp=5.0))
        await agg._process_tick(_make_tick(price=110.0, timestamp=10.0))

        assert len(agg.closed_candles()) == 0


class TestCandleData:
    async def test_empty_history(self):
        agg = _make_aggregator()
        assert agg.candle_data() == ()

    async def test_log_ret_computed(self):
        agg = _make_aggregator(interval=10)

        # Startup candle — discarded
        await agg._process_tick(_make_tick(price=90.0, timestamp=0.0))
        # Candle 1: close=100
        await agg._process_tick(_make_tick(price=100.0, timestamp=10.0))
        # Candle 2: close=105
        await agg._process_tick(_make_tick(price=105.0, timestamp=20.0))
        # Trigger close of candle 2
        await agg._process_tick(_make_tick(price=110.0, timestamp=30.0))

        data = agg.candle_data()
        assert len(data) == 2
        assert data[0].log_ret is None  # first in history, no prev
        assert data[1].log_ret == pytest.approx(math.log(105.0 / 100.0))

    async def test_vol_pace_computed(self):
        agg = _make_aggregator(interval=10)
        agg._volume_feed.get_volume = AsyncMock(side_effect=[10.0, 20.0, 0.0])

        # Startup candle — discarded (no get_volume call)
        await agg._process_tick(_make_tick(price=90.0, timestamp=0.0))
        # Candle 1: volume=10
        await agg._process_tick(_make_tick(price=100.0, timestamp=10.0))
        # Candle 2: volume=20
        await agg._process_tick(_make_tick(price=101.0, timestamp=20.0))
        # Trigger close of candle 2
        await agg._process_tick(_make_tick(price=102.0, timestamp=30.0))

        data = agg.candle_data()
        # avg volume = (10 + 20) / 2 = 15
        assert data[0].vol_pace == pytest.approx(10.0 / 15.0)
        assert data[1].vol_pace == pytest.approx(20.0 / 15.0)

    async def test_relative_index(self):
        agg = _make_aggregator(interval=10)

        # Startup + 3 complete candles + trigger = 5 ticks
        for i in range(5):
            await agg._process_tick(_make_tick(price=100.0, timestamp=i * 10.0))

        data = agg.candle_data()
        assert len(data) == 3
        assert data[0].t == -3  # oldest
        assert data[1].t == -2
        assert data[2].t == -1  # most recent
