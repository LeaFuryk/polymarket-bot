"""Tests for MarketStateService."""

import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from polybot.domain.models import (
    BtcTick,
    Candle,
    Market,
    MarketSnapshot,
    OrderBook,
    OrderBookLevel,
    PartialCandle,
    PromptState,
)
from polybot.services.market_state import MarketStateService

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _make_tick(price=67800.0, bid=67798.0, ask=67802.0) -> BtcTick:
    return BtcTick(price=price, bid=bid, ask=ask, timestamp=time.time())


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


def _make_partial(open_price=67700.0) -> PartialCandle:
    return PartialCandle(
        open=open_price,
        high=67850.0,
        low=67650.0,
        last_price=67800.0,
        start_time=time.time() - 90,
        end_time=time.time() + 210,
        tick_count=5,
        last_tick_time=time.time(),
    )


def _make_service(tick=None, market=None, partial=None, closed=(), volume=0.0):
    candle_source = MagicMock()
    type(candle_source).latest_tick = PropertyMock(return_value=tick)
    type(candle_source).partial = PropertyMock(return_value=partial)
    candle_source.closed_candles.return_value = closed
    candle_source.candle_data.return_value = ()
    candle_source.get_partial_volume = AsyncMock(return_value=volume)

    market_feed = AsyncMock()
    mkt = market or _make_market()
    market_feed.discover_market = AsyncMock(return_value=mkt)
    market_feed.get_snapshot = AsyncMock(return_value=_make_snapshot(mkt))

    return MarketStateService(candle_source, market_feed)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetState:
    async def test_returns_prompt_state(self):
        service = _make_service(tick=_make_tick())
        state = await service.get_state()

        assert state is not None
        assert isinstance(state, PromptState)

    async def test_returns_none_without_tick(self):
        service = _make_service(tick=None)
        state = await service.get_state()
        assert state is None

    async def test_returns_none_without_market(self):
        service = _make_service(tick=_make_tick())
        service._market_feed.discover_market = AsyncMock(return_value=None)
        state = await service.get_state()
        assert state is None

    async def test_current_candle_has_last_price(self):
        service = _make_service(tick=_make_tick(price=67850.0))
        state = await service.get_state()
        assert state.current_candle.last_price == 67850.0

    async def test_current_candle_has_heartbeat_age(self):
        old_tick = BtcTick(price=67800.0, bid=67798.0, ask=67802.0, timestamp=time.time() - 1.5)
        service = _make_service(tick=old_tick)
        state = await service.get_state()
        assert state.current_candle.chainlink_heartbeat_age_sec >= 1.0

    async def test_current_candle_ohlc_from_partial(self):
        service = _make_service(
            tick=_make_tick(price=67800.0),
            partial=_make_partial(open_price=67700.0),
        )
        state = await service.get_state()
        assert state.current_candle.open == 67700.0
        assert state.current_candle.high_so_far == 67850.0
        assert state.current_candle.low_so_far == 67650.0

    async def test_partial_ret_computed(self):
        import math

        service = _make_service(
            tick=_make_tick(price=67800.0),
            partial=_make_partial(open_price=67700.0),
        )
        state = await service.get_state()
        expected = math.log(67800.0 / 67700.0)
        assert state.current_candle.partial_ret == pytest.approx(expected, rel=1e-4)

    async def test_current_candle_none_without_partial(self):
        service = _make_service(tick=_make_tick(), partial=None)
        state = await service.get_state()
        assert state.current_candle.open is None
        assert state.current_candle.high_so_far is None
        assert state.current_candle.partial_ret is None

    async def test_microstructure_spread(self):
        service = _make_service(tick=_make_tick(price=67800.0, bid=67798.0, ask=67802.0))
        state = await service.get_state()
        assert state.microstructure.spread_bps == pytest.approx(0.59, abs=0.01)

    async def test_microstructure_has_polymarket_price(self):
        service = _make_service(tick=_make_tick())
        state = await service.get_state()
        assert state.microstructure.polymarket_yes_price is not None

    async def test_elapsed_pct_clamped_lower_bound(self):
        # Simulate out-of-order tick: tick.timestamp < partial.start_time
        future_partial = PartialCandle(
            open=67700.0,
            high=67850.0,
            low=67650.0,
            last_price=67800.0,
            start_time=time.time() + 100,  # start_time in the future
            end_time=time.time() + 400,
            tick_count=1,
            last_tick_time=time.time(),
        )
        service = _make_service(tick=_make_tick(), partial=future_partial)
        state = await service.get_state()
        assert state.current_candle.elapsed_pct >= 0.0

    async def test_frozen_partial_immutable_during_await(self):
        partial = _make_partial(open_price=67700.0)
        service = _make_service(tick=_make_tick(price=67800.0), partial=partial)

        state = await service.get_state()
        original_open = state.current_candle.open

        # Mutate the original partial after get_state — should not affect the result
        partial.open = 99999.0
        assert original_open == 67700.0

    async def test_volume_so_far_from_candle_source(self):
        service = _make_service(tick=_make_tick(), partial=_make_partial(), volume=18.42)
        state = await service.get_state()
        assert state.current_candle.volume_so_far == pytest.approx(18.42)

    async def test_volume_zero_without_partial(self):
        service = _make_service(tick=_make_tick(), volume=18.42)
        state = await service.get_state()
        assert state.current_candle.volume_so_far == 0.0

    async def test_volume_pace_computed(self):
        closed = tuple(
            Candle(open=100, high=110, low=90, close=105, volume=20.0, start_time=i * 300, end_time=(i + 1) * 300)
            for i in range(5)
        )
        service = _make_service(tick=_make_tick(), partial=_make_partial(), closed=closed, volume=15.0)
        state = await service.get_state()
        assert state.current_candle.volume_pace is not None
        assert state.current_candle.volume_pace > 0

    async def test_volume_pace_none_without_history(self):
        service = _make_service(tick=_make_tick(), volume=10.0)
        state = await service.get_state()
        assert state.current_candle.volume_pace is None

    async def test_polymarket_yes_delta_computed(self):
        """First call captures reference, so yes_delta = 0."""
        service = _make_service(tick=_make_tick(), partial=_make_partial())
        state = await service.get_state()
        assert state.microstructure.polymarket_yes_delta == pytest.approx(0.0)

    async def test_polymarket_vol_delta_computed(self):
        """vol_delta = 0 on first call (reference just captured)."""
        service = _make_service(tick=_make_tick(), partial=_make_partial())
        state = await service.get_state()
        assert state.microstructure.polymarket_vol_delta == pytest.approx(0.0)

    async def test_deltas_reset_on_candle_change(self):
        """When candle changes, reference is recaptured, deltas reset to 0."""
        partial1 = _make_partial(open_price=67700.0)
        service = _make_service(tick=_make_tick(), partial=partial1)
        await service.get_state()  # captures reference

        # Change partial to a new candle (different start_time)
        partial2 = PartialCandle(
            open=68000.0,
            high=68050.0,
            low=67950.0,
            last_price=68000.0,
            start_time=time.time() + 300,
            end_time=time.time() + 600,
            tick_count=1,
            last_tick_time=time.time(),
        )
        type(service._candles).partial = PropertyMock(return_value=partial2)

        state2 = await service.get_state()
        assert state2.microstructure.polymarket_yes_delta == pytest.approx(0.0)

    async def test_deltas_none_with_empty_orderbook(self):
        """When orderbook is empty, yes_delta is None and ref is not poisoned."""
        service = _make_service(tick=_make_tick(), partial=_make_partial())

        # First call with empty book — reference not captured
        empty_book = OrderBook(bids=(), asks=(), timestamp=time.time())
        empty_snapshot = MarketSnapshot(
            market=_make_market(),
            up_book=empty_book,
            down_book=empty_book,
            last_trade_price=None,
            down_last_trade_price=None,
            volume=0.0,
        )
        service._market_feed.get_snapshot = AsyncMock(return_value=empty_snapshot)
        state1 = await service.get_state()
        assert state1.microstructure.polymarket_yes_delta is None

        # Second call with real book — reference captured, delta = 0
        service._market_feed.get_snapshot = AsyncMock(return_value=_make_snapshot(_make_market()))
        state2 = await service.get_state()
        assert state2.microstructure.polymarket_yes_delta == pytest.approx(0.0)

    async def test_nonzero_delta_on_second_call(self):
        """Second call in same candle with different price shows non-zero delta."""
        service = _make_service(tick=_make_tick(), partial=_make_partial())

        # First call — captures reference (last_trade_price = 0.56 from _make_snapshot)
        await service.get_state()

        # Second call — change snapshot to have a different last_trade_price
        new_book = OrderBook(
            bids=(OrderBookLevel(0.60, 100),),
            asks=(OrderBookLevel(0.62, 100),),
            timestamp=time.time(),
        )
        new_snapshot = MarketSnapshot(
            market=_make_market(),
            up_book=new_book,
            down_book=new_book,
            last_trade_price=0.61,
            down_last_trade_price=0.39,
            volume=6000.0,
        )
        service._market_feed.get_snapshot = AsyncMock(return_value=new_snapshot)
        state2 = await service.get_state()

        # last_trade_price = 0.61, reference = 0.56 → delta = 0.05
        assert state2.microstructure.polymarket_yes_delta is not None
        assert state2.microstructure.polymarket_yes_delta != 0.0

    async def test_to_dict(self):
        service = _make_service(tick=_make_tick())
        state = await service.get_state()
        d = state.to_dict()
        assert isinstance(d, dict)
        assert "candles" in d
        assert "current_candle" in d
        assert "technicals" in d
        assert "microstructure" in d
        assert "bet_state" in d
