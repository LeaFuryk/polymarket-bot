"""Tests for MarketMonitor extracted methods."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from polybot.models.core import (
    BtcPrice,
    MarketSnapshot,
    OrderbookLevel,
    OrderbookSnapshot,
)
from polybot.shared_state import PreFilterSnapshot
from polybot.tasks.market_monitor import MarketMonitor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orderbook(best_bid: float, best_ask: float, depth: float = 100.0):
    """Build an OrderbookSnapshot with one bid/ask level."""
    return OrderbookSnapshot(
        bids=[OrderbookLevel(price=best_bid, size=depth / best_bid)],
        asks=[OrderbookLevel(price=best_ask, size=depth / best_ask)],
    )


def _make_snapshot(
    up_bid=0.48,
    up_ask=0.52,
    down_bid=0.46,
    down_ask=0.50,
    btc_price=65000.0,
):
    """Build a MarketSnapshot with sane defaults."""
    return MarketSnapshot(
        condition_id="cond_test",
        orderbook=_make_orderbook(up_bid, up_ask),
        down_orderbook=_make_orderbook(down_bid, down_ask),
        btc_price=BtcPrice(price_usd=btc_price),
    )


def _make_prefilter_result(should_skip=False, reason="", streak=0, direction=""):
    """Build a mock PreFilterResult."""
    result = MagicMock()
    result.should_skip = should_skip
    result.reason = reason
    result.consecutive_streak = streak
    result.streak_direction = direction
    result.btc_range_30m = 0.0
    result.best_entry_price = 1.0
    return result


def _make_monitor():
    """Build a MarketMonitor with fully mocked AgentContext."""
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
    shared.prefilter_history = deque(maxlen=300)
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

    # Market data
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

    # Broadcaster
    ctx.broadcaster = MagicMock()
    ctx.broadcaster.has_clients = False

    # AI Decision
    ai_decision = MagicMock()
    ai_decision.busy = False
    ai_decision.evaluate_entry = AsyncMock()

    # Rotation manager
    rotation = AsyncMock()
    rotation.discover_market = AsyncMock()

    monitor = MarketMonitor(ctx, ai_decision, rotation)
    return monitor, ctx, ai_decision, rotation


# ---------------------------------------------------------------------------
# _ensure_market
# ---------------------------------------------------------------------------


class TestEnsureMarket:
    """Tests for MarketMonitor._ensure_market()."""

    @pytest.mark.asyncio
    async def test_no_market_discovers_and_returns_false(self):
        monitor, ctx, _, rotation = _make_monitor()
        ctx.shared.current_market = None

        result = await monitor._ensure_market()

        assert result is False
        rotation.discover_market.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_expired_market_discovers_and_returns_false(self):
        monitor, ctx, _, rotation = _make_monitor()
        market = MagicMock()
        market.time_remaining.return_value = 0.0
        ctx.shared.current_market = market

        result = await monitor._ensure_market()

        assert result is False
        rotation.discover_market.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_valid_market_returns_true(self):
        monitor, ctx, _, rotation = _make_monitor()
        market = MagicMock()
        market.time_remaining.return_value = 120.0
        ctx.shared.current_market = market
        monitor._discovery_counter = 0

        result = await monitor._ensure_market()

        assert result is True
        # Counter incremented to 1, no discover yet
        assert monitor._discovery_counter == 1
        rotation.discover_market.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_periodic_discovery_at_5_ticks(self):
        monitor, ctx, _, rotation = _make_monitor()
        market = MagicMock()
        market.time_remaining.return_value = 120.0
        ctx.shared.current_market = market
        monitor._discovery_counter = 4  # next tick hits 5

        result = await monitor._ensure_market()

        assert result is True
        assert monitor._discovery_counter == 0  # reset
        rotation.discover_market.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_counter_below_5_no_discover(self):
        monitor, ctx, _, rotation = _make_monitor()
        market = MagicMock()
        market.time_remaining.return_value = 120.0
        ctx.shared.current_market = market
        monitor._discovery_counter = 2

        await monitor._ensure_market()

        assert monitor._discovery_counter == 3
        rotation.discover_market.assert_not_awaited()


# ---------------------------------------------------------------------------
# _fetch_snapshot
# ---------------------------------------------------------------------------


class TestFetchSnapshot:
    """Tests for MarketMonitor._fetch_snapshot()."""

    @pytest.mark.asyncio
    async def test_success_stores_and_returns(self):
        monitor, ctx, _, _ = _make_monitor()
        expected = _make_snapshot()
        ctx.market_data.get_snapshot.return_value = expected

        result = await monitor._fetch_snapshot()

        assert result is expected
        assert ctx.shared.latest_snapshot is expected
        assert ctx.shared.snapshot_timestamp > 0

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.market_data.get_snapshot.side_effect = RuntimeError("API down")

        result = await monitor._fetch_snapshot()

        assert result is None


# ---------------------------------------------------------------------------
# _run_prefilter
# ---------------------------------------------------------------------------


class TestRunPrefilter:
    """Tests for MarketMonitor._run_prefilter()."""

    def test_returns_correct_rr_values(self):
        monitor, ctx, _, _ = _make_monitor()
        snapshot = _make_snapshot(up_ask=0.50, down_ask=0.40)
        ctx.prefilter.check.return_value = _make_prefilter_result()

        pf_snapshot, pf_result = monitor._run_prefilter(snapshot, 120.0)

        # R/R = (1 - ask) / ask
        assert pf_snapshot.rr_up == pytest.approx(1.0)  # (1 - 0.5) / 0.5
        assert pf_snapshot.rr_down == pytest.approx(1.5)  # (1 - 0.4) / 0.4

    def test_btc_move_computed(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.shared.candle_open_btc = 65000.0
        snapshot = _make_snapshot(btc_price=65100.0)
        ctx.prefilter.check.return_value = _make_prefilter_result()

        pf_snapshot, _ = monitor._run_prefilter(snapshot, 120.0)

        assert pf_snapshot.btc_move_from_open == pytest.approx(100.0)

    def test_btc_move_zero_when_no_candle_open(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.shared.candle_open_btc = None
        snapshot = _make_snapshot(btc_price=65100.0)
        ctx.prefilter.check.return_value = _make_prefilter_result()

        pf_snapshot, _ = monitor._run_prefilter(snapshot, 120.0)

        assert pf_snapshot.btc_move_from_open == 0.0

    def test_prefilter_checks_populated(self):
        monitor, ctx, _, _ = _make_monitor()
        snapshot = _make_snapshot()
        ctx.prefilter.check.return_value = _make_prefilter_result(should_skip=True, reason="spread too wide")

        pf_snapshot, _ = monitor._run_prefilter(snapshot, 120.0)

        assert pf_snapshot.checks["prefilter_passed"] is False
        assert pf_snapshot.checks["spread_ok"] is False  # "spread" in reason
        assert pf_snapshot.checks["time_ok"] is True  # 120 >= 45
        assert pf_snapshot.reasons == ["spread too wide"]

    def test_all_checks_pass(self):
        monitor, ctx, _, _ = _make_monitor()
        snapshot = _make_snapshot()
        ctx.prefilter.check.return_value = _make_prefilter_result(should_skip=False)

        pf_snapshot, _ = monitor._run_prefilter(snapshot, 120.0)

        assert pf_snapshot.checks["prefilter_passed"] is True
        assert pf_snapshot.checks["spread_ok"] is True
        assert pf_snapshot.checks["depth_ok"] is True
        assert pf_snapshot.checks["choppy_ok"] is True
        assert pf_snapshot.checks["setup_ok"] is True

    def test_appends_to_prefilter_history(self):
        monitor, ctx, _, _ = _make_monitor()
        snapshot = _make_snapshot()
        ctx.prefilter.check.return_value = _make_prefilter_result()
        assert len(ctx.shared.prefilter_history) == 0

        monitor._run_prefilter(snapshot, 120.0)

        assert len(ctx.shared.prefilter_history) == 1

    def test_streak_propagated(self):
        monitor, ctx, _, _ = _make_monitor()
        snapshot = _make_snapshot()
        ctx.prefilter.check.return_value = _make_prefilter_result(streak=5, direction="up")

        pf_snapshot, _ = monitor._run_prefilter(snapshot, 120.0)

        assert pf_snapshot.streak == 5
        assert pf_snapshot.streak_direction == "up"

    def test_time_ok_false_below_45(self):
        monitor, ctx, _, _ = _make_monitor()
        snapshot = _make_snapshot()
        ctx.prefilter.check.return_value = _make_prefilter_result()

        pf_snapshot, _ = monitor._run_prefilter(snapshot, 30.0)

        assert pf_snapshot.checks["time_ok"] is False


# ---------------------------------------------------------------------------
# _persist_snapshots
# ---------------------------------------------------------------------------


class TestPersistSnapshots:
    """Tests for MarketMonitor._persist_snapshots()."""

    def test_queues_datastore_when_candle_id_set(self):
        monitor, ctx, _, _ = _make_monitor()
        datastore = MagicMock()
        datastore.current_candle_id = 42
        monitor._datastore = datastore
        monitor._feature_config = None

        snapshot = _make_snapshot()
        pf_snapshot = PreFilterSnapshot(
            timestamp=time.time(),
            time_remaining=120.0,
            rr_up=1.0,
            rr_down=1.5,
            btc_move_from_open=100.0,
        )
        pf_result = _make_prefilter_result()

        monitor._persist_snapshots(snapshot, pf_snapshot, pf_result)

        datastore.queue_snapshot.assert_called_once()

    def test_skips_datastore_when_no_candle_id(self):
        monitor, ctx, _, _ = _make_monitor()
        datastore = MagicMock()
        datastore.current_candle_id = None
        monitor._datastore = datastore

        snapshot = _make_snapshot()
        pf_snapshot = PreFilterSnapshot(timestamp=time.time(), time_remaining=120.0)
        pf_result = _make_prefilter_result()

        monitor._persist_snapshots(snapshot, pf_snapshot, pf_result)

        datastore.queue_snapshot.assert_not_called()

    def test_skips_datastore_when_none(self):
        monitor, ctx, _, _ = _make_monitor()
        monitor._datastore = None

        snapshot = _make_snapshot()
        pf_snapshot = PreFilterSnapshot(timestamp=time.time(), time_remaining=120.0)
        pf_result = _make_prefilter_result()

        # Should not raise
        monitor._persist_snapshots(snapshot, pf_snapshot, pf_result)

    def test_queues_market_history_when_candle_id_set(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.market_history.current_candle_id = 7

        snapshot = _make_snapshot()
        pf_snapshot = PreFilterSnapshot(
            timestamp=time.time(),
            time_remaining=120.0,
            rr_up=1.0,
            rr_down=1.5,
            btc_move_from_open=100.0,
        )
        pf_result = _make_prefilter_result()

        monitor._persist_snapshots(snapshot, pf_snapshot, pf_result)

        ctx.market_history.queue_snapshot.assert_called_once()

    def test_skips_market_history_when_no_candle_id(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.market_history.current_candle_id = None

        snapshot = _make_snapshot()
        pf_snapshot = PreFilterSnapshot(timestamp=time.time(), time_remaining=120.0)
        pf_result = _make_prefilter_result()

        monitor._persist_snapshots(snapshot, pf_snapshot, pf_result)

        ctx.market_history.queue_snapshot.assert_not_called()


# ---------------------------------------------------------------------------
# _evaluate_trigger
# ---------------------------------------------------------------------------


class TestEvaluateTrigger:
    """Tests for MarketMonitor._evaluate_trigger()."""

    @staticmethod
    def _build_pf_snapshot(snapshot):
        """Build a PreFilterSnapshot from a MarketSnapshot."""
        return PreFilterSnapshot(
            timestamp=time.time(),
            time_remaining=120.0,
            best_entry_up=snapshot.orderbook.best_ask or 1.0,
            best_entry_down=snapshot.down_orderbook.best_ask or 1.0,
            rr_up=(1.0 - (snapshot.orderbook.best_ask or 1.0)) / (snapshot.orderbook.best_ask or 1.0),
            rr_down=(1.0 - (snapshot.down_orderbook.best_ask or 1.0)) / (snapshot.down_orderbook.best_ask or 1.0),
            btc_price=65000.0,
            btc_move_from_open=100.0,
        )

    def _run_trigger(self, monitor, ctx, pf_result=None, snapshot=None, pf_snapshot=None):
        """Helper: build defaults and call _evaluate_trigger (no AI trigger expected)."""
        if snapshot is None:
            snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        if pf_result is None:
            pf_result = _make_prefilter_result()
        if pf_snapshot is None:
            pf_snapshot = self._build_pf_snapshot(snapshot)
        monitor._evaluate_trigger(snapshot, pf_snapshot, pf_result, 120.0)

    def test_prefilter_fail_no_trigger(self):
        monitor, ctx, ai_decision, _ = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0  # no cooldown
        pf_result = _make_prefilter_result(should_skip=True, reason="spread too wide")

        self._run_trigger(monitor, ctx, pf_result=pf_result)

        ai_decision.evaluate_entry.assert_not_called()
        assert "PREFILTER" in ctx.shared.monitor_status["gate_status"]

    def test_rr_below_threshold_no_trigger(self):
        monitor, ctx, ai_decision, _ = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        monitor._rr_threshold = 5.0  # very high threshold

        # up_ask=0.90 → R/R = 0.11, well below 5.0
        snapshot = _make_snapshot(up_ask=0.90, down_ask=0.90)
        pf_result = _make_prefilter_result(should_skip=False)

        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)

        ai_decision.evaluate_entry.assert_not_called()
        assert "ADAPTIVE" in ctx.shared.monitor_status["gate_status"]

    def test_cooldown_active_no_trigger(self):
        monitor, ctx, ai_decision, _ = _make_monitor()
        ctx.shared.ai_last_call_time = time.time()  # just called
        monitor._rr_threshold = 0.1  # low threshold

        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        pf_result = _make_prefilter_result(should_skip=False)

        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)

        ai_decision.evaluate_entry.assert_not_called()
        assert "COOLDOWN" in ctx.shared.monitor_status["gate_status"]

    def test_ai_busy_no_trigger(self):
        monitor, ctx, ai_decision, _ = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        ai_decision.busy = True
        monitor._rr_threshold = 0.1

        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        pf_result = _make_prefilter_result(should_skip=False)

        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)

        ai_decision.evaluate_entry.assert_not_called()
        assert "AI BUSY" in ctx.shared.monitor_status["gate_status"]

    @pytest.mark.asyncio
    async def test_all_gates_pass_triggers_ai(self):
        monitor, ctx, ai_decision, _ = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        ai_decision.busy = False
        monitor._rr_threshold = 0.1
        monitor._cooldown = 0.0  # no cooldown

        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40)
        pf_result = _make_prefilter_result(should_skip=False)

        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)
        await asyncio.sleep(0)  # let create_task fire

        ai_decision.evaluate_entry.assert_called_once()
        assert ctx.shared.monitor_status["ai_triggered"] is True

    @pytest.mark.asyncio
    async def test_adaptive_mode_triggers(self):
        monitor, ctx, ai_decision, _ = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        ai_decision.busy = False
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
        await asyncio.sleep(0)  # let create_task fire

        adaptive.should_trigger.assert_called_once()
        ai_decision.evaluate_entry.assert_called_once()

    def test_adaptive_mode_blocks(self):
        monitor, ctx, ai_decision, _ = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        ai_decision.busy = False
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

        ai_decision.evaluate_entry.assert_not_called()
        assert "ADAPTIVE" in ctx.shared.monitor_status["gate_status"]

    @pytest.mark.asyncio
    async def test_monitor_status_populated(self):
        monitor, ctx, ai_decision, _ = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        ctx.shared.candle_open_btc = 65000.0
        monitor._rr_threshold = 0.1
        monitor._cooldown = 0.0

        snapshot = _make_snapshot(up_ask=0.50, down_ask=0.50)
        pf_result = _make_prefilter_result(should_skip=False)

        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)
        await asyncio.sleep(0)  # let create_task fire

        status = ctx.shared.monitor_status
        assert "timestamp" in status
        assert "time_remaining" in status
        assert "rr_up" in status
        assert "rr_down" in status
        assert "best_side" in status
        assert "prefilter_passed" in status
        assert "adaptive_passed" in status
        assert "cooldown_active" in status
        assert "gate_status" in status

    @pytest.mark.asyncio
    async def test_best_side_down_when_down_rr_higher(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.shared.ai_last_call_time = 0.0
        monitor._rr_threshold = 0.1
        monitor._cooldown = 0.0

        # down_ask=0.30 → rr_down=2.33, up_ask=0.60 → rr_up=0.67
        snapshot = _make_snapshot(up_ask=0.60, down_ask=0.30)
        pf_result = _make_prefilter_result(should_skip=False)

        self._run_trigger(monitor, ctx, pf_result=pf_result, snapshot=snapshot)
        await asyncio.sleep(0)  # let create_task fire

        assert ctx.shared.monitor_status["best_side"] == "down"


# ---------------------------------------------------------------------------
# _tick integration
# ---------------------------------------------------------------------------


class TestTickIntegration:
    """Tests that _tick() orchestrates the extracted methods correctly."""

    @pytest.mark.asyncio
    async def test_tick_no_market(self):
        monitor, ctx, ai_decision, rotation = _make_monitor()
        ctx.shared.current_market = None

        await monitor._tick()

        rotation.discover_market.assert_awaited_once()
        ai_decision.evaluate_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_full_pass(self):
        monitor, ctx, ai_decision, rotation = _make_monitor()

        # Set up valid market
        market = MagicMock()
        market.time_remaining.return_value = 120.0
        ctx.shared.current_market = market
        ctx.shared.ai_last_call_time = 0.0
        ctx.shared.candle_open_btc = 65000.0

        # Snapshot with good R/R
        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40, btc_price=65100.0)
        ctx.market_data.get_snapshot.return_value = snapshot

        # Prefilter passes
        ctx.prefilter.check.return_value = _make_prefilter_result(should_skip=False)

        # Low threshold so trigger fires
        monitor._rr_threshold = 0.1
        monitor._cooldown = 0.0
        ai_decision.busy = False

        await monitor._tick()

        # Snapshot stored
        assert ctx.shared.latest_snapshot is snapshot
        # Prefilter history updated
        assert len(ctx.shared.prefilter_history) == 1
        # AI triggered
        ai_decision.evaluate_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_tick_fetch_failure(self):
        monitor, ctx, ai_decision, _ = _make_monitor()

        market = MagicMock()
        market.time_remaining.return_value = 120.0
        ctx.shared.current_market = market

        ctx.market_data.get_snapshot.side_effect = RuntimeError("network")

        await monitor._tick()

        # Should return early — no prefilter history, no AI trigger
        assert len(ctx.shared.prefilter_history) == 0
        ai_decision.evaluate_entry.assert_not_called()
