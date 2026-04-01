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


def _feed_ticks(agg: CandleAggregator, ticks: list[BtcTick]) -> None:
    """Feed ticks into the aggregator (sync — only updates partial)."""
    for tick in ticks:
        agg._latest_tick = tick
        agg._update_partial(tick)


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
# Tick routing tests
# ---------------------------------------------------------------------------


class TestUpdatePartial:
    def test_first_tick_creates_partial(self):
        agg = _make_aggregator()
        _feed_ticks(agg, [_make_tick(price=67800.0, timestamp=1000.0)])
        assert agg.partial is not None
        assert agg.partial.open == 67800.0

    def test_tick_in_same_candle_updates_partial(self):
        agg = _make_aggregator(interval=300)
        _feed_ticks(
            agg,
            [
                _make_tick(price=100.0, timestamp=1000.0),
                _make_tick(price=105.0, timestamp=1010.0),
                _make_tick(price=95.0, timestamp=1020.0),
            ],
        )
        assert agg.partial.open == 100.0
        assert agg.partial.high == 105.0
        assert agg.partial.low == 95.0
        assert agg.partial.tick_count == 3

    def test_future_tick_dropped(self):
        """A tick in a future interval is dropped — partial unchanged."""
        agg = _make_aggregator(interval=10)
        _feed_ticks(
            agg,
            [
                _make_tick(price=100.0, timestamp=0.0),
                _make_tick(price=110.0, timestamp=10.0),  # future interval → dropped
            ],
        )
        assert agg.partial.open == 100.0
        assert agg.partial.last_price == 100.0
        assert agg.partial.tick_count == 1

    def test_tick_after_partial_cleared_starts_new(self):
        """After expiry loop clears partial, next tick starts fresh."""
        agg = _make_aggregator(interval=10)
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=0.0)])

        # Simulate expiry loop clearing partial
        agg._partial = None

        _feed_ticks(agg, [_make_tick(price=120.0, timestamp=15.0)])
        assert agg.partial.open == 120.0

    def test_update_partial_does_not_close_candles(self):
        agg = _make_aggregator(interval=10)
        _feed_ticks(
            agg,
            [
                _make_tick(price=100.0, timestamp=0.0),
                _make_tick(price=110.0, timestamp=10.0),
            ],
        )
        assert len(agg.closed_candles()) == 0


# ---------------------------------------------------------------------------
# Candle closing tests
# ---------------------------------------------------------------------------


class TestCloseCandle:
    async def test_first_candle_discarded_and_backfilled(self):
        agg = _make_aggregator(interval=10)
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=5.0)])
        await agg._close_current_candle()
        assert agg._first_candle_complete is True
        assert agg.partial is None
        agg._volume_feed.get_candles.assert_awaited_once()

    async def test_second_candle_closes_normally(self):
        agg = _make_aggregator(interval=10)
        agg._first_candle_complete = True
        _feed_ticks(
            agg,
            [
                _make_tick(price=100.0, timestamp=10.0),
                _make_tick(price=105.0, timestamp=15.0),
            ],
        )
        await agg._close_current_candle()
        closed = agg.closed_candles()
        assert len(closed) == 1
        assert closed[0].open == 100.0
        assert closed[0].close == 105.0

    async def test_closed_candle_has_volume_from_feed(self):
        agg = _make_aggregator(interval=10)
        agg._first_candle_complete = True
        agg._volume_feed.get_volume = AsyncMock(return_value=18.42)
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=10.0)])
        await agg._close_current_candle()
        assert agg.closed_candles()[0].volume == pytest.approx(18.42)

    async def test_volume_error_falls_back_to_zero(self):
        agg = _make_aggregator(interval=10)
        agg._first_candle_complete = True
        agg._volume_feed.get_volume = AsyncMock(side_effect=Exception("timeout"))
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=10.0)])
        await agg._close_current_candle()
        assert agg.closed_candles()[0].volume == 0.0

    async def test_partial_cleared_after_close(self):
        agg = _make_aggregator(interval=10)
        agg._first_candle_complete = True
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=10.0)])
        await agg._close_current_candle()
        assert agg.partial is None

    async def test_history_limited_to_size(self):
        agg = _make_aggregator(interval=10, history_size=3)
        agg._first_candle_complete = True
        for i in range(6):
            _feed_ticks(agg, [_make_tick(price=100.0 + i, timestamp=(i + 1) * 10.0)])
            await agg._close_current_candle()
        assert len(agg.closed_candles()) <= 3


# ---------------------------------------------------------------------------
# Stream end tests
# ---------------------------------------------------------------------------


class TestStreamEnd:
    async def test_consume_ticks_raises_when_stream_ends(self):
        agg = _make_aggregator(interval=10)

        async def empty_ticks():
            return
            yield  # noqa: RET504

        agg._price_stream.ticks = empty_ticks

        with pytest.raises(RuntimeError, match="Price stream ended"):
            await agg._consume_ticks()


# ---------------------------------------------------------------------------
# Backfill tests
# ---------------------------------------------------------------------------


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
        backfill = self._make_backfill_candles(21)
        agg = _make_aggregator(interval=10, history_size=20, backfill_candles=backfill)
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=5.0)])
        await agg._close_current_candle()
        assert len(agg.closed_candles()) == 20

    async def test_backfill_not_called_on_second_close(self):
        agg = _make_aggregator(interval=10)
        agg._first_candle_complete = True
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=10.0)])
        await agg._close_current_candle()
        assert agg._volume_feed.get_candles.await_count == 0

    async def test_backfill_empty_is_safe(self):
        agg = _make_aggregator(interval=10)
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=5.0)])
        await agg._close_current_candle()
        assert len(agg.closed_candles()) == 0


class TestBackfillSmartDrop:
    def _make_candles(self, count, end_time_offset=0.0):
        now = time.time()
        return [
            Candle(
                open=100.0,
                high=110.0,
                low=90.0,
                close=105.0,
                volume=10.0,
                start_time=now - (count - i) * 300,
                end_time=now - (count - i - 1) * 300 + end_time_offset,
            )
            for i in range(count)
        ]

    async def test_keeps_all_if_last_is_closed(self):
        candles = self._make_candles(5, end_time_offset=-10.0)
        agg = _make_aggregator(interval=10, backfill_candles=candles)
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=5.0)])
        await agg._close_current_candle()
        assert len(agg.closed_candles()) == 5

    async def test_drops_last_if_in_progress(self):
        candles = self._make_candles(5, end_time_offset=600.0)
        agg = _make_aggregator(interval=10, backfill_candles=candles)
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=5.0)])
        await agg._close_current_candle()
        assert len(agg.closed_candles()) == 4


# ---------------------------------------------------------------------------
# CandleData computation tests
# ---------------------------------------------------------------------------


class TestCandleData:
    async def test_empty_history(self):
        agg = _make_aggregator()
        assert agg.candle_data() == ()

    async def test_log_ret_computed(self):
        agg = _make_aggregator(interval=10)
        agg._first_candle_complete = True
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=10.0)])
        await agg._close_current_candle()
        _feed_ticks(agg, [_make_tick(price=105.0, timestamp=20.0)])
        await agg._close_current_candle()
        data = agg.candle_data()
        assert len(data) == 2
        assert data[0].log_ret is None
        assert data[1].log_ret == pytest.approx(math.log(105.0 / 100.0))

    async def test_vol_pace_computed(self):
        agg = _make_aggregator(interval=10)
        agg._first_candle_complete = True
        agg._volume_feed.get_volume = AsyncMock(side_effect=[10.0, 20.0])
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=10.0)])
        await agg._close_current_candle()
        _feed_ticks(agg, [_make_tick(price=101.0, timestamp=20.0)])
        await agg._close_current_candle()
        data = agg.candle_data()
        assert data[0].vol_pace == pytest.approx(1.0)
        assert data[1].vol_pace == pytest.approx(20.0 / 15.0)

    async def test_relative_index(self):
        agg = _make_aggregator(interval=10)
        agg._first_candle_complete = True
        for i in range(3):
            _feed_ticks(agg, [_make_tick(price=100.0, timestamp=(i + 1) * 10.0)])
            await agg._close_current_candle()
        data = agg.candle_data()
        assert len(data) == 3
        assert data[0].t == -3
        assert data[2].t == -1
