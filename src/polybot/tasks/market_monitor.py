"""Market monitor task — fetches data every 1s, runs prefilter, triggers AI.

Runs as an asyncio.Task. Computes indicators and evaluates the AI trigger
gate when conditions are favorable.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.agent.context import AgentContext
    from polybot.indicators.results import IndicatorResults
    from polybot.models import MarketSnapshot
    from polybot.tasks.ai_decision import AIDecision

from polybot.indicators import Indicator, SessionContext
from polybot.indicators.helpers import compute_rr


class MarketMonitor:
    """Fetches market data every second, runs prefilter, triggers AI."""

    def __init__(
        self,
        ctx: AgentContext,
        ai_decision: AIDecision,
        logger: logging.Logger,
    ) -> None:
        self._log = logger
        self._config = ctx.config
        self._shared = ctx.shared
        self._market_data = ctx.market_data
        self._prefilter = ctx.prefilter
        self._portfolio = ctx.portfolio
        self._ai_decision = ai_decision
        self._datastore = ctx.datastore
        self._processor = ctx.processor
        self._market_history = ctx.market_history
        self._adaptive_entry = ctx.adaptive_entry
        self._ctx = ctx
        self._interval = ctx.config.monitor.market_monitor_interval
        self._rr_threshold = ctx.config.monitor.rr_trigger_threshold
        self._cooldown = ctx.config.monitor.ai_cooldown_seconds
        self._adaptive_enabled = ctx.config.monitor.adaptive_entry_enabled

    async def run(self) -> None:
        """Main loop — runs until shutdown."""
        self._log.info("MarketMonitor started (interval=%.1fs)", self._interval)
        while not self._shared.shutdown:
            if self._shared.rotation_in_progress:
                await asyncio.sleep(0.2)
                continue

            try:
                await self._tick()
            except Exception:
                self._log.exception("MarketMonitor tick error")

            await asyncio.sleep(self._interval)

        self._log.info("MarketMonitor stopped")

    async def _tick(self) -> None:
        """Single monitoring cycle.

        Pipeline: fetch → indicators → prefilter → persist (always)
        → adaptive entry → cooldown → fire AI.
        """
        snapshot = await self._fetch_snapshot()
        if snapshot is None:
            return

        has_position = self._portfolio.has_open_position()
        indicators = self._calculate_indicators(snapshot, has_position)
        pf_result = self._run_prefilter(snapshot, has_position)

        self._persist_snapshots(snapshot, pf_result, indicators)

        if pf_result.should_skip:
            self._update_monitor_status(
                snapshot,
                indicators,
                has_position,
                pf_result=pf_result,
            )
            return

        ae_passed, ae_reason = self._run_adaptive_entry(indicators)
        self._evaluate_trigger(snapshot, pf_result, indicators, has_position, ae_passed, ae_reason)

    async def _fetch_snapshot(self) -> MarketSnapshot | None:
        """Fetch snapshot from provider and store on shared state."""
        snapshot = await self._market_data.get_snapshot()
        if snapshot is None:
            return None
        self._shared.latest_snapshot = snapshot
        self._shared.snapshot_timestamp = time.time()
        return snapshot

    def _calculate_indicators(self, snapshot, has_position: bool) -> IndicatorResults | None:
        """Compute indicators, store on shared state, and broadcast."""
        indicators = self._compute_indicators(snapshot, has_position)
        self._shared.latest_indicator_results = indicators
        self._broadcast_indicators(indicators)
        return indicators

    def _run_prefilter(self, snapshot, has_position: bool):
        """Run prefilter gate and broadcast result."""
        pf_result = self._prefilter.check(snapshot, has_position, btc_candles=self._market_data.btc_feed.candles)
        self._broadcast_prefilter(pf_result)
        return pf_result

    # --- Indicators ---

    def _compute_indicators(self, snapshot, has_position: bool) -> IndicatorResults | None:
        """Compute all indicators once using the processor."""
        if self._processor is None:
            return None
        try:
            position_side = ""
            if has_position:
                if self._portfolio.up_position.shares > 0:
                    position_side = "up"
                elif self._portfolio.down_position.shares > 0:
                    position_side = "down"

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
                time_remaining=snapshot.time_remaining,
                position_side=position_side,
                btc_candles=self._market_data.btc_feed.candles,
                microstructure_history=self._shared.microstructure_history,
                session_trades=getattr(self._ctx, "session_trades", None),
                session_resolutions=getattr(self._ctx, "session_resolutions", None),
            )
        except Exception:
            self._log.debug("Indicator computation failed", exc_info=True)
            return None

    def _persist_snapshots(
        self,
        snapshot,
        pf_result,
        indicator_results: IndicatorResults | None = None,
    ) -> None:
        """Queue snapshots for SQLite analytics and persistent market history."""
        btc_price = snapshot.btc_price.price_usd if snapshot.btc_price else 0.0
        if indicator_results is not None:
            rr_up = indicator_results.get_extra(Indicator.RISK_REWARD, "rr_up", 0.0)
            rr_down = indicator_results.get_extra(Indicator.RISK_REWARD, "rr_down", 0.0)
            btc_move = indicator_results.get_value(Indicator.BTC_MOVE_FROM_OPEN)
        else:
            rr_up = compute_rr(snapshot.orderbook.best_ask or 1.0)
            rr_down = compute_rr(snapshot.down_orderbook.best_ask or 1.0)
            candle_open = self._shared.candle_open_btc
            btc_move = (btc_price - candle_open) if candle_open is not None and btc_price > 0 else 0.0

        if self._datastore is not None and self._datastore.current_candle_id is not None:
            self._queue_snapshot(
                snapshot,
                pf_result,
                rr_up,
                rr_down,
                btc_move,
                btc_price,
                indicator_results,
            )

        if self._market_history.current_candle_id is not None:
            self._queue_market_history_snapshot(
                snapshot,
                pf_result,
                rr_up,
                rr_down,
                btc_move,
                btc_price,
            )

    def _run_adaptive_entry(self, indicators: IndicatorResults | None) -> tuple[bool, str]:
        """Evaluate adaptive entry (or static R/R fallback). Returns (passed, reason)."""
        if indicators is not None:
            btc_move = indicators.get_value(Indicator.BTC_MOVE_FROM_OPEN)
            min_ask = indicators.get_value(Indicator.BEST_ENTRY, 1.0)
            best_rr = indicators.get_value(Indicator.RISK_REWARD)
        else:
            best_rr = 0.0
            btc_move = 0.0
            min_ask = 1.0

        if self._adaptive_enabled and self._adaptive_entry is not None:
            passed = self._adaptive_entry.should_trigger(
                abs_btc_move=abs(btc_move),
                min_ask=min_ask,
            )
            if passed:
                return True, ""
            btc_thresh = self._adaptive_entry.btc_threshold
            max_entry = self._adaptive_entry.max_entry_price
            parts = []
            if abs(btc_move) < btc_thresh:
                parts.append(f"BTC move ${abs(btc_move):.0f} < ${btc_thresh:.0f} threshold")
            if min_ask > max_entry:
                parts.append(f"min ask ${min_ask:.2f} > ${max_entry:.2f} max entry")
            return False, "; ".join(parts) if parts else "adaptive gate blocked"

        # Fallback: static R/R threshold
        if best_rr >= self._rr_threshold:
            return True, ""
        return False, f"R/R {best_rr:.2f} < {self._rr_threshold:.2f} threshold"

    def _update_monitor_status(
        self,
        snapshot,
        indicators: IndicatorResults | None,
        has_position: bool,
        *,
        pf_result=None,
        ae_passed: bool = False,
        ae_reason: str = "",
        cooldown_active: bool = False,
        cooldown_remaining: float = 0.0,
        ai_triggered: bool = False,
        gate_status: str = "",
    ) -> None:
        """Write monitor_status dict to shared state for the dashboard."""
        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook
        up_ask = up_ob.best_ask or 1.0
        down_ask = down_ob.best_ask or 1.0

        if indicators is not None:
            rr_up = indicators.get_extra(Indicator.RISK_REWARD, "rr_up", 0.0)
            rr_down = indicators.get_extra(Indicator.RISK_REWARD, "rr_down", 0.0)
            btc_move = indicators.get_value(Indicator.BTC_MOVE_FROM_OPEN)
            best_side = str(indicators.get_extra(Indicator.RISK_REWARD, "best_side", "up"))
        else:
            rr_up = compute_rr(up_ask)
            rr_down = compute_rr(down_ask)
            candle_open = self._shared.candle_open_btc
            btc_price_val = snapshot.btc_price.price_usd if snapshot.btc_price else 0.0
            btc_move = (btc_price_val - candle_open) if candle_open is not None and btc_price_val > 0 else 0.0
            best_side = "up" if rr_up >= rr_down else "down"

        prefilter_passed = pf_result is None or not pf_result.should_skip
        prefilter_reason = pf_result.reason if pf_result and not prefilter_passed else ""

        if not gate_status:
            if not prefilter_passed:
                gate_status = f"PREFILTER: {prefilter_reason}"
            elif not ae_passed:
                gate_status = f"ADAPTIVE: {ae_reason}"
            elif cooldown_active:
                gate_status = f"COOLDOWN: {cooldown_remaining:.0f}s remaining"
            elif self._ai_decision.busy:
                gate_status = "AI BUSY (waiting for previous decision)"

        btc_price = snapshot.btc_price.price_usd if snapshot.btc_price else 0.0
        self._shared.monitor_status = {
            "timestamp": time.time(),
            "time_remaining": snapshot.time_remaining,
            "btc_price": btc_price,
            "btc_move": btc_move,
            "candle_open_btc": self._shared.candle_open_btc or 0,
            "up_ask": up_ask,
            "down_ask": down_ask,
            "up_mid": up_ob.midpoint,
            "down_mid": down_ob.midpoint,
            "rr_up": round(rr_up, 3),
            "rr_down": round(rr_down, 3),
            "best_side": best_side,
            "up_spread": up_ob.spread_pct,
            "down_spread": down_ob.spread_pct,
            "up_depth": up_ob.bid_depth + up_ob.ask_depth,
            "down_depth": down_ob.bid_depth + down_ob.ask_depth,
            "streak": pf_result.consecutive_streak if pf_result else 0,
            "streak_dir": pf_result.streak_direction if pf_result else "",
            "has_position": has_position,
            # Gate pipeline
            "prefilter_passed": prefilter_passed,
            "prefilter_reason": prefilter_reason,
            "adaptive_passed": ae_passed,
            "adaptive_reason": ae_reason,
            "cooldown_active": cooldown_active,
            "cooldown_remaining": round(cooldown_remaining, 1),
            "ai_triggered": ai_triggered,
            "gate_status": gate_status,
        }

    def _evaluate_trigger(
        self,
        snapshot,
        pf_result,
        indicators: IndicatorResults | None,
        has_position: bool,
        ae_passed: bool,
        ae_reason: str,
    ) -> None:
        """Check cooldown, update dashboard status, fire AI if all gates pass."""
        now = time.time()
        elapsed = now - self._shared.ai_last_call_time
        cooldown_active = elapsed < self._cooldown
        cooldown_remaining = max(0, self._cooldown - elapsed)
        should_trigger = ae_passed and not cooldown_active and not self._ai_decision.busy

        gate_status = "TRIGGERED" if should_trigger else ""
        if ae_passed and not cooldown_active and self._ai_decision.busy:
            gate_status = "AI BUSY (waiting for previous decision)"

        self._update_monitor_status(
            snapshot,
            indicators,
            has_position,
            pf_result=pf_result,
            ae_passed=ae_passed,
            ae_reason=ae_reason,
            cooldown_active=cooldown_active,
            cooldown_remaining=cooldown_remaining,
            ai_triggered=should_trigger,
            gate_status=gate_status,
        )

        if not should_trigger:
            return

        if indicators is not None:
            btc_move = indicators.get_value(Indicator.BTC_MOVE_FROM_OPEN)
            min_ask = indicators.get_value(Indicator.BEST_ENTRY, 1.0)
            best_side = str(indicators.get_extra(Indicator.RISK_REWARD, "best_side", "up"))
            best_rr = indicators.get_value(Indicator.RISK_REWARD)
        else:
            btc_move = 0.0
            min_ask = 1.0
            best_side = "up"
            best_rr = 0.0

        if self._adaptive_enabled and self._adaptive_entry is not None:
            reason = (
                f"adaptive btc_thresh=${self._adaptive_entry.btc_threshold:.0f}, "
                f"max_entry=${self._adaptive_entry.max_entry_price:.2f}, "
                f"min_ask=${min_ask:.2f} ({best_side}), "
                f"btc_move=${btc_move:+.0f}"
            )
        else:
            reason = f"R/R={best_rr:.2f} ({best_side}), prefilter=PASS, btc_move=${btc_move:+.0f}"
        asyncio.create_task(self._ai_decision.evaluate_entry(reason))
        self._log.info("AI triggered: %s (cooldown=%.0fs elapsed)", reason, elapsed)

    def _broadcast_indicators(self, indicators) -> None:
        """Broadcast computed indicators to WS clients."""
        if indicators is None:
            return
        bc = self._ctx.broadcaster
        if not bc.has_clients:
            return

        from polybot.ws.protocol import MSG_STATUS, make_message

        msg = make_message(MSG_STATUS, {"indicators": indicators.to_dict()})
        asyncio.create_task(bc.broadcast(msg))

    def _broadcast_prefilter(self, pf_result) -> None:
        """Broadcast prefilter result to WS clients when it passes."""
        if pf_result.should_skip:
            return
        bc = self._ctx.broadcaster
        if not bc.has_clients:
            return

        from polybot.ws.protocol import MSG_STATUS, make_message

        msg = make_message(
            MSG_STATUS,
            {
                "prefilter": {
                    "passed": True,
                    "streak": pf_result.consecutive_streak,
                    "streak_direction": pf_result.streak_direction,
                    "btc_range_30m": pf_result.btc_range_30m,
                    "best_entry": pf_result.best_entry_price,
                }
            },
        )
        asyncio.create_task(bc.broadcast(msg))

    def _queue_snapshot(
        self,
        snapshot,
        pf_result,
        rr_up: float,
        rr_down: float,
        btc_move: float,
        btc_price: float,
        indicator_results: IndicatorResults | None = None,
    ) -> None:
        """Build a SnapshotRow from current tick data and queue it."""
        from polybot.datastore import SnapshotRow

        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook

        indicators_dict: dict = {}
        if indicator_results is not None:
            indicators_dict = indicator_results.to_dict()

        row = SnapshotRow(
            candle_id=self._datastore.current_candle_id,
            timestamp=snapshot.timestamp,
            time_remaining=snapshot.time_remaining,
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
            btc_price=btc_price,
            btc_move_from_open=btc_move,
            streak=pf_result.consecutive_streak,
            streak_direction=pf_result.streak_direction,
            prefilter_passed=not pf_result.should_skip,
            prefilter_reasons=pf_result.reason if pf_result.reason else "",
            indicators_json=json.dumps(indicators_dict) if indicators_dict else "{}",
        )
        self._datastore.queue_snapshot(row)

    def _queue_market_history_snapshot(
        self,
        snapshot,
        pf_result,
        rr_up: float,
        rr_down: float,
        btc_move: float,
        btc_price: float,
    ) -> None:
        """Build a MarketSnapshotRow and queue it for persistent market history."""
        from polybot.datastore import MarketSnapshotRow

        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook

        row = MarketSnapshotRow(
            candle_id=self._market_history.current_candle_id,
            timestamp=snapshot.timestamp,
            time_remaining=snapshot.time_remaining,
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
            btc_price=btc_price,
            btc_move_from_open=btc_move,
            streak=pf_result.consecutive_streak,
            streak_direction=pf_result.streak_direction,
        )
        self._market_history.queue_snapshot(row)
