"""Tests for MarketMonitor — fetch pipeline and trigger logic."""

from __future__ import annotations

import asyncio
import logging
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from polybot.indicators.core import Indicator, IndicatorResult
from polybot.indicators.helpers import compute_rr
from polybot.indicators.results import IndicatorResults
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


def _make_indicators(snapshot, candle_open_btc=65000.0):
    """Build IndicatorResults matching what the real processor would produce."""
    up_ask = snapshot.orderbook.best_ask or 1.0
    down_ask = snapshot.down_orderbook.best_ask or 1.0
    rr_up = compute_rr(up_ask)
    rr_down = compute_rr(down_ask)
    best_rr = max(rr_up, rr_down)
    best_side = "up" if rr_up >= rr_down else "down"

    btc_move = 0.0
    btc_price = snapshot.btc_price.price_usd if snapshot.btc_price else 0.0
    if candle_open_btc is not None and btc_price > 0:
        btc_move = btc_price - candle_open_btc

    return IndicatorResults(
        results=[
            IndicatorResult(
                name=Indicator.RISK_REWARD,
                value=best_rr,
                label=f"UP={rr_up:.2f}x DOWN={rr_down:.2f}x",
                extras={"rr_up": rr_up, "rr_down": rr_down, "best_side": best_side},
            ),
            IndicatorResult(
                name=Indicator.BTC_MOVE_FROM_OPEN,
                value=btc_move,
                label=f"${btc_move:+,.0f}",
            ),
            IndicatorResult(
                name=Indicator.BEST_ENTRY,
                value=min(up_ask, down_ask),
                label=f"${min(up_ask, down_ask):.3f}",
            ),
        ]
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
    def _persist(self, monitor, snapshot, pf_result):
        """Call _persist_snapshots with indicator results."""
        indicators = _make_indicators(snapshot)
        monitor._persist_snapshots(snapshot, pf_result, indicators)

    def test_queues_datastore_when_candle_id_set(self):
        monitor, ctx, _ = _make_monitor()
        datastore = MagicMock()
        datastore.current_candle_id = 42
        monitor._datastore = datastore
        monitor._feature_config = None

        self._persist(monitor, _make_snapshot(), _make_prefilter_result())
        datastore.queue_snapshot.assert_called_once()

    def test_skips_datastore_when_no_candle_id(self):
        monitor, ctx, _ = _make_monitor()
        datastore = MagicMock()
        datastore.current_candle_id = None
        monitor._datastore = datastore

        self._persist(monitor, _make_snapshot(), _make_prefilter_result())
        datastore.queue_snapshot.assert_not_called()

    def test_skips_datastore_when_none(self):
        monitor, ctx, _ = _make_monitor()
        monitor._datastore = None

        self._persist(monitor, _make_snapshot(), _make_prefilter_result())

    def test_queues_market_history_when_candle_id_set(self):
        monitor, ctx, _ = _make_monitor()
        ctx.market_history.current_candle_id = 7

        self._persist(monitor, _make_snapshot(), _make_prefilter_result())
        ctx.market_history.queue_snapshot.assert_called_once()

    def test_skips_market_history_when_no_candle_id(self):
        monitor, ctx, _ = _make_monitor()
        ctx.market_history.current_candle_id = None

        self._persist(monitor, _make_snapshot(), _make_prefilter_result())
        ctx.market_history.queue_snapshot.assert_not_called()


# ---------------------------------------------------------------------------
# _evaluate_trigger
# ---------------------------------------------------------------------------


class TestAdaptiveEntry:
    def test_static_rr_passes(self):
        monitor, ctx, _ = _make_monitor()
        monitor._rr_threshold = 0.5
        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        indicators = _make_indicators(snapshot)
        passed, reason = monitor._run_adaptive_entry(indicators)
        assert passed is True
        assert reason == ""

    def test_static_rr_blocks(self):
        monitor, ctx, _ = _make_monitor()
        monitor._rr_threshold = 5.0
        snapshot = _make_snapshot(up_ask=0.90, down_ask=0.90)
        indicators = _make_indicators(snapshot)
        passed, reason = monitor._run_adaptive_entry(indicators)
        assert passed is False
        assert "R/R" in reason

    def test_adaptive_mode_passes(self):
        monitor, ctx, _ = _make_monitor()
        monitor._adaptive_enabled = True
        adaptive = MagicMock()
        adaptive.should_trigger.return_value = (True, "")
        monitor._adaptive_entry = adaptive
        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        indicators = _make_indicators(snapshot)
        passed, _ = monitor._run_adaptive_entry(indicators)
        assert passed is True
        adaptive.should_trigger.assert_called_once()

    def test_adaptive_mode_blocks(self):
        monitor, ctx, _ = _make_monitor()
        monitor._adaptive_enabled = True
        adaptive = MagicMock()
        adaptive.should_trigger.return_value = (False, "BTC move $0 < $500 threshold")
        monitor._adaptive_entry = adaptive
        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        indicators = _make_indicators(snapshot)
        passed, reason = monitor._run_adaptive_entry(indicators)
        assert passed is False
        assert "BTC move" in reason


class TestEvaluateTrigger:
    def _run_trigger(self, monitor, ctx, pf_result=None, snapshot=None):
        if snapshot is None:
            snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        if pf_result is None:
            pf_result = _make_prefilter_result()
        indicators = _make_indicators(snapshot, candle_open_btc=ctx.shared.candle_open_btc)
        has_position = ctx.portfolio.has_open_position()
        ae_passed, ae_reason = monitor._run_adaptive_entry(indicators)
        monitor._evaluate_trigger(snapshot, pf_result, indicators, has_position, ae_passed, ae_reason)

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
    async def test_tick_prefilter_skip_still_persists(self):
        monitor, ctx, ai = _make_monitor()
        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        ctx.market_data.get_snapshot.return_value = snapshot
        ctx.prefilter.check.return_value = _make_prefilter_result(should_skip=True, reason="spread")

        # Enable datastore so we can verify persist was called
        datastore = MagicMock()
        datastore.current_candle_id = 1
        monitor._datastore = datastore

        await monitor._tick()

        ai.evaluate_entry.assert_not_called()
        datastore.queue_snapshot.assert_called_once()
        assert "PREFILTER" in ctx.shared.monitor_status["gate_status"]

    @pytest.mark.asyncio
    async def test_tick_full_pipeline_triggers_ai(self):
        monitor, ctx, ai = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        ctx.shared.candle_open_btc = 65000.0

        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40, btc_price=65100.0)
        ctx.market_data.get_snapshot.return_value = snapshot

        # Provide a processor that returns real indicators
        indicators = _make_indicators(snapshot, candle_open_btc=65000.0)
        processor = MagicMock()
        processor.compute.return_value = indicators
        monitor._processor = processor

        ctx.prefilter.check.return_value = _make_prefilter_result(should_skip=False)
        monitor._rr_threshold = 0.1
        monitor._cooldown = 0.0
        ai.busy = False

        await monitor._tick()

        ai.evaluate_entry.assert_called_once()
