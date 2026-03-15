"""Tests for MarketMonitor — parallel-fetch pipeline, rotation detection, outage tracking."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from polybot.models.core import (
    BetData,
    BtcData,
    BtcPrice,
    CandleMarket,
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


def _make_candle_market(condition_id="cond_test", remaining=120.0, slug="btc-5min-123"):
    return CandleMarket(
        condition_id=condition_id,
        up_token_id="up_tok_1",
        down_token_id="down_tok_1",
        slug=slug,
        title="BTC 5min",
        start_time=time.time() - 180,
        end_time=time.time() + remaining,
    )


def _make_bet_data(condition_id="cond_test", remaining=120.0, up_bid=0.48, up_ask=0.52, down_bid=0.46, down_ask=0.50):
    market = _make_candle_market(condition_id=condition_id, remaining=remaining)
    return BetData(
        market=market,
        orderbook=_make_orderbook(up_bid, up_ask),
        down_orderbook=_make_orderbook(down_bid, down_ask),
        last_trade_price=0.50,
    )


def _make_btc_data(btc_price=65000.0):
    return BtcData(
        price=BtcPrice(price_usd=btc_price) if btc_price else None,
        candles=[],
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

    # Outage tracking on ctx
    ctx.discovery_failures = 0
    ctx.outage_start = None
    ctx.outage_recovered = None
    ctx.last_outage_duration = None
    ctx.current_market = None

    # Portfolio
    portfolio = MagicMock()
    portfolio.up_position.shares = 0.0
    portfolio.down_position.shares = 0.0
    ctx.portfolio = portfolio

    # Prefilter
    ctx.prefilter = MagicMock()
    ctx.prefilter.check.return_value = _make_prefilter_result()

    # Market data — polymarket + btc repos
    polymarket = AsyncMock()
    polymarket.fetch = AsyncMock(return_value=_make_bet_data())
    btc_repo = AsyncMock()
    btc_repo.fetch = AsyncMock(return_value=_make_btc_data())

    ctx.market_data = MagicMock()
    ctx.market_data.polymarket = polymarket
    ctx.market_data.btc_repo = btc_repo
    ctx.market_data.build_snapshot = MagicMock(return_value=_make_snapshot())

    # Resolution tracker
    ctx.resolution_tracker = MagicMock()

    # Orderbook (for outage cancel_all)
    ctx.orderbook = MagicMock()
    ctx.orderbook.cancel_all.return_value = 0

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

    # Rotation manager
    rotation = AsyncMock()
    rotation.handle_transition = AsyncMock()
    rotation.setup_new_market = AsyncMock()

    monitor = MarketMonitor(ctx, ai_decision, rotation)
    return monitor, ctx, ai_decision, rotation


# ---------------------------------------------------------------------------
# Rotation detection
# ---------------------------------------------------------------------------


class TestRotated:
    """Tests for MarketMonitor._rotated()."""

    def test_no_current_market_not_rotated(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.current_market = None
        bet_data = _make_bet_data(condition_id="cond_new")
        assert monitor._rotated(bet_data) is False

    def test_same_condition_not_rotated(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.current_market = _make_candle_market(condition_id="cond_1")
        bet_data = _make_bet_data(condition_id="cond_1")
        assert monitor._rotated(bet_data) is False

    def test_different_condition_rotated(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.current_market = _make_candle_market(condition_id="cond_1")
        bet_data = _make_bet_data(condition_id="cond_2")
        assert monitor._rotated(bet_data) is True


# ---------------------------------------------------------------------------
# Outage tracking
# ---------------------------------------------------------------------------


class TestOutageTracking:
    """Tests for discovery failure/success handling."""

    def test_first_failure_increments_counter(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.discovery_failures = 0
        monitor._handle_discovery_failure()
        assert ctx.discovery_failures == 1
        assert ctx.outage_start is None

    def test_third_failure_starts_outage(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.discovery_failures = 2
        monitor._handle_discovery_failure()
        assert ctx.discovery_failures == 3
        assert ctx.outage_start is not None

    def test_ongoing_outage_logs_periodically(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.discovery_failures = 11
        ctx.outage_start = time.time() - 60
        monitor._handle_discovery_failure()
        assert ctx.discovery_failures == 12  # 12 % 12 == 0 → would log

    def test_success_clears_outage(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.outage_start = time.time() - 30
        ctx.discovery_failures = 5
        monitor._handle_discovery_success()
        assert ctx.discovery_failures == 0
        assert ctx.outage_start is None
        assert ctx.outage_recovered is not None

    def test_success_no_outage_is_noop(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.outage_start = None
        ctx.discovery_failures = 0
        monitor._handle_discovery_success()
        assert ctx.discovery_failures == 0
        assert ctx.outage_recovered is None

    def test_recovery_banner_cleared_after_60s(self):
        monitor, ctx, _, _ = _make_monitor()
        ctx.outage_start = None
        ctx.outage_recovered = time.time() - 120  # 120s ago
        monitor._handle_discovery_success()
        assert ctx.outage_recovered is None


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
        monitor._evaluate_trigger(snapshot, pf_snapshot, pf_result)

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
    """Tests that _tick() orchestrates the parallel-fetch pipeline correctly."""

    @pytest.mark.asyncio
    async def test_tick_discovery_failure_returns_early(self):
        monitor, ctx, ai_decision, rotation = _make_monitor()
        ctx.market_data.polymarket.fetch.return_value = None

        await monitor._tick()

        assert ctx.discovery_failures == 1
        rotation.setup_new_market.assert_not_awaited()
        ai_decision.evaluate_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_tick_first_market_setup(self):
        """First tick — no current market, bet_data found → setup_new_market called."""
        monitor, ctx, ai_decision, rotation = _make_monitor()
        ctx.current_market = None

        bet_data = _make_bet_data()
        ctx.market_data.polymarket.fetch.return_value = bet_data

        await monitor._tick()

        rotation.handle_transition.assert_not_awaited()  # no rotation
        rotation.setup_new_market.assert_awaited_once_with(bet_data.market)
        assert ctx.shared.latest_snapshot is not None

    @pytest.mark.asyncio
    async def test_tick_same_market_no_rotation(self):
        """Same condition_id → no rotation, no setup_new_market."""
        monitor, ctx, ai_decision, rotation = _make_monitor()
        ctx.current_market = _make_candle_market(condition_id="cond_test")

        bet_data = _make_bet_data(condition_id="cond_test")
        ctx.market_data.polymarket.fetch.return_value = bet_data

        await monitor._tick()

        rotation.handle_transition.assert_not_awaited()
        rotation.setup_new_market.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_tick_rotation_triggers_transition_and_setup(self):
        """Different condition_id → handle_transition + setup_new_market."""
        monitor, ctx, ai_decision, rotation = _make_monitor()
        ctx.current_market = _make_candle_market(condition_id="cond_old")

        bet_data = _make_bet_data(condition_id="cond_new")
        ctx.market_data.polymarket.fetch.return_value = bet_data

        await monitor._tick()

        rotation.handle_transition.assert_awaited_once()
        rotation.setup_new_market.assert_awaited_once_with(bet_data.market)

    @pytest.mark.asyncio
    async def test_tick_post_outage_skips_transition(self):
        """Rotation during outage recovery → skip transition, cancel stale orders."""
        monitor, ctx, ai_decision, rotation = _make_monitor()
        ctx.current_market = _make_candle_market(condition_id="cond_old")
        ctx.outage_start = time.time() - 30  # in outage
        ctx.discovery_failures = 5

        bet_data = _make_bet_data(condition_id="cond_new")
        ctx.market_data.polymarket.fetch.return_value = bet_data

        await monitor._tick()

        rotation.handle_transition.assert_not_awaited()  # skipped
        rotation.setup_new_market.assert_awaited_once_with(bet_data.market)
        ctx.orderbook.cancel_all.assert_called_once()
        # Outage should be cleared
        assert ctx.discovery_failures == 0
        assert ctx.outage_start is None

    @pytest.mark.asyncio
    async def test_tick_full_pipeline(self):
        """Full tick — same market, all gates pass, AI triggered."""
        monitor, ctx, ai_decision, rotation = _make_monitor()
        ctx.current_market = _make_candle_market(condition_id="cond_test")
        ctx.shared.ai_last_call_time = 0.0
        ctx.shared.candle_open_btc = 65000.0

        # Good R/R snapshot
        snapshot = _make_snapshot(up_ask=0.30, down_ask=0.40, btc_price=65100.0)
        ctx.market_data.build_snapshot.return_value = snapshot

        bet_data = _make_bet_data(condition_id="cond_test")
        ctx.market_data.polymarket.fetch.return_value = bet_data

        ctx.prefilter.check.return_value = _make_prefilter_result(should_skip=False)
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
    async def test_tick_builds_snapshot_from_repos(self):
        """Verify build_snapshot is called with the fetched bet_data and btc_data."""
        monitor, ctx, _, _ = _make_monitor()
        ctx.current_market = _make_candle_market(condition_id="cond_test")

        bet_data = _make_bet_data(condition_id="cond_test")
        btc_data = _make_btc_data(65500.0)
        ctx.market_data.polymarket.fetch.return_value = bet_data
        ctx.market_data.btc_repo.fetch.return_value = btc_data

        await monitor._tick()

        ctx.market_data.build_snapshot.assert_called_once_with(bet_data, btc_data)
