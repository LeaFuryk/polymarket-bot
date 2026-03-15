"""Market monitor task — fetches data every 1s, runs prefilter, triggers AI.

Runs as an asyncio.Task. Records PreFilterSnapshots and sets the AI trigger
event when conditions are favorable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.agent.context import AgentContext
    from polybot.agent.rotation import RotationManager
    from polybot.indicators.results import IndicatorResults
    from polybot.tasks.ai_decision import AIDecision

from polybot.dashboard import DashboardMessageBuilder
from polybot.indicators import SessionContext
from polybot.indicators.helpers import compute_rr
from polybot.shared_state import PreFilterSnapshot

logger = logging.getLogger(__name__)


class MarketMonitor:
    """Fetches market data every second, runs prefilter, triggers AI."""

    def __init__(
        self,
        ctx: AgentContext,
        ai_decision: AIDecision,
        rotation_manager: RotationManager,
    ) -> None:
        self._config = ctx.config
        self._shared = ctx.shared
        self._market_data = ctx.market_data
        self._prefilter = ctx.prefilter
        self._portfolio = ctx.portfolio
        self._resolution_tracker = ctx.resolution_tracker
        self._ai_decision = ai_decision
        self._rotation = rotation_manager
        self._datastore = ctx.datastore
        self._feature_config = ctx.feature_config if ctx.datastore else None
        self._processor = ctx.processor
        self._market_history = ctx.market_history
        self._adaptive_entry = ctx.adaptive_entry
        self._ctx = ctx
        self._interval = ctx.config.monitor.market_monitor_interval
        self._rr_threshold = ctx.config.monitor.rr_trigger_threshold
        self._cooldown = ctx.config.monitor.ai_cooldown_seconds
        self._adaptive_enabled = ctx.config.monitor.adaptive_entry_enabled
        self._discovery_counter = 0

    async def run(self) -> None:
        """Main loop — runs until shutdown."""
        logger.info("MarketMonitor started (interval=%.1fs)", self._interval)
        while not self._shared.shutdown:
            if self._shared.rotation_in_progress:
                await asyncio.sleep(0.2)
                continue

            try:
                await self._tick()
            except Exception:
                logger.exception("MarketMonitor tick error")

            await asyncio.sleep(self._interval)

        logger.info("MarketMonitor stopped")

    async def _tick(self) -> None:
        """Single monitoring cycle.

        Pipeline: ensure market → fetch snapshot → compute indicators
        → prefilter → if passed: evaluate AI trigger.
        """
        if not await self._ensure_market():
            return

        snapshot = await self._fetch_snapshot()
        if snapshot is None:
            return

        time_remaining = self._shared.current_market.time_remaining()

        # Compute indicators once for the whole tick
        indicators = self._compute_indicators(snapshot, time_remaining)
        self._shared.latest_indicator_results = indicators

        # Run prefilter gate
        has_position = self._portfolio.up_position.shares > 0 or self._portfolio.down_position.shares > 0
        pf_result = self._prefilter.check(time_remaining, snapshot, has_position)

        # Record tick (always — analytics + dashboard history)
        pf_snapshot = self._record_tick(snapshot, pf_result, time_remaining)
        self._persist_snapshots(snapshot, pf_snapshot, pf_result, indicators)

        # Evaluate AI trigger (always updates dashboard; only fires AI if all gates pass)
        self._evaluate_trigger(snapshot, pf_snapshot, pf_result, time_remaining)

        # Broadcast fresh data to WS clients
        await self._broadcast_updates()

    async def _ensure_market(self) -> bool:
        """Discovery/rotation guard. Returns True if ready to monitor."""
        market = self._shared.current_market
        if market is None:
            await self._rotation.discover_market()
            return False

        if market.time_remaining() <= 0:
            await self._rotation.discover_market()
            return False

        self._discovery_counter += 1
        if self._discovery_counter >= 5:
            self._discovery_counter = 0
            await self._rotation.discover_market()

        return True

    async def _fetch_snapshot(self):
        """Fetch from provider, store on shared state. Returns None on failure."""
        try:
            snapshot = await self._market_data.get_snapshot()
        except Exception:
            logger.debug("MarketMonitor: data fetch failed", exc_info=True)
            return None

        self._shared.latest_snapshot = snapshot
        self._shared.snapshot_timestamp = time.time()
        return snapshot

    def _compute_indicators(self, snapshot, time_remaining: float) -> IndicatorResults | None:
        """Compute all indicators once using the processor."""
        if self._processor is None:
            return None
        try:
            has_position = self._portfolio.up_position.shares > 0 or self._portfolio.down_position.shares > 0
            session = SessionContext(
                wins=self._shared.session_wins,
                losses=self._shared.session_losses,
                candle_open_btc=self._shared.candle_open_btc,
            )
            return self._processor.compute(
                snapshot,
                session,
                candle_open_btc=self._shared.candle_open_btc,
                has_open_position=has_position,
                time_remaining=time_remaining,
            )
        except Exception:
            logger.debug("Indicator computation failed", exc_info=True)
            return None

    def _record_tick(self, snapshot, pf_result, time_remaining: float) -> PreFilterSnapshot:
        """Build a PreFilterSnapshot from the current tick and append to history."""
        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook

        rr_up = compute_rr(up_ob.best_ask or 1.0)
        rr_down = compute_rr(down_ob.best_ask or 1.0)

        btc_move = 0.0
        btc_price_val = snapshot.btc_price.price_usd if snapshot.btc_price else 0.0
        candle_open = self._shared.candle_open_btc
        if candle_open is not None and btc_price_val > 0:
            btc_move = btc_price_val - candle_open

        pf_snapshot = PreFilterSnapshot(
            timestamp=time.time(),
            time_remaining=time_remaining,
            checks={
                "time_ok": time_remaining >= 45,
                "spread_ok": not pf_result.should_skip or "spread" not in pf_result.reason.lower(),
                "depth_ok": not pf_result.should_skip or "thin" not in pf_result.reason.lower(),
                "choppy_ok": not pf_result.should_skip or "choppy" not in pf_result.reason.lower(),
                "setup_ok": not pf_result.should_skip or "setup" not in pf_result.reason.lower(),
                "prefilter_passed": not pf_result.should_skip,
            },
            reasons=[pf_result.reason] if pf_result.reason else [],
            best_entry_up=up_ob.best_ask or 1.0,
            best_entry_down=down_ob.best_ask or 1.0,
            rr_up=rr_up,
            rr_down=rr_down,
            btc_price=btc_price_val,
            up_mid=up_ob.midpoint,
            down_mid=down_ob.midpoint,
            up_spread_pct=up_ob.spread_pct,
            down_spread_pct=down_ob.spread_pct,
            streak=pf_result.consecutive_streak,
            streak_direction=pf_result.streak_direction,
            btc_move_from_open=btc_move,
        )
        self._shared.prefilter_history.append(pf_snapshot)
        return pf_snapshot

    def _persist_snapshots(
        self,
        snapshot,
        pf_snapshot: PreFilterSnapshot,
        pf_result,
        indicator_results: IndicatorResults | None = None,
    ) -> None:
        """Queue snapshots for SQLite analytics and persistent market history."""
        rr_up = pf_snapshot.rr_up
        rr_down = pf_snapshot.rr_down
        btc_move = pf_snapshot.btc_move_from_open

        if self._datastore is not None and self._datastore.current_candle_id is not None:
            self._queue_snapshot(
                snapshot,
                pf_snapshot,
                pf_result,
                rr_up,
                rr_down,
                btc_move,
                indicator_results,
            )

        if self._market_history.current_candle_id is not None:
            self._queue_market_history_snapshot(
                snapshot,
                pf_snapshot,
                rr_up,
                rr_down,
                btc_move,
            )

    def _evaluate_trigger(self, snapshot, pf_snapshot: PreFilterSnapshot, pf_result, time_remaining: float) -> None:
        """Gate pipeline: adaptive/static R/R, cooldown, AI busy. Fires evaluate_entry task."""
        up_ask = pf_snapshot.best_entry_up
        down_ask = pf_snapshot.best_entry_down
        rr_up = pf_snapshot.rr_up
        rr_down = pf_snapshot.rr_down
        btc_move = pf_snapshot.btc_move_from_open
        btc_price_val = pf_snapshot.btc_price
        candle_open = self._shared.candle_open_btc

        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook

        best_rr = max(rr_up, rr_down)
        prefilter_passed = not pf_result.should_skip
        min_ask = min(up_ask, down_ask)
        best_side = "up" if rr_up >= rr_down else "down"
        has_position = self._portfolio.up_position.shares > 0 or self._portfolio.down_position.shares > 0

        # Adaptive trigger: uses rolling reversal rate to set BTC threshold + max entry
        adaptive_passed = False
        adaptive_reason = ""
        if self._adaptive_enabled and self._adaptive_entry is not None:
            adaptive_passed = self._adaptive_entry.should_trigger(
                abs_btc_move=abs(btc_move),
                min_ask=min_ask,
            )
            if not adaptive_passed:
                btc_thresh = self._adaptive_entry.btc_threshold
                max_entry = self._adaptive_entry.max_entry_price
                parts = []
                if abs(btc_move) < btc_thresh:
                    parts.append(f"BTC move ${abs(btc_move):.0f} < ${btc_thresh:.0f} threshold")
                if min_ask > max_entry:
                    parts.append(f"min ask ${min_ask:.2f} > ${max_entry:.2f} max entry")
                adaptive_reason = "; ".join(parts) if parts else "adaptive gate blocked"
            should_trigger = prefilter_passed and adaptive_passed
        else:
            # Fallback: static R/R threshold
            adaptive_passed = best_rr >= self._rr_threshold
            if not adaptive_passed:
                adaptive_reason = f"R/R {best_rr:.2f} < {self._rr_threshold:.2f} threshold"
            should_trigger = prefilter_passed and adaptive_passed

        # Check cooldown
        now = time.time()
        elapsed = now - self._shared.ai_last_call_time
        cooldown_active = elapsed < self._cooldown
        cooldown_remaining = max(0, self._cooldown - elapsed)

        # Build gate status for dashboard (every tick)
        gate_status = "TRIGGERED" if should_trigger and not cooldown_active else ""
        if not prefilter_passed:
            gate_status = f"PREFILTER: {pf_result.reason}"
        elif not adaptive_passed:
            gate_status = f"ADAPTIVE: {adaptive_reason}"
        elif cooldown_active:
            gate_status = f"COOLDOWN: {cooldown_remaining:.0f}s remaining"
        elif self._ai_decision.busy:
            gate_status = "AI BUSY (waiting for previous decision)"

        self._shared.monitor_status = {
            "timestamp": now,
            "time_remaining": time_remaining,
            "btc_price": btc_price_val,
            "btc_move": btc_move,
            "candle_open_btc": candle_open or 0,
            "up_ask": up_ask,
            "down_ask": down_ask,
            "up_mid": pf_snapshot.up_mid,
            "down_mid": pf_snapshot.down_mid,
            "rr_up": round(rr_up, 3),
            "rr_down": round(rr_down, 3),
            "best_side": best_side,
            "up_spread": up_ob.spread_pct,
            "down_spread": down_ob.spread_pct,
            "up_depth": up_ob.bid_depth + up_ob.ask_depth,
            "down_depth": down_ob.bid_depth + down_ob.ask_depth,
            "streak": pf_result.consecutive_streak,
            "streak_dir": pf_result.streak_direction,
            "has_position": has_position,
            # Gate pipeline
            "prefilter_passed": prefilter_passed,
            "prefilter_reason": pf_result.reason if not prefilter_passed else "",
            "adaptive_passed": adaptive_passed,
            "adaptive_reason": adaptive_reason,
            "cooldown_active": cooldown_active,
            "cooldown_remaining": round(cooldown_remaining, 1),
            "ai_triggered": should_trigger and not cooldown_active,
            "gate_status": gate_status,
        }

        if should_trigger and not self._ai_decision.busy:
            if not cooldown_active:
                if self._adaptive_enabled and self._adaptive_entry is not None:
                    reason = (
                        f"adaptive btc_thresh=${self._adaptive_entry.btc_threshold:.0f}, "
                        f"max_entry=${self._adaptive_entry.max_entry_price:.2f}, "
                        f"min_ask=${min_ask:.2f} ({best_side}), "
                        f"btc_move=${btc_move:+.0f}"
                    )
                else:
                    reason = (
                        f"R/R={best_rr:.2f} ({best_side}), "
                        f"prefilter={'PASS' if prefilter_passed else 'SKIP'}, "
                        f"btc_move=${btc_move:+.0f}"
                    )
                asyncio.create_task(self._ai_decision.evaluate_entry(reason))
                logger.info(
                    "AI triggered: %s (cooldown=%.0fs elapsed)",
                    reason,
                    elapsed,
                )

    async def _broadcast_updates(self) -> None:
        """Push lightweight market + status updates to WS clients."""
        if self._ctx is None:
            return
        bc = self._ctx.broadcaster
        if bc.has_clients:
            builder = DashboardMessageBuilder()
            await bc.broadcast(builder.build_market_update(self._ctx))
            await bc.broadcast(builder.build_status_update(self._ctx, ws_client_count=bc.client_count))

    def _queue_snapshot(
        self,
        snapshot,
        pf_snapshot: PreFilterSnapshot,
        pf_result,
        rr_up: float,
        rr_down: float,
        btc_move: float,
        indicator_results: IndicatorResults | None = None,
    ) -> None:
        """Build a SnapshotRow from current tick data and queue it."""
        from polybot.datastore import SnapshotRow

        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook

        # Use pre-computed indicator results when available
        indicators_dict: dict = {}
        if indicator_results is not None:
            indicators_dict = indicator_results.to_dict()
        elif self._feature_config is not None:
            try:
                from polybot.indicators import SessionContext, compute_indicators

                self._feature_config.load()
                session_ctx = SessionContext(
                    wins=self._shared.session_wins,
                    losses=self._shared.session_losses,
                    candle_open_btc=self._shared.candle_open_btc,
                )
                results = compute_indicators(snapshot, self._feature_config, session_ctx)
                indicators_dict = {r.name: {"value": r.value, "label": r.label} for r in results}
            except Exception:
                logger.debug("Indicator computation failed for snapshot", exc_info=True)

        row = SnapshotRow(
            candle_id=self._datastore.current_candle_id,
            timestamp=pf_snapshot.timestamp,
            time_remaining=pf_snapshot.time_remaining,
            up_best_bid=up_ob.best_bid,
            up_best_ask=up_ob.best_ask,
            up_mid=up_ob.midpoint,
            up_spread_pct=up_ob.spread_pct,
            up_bid_depth=up_ob.bid_depth,
            up_ask_depth=up_ob.ask_depth,
            down_best_bid=down_ob.best_bid,
            down_best_ask=down_ob.best_ask,
            down_mid=down_ob.midpoint,
            down_spread_pct=down_ob.spread_pct,
            down_bid_depth=down_ob.bid_depth,
            down_ask_depth=down_ob.ask_depth,
            rr_up=rr_up,
            rr_down=rr_down,
            btc_price=pf_snapshot.btc_price,
            btc_move_from_open=btc_move,
            streak=pf_snapshot.streak,
            streak_direction=pf_snapshot.streak_direction,
            prefilter_passed=not pf_result.should_skip,
            prefilter_reasons="; ".join(pf_snapshot.reasons),
            indicators_json=json.dumps(indicators_dict) if indicators_dict else "{}",
        )
        self._datastore.queue_snapshot(row)

    def _queue_market_history_snapshot(
        self,
        snapshot,
        pf_snapshot: PreFilterSnapshot,
        rr_up: float,
        rr_down: float,
        btc_move: float,
    ) -> None:
        """Build a MarketSnapshotRow and queue it for persistent market history."""
        from polybot.datastore import MarketSnapshotRow

        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook

        row = MarketSnapshotRow(
            candle_id=self._market_history.current_candle_id,
            timestamp=pf_snapshot.timestamp,
            time_remaining=pf_snapshot.time_remaining,
            up_best_bid=up_ob.best_bid,
            up_best_ask=up_ob.best_ask,
            up_mid=up_ob.midpoint,
            up_spread_pct=up_ob.spread_pct,
            up_bid_depth=up_ob.bid_depth,
            up_ask_depth=up_ob.ask_depth,
            down_best_bid=down_ob.best_bid,
            down_best_ask=down_ob.best_ask,
            down_mid=down_ob.midpoint,
            down_spread_pct=down_ob.spread_pct,
            down_bid_depth=down_ob.bid_depth,
            down_ask_depth=down_ob.ask_depth,
            rr_up=rr_up,
            rr_down=rr_down,
            btc_price=pf_snapshot.btc_price,
            btc_move_from_open=btc_move,
            streak=pf_snapshot.streak,
            streak_direction=pf_snapshot.streak_direction,
        )
        self._market_history.queue_snapshot(row)
