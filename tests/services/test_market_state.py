"""Tests for MarketStateService."""

import time
from unittest.mock import AsyncMock

import pytest
from polybot.domain.models import (
    BtcTick,
    Market,
    MarketSnapshot,
    OrderBook,
    OrderBookLevel,
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
    )


def _make_service(tick=None, market=None, volume=10.0):
    price_stream = AsyncMock()
    volume_feed = AsyncMock()
    market_feed = AsyncMock()

    mkt = market or _make_market()
    market_feed.discover_market = AsyncMock(return_value=mkt)
    market_feed.get_snapshot = AsyncMock(return_value=_make_snapshot(mkt))
    volume_feed.get_volume = AsyncMock(return_value=volume)

    service = MarketStateService(price_stream, volume_feed, market_feed)
    service._latest_tick = tick
    return service


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

    async def test_current_candle_has_volume(self):
        service = _make_service(tick=_make_tick(), volume=18.42)
        state = await service.get_state()
        assert state.current_candle.volume_so_far == pytest.approx(18.42)

    async def test_current_candle_has_heartbeat_age(self):
        old_tick = BtcTick(price=67800.0, bid=67798.0, ask=67802.0, timestamp=time.time() - 1.5)
        service = _make_service(tick=old_tick)
        state = await service.get_state()
        assert state.current_candle.chainlink_heartbeat_age_sec >= 1.0

    async def test_microstructure_spread(self):
        # bid=67798, ask=67802, mid=67800 → spread = 4/67800 * 10000 ≈ 0.59 bps
        service = _make_service(tick=_make_tick(price=67800.0, bid=67798.0, ask=67802.0))
        state = await service.get_state()
        assert state.microstructure.spread_bps == pytest.approx(0.59, abs=0.01)

    async def test_microstructure_has_polymarket_price(self):
        service = _make_service(tick=_make_tick())
        state = await service.get_state()
        assert state.microstructure.polymarket_yes_price is not None

    async def test_microstructure_has_imbalance(self):
        service = _make_service(tick=_make_tick())
        state = await service.get_state()
        assert -1.0 <= state.microstructure.ob_imbalance <= 1.0

    async def test_candles_empty_for_now(self):
        service = _make_service(tick=_make_tick())
        state = await service.get_state()
        assert state.candles == ()

    async def test_technicals_none_for_now(self):
        service = _make_service(tick=_make_tick())
        state = await service.get_state()
        assert state.technicals.rsi14 is None
        assert state.technicals.macd_hist is None

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
