"""Tests for RotationManager — rotation handling and market setup."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from polybot.agent.rotation import RotationManager
from polybot.models.core import BtcPrice, CandleMarket

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candle_market(condition_id="cond_1", remaining=120.0, slug="btc-5min-123"):
    return CandleMarket(
        condition_id=condition_id,
        up_token_id="up_tok_1",
        down_token_id="down_tok_1",
        slug=slug,
        title="BTC 5min",
        start_time=time.time() - 180,
        end_time=time.time() + remaining,
    )


def _make_ctx():
    ctx = MagicMock()
    ctx.current_market = None
    ctx.live_engine = None
    ctx.live_mode = False
    ctx.config = MagicMock()
    ctx.market_data = MagicMock()
    ctx.market_data.btc_feed.get_price = AsyncMock(return_value=BtcPrice(price_usd=65000.0))
    ctx.market_data.outage_recovered = None
    ctx.market_data.last_outage_duration = 0.0
    ctx.shared = MagicMock()
    ctx.orderbook = MagicMock()
    ctx.orderbook.cancel_all.return_value = 0
    ctx.datastore = None
    ctx.market_history = MagicMock()
    ctx.resolution_tracker = MagicMock()
    return ctx


def _make_rotation(ctx=None):
    ctx = ctx or _make_ctx()
    return RotationManager(ctx), ctx


# ---------------------------------------------------------------------------
# handle_rotation
# ---------------------------------------------------------------------------


class TestHandleRotation:
    @pytest.mark.asyncio
    async def test_first_market_sets_up(self):
        rm, ctx = _make_rotation()
        ctx.current_market = None
        market = _make_candle_market()
        ctx.market_data.fetched_market = market

        await rm.handle_rotation()

        assert ctx.current_market is market
        ctx.market_data.set_market.assert_called_once_with(market)

    @pytest.mark.asyncio
    async def test_rotation_calls_transition(self):
        rm, ctx = _make_rotation()
        old = _make_candle_market(condition_id="cond_old")
        new = _make_candle_market(condition_id="cond_new")
        ctx.current_market = old
        ctx.market_data.fetched_market = new

        rm._handle_market_transition = AsyncMock()

        await rm.handle_rotation()

        rm._handle_market_transition.assert_awaited_once()
        assert ctx.current_market is new

    @pytest.mark.asyncio
    async def test_post_outage_rotation_skips_transition(self):
        rm, ctx = _make_rotation()
        old = _make_candle_market(condition_id="cond_old")
        new = _make_candle_market(condition_id="cond_new")
        ctx.current_market = old
        ctx.market_data.fetched_market = new
        ctx.market_data.outage_recovered = time.time()
        ctx.market_data.last_outage_duration = 30.0

        rm._handle_market_transition = AsyncMock()

        await rm.handle_rotation()

        rm._handle_market_transition.assert_not_awaited()
        ctx.orderbook.cancel_all.assert_called_once()
        assert ctx.current_market is new


# ---------------------------------------------------------------------------
# _setup_new_market
# ---------------------------------------------------------------------------


class TestSetupNewMarket:
    @pytest.mark.asyncio
    async def test_sets_market_and_records_btc_open(self):
        rm, ctx = _make_rotation()
        market = _make_candle_market()

        await rm._setup_new_market(market)

        assert ctx.current_market is market
        ctx.market_data.set_market.assert_called_once_with(market)
        ctx.config.market.condition_id = market.condition_id
        ctx.config.market.token_id = market.up_token_id
        ctx.resolution_tracker.record_candle_open.assert_called_once()

    @pytest.mark.asyncio
    async def test_sets_live_engine_token_ids(self):
        rm, ctx = _make_rotation()
        ctx.live_engine = MagicMock()
        market = _make_candle_market()

        await rm._setup_new_market(market)

        ctx.live_engine.set_current_token_ids.assert_called_once_with(
            market.up_token_id,
            market.down_token_id,
        )

    @pytest.mark.asyncio
    async def test_begins_candle_in_datastore(self):
        rm, ctx = _make_rotation()
        ctx.datastore = MagicMock()
        market = _make_candle_market()

        await rm._setup_new_market(market)

        ctx.datastore.begin_candle.assert_called_once()

    @pytest.mark.asyncio
    async def test_begins_candle_in_market_history(self):
        rm, ctx = _make_rotation()
        market = _make_candle_market()

        await rm._setup_new_market(market)

        ctx.market_history.begin_candle.assert_called_once()
