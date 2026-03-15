"""Tests for RotationManager — outage tracking, rotation detection, market setup."""

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
    ctx.discovery_failures = 0
    ctx.outage_start = None
    ctx.outage_recovered = None
    ctx.last_outage_duration = None
    ctx.current_market = None
    ctx.live_engine = None
    ctx.live_mode = False
    ctx.market_data = MagicMock()
    ctx.market_data.btc_feed.get_price = AsyncMock(return_value=BtcPrice(price_usd=65000.0))
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
# record_discovery_failure
# ---------------------------------------------------------------------------


class TestRecordDiscoveryFailure:
    def test_first_failure_increments_counter(self):
        rm, ctx = _make_rotation()
        rm.record_discovery_failure()
        assert ctx.discovery_failures == 1
        assert ctx.outage_start is None

    def test_third_failure_starts_outage(self):
        rm, ctx = _make_rotation()
        ctx.discovery_failures = 2
        rm.record_discovery_failure()
        assert ctx.discovery_failures == 3
        assert ctx.outage_start is not None

    def test_ongoing_outage_does_not_reset_start(self):
        rm, ctx = _make_rotation()
        ctx.discovery_failures = 5
        start = time.time() - 60
        ctx.outage_start = start
        rm.record_discovery_failure()
        assert ctx.outage_start == start  # unchanged
        assert ctx.discovery_failures == 6


# ---------------------------------------------------------------------------
# _clear_outage
# ---------------------------------------------------------------------------


class TestClearOutage:
    def test_clears_outage_state(self):
        rm, ctx = _make_rotation()
        ctx.outage_start = time.time() - 30
        ctx.discovery_failures = 5
        rm._clear_outage()
        assert ctx.discovery_failures == 0
        assert ctx.outage_start is None
        assert ctx.outage_recovered is not None

    def test_noop_when_no_outage(self):
        rm, ctx = _make_rotation()
        rm._clear_outage()
        assert ctx.discovery_failures == 0
        assert ctx.outage_recovered is None

    def test_recovery_banner_cleared_after_60s(self):
        rm, ctx = _make_rotation()
        ctx.outage_recovered = time.time() - 120
        rm._clear_outage()
        assert ctx.outage_recovered is None


# ---------------------------------------------------------------------------
# handle_fetched_market
# ---------------------------------------------------------------------------


class TestHandleFetchedMarket:
    @pytest.mark.asyncio
    async def test_first_market_sets_up(self):
        rm, ctx = _make_rotation()
        ctx.current_market = None
        market = _make_candle_market()

        await rm.handle_fetched_market(market)

        assert ctx.current_market is market
        ctx.market_data.set_market.assert_called_once_with(market)

    @pytest.mark.asyncio
    async def test_same_market_no_transition(self):
        rm, ctx = _make_rotation()
        market = _make_candle_market(condition_id="cond_1")
        ctx.current_market = market

        await rm.handle_fetched_market(market)

        # No transition, no setup
        assert ctx.current_market is market

    @pytest.mark.asyncio
    async def test_rotation_calls_transition(self):
        rm, ctx = _make_rotation()
        old = _make_candle_market(condition_id="cond_old")
        new = _make_candle_market(condition_id="cond_new")
        ctx.current_market = old

        # Mock _handle_market_transition to avoid full resolution flow
        rm._handle_market_transition = AsyncMock()

        await rm.handle_fetched_market(new)

        rm._handle_market_transition.assert_awaited_once()
        assert ctx.current_market is new

    @pytest.mark.asyncio
    async def test_post_outage_rotation_skips_transition(self):
        rm, ctx = _make_rotation()
        old = _make_candle_market(condition_id="cond_old")
        new = _make_candle_market(condition_id="cond_new")
        ctx.current_market = old
        ctx.outage_start = time.time() - 30
        ctx.discovery_failures = 5

        rm._handle_market_transition = AsyncMock()

        await rm.handle_fetched_market(new)

        rm._handle_market_transition.assert_not_awaited()
        ctx.orderbook.cancel_all.assert_called_once()
        assert ctx.current_market is new
        # Outage cleared
        assert ctx.outage_start is None
        assert ctx.discovery_failures == 0

    @pytest.mark.asyncio
    async def test_clears_outage_on_success(self):
        rm, ctx = _make_rotation()
        ctx.outage_start = time.time() - 30
        ctx.discovery_failures = 5
        market = _make_candle_market()
        ctx.current_market = market

        await rm.handle_fetched_market(market)

        assert ctx.discovery_failures == 0
        assert ctx.outage_start is None
        assert ctx.outage_recovered is not None


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
        ctx.shared.candle_open_btc = 65000.0
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
