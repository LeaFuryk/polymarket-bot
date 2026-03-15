"""Tests for MarketMonitor — fetch pipeline and trigger logic."""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from polybot.models.core import (
    BtcPrice,
    MarketSnapshot,
    OrderbookLevel,
    OrderbookSnapshot,
)
from polybot.tasks.market_monitor import MarketMonitor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orderbook(best_bid: float, best_ask: float, depth: float = 100.0):
    return OrderbookSnapshot(
        bids=[OrderbookLevel(price=best_bid, size=depth / best_bid)],
        asks=[OrderbookLevel(price=best_ask, size=depth / best_ask)],
    )


def _make_snapshot(up_bid=0.48, up_ask=0.52, down_bid=0.46, down_ask=0.50, btc_price=65000.0):
    return MarketSnapshot(
        condition_id="cond_test",
        orderbook=_make_orderbook(up_bid, up_ask),
        down_orderbook=_make_orderbook(down_bid, down_ask),
        btc_price=BtcPrice(price_usd=btc_price),
    )


def _make_prefilter_result(should_skip=False, reason="", streak=0, direction=""):
    result = MagicMock()
    result.should_skip = should_skip
    result.reason = reason
    result.consecutive_streak = streak
    result.streak_direction = direction
    result.btc_range_30m = 0.0
    result.best_entry_price = 1.0
    return result


def _make_monitor():
    ctx = MagicMock()

    # Config
    ctx.config.monitor.market_monitor_interval = 1.0
    ctx.config.monitor.rr_trigger_threshold = 0.5
    ctx.config.monitor.ai_cooldown_seconds = 10.0
    ctx.config.monitor.adaptive_entry_enabled = False

    # SharedState
    shared = MagicMock()
    shared.current_market = None
    shared.latest_snapshot = None
    shared.snapshot_timestamp = 0.0
    shared.tick_spreads_up = []
    shared.tick_spreads_down = []
    shared.ai_last_call_time = 0.0
    shared.candle_open_btc = 65000.0
    shared.monitor_status = {}
    shared.shutdown = False
    shared.rotation_in_progress = False
    shared.session_wins = 0
    shared.session_losses = 0
    ctx.shared = shared

    # Portfolio
    portfolio = MagicMock()
    portfolio.up_position.shares = 0.0
    portfolio.down_position.shares = 0.0
    ctx.portfolio = portfolio

    # Prefilter
    ctx.prefilter = MagicMock()
    ctx.prefilter.check.return_value = _make_prefilter_result()

    # Market data provider
    ctx.market_data = AsyncMock()
    ctx.market_data.get_snapshot = AsyncMock(return_value=_make_snapshot())

    # Resolution tracker
    ctx.resolution_tracker = MagicMock()

    # Datastores
    ctx.datastore = None
    ctx.feature_config = None
    ctx.market_history = MagicMock()
    ctx.market_history.current_candle_id = None

    # Adaptive entry
    ctx.adaptive_entry = None

    # Indicators processor
    ctx.processor = None

    # Broadcaster
    ctx.broadcaster = MagicMock()
    ctx.broadcaster.has_clients = False

    # AI Decision
    ai_decision = MagicMock()
    ai_decision.busy = False
    ai_decision.evaluate_entry = AsyncMock()

    monitor = MarketMonitor(ctx, ai_decision, logger=logging.getLogger("test"))
    return monitor, ctx, ai_decision


# ---------------------------------------------------------------------------
# _persist_snapshots
# ---------------------------------------------------------------------------


class TestPersistSnapshots:
    def test_queues_datastore_when_candle_id_set(self):
        monitor, ctx, _ = _make_monitor()
        datastore = MagicMock()
        datastore.current_candle_id = 42
        monitor._datastore = datastore
        monitor._feature_config = None

        snapshot = _make_snapshot()
        pf_result = _make_prefilter_result()
        monitor._persist_snapshots(snapshot, pf_result)
        datastore.queue_snapshot.assert_called_once()

    def test_skips_datastore_when_no_candle_id(self):
        monitor, ctx, _ = _make_monitor()
        datastore = MagicMock()
        datastore.current_candle_id = None
        monitor._datastore = datastore

        snapshot = _make_snapshot()
        pf_result = _make_prefilter_result()
        monitor._persist_snapshots(snapshot, pf_result)
        datastore.queue_snapshot.assert_not_called()

    def test_skips_datastore_when_none(self):
        monitor, ctx, _ = _make_monitor()
        monitor._datastore = None

        snapshot = _make_snapshot()
        pf_result = _make_prefilter_result()
        monitor._persist_snapshots(snapshot, pf_result)

    def test_queues_market_history_when_candle_id_set(self):
        monitor, ctx, _ = _make_monitor()
        ctx.market_history.current_candle_id = 7

        snapshot = _make_snapshot()
        pf_result = _make_prefilter_result()
        monitor._persist_snapshots(snapshot, pf_result)
        ctx.market_history.queue_snapshot.assert_called_once()

    def test_skips_market_history_when_no_candle_id(self):
        monitor, ctx, _ = _make_monitor()
        ctx.market_history.current_candle_id = None

        snapshot = _make_snapshot()
        pf_result = _make_prefilter_result()
        monitor._persist_snapshots(snapshot, pf_result)
        ctx.market_history.queue_snapshot.assert_not_called()


# ---------------------------------------------------------------------------
# _evaluate_trigger
# ---------------------------------------------------------------------------


class TestEvaluateTrigger:
    def _run_trigger(self, monitor, ctx, pf_result=None, snapshot=None):
        if snapshot is None:
            snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        if pf_result is None:
            pf_result = _make_prefilter_result()
        monitor._evaluate_trigger(snapshot, pf_result)

    def test_prefilter_fail_no_trigger(self):
        monitor, ctx, ai = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        pf_result = _make_prefilter_result(should_skip=True, reason="spread too wide")
        self._run_trigger(monitor, ctx, pf_result=pf_result)
        ai.evaluate_entry.assert_not_called()
        assert "PREFILTER" in ctx.shared.monitor_status["gate_status"]

    def test_rr_below_threshold_no_trigger(self):
        monitor, ctx, ai = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        monitor._rr_threshold = 5.0
        snapshot = _make_snapshot(up_ask=0.90, down_ask=0.90)
        pf_result = _make_prefilter_result(should_skip=False)
        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)
        ai.evaluate_entry.assert_not_called()
        assert "ADAPTIVE" in ctx.shared.monitor_status["gate_status"]

    def test_cooldown_active_no_trigger(self):
        monitor, ctx, ai = _make_monitor()
        ctx.shared.ai_last_call_time = time.time()
        monitor._rr_threshold = 0.1
        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        pf_result = _make_prefilter_result(should_skip=False)
        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)
        ai.evaluate_entry.assert_not_called()
        assert "COOLDOWN" in ctx.shared.monitor_status["gate_status"]

    def test_ai_busy_no_trigger(self):
        monitor, ctx, ai = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        ai.busy = True
        monitor._rr_threshold = 0.1
        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        pf_result = _make_prefilter_result(should_skip=False)
        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)
        ai.evaluate_entry.assert_not_called()
        assert "AI BUSY" in ctx.shared.monitor_status["gate_status"]

    @pytest.mark.asyncio
    async def test_all_gates_pass_triggers_ai(self):
        monitor, ctx, ai = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        ai.busy = False
        monitor._rr_threshold = 0.1
        monitor._cooldown = 0.0
        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        pf_result = _make_prefilter_result(should_skip=False)
        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)
        await asyncio.sleep(0)
        ai.evaluate_entry.assert_called_once()
        assert ctx.shared.monitor_status["ai_triggered"] is True

    @pytest.mark.asyncio
    async def test_adaptive_mode_triggers(self):
        monitor, ctx, ai = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        ai.busy = False
        monitor._adaptive_enabled = True
        monitor._cooldown = 0.0
        adaptive = MagicMock()
        adaptive.should_trigger.return_value = True
        adaptive.btc_threshold = 50.0
        adaptive.max_entry_price = 0.60
        monitor._adaptive_entry = adaptive
        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        pf_result = _make_prefilter_result(should_skip=False)
        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)
        await asyncio.sleep(0)
        adaptive.should_trigger.assert_called_once()
        ai.evaluate_entry.assert_called_once()

    def test_adaptive_mode_blocks(self):
        monitor, ctx, ai = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        ai.busy = False
        monitor._adaptive_enabled = True
        monitor._cooldown = 0.0
        adaptive = MagicMock()
        adaptive.should_trigger.return_value = False
        adaptive.btc_threshold = 500.0
        adaptive.max_entry_price = 0.20
        monitor._adaptive_entry = adaptive
        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        pf_result = _make_prefilter_result(should_skip=False)
        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)
        ai.evaluate_entry.assert_not_called()
        assert "ADAPTIVE" in ctx.shared.monitor_status["gate_status"]

    @pytest.mark.asyncio
    async def test_best_side_down_when_down_rr_higher(self):
        monitor, ctx, _ = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        monitor._rr_threshold = 0.1
        monitor._cooldown = 0.0
        snapshot = _make_snapshot(up_ask=0.60, down_ask=0.30)
        pf_result = _make_prefilter_result(should_skip=False)
        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)
        await asyncio.sleep(0)
        assert ctx.shared.monitor_status["best_side"] == "down"


# ---------------------------------------------------------------------------
# _tick integration
# ---------------------------------------------------------------------------


class TestTickIntegration:
    @pytest.mark.asyncio
    async def test_tick_returns_early_on_none(self):
        monitor, ctx, ai = _make_monitor()
        ctx.market_data.get_snapshot.return_value = None

        await monitor._tick()

        ai.evaluate_entry.assert_not_called()
        assert ctx.shared.latest_snapshot is None

    @pytest.mark.asyncio
    async def test_tick_stores_snapshot(self):
        monitor, ctx, _ = _make_monitor()
        expected = _make_snapshot()
        ctx.market_data.get_snapshot.return_value = expected

        await monitor._tick()

        assert ctx.shared.latest_snapshot is expected
        assert ctx.shared.snapshot_timestamp > 0

    @pytest.mark.asyncio
    async def test_tick_full_pipeline_triggers_ai(self):
        monitor, ctx, ai = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        ctx.shared.candle_open_btc = 65000.0

        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40, btc_price=65100.0)
        ctx.market_data.get_snapshot.return_value = snapshot

        ctx.prefilter.check.return_value = _make_prefilter_result(should_skip=False)
        monitor._rr_threshold = 0.1
        monitor._cooldown = 0.0
        ai.busy = False

        await monitor._tick()

        ai.evaluate_entry.assert_called_once()
