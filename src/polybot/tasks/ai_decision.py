"""AI decision service — callable by MarketMonitor and PositionMonitor.

Called directly via ``evaluate_entry()`` and ``evaluate_exit()`` (no internal
loop). An ``asyncio.Lock`` serialises concurrent calls so an exit waits for
an in-progress entry to finish rather than being dropped.
"""

from __future__ import annotations

import asyncio
import logging
import time

from polybot.adaptive_entry import AdaptiveEntryTracker
from polybot.calibration import ConfidenceCalibrator
from polybot.config import AppConfig
from polybot.decision_engine.engine import DecisionEngine
from polybot.execution.live import LiveExecutionEngine
from polybot.exit_tracker import ExitTracker
from polybot.indicators import (
    FeatureConfig,
    SessionContext,
    compute_indicators,
    format_indicators,
)
from polybot.knowledge import KnowledgeManager
from polybot.logging.trade_log import TradeLog
from polybot.ml_scorer import MLScorer
from polybot.models import (
    Action,
    CandleMarket,
    FeatureVector,
    OrderType,
    ResolutionRecord,
    TokenSide,
    TradeRecord,
    TradingDecision,
)
from polybot.prefilter import PreFilter
from polybot.resolution import ResolutionTracker
from polybot.risk.manager import RiskManager
from polybot.shared_state import EntryContext, SharedState
from polybot.shared_state.stop_loss_record import StopLossRecord
from polybot.simulator.engine import ExecutionSimulator
from polybot.simulator.orderbook import SimulatedOrderBook
from polybot.simulator.portfolio import Portfolio
from polybot.tasks.context_builder import (
    append_section,
    build_chainlink_warning,
    build_counter_trend_advisory,
    build_reversal_regime_warning,
    build_stop_loss_warning,
    build_velocity_conflict_warning,
    format_ml_line,
)
from polybot.tasks.decision_guards import (
    apply_anti_flip,
    apply_confidence_gate,
    apply_entry_price_cap,
    apply_position_sizing,
    apply_reversal_regime_scaling,
    apply_single_entry,
    apply_velocity_conflict_scaling,
    clamp_sell_size,
    compute_position_scale,
    force_exit_side,
    override_to_hold,
)
from polybot.tasks.prompt_context import (
    compute_btc_trajectory,
    compute_entry_timing_stats,
    compute_retracement_context,
    compute_reversal_regime,
    detect_velocity_magnitude_conflict,
    format_microstructure,
)
from polybot.tasks.trade_logger import build_decision_row, build_trade_record

logger = logging.getLogger(__name__)


class AIDecision:
    """Event-driven AI decision maker."""

    def __init__(
        self,
        config: AppConfig,
        shared: SharedState,
        decision_engine: DecisionEngine,
        execution_sim: ExecutionSimulator,
        orderbook: SimulatedOrderBook,
        portfolio: Portfolio,
        risk: RiskManager,
        trade_log: TradeLog,
        prefilter: PreFilter,
        calibrator: ConfidenceCalibrator,
        exit_tracker: ExitTracker,
        ml_scorer: MLScorer,
        knowledge_manager: KnowledgeManager,
        feature_config: FeatureConfig,
        resolution_tracker: ResolutionTracker,
        # Mutable state references from agent
        recent_resolutions: list[ResolutionRecord],
        recent_trades: list[TradeRecord],
        session_trades: list[TradeRecord],
        pending_ml_features: dict[str, dict[str, float]],
        adaptive_entry: AdaptiveEntryTracker | None = None,
        live_engine: LiveExecutionEngine | None = None,
        shadow_portfolio: Portfolio | None = None,
    ) -> None:
        self._config = config
        self._shared = shared
        self._engine = decision_engine
        self._exec_sim = execution_sim
        self._orderbook = orderbook
        self._portfolio = portfolio
        self._risk = risk
        self._trade_log = trade_log
        self._prefilter = prefilter
        self._calibrator = calibrator
        self._exit_tracker = exit_tracker
        self._ml_scorer = ml_scorer
        self._knowledge = knowledge_manager
        self._feature_config = feature_config
        self._resolution_tracker = resolution_tracker
        self._adaptive_entry = adaptive_entry

        # Live trading engine (None in paper mode)
        self._live_engine = live_engine
        self._shadow_portfolio = shadow_portfolio
        self._live_mode = live_engine is not None

        # Optional SQLite analytics
        self._datastore = None  # set by agent if sqlite_enabled

        # Shared mutable state from agent
        self._recent_resolutions = recent_resolutions
        self._recent_trades = recent_trades
        self._session_trades = session_trades
        self._pending_ml_features = pending_ml_features

        # Optional callback for WS trade event push
        self.on_trade_callback = None  # set by agent: Callable[[TradeRecord], Awaitable[None]]

        # Serialise concurrent entry/exit calls
        self._lock = asyncio.Lock()

        # Track sold sides per candle to block side-flips (sell A → buy B)
        self._sold_sides: dict[str, set[str]] = {}  # slug → {UP, DOWN}
        # Track bought sides per candle to prevent double-entry on same side
        self._bought_sides: dict[str, set[str]] = {}  # slug → {UP, DOWN}

        # Internal counters (synced to agent via shared references)
        self._cycle_count = 0
        self._total_api_cost: float = 0.0
        self._contrarian_flip_active = False
        self._reversal_flip_side: str | None = None  # "up"/"down" during reversal retracement
        self._last_cycle_api_cost: float = 0.0

        # Session stats (agent reads these)
        self.session_wins: int = 0
        self.session_losses: int = 0
        self.session_resolution_pnl: float = 0.0

        # Dashboard state (agent reads these)
        self.last_action: str = "—"
        self.last_reasoning: str = ""
        self.last_risk_status: str = "OK"
        self.last_token_side: str = ""

        # Per-cycle screen tracking (None=no screen, True=passed, False=rejected)
        self._last_screen_passed: bool | None = None

        # Ensemble disagreement tracking
        self._screen_calls: int = 0
        self._screen_passes: int = 0  # Haiku said "trade"
        self._sonnet_trades: int = 0  # Sonnet actually traded after Haiku pass
        self._ml_sonnet_agree: int = 0  # ML and Sonnet picked same direction
        self._ml_sonnet_total: int = 0  # total decisions where both had a direction

    @property
    def total_api_cost(self) -> float:
        return self._total_api_cost

    @total_api_cost.setter
    def total_api_cost(self, value: float) -> None:
        self._total_api_cost = value

    @property
    def last_cycle_api_cost(self) -> float:
        return self._last_cycle_api_cost

    @property
    def busy(self) -> bool:
        """True when an entry/exit evaluation is in progress."""
        return self._lock.locked()

    async def evaluate_entry(self, trigger_reason: str) -> None:
        """Handle an entry opportunity trigger from the market monitor."""
        async with self._lock:
            if self._shared.rotation_in_progress:
                return

            # Publish trigger reason for dashboard / WS
            self._shared.ai_trigger_reason = trigger_reason

            # Record call time immediately to prevent MarketMonitor from
            # re-triggering during the async Haiku/Sonnet call
            self._record_ai_call_time()

            self._last_screen_passed = None  # Reset per cycle
            self._cycle_count += 1
            cycle = self._cycle_count
            logger.info("=== AI Decision Cycle %d (trigger: %s) ===", cycle, trigger_reason)

            snapshot = self._shared.latest_snapshot
            market = self._shared.current_market
            if snapshot is None or market is None:
                self.last_action = "SKIP (no data)"
                return

            time_remaining = market.time_remaining()
            buffer = self._config.agent.resolution_buffer_seconds
            if time_remaining < buffer:
                self.last_action = f"SKIP ({time_remaining:.0f}s to resolution)"
                return

            up_ob = snapshot.orderbook
            down_ob = snapshot.down_orderbook
            up_mid = up_ob.midpoint
            down_mid = down_ob.midpoint

            # Mark-to-market
            if up_mid is not None:
                self._portfolio.mark_to_market(up_mid, down_mid)
            portfolio_value = self._portfolio.total_value_at_market(up_mid or 0.5, down_mid)
            self._risk.update_portfolio_peak(portfolio_value)

            # Check pending limit order fills
            limit_fills = self._orderbook.check_fills(up_ob)
            for fill in limit_fills:
                self._portfolio.apply_fill(fill, TokenSide.UP)
                pnl = 0.0
                if fill.side.value == "SELL":
                    pnl = (fill.fill_price - self._portfolio.up_position.avg_entry_price) * fill.size
                self._risk.record_trade(pnl, fill.fee_amount)
                logger.info("Limit fill: %s %.2f @ %.4f", fill.side.value, fill.size, fill.fill_price)

            # Pre-trade risk checks
            pre_checks = self._risk.pre_trade_checks(snapshot)
            pre_failed = [c for c in pre_checks if not c.passed]
            if pre_failed:
                reasons = "; ".join(c.reason for c in pre_failed)
                logger.warning("Pre-trade risk blocked: %s", reasons)
                self.last_action = "BLOCKED (pre-trade)"
                self.last_risk_status = reasons
                self._log_cycle(cycle, snapshot, risk_blocked=True, risk_reason=reasons)
                return

            await self._run_ai_decision(cycle, snapshot, market, time_remaining, portfolio_value)

    async def evaluate_exit(self, exit_signal: dict) -> None:
        """Handle a stop-loss/take-profit exit trigger from position monitor."""
        async with self._lock:
            if self._shared.rotation_in_progress:
                return

            self._cycle_count += 1
            cycle = self._cycle_count
            token_side_str = exit_signal.get("token_side", "up")
            reason = exit_signal.get("reason", "unknown")
            pnl_pct = exit_signal.get("pnl_pct", 0.0)
            logger.info(
                "=== AI Exit Decision Cycle %d (SL/TP: %s %s, P&L=%.1f%%) ===",
                cycle,
                token_side_str,
                reason,
                pnl_pct * 100,
            )

            # Exit trigger cooldown: skip if on cooldown and not a true emergency (> -30%)
            # Reversal retracement bypasses cooldown — it's time-sensitive
            trigger_type = exit_signal.get("trigger_type", "")
            cooldown = self._config.monitor.ai_cooldown_seconds
            elapsed = time.time() - self._shared.ai_last_call_time
            if elapsed < cooldown and pnl_pct > -0.30 and trigger_type != "reversal_retracement":
                logger.info(
                    "Exit trigger on cooldown (%.0fs < %.0fs, pnl=%.1f%% > -30%%) — skipping",
                    elapsed,
                    cooldown,
                    pnl_pct * 100,
                )
                return

            snapshot = self._shared.latest_snapshot
            market = self._shared.current_market
            if snapshot is None or market is None:
                return

            time_remaining = market.time_remaining()

            # Guard against selling winners near expiry: if position is profitable
            # and BTC direction matches position side and < 120s remaining, skip exit
            if pnl_pct > 0 and time_remaining < 120 and trigger_type != "reversal_retracement":
                btc_price_now = snapshot.btc_price.price_usd if snapshot.btc_price else None
                candle_open = self._shared.candle_open_btc
                if btc_price_now is not None and candle_open is not None:
                    btc_diff = btc_price_now - candle_open
                    btc_favors_up = btc_diff >= 0
                    position_is_up = token_side_str.lower() == "up"
                    direction_matches = (position_is_up and btc_favors_up) or (not position_is_up and not btc_favors_up)
                    if direction_matches:
                        logger.info(
                            "Skipping exit on winning %s position (P&L=%.1f%%, BTC %s$%.0f, "
                            "%.0fs left) — let it ride to resolution",
                            token_side_str,
                            pnl_pct * 100,
                            "+" if btc_diff >= 0 else "",
                            btc_diff,
                            time_remaining,
                        )
                        return

            up_ob = snapshot.orderbook
            down_ob = snapshot.down_orderbook
            up_mid = up_ob.midpoint
            down_mid = down_ob.midpoint

            if up_mid is not None:
                self._portfolio.mark_to_market(up_mid, down_mid)
            portfolio_value = self._portfolio.total_value_at_market(up_mid or 0.5, down_mid)

            # Add exit context to the AI call
            sold_up = token_side_str.lower() == "up"
            opposite_side = "DOWN" if sold_up else "UP"

            if trigger_type == "reversal_retracement":
                # Single AI call: HOLD (keep position) or BUY opposite (auto-close + flip)
                # Compute rich retracement analytics from per-second prefilter history
                retracement_ctx = compute_retracement_context(
                    list(self._shared.prefilter_history),
                    token_side_str,
                    snapshot,
                )

                opp_ob = snapshot.down_orderbook if sold_up else snapshot.orderbook
                opp_ask = opp_ob.best_ask
                opp_line = f"- {opposite_side} ask: ${opp_ask:.2f}\n" if opp_ask else ""
                exit_context = (
                    f"\n## REVERSAL RETRACEMENT — HOLD OR FLIP?\n"
                    f"- Position: {token_side_str.upper()}\n"
                    f"- Current P&L: {pnl_pct:+.1%}\n"
                    f"{opp_line}"
                    f"{retracement_ctx}\n"
                    f"\n### Decision Guide\n"
                    f"- The RETRACEMENT PATTERN is the signal — do NOT evaluate the current BTC move as a standalone entry.\n"
                    f"- Zero crossing (BTC moved to opposite side) = strong flip signal.\n"
                    f"- Accelerating retreat + time since peak > 30s = likely real reversal.\n"
                    f"- Decelerating retreat or very recent peak = likely pullback, consider HOLD.\n"
                    f"- **HOLD** = keep position open, stop-loss remains active.\n"
                    f"- **BUY {opposite_side}** = close {token_side_str.upper()} and flip to {opposite_side}.\n"
                )
                # Set flag so anti-hedge auto-closes current position instead of blocking
                self._reversal_flip_side = token_side_str.lower()
                self._contrarian_flip_active = True
                try:
                    await self._run_ai_decision(
                        cycle,
                        snapshot,
                        market,
                        time_remaining,
                        portfolio_value,
                        extra_context=exit_context,
                        # No forced_exit_side — AI chooses HOLD or BUY opposite
                    )
                finally:
                    self._reversal_flip_side = None
                    self._contrarian_flip_active = False
            else:
                exit_context = (
                    f"\n## EXIT TRIGGER\n"
                    f"- Token: {token_side_str.upper()}\n"
                    f"- Reason: {reason}\n"
                    f"- Current P&L: {pnl_pct:+.1%}\n"
                    f"- Action needed: Evaluate whether to SELL this position NOW.\n"
                )

                await self._run_ai_decision(
                    cycle,
                    snapshot,
                    market,
                    time_remaining,
                    portfolio_value,
                    extra_context=exit_context,
                    forced_exit_side=token_side_str,
                )

                # Safeguard #3: Record stop-loss exit for cooldown warning
                if trigger_type == "stop_loss":
                    self._shared.last_stop_loss = StopLossRecord(
                        token_side=token_side_str,
                        pnl_pct=pnl_pct,
                        timestamp=time.time(),
                    )

                # --- Contrarian flip (post-SL only) ---
                # After SL, if position closed and BTC confirms reversal,
                # trigger a second AI call for the opposite side.
                if trigger_type == "stop_loss":
                    pos = self._portfolio.up_position if sold_up else self._portfolio.down_position
                    if pos.shares <= 0:
                        await self._try_contrarian_flip(token_side_str, pnl_pct, trigger_type)

    async def _try_contrarian_flip(
        self,
        token_side_str: str,
        pnl_pct: float,
        trigger_type: str,
    ) -> None:
        """After exiting a position, evaluate buying the opposite side.

        Triggered after stop-loss or reversal-retracement exits. Checks that
        BTC confirms the reversal and enough time remains, then calls AI to
        decide BUY or HOLD. The anti-flip guard is bypassed for this call.
        """
        snap = self._shared.latest_snapshot
        mkt = self._shared.current_market
        if snap is None or mkt is None:
            return

        tr = mkt.time_remaining()
        btc_now = snap.btc_price.price_usd if snap.btc_price else None
        candle_open = self._shared.candle_open_btc

        # Determine opposite side and its ask price
        sold_up = token_side_str.lower() == "up"
        opposite_side = "DOWN" if sold_up else "UP"
        opp_ob = snap.down_orderbook if sold_up else snap.orderbook
        opp_ask = opp_ob.best_ask

        # BTC confirms reversal: move is against the sold position
        btc_confirms = False
        btc_move = 0.0
        if btc_now is not None and candle_open is not None:
            btc_move = btc_now - candle_open
            # If we sold UP, BTC should be dropping (btc_move < 0)
            # If we sold DOWN, BTC should be rising (btc_move > 0)
            btc_confirms = (sold_up and btc_move < 0) or (not sold_up and btc_move > 0)

        # Log skip reasons for debugging
        skip_reasons = []
        if tr < 60:
            skip_reasons.append(f"time={tr:.0f}s<60s")
        if not btc_confirms:
            skip_reasons.append(f"BTC {'$' if btc_move >= 0 else '-$'}{abs(btc_move):.0f} doesn't confirm reversal")

        if skip_reasons:
            logger.info("Contrarian flip: skip — %s", ", ".join(skip_reasons))
            return

        reason_label = "stop-loss" if trigger_type == "stop_loss" else "reversal exit"
        logger.info(
            "Contrarian flip: triggering %s entry after %s (BTC %s$%.0f, %s ask=$%.2f, %.0fs left)",
            opposite_side,
            reason_label,
            "+" if btc_move >= 0 else "",
            btc_move,
            opposite_side,
            opp_ask or 0,
            tr,
        )
        flip_context = (
            f"\n## CONTRARIAN FLIP OPPORTUNITY\n"
            f"- Just exited {token_side_str.upper()} at {pnl_pct:+.1%} ({reason_label})\n"
            f"- BTC reversed: ${btc_move:+.0f} from candle open\n"
            f"- {opposite_side} ask = ${opp_ask:.2f}\n"
            f"- Consider buying {opposite_side} to recover — the reversal is confirmed.\n"
        )
        # Re-read portfolio value
        up_mid2 = snap.orderbook.midpoint
        down_mid2 = snap.down_orderbook.midpoint
        if up_mid2 is not None:
            self._portfolio.mark_to_market(up_mid2, down_mid2)
        pv = self._portfolio.total_value_at_market(up_mid2 or 0.5, down_mid2)

        self._contrarian_flip_active = True
        try:
            self._cycle_count += 1
            await self._run_ai_decision(
                self._cycle_count,
                snap,
                mkt,
                tr,
                pv,
                extra_context=flip_context,
            )
        finally:
            self._contrarian_flip_active = False

    async def _auto_close_for_flip(
        self,
        close_side: str,  # "up" or "down"
        market: CandleMarket | None,
        time_remaining: float,
        snapshot,
        cycle: int = 0,
    ) -> bool:
        """Auto-close a position as part of reversal flip. Returns True if closed."""
        token_side = TokenSide.UP if close_side == "up" else TokenSide.DOWN
        position = self._portfolio.get_position(token_side)
        if position.shares <= 0:
            return True

        ob = snapshot.orderbook if close_side == "up" else snapshot.down_orderbook
        sell_decision = TradingDecision(
            action=Action.SELL,
            order_type=OrderType.MARKET,
            size=position.shares,
            confidence=0.5,
            reasoning="Auto-close for reversal flip",
            market_view="",
            token_side=token_side,
        )

        fill = None
        if self._live_mode and self._live_engine:
            live_result = await self._live_engine.execute(sell_decision, ob)
            fill = live_result.fill if live_result else None
            paper_fill = self._exec_sim.execute(sell_decision, ob)
            if paper_fill and self._shadow_portfolio:
                self._shadow_portfolio.apply_fill(paper_fill, token_side)
        else:
            fill = self._exec_sim.execute(sell_decision, ob)

        if not fill:
            logger.warning("Reversal flip: failed to close %s position", close_side.upper())
            return False

        self._portfolio.apply_fill(fill, token_side)
        realized = (fill.fill_price - position.avg_entry_price) * fill.size
        self._risk.record_trade(realized, fill.fee_amount)

        if market:
            self._exit_tracker.register_exit(
                slug=market.slug,
                token_side=token_side.value,
                entry_price=position.avg_entry_price,
                exit_price=fill.fill_price,
                exit_size=fill.size,
                time_remaining=time_remaining,
            )
            self._sold_sides.setdefault(market.slug, set()).add(token_side.value)

        self._shared.entry_context.pop(token_side.value, None)
        self._shared.dynamic_sl.pop(token_side.value, None)
        self._shared.dynamic_tp.pop(token_side.value, None)

        logger.info(
            "Reversal flip: auto-closed %s (%.1f shares @ $%.4f, P&L $%.2f)",
            close_side.upper(),
            fill.size,
            fill.fill_price,
            realized,
        )
        self._log_cycle(cycle, snapshot, decision=sell_decision, fill=fill)
        return True

    async def _run_ai_decision(
        self,
        cycle: int,
        snapshot,
        market: CandleMarket,
        time_remaining: float,
        portfolio_value: float,
        extra_context: str = "",
        forced_exit_side: str | None = None,
    ) -> None:
        """Core AI decision logic — shared between entry and exit triggers."""
        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook
        up_mid = up_ob.midpoint
        down_mid = down_ob.midpoint

        candle_open_btc = self._shared.candle_open_btc

        # Build feature vector
        features = FeatureVector(
            market=snapshot,
            position=self._portfolio.position,
            up_position=self._portfolio.up_position,
            down_position=self._portfolio.down_position,
            risk=self._risk.state,
            portfolio_cash=self._portfolio.cash,
            portfolio_total_value=portfolio_value,
            cycle_number=cycle,
            time_remaining=time_remaining,
        )

        exit_summary = self._exit_tracker.get_summary()
        calibration_summary = self._calibrator.get_calibration_summary()
        if exit_summary:
            calibration_summary = calibration_summary + "\n" + exit_summary

        feedback_context = self._knowledge.build_feedback_context(
            self._recent_resolutions,
            self.session_wins,
            self.session_losses,
            self.session_resolution_pnl,
            calibration_summary=calibration_summary,
            recent_trades=self._recent_trades,
        )
        if extra_context:
            feedback_context = extra_context + "\n" + feedback_context

        # Compute indicators
        self._feature_config.load()
        session_ctx = SessionContext(
            wins=self.session_wins,
            losses=self.session_losses,
            candle_open_btc=candle_open_btc,
        )
        indicator_results = compute_indicators(snapshot, self._feature_config, session_ctx)
        indicators_text = format_indicators(indicator_results)

        # Velocity conflict (computed early for ML features)
        velocity_conflict = detect_velocity_magnitude_conflict(
            list(self._shared.prefilter_history),
            time_remaining=features.time_remaining,
        )

        # Reversal regime (computed early for ML features)
        _prefilter_list = list(self._shared.prefilter_history)
        _regime_result = compute_reversal_regime(
            self._shared.microstructure_history,
            current_prefilter_history=_prefilter_list if len(_prefilter_list) >= 10 else None,
        )
        reversal_score = 0.0
        zero_crossings_avg = 0.0
        if _regime_result is not None:
            reversal_score = _regime_result[0]
            if self._shared.microstructure_history:
                zero_crossings_avg = sum(h.zero_crossings for h in self._shared.microstructure_history) / len(
                    self._shared.microstructure_history
                )

        # ML prediction
        btc_price_val = snapshot.btc_price.price_usd if snapshot.btc_price else None
        ml_features = self._ml_scorer.extract_features(
            candles=snapshot.btc_candles,
            btc_price=btc_price_val,
            candle_open=candle_open_btc,
            up_mid=up_mid,
            down_mid=down_mid,
            up_bid_depth=snapshot.orderbook.bid_depth,
            up_ask_depth=snapshot.orderbook.ask_depth,
            reversal_rate=self._adaptive_entry.rolling_reversal_rate if self._adaptive_entry else 0.0,
            btc_velocity=velocity_conflict.velocity_rate,
            velocity_conflict_severity=velocity_conflict.severity,
            reversal_regime=reversal_score,
            zero_crossings_avg=zero_crossings_avg,
        )
        ml_prediction = self._ml_scorer.predict(ml_features)
        if market:
            self._pending_ml_features[market.slug] = ml_features

        ml_line = format_ml_line(
            model_trained=ml_prediction.model_trained,
            up_probability=ml_prediction.up_probability,
            confidence=ml_prediction.confidence,
            feature_contributions=ml_prediction.feature_contributions,
            scorer_summary=self._ml_scorer.get_summary(),
        )
        if indicators_text:
            indicators_text += "\n" + ml_line
        else:
            indicators_text = "## Computed Indicators\n" + ml_line

        # Inject adaptive entry reversal context
        if self._adaptive_entry is not None:
            abs_btc_move = 0.0
            if candle_open_btc is not None and snapshot.btc_price:
                abs_btc_move = abs(snapshot.btc_price.price_usd - candle_open_btc)
            reversal_ctx = self._adaptive_entry.get_ai_context(abs_btc_move=abs_btc_move)
            indicators_text = append_section(indicators_text, reversal_ctx)

        # Inject BTC trajectory, microstructure, and entry timing
        indicators_text = append_section(indicators_text, compute_btc_trajectory(list(self._shared.prefilter_history)))
        indicators_text = append_section(indicators_text, format_microstructure(self._shared.microstructure_history))
        indicators_text = append_section(
            indicators_text, compute_entry_timing_stats(self._session_trades, self._recent_resolutions)
        )

        # Reversal regime warning (score already computed above for ML)
        if _regime_result is not None:
            _rev_score, _rev_label = _regime_result
            indicators_text = append_section(
                indicators_text,
                build_reversal_regime_warning(_rev_score, _rev_label, self._shared.microstructure_history),
            )

        # Velocity-magnitude conflict warning
        indicators_text = append_section(indicators_text, build_velocity_conflict_warning(velocity_conflict))

        # Safeguard warnings
        if snapshot.btc_price and snapshot.btc_price.price_divergence is not None:
            indicators_text = append_section(
                indicators_text, build_chainlink_warning(snapshot.btc_price.price_divergence)
            )

        trend_result = next(
            (r for r in indicator_results if r.name == "Market Trend"),
            None,
        )
        if trend_result:
            indicators_text = append_section(indicators_text, build_counter_trend_advisory(trend_result.value))

        if self._shared.last_stop_loss is not None:
            sl_info = self._shared.last_stop_loss
            indicators_text = append_section(
                indicators_text, build_stop_loss_warning(sl_info.token_side, sl_info.pnl_pct)
            )

        # Two-pass screening (entry only, not exits)
        has_position = self._portfolio.up_position.shares > 0 or self._portfolio.down_position.shares > 0
        if self._config.ai.two_pass_enabled and not has_position and not extra_context:
            should_trade, screen_reason, screen_cost = await self._engine.screen(
                features,
                indicators_text=indicators_text,
                candle_open_btc=candle_open_btc,
            )
            self._portfolio.cash -= screen_cost
            self._total_api_cost += screen_cost
            self._last_cycle_api_cost = screen_cost
            self._screen_calls += 1

            if not should_trade:
                self._last_screen_passed = False
                self.last_action = f"HOLD (screen: {screen_reason[:60]})"
                self.last_reasoning = screen_reason
                # Build a lightweight decision so reasoning + screen context
                # are captured in the trade record for the dashboard
                from polybot.decision_engine.prompts import format_screening_context

                screen_input = format_screening_context(
                    features,
                    indicators_text,
                    candle_open_btc=candle_open_btc,
                )
                screen_decision = TradingDecision(
                    action=Action.HOLD,
                    order_type=OrderType.MARKET,
                    size=0.0,
                    confidence=0.0,
                    reasoning=screen_reason,
                    market_view="",
                    token_side=TokenSide.UP,
                )
                self._log_cycle(
                    cycle,
                    snapshot,
                    decision=screen_decision,
                    risk_blocked=False,
                    risk_reason="",
                    screen_input=screen_input,
                )
                return

            self._last_screen_passed = True
            self._screen_passes += 1
            # Pass screening reasoning to Sonnet — free "second opinion" context
            indicators_text += f"\n\n## Pre-Screening Note (fast model)\n{screen_reason}"

        # Full AI decision
        decision, latency_ms, api_cost = await self._engine.decide(
            features,
            feedback_context=feedback_context,
            indicators_text=indicators_text,
            ai_cycle_cost=self._last_cycle_api_cost,
            ai_session_cost=self._total_api_cost,
            candle_open_btc=candle_open_btc,
            velocity_conflict=velocity_conflict,
        )

        self._portfolio.cash -= api_cost
        self._total_api_cost += api_cost
        self._last_cycle_api_cost = api_cost
        logger.info("API cost: $%.4f (session total: $%.4f)", api_cost, self._total_api_cost)

        # Ensemble tracking: ML vs Sonnet direction agreement
        if decision.action == Action.BUY and ml_prediction.model_trained:
            self._sonnet_trades += 1
            ml_dir = "up" if ml_prediction.up_probability > 0.5 else "down"
            sonnet_dir = decision.token_side.value
            self._ml_sonnet_total += 1
            if ml_dir == sonnet_dir:
                self._ml_sonnet_agree += 1
            else:
                logger.info(
                    "Ensemble disagreement: ML=%s (%.0f%%) vs Sonnet=%s (conf=%.2f)",
                    ml_dir,
                    ml_prediction.up_probability * 100,
                    sonnet_dir,
                    decision.confidence,
                )

        # Clamp sell size to actual held shares
        held = self._portfolio.get_position(decision.token_side).shares
        decision = clamp_sell_size(decision, held)

        # Force token_side on exit triggers
        decision = force_exit_side(decision, forced_exit_side)

        # Hard confidence gate (BUY only)
        decision = apply_confidence_gate(decision, self._config.agent.min_confidence)

        # Calibration gate (BUY only)
        if decision.action == Action.BUY:
            cal = self._calibrator.check(decision.confidence)
            if cal.is_reliable and not cal.should_trade:
                logger.info(
                    "Calibration override to HOLD — stated %.2f but actual %.0f%%",
                    decision.confidence,
                    cal.calibrated_win_rate * 100,
                )
                decision = override_to_hold(
                    decision,
                    f"Calibration override: {cal.reason}. Original: {decision.reasoning[:80]}",
                )

        # Anti-hedging guard: don't buy one side while holding the other
        # When _reversal_flip_side is set, auto-close the held position instead of blocking
        if decision.action == Action.BUY:
            if decision.token_side == TokenSide.DOWN and self._portfolio.up_position.shares > 0:
                if self._reversal_flip_side:
                    closed = await self._auto_close_for_flip("up", market, time_remaining, snapshot, cycle)
                    if not closed:
                        decision = override_to_hold(
                            decision,
                            f"Reversal flip: failed to close UP position. Original: {decision.reasoning[:80]}",
                        )
                else:
                    logger.info(
                        "Anti-hedge block: skipping DOWN buy while holding %.1f UP shares",
                        self._portfolio.up_position.shares,
                    )
                    decision = override_to_hold(
                        decision,
                        f"Anti-hedge: holding UP shares, blocked DOWN buy. Original: {decision.reasoning[:80]}",
                    )
            elif decision.token_side == TokenSide.UP and self._portfolio.down_position.shares > 0:
                if self._reversal_flip_side:
                    closed = await self._auto_close_for_flip("down", market, time_remaining, snapshot, cycle)
                    if not closed:
                        decision = override_to_hold(
                            decision,
                            f"Reversal flip: failed to close DOWN position. Original: {decision.reasoning[:80]}",
                        )
                else:
                    logger.info(
                        "Anti-hedge block: skipping UP buy while holding %.1f DOWN shares",
                        self._portfolio.down_position.shares,
                    )
                    decision = override_to_hold(
                        decision,
                        f"Anti-hedge: holding DOWN shares, blocked UP buy. Original: {decision.reasoning[:80]}",
                    )

        # Anti-flip guard: block buying opposite side after selling on same candle
        if decision.action == Action.BUY and market and not self._contrarian_flip_active:
            decision = apply_anti_flip(decision, self._sold_sides.get(market.slug, set()), slug=market.slug)

        # Single-entry-per-side: block buying same side twice on same candle
        if decision.action == Action.BUY and market:
            decision = apply_single_entry(decision, self._bought_sides.get(market.slug, set()), slug=market.slug)

        # Entry price hard cap
        if decision.action == Action.BUY:
            cap_ob = down_ob if decision.token_side == TokenSide.DOWN else up_ob
            decision = apply_entry_price_cap(decision, cap_ob.best_ask or 0.5)

        # Position sizing (R/R, move magnitude, counter-trend)
        if decision.action == Action.BUY:
            target_ob = down_ob if decision.token_side == TokenSide.DOWN else up_ob
            est_fill = target_ob.best_ask or 0.5
            rr_ratio = (1.0 - est_fill) / est_fill if est_fill > 0 else 0

            btc_price_now = snapshot.btc_price.price_usd if snapshot.btc_price else None
            btc_move = 0.0
            if candle_open_btc is not None and btc_price_now is not None:
                btc_move = abs(btc_price_now - candle_open_btc)

            trend_result = next(
                (r for r in indicator_results if r.name == "Market Trend"),
                None,
            )
            trend_score = trend_result.value if trend_result is not None else None

            scale, trend_scale = compute_position_scale(rr_ratio, btc_move, trend_score, decision.token_side)
            decision = apply_position_sizing(decision, scale, trend_scale)

        # Velocity conflict sizing guard
        if decision.action == Action.BUY:
            decision = apply_velocity_conflict_scaling(decision, velocity_conflict)

        # Reversal regime sizing guard
        if decision.action == Action.BUY:
            decision = apply_reversal_regime_scaling(decision, reversal_score)

        # Shadow predictions for HOLD
        if decision.action == Action.HOLD and decision.hypothetical_direction and market:
            self._calibrator.register_shadow(
                market.slug,
                decision.hypothetical_direction,
                decision.confidence,
            )

        self.last_action = f"{decision.action.value} {decision.token_side.value} {decision.size:.1f}"
        self.last_reasoning = decision.reasoning[:120]
        self.last_token_side = decision.token_side.value

        # Post-trade risk checks
        risk_blocked = False
        risk_reason = ""
        if decision.action != Action.HOLD:
            token_position = self._portfolio.get_position(decision.token_side)
            post_checks = self._risk.post_trade_checks(
                decision,
                token_position,
                self._portfolio.cash,
                portfolio_value,
                snapshot,
            )
            post_failed = [c for c in post_checks if not c.passed]
            if post_failed:
                risk_reason = "; ".join(c.reason for c in post_failed)
                logger.warning(
                    "Post-trade risk blocked %s %s: %s", decision.action.value, decision.token_side.value, risk_reason
                )
                self.last_action = f"BLOCKED ({decision.action.value} {decision.token_side.value})"
                self.last_risk_status = risk_reason
                risk_blocked = True

        # Execute (paper_fill is only set in live mode for shadow comparison)
        fill = None
        paper_fill = None
        live_result = None  # LiveOrderResult telemetry (live mode only)
        if not risk_blocked and decision.action != Action.HOLD:
            target_ob = down_ob if decision.token_side == TokenSide.DOWN else up_ob

            if self._live_mode and self._live_engine and decision.order_type == OrderType.MARKET:
                # Live mode: execute on CLOB + shadow paper sim
                live_result = await self._live_engine.execute(decision, target_ob)
                fill = live_result.fill if live_result else None
                paper_fill = self._exec_sim.execute(decision, target_ob)

                # Apply shadow paper fill to shadow portfolio
                if paper_fill and self._shadow_portfolio:
                    self._shadow_portfolio.apply_fill(paper_fill, decision.token_side)

                if fill and paper_fill:
                    drift_pct = (
                        ((fill.fill_price - paper_fill.fill_price) / paper_fill.fill_price * 100)
                        if paper_fill.fill_price > 0
                        else 0
                    )
                    logger.info(
                        "Live fill $%.4f vs Paper fill $%.4f (drift %+.1f%%)",
                        fill.fill_price,
                        paper_fill.fill_price,
                        drift_pct,
                    )
                elif not fill and paper_fill:
                    logger.info(
                        "Live SKIPPED but Paper would have filled at $%.4f",
                        paper_fill.fill_price,
                    )

                # Mark unfilled live trades as blocked for dashboard visibility
                if fill is None and not risk_blocked:
                    risk_blocked = True
                    risk_reason = self._live_engine.last_skip_reason or "limit order timeout"
            elif decision.order_type == OrderType.MARKET:
                # Paper mode: execute on simulator only
                fill = self._exec_sim.execute(decision, target_ob)
            elif decision.order_type == OrderType.LIMIT:
                self._orderbook.add_order(decision)

        # Apply fill
        if fill:
            self._portfolio.apply_fill(fill, decision.token_side)
            token_pos = self._portfolio.get_position(decision.token_side)
            realized = 0.0
            if fill.side.value == "SELL":
                realized = (fill.fill_price - token_pos.avg_entry_price) * fill.size
            self._risk.record_trade(realized, fill.fee_amount)

            if decision.action == Action.BUY and market:
                self._calibrator.register_trade(
                    slug=market.slug,
                    confidence=decision.confidence,
                    token_side=decision.token_side.value,
                    entry_price=fill.fill_price,
                )
                # Safeguard #2: Track bought side to block double-entry
                self._bought_sides.setdefault(market.slug, set()).add(
                    decision.token_side.value.upper(),
                )
                # Store entry context for dynamic SL/TP
                btc_move_now = 0.0
                if candle_open_btc and snapshot.btc_price:
                    btc_move_now = snapshot.btc_price.price_usd - candle_open_btc
                self._shared.entry_context[decision.token_side.value] = EntryContext(
                    entry_price=fill.fill_price,
                    entry_time=time.time(),
                    ml_up_probability=ml_prediction.up_probability if ml_prediction.model_trained else 0.5,
                    ml_confidence=ml_prediction.confidence if ml_prediction.model_trained else "neutral",
                    btc_move_at_entry=btc_move_now,
                    reversal_rate_at_entry=self._shared.reversal_rate,
                    confidence_at_entry=decision.confidence,
                )

            if decision.action == Action.SELL and market:
                self._exit_tracker.register_exit(
                    slug=market.slug,
                    token_side=decision.token_side.value,
                    entry_price=token_pos.avg_entry_price,
                    exit_price=fill.fill_price,
                    exit_size=fill.size,
                    time_remaining=time_remaining,
                )
                # Track sold side to block side-flips on this candle
                self._sold_sides.setdefault(market.slug, set()).add(
                    decision.token_side.value,
                )
                # Clear entry context for dynamic SL/TP
                self._shared.entry_context.pop(decision.token_side.value, None)
                self._shared.dynamic_sl.pop(decision.token_side.value, None)
                self._shared.dynamic_tp.pop(decision.token_side.value, None)

        # Post-fill mark-to-market
        if up_mid is not None:
            self._portfolio.mark_to_market(up_mid, down_mid)
        portfolio_value = self._portfolio.total_value_at_market(up_mid or 0.5, down_mid)
        self._risk.update_portfolio_peak(portfolio_value)
        self.last_risk_status = "HALTED" if self._risk.state.is_halted else "OK"

        # Log
        self._log_cycle(
            cycle,
            snapshot,
            decision=decision,
            latency_ms=latency_ms,
            fill=fill,
            risk_blocked=risk_blocked,
            risk_reason=risk_reason,
            paper_fill=paper_fill,
            live_result=live_result,
        )

        self._record_ai_call_time()

    def _record_ai_call_time(self) -> None:
        """Record the time of the last AI call for cooldown tracking."""
        self._shared.ai_last_call_time = time.time()

    def _log_cycle(
        self,
        cycle,
        snapshot,
        decision=None,
        latency_ms=0.0,
        fill=None,
        risk_blocked=False,
        risk_reason="",
        paper_fill=None,
        screen_input=None,
        live_result=None,
    ) -> None:
        """Log a cycle to trade log and update trade history."""
        record = build_trade_record(
            cycle=cycle,
            snapshot=snapshot,
            portfolio=self._portfolio,
            risk_state=self._risk.state,
            market=self._shared.current_market,
            decision=decision,
            latency_ms=latency_ms,
            fill=fill,
            risk_blocked=risk_blocked,
            risk_reason=risk_reason,
            paper_fill=paper_fill,
            live_result=live_result,
            screen_passed=self._last_screen_passed,
            screen_input=screen_input,
            last_cycle_api_cost=self._last_cycle_api_cost,
            signal_type=self._shared.signal_type,
            reversal_rate=self._shared.reversal_rate,
        )

        self._trade_log.write(record)

        # Queue decision for SQLite analytics
        if self._datastore is not None and self._datastore.current_candle_id is not None:
            row = build_decision_row(
                datastore_candle_id=self._datastore.current_candle_id,
                cycle=cycle,
                snapshot=snapshot,
                portfolio=self._portfolio,
                feature_config=self._feature_config,
                session_wins=self.session_wins,
                session_losses=self.session_losses,
                candle_open_btc=self._shared.candle_open_btc,
                decision=decision,
                latency_ms=latency_ms,
                fill=fill,
                risk_blocked=risk_blocked,
                risk_reason=risk_reason,
                last_cycle_api_cost=self._last_cycle_api_cost,
                live_result=live_result,
            )
            self._datastore.queue_decision(row)

        self._recent_trades.append(record)
        if len(self._recent_trades) > 50:
            del self._recent_trades[:-50]
        self._session_trades.append(record)

        # Push trade event to WS clients
        if self.on_trade_callback is not None:
            try:
                import asyncio

                asyncio.get_event_loop().create_task(self.on_trade_callback(record))
            except Exception:
                logger.debug("on_trade_callback failed", exc_info=True)
