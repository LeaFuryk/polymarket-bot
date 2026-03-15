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
    from polybot.tasks.ai_decision import AIDecision
from polybot.indicators import (
    SessionContext,
    compute_indicators,
)
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
                await self._broadcast_updates()
            except Exception:
                logger.exception("MarketMonitor tick error")

            await asyncio.sleep(self._interval)

        logger.info("MarketMonitor stopped")

    async def _tick(self) -> None:
        """Single monitoring cycle."""
        market = self._shared.current_market
        if market is None:
            await self._rotation.discover_market()
            return

        time_remaining = market.time_remaining()
        if time_remaining <= 0:
            await self._rotation.discover_market()
            return

        # Periodic discovery during normal operation (every 5 ticks ≈ 5s)
        self._discovery_counter += 1
        if self._discovery_counter >= 5:
            self._discovery_counter = 0
            await self._rotation.discover_market()

        # Fetch market snapshot
        try:
            snapshot = await self._market_data.get_snapshot()
        except Exception:
            logger.debug("MarketMonitor: data fetch failed", exc_info=True)
            return

        self._shared.latest_snapshot = snapshot
        self._shared.snapshot_timestamp = time.time()

        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook
        up_mid = up_ob.midpoint
        down_mid = down_ob.midpoint

        # Compute R/R for both tokens
        up_ask = up_ob.best_ask or 1.0
        down_ask = down_ob.best_ask or 1.0
        rr_up = (1.0 - up_ask) / up_ask if up_ask > 0 else 0
        rr_down = (1.0 - down_ask) / down_ask if down_ask > 0 else 0

        # Compute BTC move from candle open
        btc_move = 0.0
        btc_price_val = snapshot.btc_price.price_usd if snapshot.btc_price else 0.0
        candle_open = self._shared.candle_open_btc
        if candle_open is not None and btc_price_val > 0:
            btc_move = btc_price_val - candle_open

        # Run prefilter checks (1-5, no R/R gate)
        has_position = self._portfolio.up_position.shares > 0 or self._portfolio.down_position.shares > 0
        pf_result = self._prefilter.check(time_remaining, snapshot, has_position)

        # Build snapshot record
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
            best_entry_up=up_ask,
            best_entry_down=down_ask,
            rr_up=rr_up,
            rr_down=rr_down,
            btc_price=btc_price_val,
            up_mid=up_mid,
            down_mid=down_mid,
            up_spread_pct=up_ob.spread_pct,
            down_spread_pct=down_ob.spread_pct,
            streak=pf_result.consecutive_streak,
            streak_direction=pf_result.streak_direction,
            btc_move_from_open=btc_move,
        )
        self._shared.prefilter_history.append(pf_snapshot)

        # Queue snapshot for SQLite analytics
        if self._datastore is not None and self._datastore.current_candle_id is not None:
            self._queue_snapshot(
                snapshot,
                pf_snapshot,
                pf_result,
                rr_up,
                rr_down,
                btc_move,
            )

        # Queue snapshot for persistent market history
        if self._market_history.current_candle_id is not None:
            self._queue_market_history_snapshot(
                snapshot,
                pf_snapshot,
                rr_up,
                rr_down,
                btc_move,
            )

        # Decide whether to trigger AI (entry only — exits come from PositionMonitor's queue)
        best_rr = max(rr_up, rr_down)
        prefilter_passed = not pf_result.should_skip
        min_ask = min(up_ask, down_ask)
        best_side = "up" if rr_up >= rr_down else "down"

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
            "up_mid": up_mid,
            "down_mid": down_mid,
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
        ws = self._ctx.ws_broadcaster
        if ws.has_clients:
            await ws.broadcast(ws.build_market_update(self._ctx))
            await ws.broadcast(ws.build_status_update(self._ctx))

    def _queue_snapshot(
        self,
        snapshot,
        pf_snapshot: PreFilterSnapshot,
        pf_result,
        rr_up: float,
        rr_down: float,
        btc_move: float,
    ) -> None:
        """Build a SnapshotRow from current tick data and queue it."""
        from polybot.datastore import SnapshotRow

        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook

        # Compute indicators if feature_config is available
        indicators_dict: dict = {}
        if self._feature_config is not None:
            try:
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
