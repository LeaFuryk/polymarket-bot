"""Tests for CandleAggregator."""

import time
from unittest.mock import AsyncMock

import pytest
from polybot_data.domain.models import BtcTick, PartialCandle
from polybot_data.services.candle_aggregator import CandleAggregator

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


def _make_aggregator(interval=300) -> CandleAggregator:
    price_stream = AsyncMock()
    volume_feed = AsyncMock()
    volume_feed.get_volume = AsyncMock(return_value=10.0)
    return CandleAggregator(price_stream, volume_feed, interval=interval)


def _feed_ticks(agg: CandleAggregator, ticks: list[BtcTick]) -> None:
    """Feed ticks into the aggregator (sync — only updates partial)."""
    for tick in ticks:
        agg._latest_tick = tick
        agg._update_partial(tick)


def _feed_valid_candle(agg: CandleAggregator, base_price: float = 100.0, base_ts: float = 10.0) -> None:
    """Feed 3 ticks in the same interval to make a valid candle (min tick threshold)."""
    _feed_ticks(
        agg,
        [
            _make_tick(price=base_price, timestamp=base_ts),
            _make_tick(price=base_price + 2, timestamp=base_ts + 1),
            _make_tick(price=base_price + 1, timestamp=base_ts + 2),
        ],
    )


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

    def test_update_partial_does_not_emit_event(self):
        """_update_partial never emits candle_close events."""
        from pyee.asyncio import AsyncIOEventEmitter

        events = AsyncIOEventEmitter()
        received = []
        events.on("candle_close", lambda candle: received.append(candle))

        agg = _make_aggregator(interval=10)
        agg.events = events
        _feed_ticks(
            agg,
            [
                _make_tick(price=100.0, timestamp=0.0),
                _make_tick(price=110.0, timestamp=10.0),
            ],
        )
        assert len(received) == 0


# ---------------------------------------------------------------------------
# Candle closing tests
# ---------------------------------------------------------------------------


class TestCloseCandle:
    async def test_first_candle_discarded(self):
        agg = _make_aggregator(interval=10)
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=5.0)])
        await agg._close_current_candle()
        assert agg._first_candle_complete is True
        assert agg.partial is None

    async def test_second_candle_closes_normally(self):
        from pyee.asyncio import AsyncIOEventEmitter

        events = AsyncIOEventEmitter()
        received = []
        events.on("candle_close", lambda candle: received.append(candle))

        agg = _make_aggregator(interval=10)
        agg.events = events
        agg._first_candle_complete = True
        _feed_valid_candle(agg, base_price=100.0, base_ts=10.0)
        await agg._close_current_candle()
        assert len(received) == 1
        assert received[0].open == 100.0

    async def test_closed_candle_has_volume_from_feed(self):
        from pyee.asyncio import AsyncIOEventEmitter

        events = AsyncIOEventEmitter()
        received = []
        events.on("candle_close", lambda candle: received.append(candle))

        agg = _make_aggregator(interval=10)
        agg.events = events
        agg._first_candle_complete = True
        agg._volume_feed.get_volume = AsyncMock(return_value=18.42)
        _feed_valid_candle(agg, base_price=100.0, base_ts=10.0)
        await agg._close_current_candle()
        assert len(received) == 1
        assert received[0].volume == pytest.approx(18.42)

    async def test_volume_error_falls_back_to_zero(self):
        from pyee.asyncio import AsyncIOEventEmitter

        events = AsyncIOEventEmitter()
        received = []
        events.on("candle_close", lambda candle: received.append(candle))

        agg = _make_aggregator(interval=10)
        agg.events = events
        agg._first_candle_complete = True
        agg._volume_feed.get_volume = AsyncMock(side_effect=Exception("timeout"))
        _feed_valid_candle(agg, base_price=100.0, base_ts=10.0)
        await agg._close_current_candle()
        assert len(received) == 1
        assert received[0].volume == 0.0

    async def test_partial_cleared_after_close(self):
        agg = _make_aggregator(interval=10)
        agg._first_candle_complete = True
        _feed_valid_candle(agg, base_price=100.0, base_ts=10.0)
        await agg._close_current_candle()
        assert agg.partial is None

    async def test_get_partial_volume(self):
        agg = _make_aggregator(interval=10)
        agg._volume_feed.get_volume = AsyncMock(return_value=12.5)
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=5.0)])
        vol = await agg.get_partial_volume()
        assert vol == pytest.approx(12.5)

    async def test_get_partial_volume_no_partial(self):
        agg = _make_aggregator(interval=10)
        vol = await agg.get_partial_volume()
        assert vol == 0.0

    async def test_get_partial_volume_error_returns_zero(self):
        agg = _make_aggregator(interval=10)
        agg._volume_feed.get_volume = AsyncMock(side_effect=Exception("timeout"))
        _feed_ticks(agg, [_make_tick(price=100.0, timestamp=5.0)])
        vol = await agg.get_partial_volume()
        assert vol == 0.0

    async def test_candle_close_event_emitted(self):
        from pyee.asyncio import AsyncIOEventEmitter

        events = AsyncIOEventEmitter()
        received = []
        events.on("candle_close", lambda candle: received.append(candle))

        agg = _make_aggregator(interval=10)
        agg.events = events
        agg._first_candle_complete = True
        _feed_valid_candle(agg, base_price=100.0, base_ts=10.0)
        await agg._close_current_candle()
        assert len(received) == 1
        assert received[0].open == 100.0

    async def test_no_event_emitter_by_default_still_works(self):
        """Closing a candle without a custom emitter does not raise."""
        agg = _make_aggregator(interval=10)
        agg._first_candle_complete = True
        _feed_valid_candle(agg, base_price=100.0, base_ts=10.0)
        # Should not raise even though no custom emitter is attached
        await agg._close_current_candle()
        assert agg.partial is None


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
