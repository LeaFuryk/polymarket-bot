"""AI decision task — event-driven, makes trades when triggered.

Waits on ai_trigger_event (entry opportunity) or exit_trigger_queue
(stop-loss/take-profit). Contains the core decision logic extracted
from the old _run_cycle().
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from polybot.calibration import ConfidenceCalibrator
from polybot.config import AppConfig
from polybot.decision_engine.engine import DecisionEngine
from polybot.exit_tracker import ExitTracker
from polybot.indicators import (
    FeatureConfig,
    IndicatorResult,
    SessionContext,
    compute_indicators,
    format_indicators,
)
from polybot.knowledge import KnowledgeManager
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
from polybot.adaptive_entry import AdaptiveEntryTracker
from polybot.prefilter import PreFilter
from polybot.shared_state import PreFilterSnapshot
from polybot.resolution import ResolutionTracker
from polybot.risk.manager import RiskManager
from polybot.shared_state import SharedState
from polybot.simulator.engine import ExecutionSimulator
from polybot.simulator.orderbook import SimulatedOrderBook
from polybot.simulator.portfolio import Portfolio
from polybot.logging.trade_log import TradeLog

logger = logging.getLogger(__name__)


def _compute_btc_trajectory(history: list[PreFilterSnapshot]) -> str | None:
    """Compute BTC velocity and peak-drawback from prefilter snapshots.

    Returns a compact trajectory section for the AI prompt, or None
    if insufficient data.
    """
    if len(history) < 15:
        return None

    moves = [s.btc_move_from_open for s in history]

    # Velocity: rate of change over last ~10s vs ~20-30s ago
    recent = moves[-10:]
    earlier = moves[-30:-20] if len(moves) >= 30 else moves[:10]

    if len(recent) < 2 or len(earlier) < 2:
        return None

    current_vel = (recent[-1] - recent[0]) / len(recent)
    earlier_vel = (earlier[-1] - earlier[0]) / len(earlier)

    # Peak drawback: furthest BTC move vs current
    current_move = moves[-1]
    # Find peak in the direction of the current move
    if current_move >= 0:
        peak = max(moves)
        drawback = peak - current_move
    else:
        peak = min(moves)
        drawback = abs(peak) - abs(current_move)

    # Format
    vel_dir = "accelerating" if abs(current_vel) > abs(earlier_vel) * 1.2 else "decelerating" if abs(current_vel) < abs(earlier_vel) * 0.8 else "steady"
    parts = [
        f"## BTC Trajectory (intra-candle)",
        f"- Velocity: ${current_vel:+.1f}/s ({vel_dir}, was ${earlier_vel:+.1f}/s)",
    ]
    if abs(drawback) >= 5.0:
        parts.append(f"- Peak drawback: peak was ${peak:+,.0f} from open, now ${current_move:+,.0f} (pulled back ${drawback:.0f})")
    else:
        parts.append(f"- No significant drawback (peak ${peak:+,.0f}, current ${current_move:+,.0f})")

    return "\n".join(parts)


def _format_microstructure(history: list) -> str | None:
    """Format cross-candle microstructure summary for the AI prompt.

    Takes SharedState.microstructure_history (list of CandleMicrostructure).
    Returns None if insufficient data (< 2 candles).
    """
    if len(history) < 2:
        return None

    recent = history[-1]
    prev = history[-2]

    # Spread trend
    spread_up_delta = recent.avg_spread_up - prev.avg_spread_up
    spread_down_delta = recent.avg_spread_down - prev.avg_spread_down
    spread_dir = "widening" if (spread_up_delta + spread_down_delta) > 0.002 else "narrowing" if (spread_up_delta + spread_down_delta) < -0.002 else "stable"

    # Volatility trend (BTC range per candle)
    ranges = [h.btc_range for h in history]
    avg_range = sum(ranges) / len(ranges)
    range_dir = "increasing" if recent.btc_range > avg_range * 1.2 else "decreasing" if recent.btc_range < avg_range * 0.8 else "stable"

    parts = [
        f"## Cross-Candle Microstructure (last {len(history)} candles)",
        f"- Spreads: {spread_dir} (UP avg {recent.avg_spread_up:.2%}, DOWN avg {recent.avg_spread_down:.2%})",
        f"- BTC intra-candle range: ${recent.btc_range:.0f} ({range_dir}, avg ${avg_range:.0f})",
    ]

    return "\n".join(parts)


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

        # Optional SQLite analytics
        self._datastore = None  # set by agent if sqlite_enabled

        # Shared mutable state from agent
        self._recent_resolutions = recent_resolutions
        self._recent_trades = recent_trades
        self._session_trades = session_trades
        self._pending_ml_features = pending_ml_features

        # Track sold sides per candle to block side-flips (sell A → buy B)
        self._sold_sides: dict[str, set[str]] = {}  # slug → {UP, DOWN}

        # Internal counters (synced to agent via shared references)
        self._cycle_count = 0
        self._total_api_cost: float = 0.0
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

    async def run(self) -> None:
        """Main loop — waits for triggers, makes decisions."""
        logger.info("AIDecision task started")
        while not self._shared.shutdown:
            try:
                # Wait for either AI trigger or exit trigger
                trigger_type = await self._wait_for_trigger()
                if trigger_type is None:
                    continue

                if self._shared.rotation_in_progress:
                    continue

                if trigger_type == "entry":
                    await self._handle_entry_trigger()
                elif trigger_type == "exit":
                    await self._handle_exit_trigger()

            except Exception:
                logger.exception("AIDecision error")
                await asyncio.sleep(1)

        logger.info("AIDecision task stopped")

    async def _wait_for_trigger(self) -> str | None:
        """Wait for an entry or exit trigger. Returns trigger type or None."""
        # Check exit queue first (non-blocking)
        try:
            exit_signal = self._shared.exit_trigger_queue.get_nowait()
            self._pending_exit = exit_signal
            return "exit"
        except asyncio.QueueEmpty:
            pass

        # Wait for entry trigger with timeout (so we can check exit queue periodically)
        try:
            await asyncio.wait_for(
                self._shared.ai_trigger_event.wait(),
                timeout=2.0,
            )
            self._shared.ai_trigger_event.clear()
            return "entry"
        except asyncio.TimeoutError:
            return None

    async def _handle_entry_trigger(self) -> None:
        """Handle an entry opportunity trigger from the market monitor."""
        self._cycle_count += 1
        cycle = self._cycle_count
        logger.info("=== AI Decision Cycle %d (trigger: %s) ===", cycle, self._shared.ai_trigger_reason)

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
            self._record_ai_call_time()
            return

        await self._run_ai_decision(cycle, snapshot, market, time_remaining, portfolio_value)

    async def _handle_exit_trigger(self) -> None:
        """Handle a stop-loss/take-profit exit trigger from position monitor."""
        exit_signal = self._pending_exit
        self._cycle_count += 1
        cycle = self._cycle_count
        token_side_str = exit_signal.get("token_side", "up")
        reason = exit_signal.get("reason", "unknown")
        pnl_pct = exit_signal.get("pnl_pct", 0.0)
        logger.info(
            "=== AI Exit Decision Cycle %d (SL/TP: %s %s, P&L=%.1f%%) ===",
            cycle, token_side_str, reason, pnl_pct * 100,
        )

        # Exit trigger cooldown: skip if on cooldown and not a true emergency (> -30%)
        cooldown = self._config.monitor.ai_cooldown_seconds
        elapsed = time.time() - self._shared.ai_last_call_time
        if elapsed < cooldown and pnl_pct > -0.30:
            logger.info(
                "Exit trigger on cooldown (%.0fs < %.0fs, pnl=%.1f%% > -30%%) — skipping",
                elapsed, cooldown, pnl_pct * 100,
            )
            return

        snapshot = self._shared.latest_snapshot
        market = self._shared.current_market
        if snapshot is None or market is None:
            return

        time_remaining = market.time_remaining()

        # Guard against selling winners near expiry: if position is profitable
        # and BTC direction matches position side and < 120s remaining, skip exit
        if pnl_pct > 0 and time_remaining < 120:
            btc_price_now = snapshot.btc_price.price_usd if snapshot.btc_price else None
            candle_open = self._shared.candle_open_btc
            if btc_price_now is not None and candle_open is not None:
                btc_diff = btc_price_now - candle_open
                btc_favors_up = btc_diff >= 0
                position_is_up = token_side_str.lower() == "up"
                direction_matches = (position_is_up and btc_favors_up) or (
                    not position_is_up and not btc_favors_up
                )
                if direction_matches:
                    logger.info(
                        "Skipping exit on winning %s position (P&L=%.1f%%, BTC %s$%.0f, "
                        "%.0fs left) — let it ride to resolution",
                        token_side_str, pnl_pct * 100,
                        "+" if btc_diff >= 0 else "", btc_diff, time_remaining,
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
        exit_context = (
            f"\n## EXIT TRIGGER\n"
            f"- Token: {token_side_str.upper()}\n"
            f"- Reason: {reason}\n"
            f"- Current P&L: {pnl_pct:+.1%}\n"
            f"- Action needed: Evaluate whether to SELL this position NOW.\n"
        )

        await self._run_ai_decision(
            cycle, snapshot, market, time_remaining, portfolio_value,
            extra_context=exit_context,
            forced_exit_side=token_side_str,
        )

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
        )
        ml_prediction = self._ml_scorer.predict(ml_features)
        if market:
            self._pending_ml_features[market.slug] = ml_features

        if ml_prediction.model_trained:
            # Show top 3 feature drivers so the AI knows WHY the ML predicts a direction
            top_feats = sorted(
                ml_prediction.feature_contributions.items(),
                key=lambda x: abs(x[1]),
                reverse=True,
            )[:3]
            drivers = ", ".join(f"{n}: {v:+.2f}" for n, v in top_feats)
            ml_line = (
                f"- ML Baseline: {ml_prediction.up_probability:.0%} UP probability "
                f"({ml_prediction.confidence}) — drivers: {drivers}"
            )
        else:
            ml_line = f"- ML Baseline: {self._ml_scorer.get_summary()}"
        if indicators_text:
            indicators_text += "\n" + ml_line
        else:
            indicators_text = "## Computed Indicators\n" + ml_line

        # Inject adaptive entry reversal context (visible to both Haiku screen and Sonnet)
        if self._adaptive_entry is not None:
            reversal_ctx = self._adaptive_entry.get_ai_context()
            if reversal_ctx:
                indicators_text = indicators_text + "\n\n" + reversal_ctx if indicators_text else reversal_ctx

        # Inject BTC trajectory (velocity + peak drawback) from prefilter snapshots
        trajectory_ctx = _compute_btc_trajectory(list(self._shared.prefilter_history))
        if trajectory_ctx:
            indicators_text = indicators_text + "\n\n" + trajectory_ctx if indicators_text else trajectory_ctx

        # Cross-candle microstructure memory
        micro_ctx = _format_microstructure(self._shared.microstructure_history)
        if micro_ctx:
            indicators_text = indicators_text + "\n\n" + micro_ctx if indicators_text else micro_ctx

        # Two-pass screening (entry only, not exits)
        has_position = (
            self._portfolio.up_position.shares > 0
            or self._portfolio.down_position.shares > 0
        )
        if self._config.ai.two_pass_enabled and not has_position and not extra_context:
            should_trade, screen_reason, screen_cost = await self._engine.screen(
                features, indicators_text=indicators_text,
            )
            self._portfolio.cash -= screen_cost
            self._total_api_cost += screen_cost
            self._last_cycle_api_cost = screen_cost
            self._screen_calls += 1

            if not should_trade:
                self.last_action = f"HOLD (screen: {screen_reason[:60]})"
                self.last_reasoning = screen_reason
                self._log_cycle(cycle, snapshot, risk_blocked=False, risk_reason="")
                self._record_ai_call_time()
                return

            self._screen_passes += 1
            # Pass screening reasoning to Sonnet — free "second opinion" context
            indicators_text += f"\n\n## Pre-Screening Note (fast model)\n{screen_reason}"

        # Full AI decision
        decision, latency_ms, api_cost = await self._engine.decide(
            features, feedback_context=feedback_context, indicators_text=indicators_text,
            ai_cycle_cost=self._last_cycle_api_cost, ai_session_cost=self._total_api_cost,
            candle_open_btc=candle_open_btc,
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
                    ml_dir, ml_prediction.up_probability * 100,
                    sonnet_dir, decision.confidence,
                )

        # Force token_side on exit triggers: don't trust AI's token_side for SELLs
        # This prevents the anti-flip guard from tracking the wrong side
        if forced_exit_side and decision.action == Action.SELL:
            correct_side = TokenSide(forced_exit_side.lower())
            if decision.token_side != correct_side:
                logger.warning(
                    "Forcing exit token_side: AI said %s but exit trigger is %s",
                    decision.token_side.value, correct_side.value,
                )
                decision = TradingDecision(
                    action=decision.action,
                    order_type=decision.order_type,
                    size=decision.size,
                    confidence=decision.confidence,
                    reasoning=decision.reasoning,
                    market_view=decision.market_view,
                    token_side=correct_side,
                    hypothetical_direction=decision.hypothetical_direction,
                    confidence_drivers=decision.confidence_drivers,
                )

        # Hard confidence gate (BUY only)
        min_conf = self._config.agent.min_confidence
        if decision.action == Action.BUY and decision.confidence < min_conf:
            logger.info(
                "Overriding %s to HOLD — confidence %.2f < %.2f",
                decision.action.value, decision.confidence, min_conf,
            )
            decision = TradingDecision(
                action=Action.HOLD,
                order_type=OrderType.MARKET,
                size=0.0,
                confidence=decision.confidence,
                reasoning=f"Overridden: confidence {decision.confidence:.2f} below {min_conf}. "
                          f"Original: {decision.reasoning[:100]}",
                market_view=decision.market_view,
                token_side=decision.token_side,
                hypothetical_direction=decision.hypothetical_direction,
                confidence_drivers=decision.confidence_drivers,
            )

        # Calibration gate (BUY only)
        if decision.action == Action.BUY:
            cal = self._calibrator.check(decision.confidence)
            if cal.is_reliable and not cal.should_trade:
                logger.info(
                    "Calibration override to HOLD — stated %.2f but actual %.0f%%",
                    decision.confidence, cal.calibrated_win_rate * 100,
                )
                decision = TradingDecision(
                    action=Action.HOLD,
                    order_type=OrderType.MARKET,
                    size=0.0,
                    confidence=decision.confidence,
                    reasoning=f"Calibration override: {cal.reason}. Original: {decision.reasoning[:80]}",
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                    hypothetical_direction=decision.hypothetical_direction,
                    confidence_drivers=decision.confidence_drivers,
                )

        # Anti-hedging guard: don't buy one side while holding the other
        if decision.action == Action.BUY:
            if decision.token_side == TokenSide.DOWN and self._portfolio.up_position.shares > 0:
                logger.info(
                    "Anti-hedge block: skipping DOWN buy while holding %.1f UP shares",
                    self._portfolio.up_position.shares,
                )
                decision = TradingDecision(
                    action=Action.HOLD,
                    order_type=OrderType.MARKET,
                    size=0.0,
                    confidence=decision.confidence,
                    reasoning=f"Anti-hedge: holding UP shares, blocked DOWN buy. Original: {decision.reasoning[:80]}",
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                    hypothetical_direction=decision.hypothetical_direction,
                    confidence_drivers=decision.confidence_drivers,
                )
            elif decision.token_side == TokenSide.UP and self._portfolio.down_position.shares > 0:
                logger.info(
                    "Anti-hedge block: skipping UP buy while holding %.1f DOWN shares",
                    self._portfolio.down_position.shares,
                )
                decision = TradingDecision(
                    action=Action.HOLD,
                    order_type=OrderType.MARKET,
                    size=0.0,
                    confidence=decision.confidence,
                    reasoning=f"Anti-hedge: holding DOWN shares, blocked UP buy. Original: {decision.reasoning[:80]}",
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                    hypothetical_direction=decision.hypothetical_direction,
                    confidence_drivers=decision.confidence_drivers,
                )

        # Anti-flip guard: block buying opposite side after selling on same candle
        # Same-side re-entry (adding back) is still allowed
        if decision.action == Action.BUY and market:
            sold = self._sold_sides.get(market.slug, set())
            opposite = "UP" if decision.token_side == TokenSide.DOWN else "DOWN"
            if opposite in sold:
                logger.info(
                    "Anti-flip block: already sold %s on %s, blocking %s buy",
                    opposite, market.slug, decision.token_side.value,
                )
                decision = TradingDecision(
                    action=Action.HOLD,
                    order_type=OrderType.MARKET,
                    size=0.0,
                    confidence=decision.confidence,
                    reasoning=f"Anti-flip: sold {opposite} on this candle, blocked {decision.token_side.value} buy. Original: {decision.reasoning[:80]}",
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                    hypothetical_direction=decision.hypothetical_direction,
                    confidence_drivers=decision.confidence_drivers,
                )

        # Extended R/R position sizing (no hard block)
        if decision.action == Action.BUY:
            target_ob = down_ob if decision.token_side == TokenSide.DOWN else up_ob
            est_fill = target_ob.best_ask or 0.5
            reward = 1.0 - est_fill
            risk_val = est_fill
            rr_ratio = reward / risk_val if risk_val > 0 else 0

            # R/R scale — gentle nudge only (0.75-1.0 range)
            # Data shows cheap entries (high R/R) often lose — they're contrarian traps.
            # Expensive entries (low R/R) win ~85% because price reflects conviction.
            # So we don't reward cheap entries with bigger positions.
            if rr_ratio >= 1.0:
                rr_scale = 1.0
            elif rr_ratio >= 0.3:
                rr_scale = 0.75 + 0.25 * (rr_ratio - 0.3) / 0.7  # 75%-100%
            else:
                rr_scale = 0.75  # minimum 75%

            # Move-magnitude scaling (raised floors — small moves still get decent size)
            move_scale = 1.0
            btc_price_now = snapshot.btc_price.price_usd if snapshot.btc_price else None
            btc_move = 0.0
            if candle_open_btc is not None and btc_price_now is not None:
                btc_move = abs(btc_price_now - candle_open_btc)
                if btc_move < 10:
                    move_scale = 0.80
                elif btc_move < 30:
                    move_scale = 0.90
                elif btc_move < 60:
                    move_scale = 1.0

            # Counter-trend size scaling (trend-aware position reduction)
            trend_result = next(
                (r for r in indicator_results if r.name == "Market Trend"), None,
            )
            trend_scale = 1.0
            if trend_result is not None:
                trend_score = trend_result.value
                is_counter = (
                    (decision.token_side == TokenSide.DOWN and trend_score > 0.3)
                    or (decision.token_side == TokenSide.UP and trend_score < -0.3)
                )
                if is_counter:
                    abs_score = abs(trend_score)
                    trend_scale = 0.50 if abs_score >= 0.7 else 0.70
                    trend_label = (
                        "STRONG BULLISH" if trend_score >= 0.5
                        else "BULLISH" if trend_score >= 0.2
                        else "NEUTRAL" if trend_score > -0.2
                        else "BEARISH" if trend_score > -0.5
                        else "STRONG BEARISH"
                    )
                    logger.info(
                        "Counter-trend sizing: %s in %s trend (score=%.2f) → %.0f%%",
                        decision.token_side.value, trend_label, trend_score,
                        trend_scale * 100,
                    )

            combined_scale = rr_scale * move_scale * trend_scale
            if combined_scale < 1.0:
                original_size = decision.size
                scaled_size = round(decision.size * combined_scale, 1)
                if scaled_size >= 1.0:
                    decision = TradingDecision(
                        action=decision.action,
                        order_type=decision.order_type,
                        size=scaled_size,
                        confidence=decision.confidence,
                        reasoning=decision.reasoning,
                        market_view=decision.market_view,
                        token_side=decision.token_side,
                        limit_price=decision.limit_price,
                    )
                    logger.info(
                        "Position sizing: %.1f → %.1f (R/R=%.2f×%.0f%%, move=$%.0f×%.0f%%)",
                        original_size, scaled_size, rr_ratio, rr_scale * 100,
                        btc_move, move_scale * 100,
                    )

            # Enforce minimum position size (lower floor for counter-trend)
            min_shares = 20 if trend_scale < 1.0 else 40
            if decision.size < min_shares:
                logger.info(
                    "Min size floor: %.1f → %d shares%s",
                    decision.size, min_shares,
                    " (counter-trend)" if trend_scale < 1.0 else "",
                )
                decision = TradingDecision(
                    action=decision.action,
                    order_type=decision.order_type,
                    size=min_shares,
                    confidence=decision.confidence,
                    reasoning=decision.reasoning,
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                    limit_price=decision.limit_price,
                )

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
                decision, token_position,
                self._portfolio.cash, portfolio_value, snapshot,
            )
            post_failed = [c for c in post_checks if not c.passed]
            if post_failed:
                risk_reason = "; ".join(c.reason for c in post_failed)
                logger.warning("Post-trade risk blocked %s %s: %s",
                               decision.action.value, decision.token_side.value, risk_reason)
                self.last_action = f"BLOCKED ({decision.action.value} {decision.token_side.value})"
                self.last_risk_status = risk_reason
                risk_blocked = True

        # Execute
        fill = None
        if not risk_blocked and decision.action != Action.HOLD:
            target_ob = down_ob if decision.token_side == TokenSide.DOWN else up_ob
            if decision.order_type == OrderType.MARKET:
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

        # Post-fill mark-to-market
        if up_mid is not None:
            self._portfolio.mark_to_market(up_mid, down_mid)
        portfolio_value = self._portfolio.total_value_at_market(up_mid or 0.5, down_mid)
        self._risk.update_portfolio_peak(portfolio_value)
        self.last_risk_status = "HALTED" if self._risk.state.is_halted else "OK"

        # Log
        self._log_cycle(
            cycle, snapshot,
            decision=decision, latency_ms=latency_ms,
            fill=fill, risk_blocked=risk_blocked, risk_reason=risk_reason,
        )

        self._record_ai_call_time()

    def _record_ai_call_time(self) -> None:
        """Record the time of the last AI call for cooldown tracking."""
        self._shared.ai_last_call_time = time.time()

    def _log_cycle(
        self, cycle, snapshot, decision=None, latency_ms=0.0,
        fill=None, risk_blocked=False, risk_reason="",
    ) -> None:
        """Log a cycle to trade log and update trade history."""
        ob = snapshot.orderbook
        pos = self._portfolio.position
        mid = ob.midpoint
        down_mid = snapshot.down_orderbook.midpoint

        record = TradeRecord(
            cycle_number=cycle,
            midpoint=ob.midpoint,
            spread=ob.spread,
            spread_pct=ob.spread_pct,
            best_bid=ob.best_bid,
            best_ask=ob.best_ask,
            bid_depth=ob.bid_depth,
            ask_depth=ob.ask_depth,
            last_trade_price=snapshot.last_trade_price,
            btc_price_usd=snapshot.btc_price.price_usd if snapshot.btc_price else None,
            volume_24h=snapshot.volume_24h,
            position_shares=pos.shares,
            position_avg_entry=pos.avg_entry_price,
            cash=self._portfolio.cash,
            portfolio_value=self._portfolio.total_value_at_market(mid or 0.5, down_mid),
            realized_pnl=pos.realized_pnl,
            unrealized_pnl=pos.unrealized_pnl,
            daily_pnl=self._risk.state.daily_pnl,
            risk_halted=self._risk.state.is_halted,
            risk_blocked=risk_blocked,
            risk_block_reason=risk_reason,
        )

        market = self._shared.current_market
        if market:
            record.candle_slug = market.slug
            record.extra["time_remaining"] = market.time_remaining()

        if decision:
            record.action = decision.action
            record.order_type = decision.order_type
            record.token_side = decision.token_side
            record.decision_size = decision.size
            record.limit_price = decision.limit_price
            record.confidence = decision.confidence
            record.reasoning = decision.reasoning
            record.market_view = decision.market_view
            record.ai_latency_ms = latency_ms
            record.ai_cost = self._last_cycle_api_cost
            if decision.hypothetical_direction:
                record.extra["hypothetical_direction"] = decision.hypothetical_direction
            if decision.confidence_drivers:
                record.extra["confidence_drivers"] = decision.confidence_drivers

        if fill:
            record.fill_price = fill.fill_price
            record.fill_size = fill.size
            record.slippage_bps = fill.slippage_bps
            record.fee_amount = fill.fee_amount

        self._trade_log.write(record)

        # Queue decision for SQLite analytics
        if self._datastore is not None and self._datastore.current_candle_id is not None:
            self._queue_decision(cycle, snapshot, decision, latency_ms, fill, risk_blocked, risk_reason)

        self._recent_trades.append(record)
        if len(self._recent_trades) > 50:
            del self._recent_trades[:-50]
        self._session_trades.append(record)

    def _queue_decision(
        self, cycle, snapshot, decision=None, latency_ms=0.0,
        fill=None, risk_blocked=False, risk_reason="",
    ) -> None:
        """Build a DecisionRow and queue it for SQLite analytics."""
        import json
        from polybot.datastore import DecisionRow

        # Compute indicators for the decision context
        indicators_dict: dict = {}
        try:
            self._feature_config.load()
            session_ctx = SessionContext(
                wins=self.session_wins,
                losses=self.session_losses,
                candle_open_btc=self._shared.candle_open_btc,
            )
            results = compute_indicators(snapshot, self._feature_config, session_ctx)
            indicators_dict = {
                r.name: {"value": r.value, "label": r.label}
                for r in results
            }
        except Exception:
            logger.debug("Indicator computation failed for decision", exc_info=True)

        row = DecisionRow(
            candle_id=self._datastore.current_candle_id,
            timestamp=time.time(),
            cycle=cycle,
            trigger_type="entry",
            action=decision.action.value if decision else "HOLD",
            token_side=decision.token_side.value if decision else "up",
            confidence=decision.confidence if decision else 0.0,
            reasoning=decision.reasoning if decision else "",
            market_view=decision.market_view if decision else "",
            decision_size=decision.size if decision else 0.0,
            fill_price=fill.fill_price if fill else None,
            fill_size=fill.size if fill else None,
            slippage_bps=fill.slippage_bps if fill else None,
            fee_amount=fill.fee_amount if fill else 0.0,
            risk_blocked=risk_blocked,
            risk_reason=risk_reason,
            cash=self._portfolio.cash,
            portfolio_value=self._portfolio.total_value,
            up_shares=self._portfolio.up_position.shares,
            down_shares=self._portfolio.down_position.shares,
            ai_cost=self._last_cycle_api_cost,
            ai_latency_ms=latency_ms,
            indicators_json=json.dumps(indicators_dict) if indicators_dict else "{}",
        )
        self._datastore.queue_decision(row)
