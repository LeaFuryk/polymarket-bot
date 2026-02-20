"""Core trading agent — orchestrates the decision loop with dynamic market discovery."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from pathlib import Path

from rich.live import Live
from rich.table import Table
from rich.text import Text

from polybot.calibration import ConfidenceCalibrator
from polybot.config import AppConfig
from polybot.exit_tracker import ExitTracker
from polybot.decision_engine.engine import DecisionEngine
from polybot.indicators import (
    FeatureConfig,
    SessionContext,
    compute_indicators,
    format_indicators,
)
from polybot.knowledge import KnowledgeManager
from polybot.ml_scorer import MLScorer
from polybot.prefilter import PreFilter
from polybot.logging.trade_log import TradeLog
from polybot.market_data.discovery import MarketDiscovery
from polybot.market_data.provider import MarketDataProvider
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
from polybot.resolution import ResolutionTracker
from polybot.risk.manager import RiskManager
from polybot.simulator.engine import ExecutionSimulator
from polybot.simulator.orderbook import SimulatedOrderBook
from polybot.simulator.portfolio import Portfolio

logger = logging.getLogger(__name__)


def _setup_logging(config: AppConfig) -> None:
    """Configure structured logging with console + file output."""
    log_dir = Path(config.logging.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler
    fh = logging.FileHandler(log_dir / "polybot.log")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler (only if dashboard is off — dashboard replaces stdout)
    if not config.logging.dashboard_enabled:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(fmt)
        root.addHandler(ch)


def _compute_pnl_from_trades(trades: list[dict], winner: str) -> float:
    """Reconstruct PnL for an unresolved candle from its logged trades."""
    up_shares = 0.0
    up_cost = 0.0
    down_shares = 0.0
    down_cost = 0.0

    for t in trades:
        if t.get("risk_blocked") or not t.get("fill_price"):
            continue
        size = t.get("fill_size") or t.get("size") or t.get("decision_size") or 0
        price = t["fill_price"]
        side = t.get("token_side", "up")
        action = t.get("action", "HOLD")

        if action == "BUY":
            if side == "up":
                up_shares += size
                up_cost += size * price
            else:
                down_shares += size
                down_cost += size * price
        elif action == "SELL":
            if side == "up":
                up_shares -= size
                up_cost -= size * price
            else:
                down_shares -= size
                down_cost -= size * price

    # Settlement: winning token pays $1, losing pays $0
    if winner == "up":
        pnl = (up_shares * 1.0 - up_cost) + (0 - down_cost)
    else:
        pnl = (0 - up_cost) + (down_shares * 1.0 - down_cost)

    return pnl


class TradingAgent:
    """Main trading loop — glues together all sub-components with market rotation."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._shutdown = False

        # Sub-components
        self._discovery = MarketDiscovery(config)
        self._market_data = MarketDataProvider(config)
        self._decision_engine = DecisionEngine(config.ai)
        self._execution_sim = ExecutionSimulator(config.simulator)
        self._orderbook = SimulatedOrderBook(config.simulator)
        self._portfolio = Portfolio(config.agent.initial_cash)
        self._risk = RiskManager(config.risk, config.agent.initial_cash)
        self._trade_log = TradeLog(config.logging)

        # Resolution tracking
        self._resolution_tracker = ResolutionTracker(
            self._market_data.btc_feed,
            rest_client=self._market_data._rest,
        )

        # Rules-based pre-filter (skips AI on obvious HOLDs)
        self._prefilter = PreFilter()

        # Confidence calibration (tracks stated vs actual win rates)
        self._calibrator = ConfidenceCalibrator(
            data_dir=Path(config.logging.log_dir),
        )

        # Exit strategy tracker (what-if analysis for SELL decisions)
        self._exit_tracker = ExitTracker(
            data_dir=Path(config.logging.log_dir),
        )

        # ML scorer (logistic regression baseline)
        self._ml_scorer = MLScorer(
            data_dir=Path(config.logging.log_dir),
        )

        # Knowledge / feedback learning
        self._knowledge_manager = KnowledgeManager(config.logging.knowledge_dir, config.ai)
        self._feature_config = FeatureConfig(Path(config.logging.knowledge_dir).parent / "feature_config.json")
        self._recent_resolutions: list[ResolutionRecord] = []
        self._recent_trades: list[TradeRecord] = []
        self._resolutions_since_reflection: int = 0

        # Restore persisted state
        self._state_path = Path(config.logging.log_dir) / "agent_state.json"
        self._load_agent_state()

        # Current candle market
        self._current_market: CandleMarket | None = None

        # Dashboard state
        self._last_action = "—"
        self._last_reasoning = ""
        self._last_risk_status = "OK"
        self._last_token_side = ""

        # Session resolution stats
        self._session_wins = 0
        self._session_losses = 0
        self._session_resolution_pnl = 0.0
        self._last_resolution: ResolutionRecord | None = None

        # AI cost tracking
        self._total_api_cost: float = 0.0
        self._last_cycle_api_cost: float = 0.0

        # ML features for training after resolution
        self._last_ml_features: tuple[str, dict[str, float]] | None = None
        self._pending_ml_features: dict[str, dict[str, float]] = {}

    async def run(self) -> None:
        """Main entry point — run the trading loop until shutdown."""
        _setup_logging(self._config)
        logger.info("TradingAgent starting — cash=%.2f", self._config.agent.initial_cash)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

        # Load BTC 5-min candle history before starting the loop
        await self._market_data.btc_feed.load_candle_history(200)

        # Resolve any pending bets from previous sessions
        await self._resolve_pending_bets()

        try:
            if self._config.logging.dashboard_enabled:
                await self._run_with_dashboard()
            else:
                await self._run_plain()
        finally:
            await self._shutdown_components()

    def _handle_signal(self) -> None:
        logger.info("Shutdown signal received")
        self._shutdown = True

    async def _run_plain(self) -> None:
        cycle = 0
        max_cycles = self._config.agent.max_cycles
        while not self._shutdown:
            cycle += 1
            if max_cycles and cycle > max_cycles:
                logger.info("Reached max_cycles=%d, stopping", max_cycles)
                break
            await self._run_cycle(cycle)
            if not self._shutdown and (not max_cycles or cycle < max_cycles):
                await self._interruptible_sleep(self._config.agent.decision_interval)

    async def _run_with_dashboard(self) -> None:
        cycle = 0
        max_cycles = self._config.agent.max_cycles
        refresh = self._config.logging.dashboard_refresh_rate
        with Live(self._build_dashboard(0, None), refresh_per_second=refresh) as live:
            while not self._shutdown:
                cycle += 1
                if max_cycles and cycle > max_cycles:
                    logger.info("Reached max_cycles=%d, stopping", max_cycles)
                    break
                snapshot = await self._run_cycle(cycle)
                live.update(self._build_dashboard(cycle, snapshot))
                if not self._shutdown and (not max_cycles or cycle < max_cycles):
                    await self._interruptible_sleep(self._config.agent.decision_interval)

    async def _discover_market(self) -> CandleMarket | None:
        """Discover the current candle market, handling rotation."""
        new_market = await self._discovery.get_current_market()
        if new_market is None:
            # Try next market if current one isn't available yet
            new_market = await self._discovery.get_next_market()

        if new_market is None:
            logger.warning("Could not discover any candle market")
            return self._current_market

        # Check if market has rotated
        if self._current_market and new_market.condition_id != self._current_market.condition_id:
            logger.info(
                "Market rotation: %s → %s",
                self._current_market.slug, new_market.slug,
            )
            await self._handle_market_transition()

        if self._current_market is None or new_market.condition_id != self._current_market.condition_id:
            self._current_market = new_market
            self._market_data.set_market(new_market)
            logger.info("Active market: %s (ends in %.0fs)", new_market.title, new_market.time_remaining())

            # Record BTC price at candle open for resolution tracking
            btc_snapshot = await self._market_data.btc_feed.get_price()
            if btc_snapshot:
                self._resolution_tracker.record_candle_open(new_market, btc_snapshot.price_usd)

        return self._current_market

    async def _handle_market_transition(self) -> None:
        """Handle transition between candle markets — resolve winner via BTC price."""
        # Cancel pending limit orders (they're for the old market)
        cancelled = self._orderbook.cancel_all()
        if cancelled:
            logger.info("Cancelled %d pending orders on market rotation", cancelled)

        # Resolve candle winner using BTC price
        if self._current_market is not None:
            btc_snapshot = await self._market_data.btc_feed.get_price()
            btc_price = btc_snapshot.price_usd if btc_snapshot else 0.0

            resolution = await self._resolution_tracker.resolve(
                self._current_market, btc_price,
            )

            # Settle positions using actual winner
            resolution_pnl = self._portfolio.resolve_market(resolution.winner)
            resolution.total_pnl = resolution_pnl
            resolution.up_pnl = self._portfolio.up_position.realized_pnl
            resolution.down_pnl = self._portfolio.down_position.realized_pnl

            # Log resolution
            self._trade_log.write_resolution(resolution)
            self._last_resolution = resolution

            # Record outcome for confidence calibration and exit analysis
            self._calibrator.record_outcome(resolution.slug, resolution.winner)
            self._exit_tracker.record_outcome(resolution.slug, resolution.winner)

            # Train ML model on resolution outcome
            ml_feats = self._pending_ml_features.pop(resolution.slug, None)
            if ml_feats:
                self._ml_scorer.train(ml_feats, up_won=(resolution.winner == "up"))

            # Update session stats (skip flat resolutions with no position)
            had_position = resolution_pnl != 0.0
            if had_position:
                if resolution_pnl > 0:
                    self._session_wins += 1
                else:
                    self._session_losses += 1
                self._session_resolution_pnl += resolution_pnl

            logger.info(
                "Resolution: %s winner=%s pnl=%.4f | Session: W%d/L%d total_pnl=%.4f",
                resolution.slug, resolution.winner, resolution_pnl,
                self._session_wins, self._session_losses, self._session_resolution_pnl,
            )

            # Track for feedback learning
            self._recent_resolutions.append(resolution)
            if len(self._recent_resolutions) > 20:
                self._recent_resolutions = self._recent_resolutions[-20:]

            self._resolutions_since_reflection += 1
            self._save_agent_state()
            if self._resolutions_since_reflection >= 10:
                logger.info("Triggering reflection after %d resolutions", self._resolutions_since_reflection)
                self._resolutions_since_reflection = 0
                await self._knowledge_manager.reflect(
                    self._recent_resolutions, self._recent_trades,
                )
                # Deduct reflection API cost
                reflection_cost = self._knowledge_manager.last_reflection_cost
                if reflection_cost > 0:
                    self._portfolio.cash -= reflection_cost
                    self._total_api_cost += reflection_cost
                    logger.info("Reflection API cost: $%.4f (session total: $%.4f)", reflection_cost, self._total_api_cost)

        # Reset positions for new market
        self._portfolio.reset_positions()

    async def _run_cycle(self, cycle: int):
        """Execute one decision cycle. Returns the market snapshot."""
        logger.info("=== Cycle %d ===", cycle)

        # 0. Discover/rotate market
        market = await self._discover_market()
        if market is None:
            logger.warning("No market available, skipping cycle")
            self._last_action = "SKIP (no market)"
            return None

        # Check resolution buffer
        time_remaining = market.time_remaining()
        buffer = self._config.agent.resolution_buffer_seconds
        if time_remaining < buffer:
            logger.info("Too close to resolution (%.0fs < %ds), skipping", time_remaining, buffer)
            self._last_action = f"SKIP ({time_remaining:.0f}s to resolution)"
            return None

        # 1. Fetch market data
        try:
            snapshot = await self._market_data.get_snapshot()
        except Exception:
            logger.exception("Failed to fetch market data, skipping cycle")
            self._last_action = "SKIP (data error)"
            return None

        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook
        up_mid = up_ob.midpoint
        down_mid = down_ob.midpoint

        # 2. Mark-to-market portfolio
        if up_mid is not None:
            self._portfolio.mark_to_market(up_mid, down_mid)
        portfolio_value = self._portfolio.total_value_at_market(
            up_mid or 0.5, down_mid
        )
        self._risk.update_portfolio_peak(portfolio_value)

        # 3. Check pending limit order fills (using Up orderbook for now)
        limit_fills = self._orderbook.check_fills(up_ob)
        for fill in limit_fills:
            # TODO: track which token side the limit order was for
            self._portfolio.apply_fill(fill, TokenSide.UP)
            pnl = 0.0
            if fill.side.value == "SELL":
                pnl = (fill.fill_price - self._portfolio.up_position.avg_entry_price) * fill.size
            self._risk.record_trade(pnl, fill.fee_amount)
            logger.info("Limit fill applied: %s %.2f @ %.4f", fill.side.value, fill.size, fill.fill_price)

        # 4. Pre-trade risk checks
        pre_checks = self._risk.pre_trade_checks(snapshot)
        pre_failed = [c for c in pre_checks if not c.passed]
        if pre_failed:
            reasons = "; ".join(c.reason for c in pre_failed)
            logger.warning("Pre-trade risk blocked: %s", reasons)
            self._last_action = "BLOCKED (pre-trade)"
            self._last_risk_status = reasons
            self._log_cycle(cycle, snapshot, risk_blocked=True, risk_reason=reasons)
            return snapshot

        # 4b. Rules-based pre-filter (skip AI on obvious HOLDs)
        has_position = (
            self._portfolio.up_position.shares > 0
            or self._portfolio.down_position.shares > 0
        )
        pf_result = self._prefilter.check(time_remaining, snapshot, has_position)
        if pf_result.should_skip:
            self._last_action = f"HOLD (pre-filter: {pf_result.reason[:60]})"
            self._last_reasoning = pf_result.reason
            self._log_cycle(cycle, snapshot, risk_blocked=False, risk_reason="")
            self._write_dashboard_json(cycle, snapshot)
            return snapshot

        # 5. Build feature vector and get AI decision
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

        feedback_context = self._knowledge_manager.build_feedback_context(
            self._recent_resolutions,
            self._session_wins,
            self._session_losses,
            self._session_resolution_pnl,
            calibration_summary=calibration_summary,
        )
        logger.debug("Feedback context: %s", feedback_context[:200])

        # Compute dynamic indicators
        self._feature_config.load()
        candle_open_btc = None
        if self._current_market:
            candle_open_btc = self._resolution_tracker.get_candle_open(
                self._current_market.condition_id
            )
        session_ctx = SessionContext(
            wins=self._session_wins,
            losses=self._session_losses,
            candle_open_btc=candle_open_btc,
        )
        indicator_results = compute_indicators(snapshot, self._feature_config, session_ctx)
        indicators_text = format_indicators(indicator_results)
        if indicators_text:
            logger.debug("Indicators: %s", indicators_text[:200])

        # Compute ML baseline prediction
        btc_price_val = snapshot.btc_price.price_usd if snapshot.btc_price else None
        ml_features = self._ml_scorer.extract_features(
            candles=snapshot.btc_candles,
            btc_price=btc_price_val,
            candle_open=candle_open_btc,
            up_mid=up_mid,
            down_mid=down_mid,
            up_bid_depth=snapshot.orderbook.bid_depth,
            up_ask_depth=snapshot.orderbook.ask_depth,
        )
        ml_prediction = self._ml_scorer.predict(ml_features)
        # Store features for training after resolution
        if self._current_market:
            self._pending_ml_features[self._current_market.slug] = ml_features

        # Append ML prediction to indicators text
        if ml_prediction.model_trained:
            ml_line = (
                f"- ML Baseline: {ml_prediction.up_probability:.0%} UP probability "
                f"({ml_prediction.confidence})"
            )
        else:
            ml_line = f"- ML Baseline: {self._ml_scorer.get_summary()}"
        if indicators_text:
            indicators_text += "\n" + ml_line
        else:
            indicators_text = "## Computed Indicators\n" + ml_line

        # 5b. Two-pass screening: fast Haiku check before expensive Sonnet call
        if self._config.ai.two_pass_enabled and not has_position:
            should_trade, screen_reason, screen_cost = await self._decision_engine.screen(
                features, indicators_text=indicators_text,
            )
            # Deduct screening cost
            self._portfolio.cash -= screen_cost
            self._total_api_cost += screen_cost
            self._last_cycle_api_cost = screen_cost

            if not should_trade:
                self._last_action = f"HOLD (screen: {screen_reason[:60]})"
                self._last_reasoning = screen_reason
                self._log_cycle(cycle, snapshot, risk_blocked=False, risk_reason="")
                self._write_dashboard_json(cycle, snapshot)
                return snapshot

        decision, latency_ms, api_cost = await self._decision_engine.decide(
            features, feedback_context=feedback_context, indicators_text=indicators_text,
            ai_cycle_cost=self._last_cycle_api_cost, ai_session_cost=self._total_api_cost,
            candle_open_btc=candle_open_btc,
        )

        # Deduct API cost from cash (the bot pays for its own brain)
        self._portfolio.cash -= api_cost
        self._total_api_cost += api_cost
        self._last_cycle_api_cost = api_cost
        logger.info("API cost: $%.4f (session total: $%.4f)", api_cost, self._total_api_cost)

        # Hard confidence gate: override low-confidence trades to HOLD
        if decision.action != Action.HOLD and decision.confidence < 0.6:
            logger.info(
                "Overriding %s to HOLD — confidence %.2f < 0.6 threshold",
                decision.action.value, decision.confidence,
            )
            decision = TradingDecision(
                action=Action.HOLD,
                order_type=OrderType.MARKET,
                size=0.0,
                confidence=decision.confidence,
                reasoning=f"Overridden: confidence {decision.confidence:.2f} below 0.6 threshold. "
                          f"Original: {decision.reasoning[:100]}",
                market_view=decision.market_view,
                token_side=decision.token_side,
            )

        # Calibration gate: check if stated confidence is actually profitable
        if decision.action != Action.HOLD:
            cal = self._calibrator.check(decision.confidence)
            if cal.is_reliable and not cal.should_trade:
                logger.info(
                    "Calibration override %s to HOLD — stated %.2f but actual win rate %.0f%% "
                    "(%d samples, need %.0f%% break-even)",
                    decision.action.value, decision.confidence,
                    cal.calibrated_win_rate * 100, cal.sample_count,
                    self._calibrator._break_even * 100,
                )
                decision = TradingDecision(
                    action=Action.HOLD,
                    order_type=OrderType.MARKET,
                    size=0.0,
                    confidence=decision.confidence,
                    reasoning=f"Calibration override: {cal.reason}. "
                              f"Original: {decision.reasoning[:80]}",
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                )

        self._last_action = f"{decision.action.value} {decision.token_side.value} {decision.size:.1f}"
        self._last_reasoning = decision.reasoning[:120]
        self._last_token_side = decision.token_side.value

        # 6. Post-trade risk checks (skip for HOLD)
        risk_blocked = False
        risk_reason = ""
        if decision.action != Action.HOLD:
            # Get the position for the specific token being traded
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
                self._last_action = f"BLOCKED ({decision.action.value} {decision.token_side.value})"
                self._last_risk_status = risk_reason
                risk_blocked = True

        # 7. Execute — select correct orderbook based on token_side
        fill = None
        if not risk_blocked and decision.action != Action.HOLD:
            target_ob = down_ob if decision.token_side == TokenSide.DOWN else up_ob
            if decision.order_type == OrderType.MARKET:
                fill = self._execution_sim.execute(decision, target_ob)
            elif decision.order_type == OrderType.LIMIT:
                self._orderbook.add_order(decision)

        # 8. Apply fill
        if fill:
            self._portfolio.apply_fill(fill, decision.token_side)
            token_pos = self._portfolio.get_position(decision.token_side)
            realized = 0.0
            if fill.side.value == "SELL":
                realized = (fill.fill_price - token_pos.avg_entry_price) * fill.size
            self._risk.record_trade(realized, fill.fee_amount)

            # Register with calibration tracker (BUY only — SELLs are exits)
            if decision.action == Action.BUY and self._current_market:
                self._calibrator.register_trade(
                    slug=self._current_market.slug,
                    confidence=decision.confidence,
                    token_side=decision.token_side.value,
                    entry_price=fill.fill_price,
                )

            # Register exits for what-if analysis (SELL only)
            if decision.action == Action.SELL and self._current_market:
                self._exit_tracker.register_exit(
                    slug=self._current_market.slug,
                    token_side=decision.token_side.value,
                    entry_price=token_pos.avg_entry_price,
                    exit_price=fill.fill_price,
                    exit_size=fill.size,
                    time_remaining=time_remaining,
                )

        # 9. Post-fill mark-to-market
        if up_mid is not None:
            self._portfolio.mark_to_market(up_mid, down_mid)
        portfolio_value = self._portfolio.total_value_at_market(up_mid or 0.5, down_mid)
        self._risk.update_portfolio_peak(portfolio_value)
        self._last_risk_status = "HALTED" if self._risk.state.is_halted else "OK"

        # 10. Log
        self._log_cycle(
            cycle, snapshot,
            decision=decision, latency_ms=latency_ms,
            fill=fill, risk_blocked=risk_blocked, risk_reason=risk_reason,
        )

        # 11. Write dashboard JSON
        self._write_dashboard_json(cycle, snapshot)

        return snapshot

    def _log_cycle(
        self, cycle, snapshot, decision=None, latency_ms=0.0,
        fill=None, risk_blocked=False, risk_reason="",
    ) -> None:
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

        # Attach candle metadata for dashboard
        if self._current_market:
            record.candle_slug = self._current_market.slug
            record.extra["time_remaining"] = self._current_market.time_remaining()

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

        if fill:
            record.fill_price = fill.fill_price
            record.fill_size = fill.size
            record.slippage_bps = fill.slippage_bps
            record.fee_amount = fill.fee_amount

        self._trade_log.write(record)

        # Track all trades (including HOLDs) for dashboard and reflection
        self._recent_trades.append(record)
        if len(self._recent_trades) > 50:
            self._recent_trades = self._recent_trades[-50:]

    # --- Dashboard Data Writer ---

    def _write_dashboard_json(self, cycle: int, snapshot) -> None:
        """Write dashboard_data.json for the web dashboard."""
        from datetime import datetime, timezone

        try:
            dashboard_path = Path(self._config.logging.log_dir) / "dashboard_data.json"
            dashboard_path.parent.mkdir(parents=True, exist_ok=True)

            up_mid = snapshot.orderbook.midpoint if snapshot else None
            down_mid = snapshot.down_orderbook.midpoint if snapshot else None
            portfolio_value = self._portfolio.total_value_at_market(
                up_mid or 0.5, down_mid
            )

            total_games = self._session_wins + self._session_losses
            win_rate = (self._session_wins / total_games * 100) if total_games > 0 else 0.0

            # Build current market info
            current_market = {}
            if self._current_market:
                m = self._current_market
                current_market = {
                    "slug": m.slug,
                    "title": m.title,
                    "polymarket_url": f"https://polymarket.com/event/{m.slug}",
                    "time_remaining": m.time_remaining(),
                    "up_mid": up_mid,
                    "down_mid": down_mid,
                }

            # BTC info
            btc_info = {}
            if snapshot and snapshot.btc_price:
                btc_info = {
                    "price_usd": snapshot.btc_price.price_usd,
                    "change_24h_pct": snapshot.btc_price.change_24h_pct,
                    "last_candle_direction": (
                        snapshot.btc_candles[-1].direction if snapshot.btc_candles else "unknown"
                    ),
                }

            # Positions
            positions = {
                "up_shares": self._portfolio.up_position.shares,
                "up_avg_entry": self._portfolio.up_position.avg_entry_price,
                "down_shares": self._portfolio.down_position.shares,
                "down_avg_entry": self._portfolio.down_position.avg_entry_price,
            }

            # Trades list — includes per-trade financial snapshot for session tracking
            trades = []
            for t in self._recent_trades:
                trade_entry = {
                    "timestamp": datetime.fromtimestamp(t.timestamp, tz=timezone.utc).isoformat(),
                    "cycle": t.cycle_number,
                    "action": t.action.value,
                    "token_side": t.token_side.value,
                    "size": t.decision_size,
                    "fill_price": t.fill_price,
                    "confidence": t.confidence,
                    "reasoning": t.reasoning,
                    "market_view": t.market_view,
                    "candle_slug": t.candle_slug,
                    "polymarket_url": (
                        f"https://polymarket.com/event/{t.candle_slug}" if t.candle_slug else ""
                    ),
                    "time_remaining_at_trade": t.extra.get("time_remaining", 0),
                    "risk_blocked": t.risk_blocked,
                    "risk_block_reason": t.risk_block_reason,
                    # Per-trade financial state (for per-session dashboard metrics)
                    "cash": t.cash,
                    "portfolio_value": t.portfolio_value,
                    "fee": t.fee_amount,
                    "realized_pnl": t.realized_pnl,
                    "unrealized_pnl": t.unrealized_pnl,
                    "ai_cost": t.ai_cost,
                }
                trades.append(trade_entry)

            # Resolutions list
            resolutions = []
            for r in self._recent_resolutions:
                resolutions.append({
                    "timestamp": datetime.fromtimestamp(r.timestamp, tz=timezone.utc).isoformat(),
                    "slug": r.slug,
                    "winner": r.winner,
                    "btc_open": r.btc_open,
                    "btc_close": r.btc_close,
                    "btc_move": r.btc_close - r.btc_open,
                    "pnl": r.total_pnl,
                })

            # Merge historical + current session data for full dashboard view
            all_trades = self._historical_trades + trades
            all_resolutions = self._historical_resolutions + resolutions

            # Compute all-time stats from all resolutions
            all_time_pnl = sum(r.get("pnl", 0) for r in all_resolutions)
            all_time_wins = sum(1 for r in all_resolutions if r.get("pnl", 0) > 0.001)
            all_time_losses = sum(1 for r in all_resolutions if r.get("pnl", 0) < -0.001)
            all_time_total = all_time_wins + all_time_losses
            all_time_win_rate = (all_time_wins / all_time_total * 100) if all_time_total > 0 else 0.0

            data = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "session": {
                    "wins": self._session_wins,
                    "losses": self._session_losses,
                    "win_rate": win_rate,
                    "total_pnl": self._session_resolution_pnl,
                    "total_fees": self._portfolio.total_fees,
                    "total_ai_cost": self._total_api_cost,
                    "cash": self._portfolio.cash,
                    "portfolio_value": portfolio_value,
                    "initial_cash": self._config.agent.initial_cash,
                    "market_trading_pnl": self._portfolio.market_trading_pnl,
                    "cycles_run": cycle,
                    "prefilter_skip_rate": self._prefilter.skip_rate,
                    "prefilter_skipped": self._prefilter.total_skipped,
                    "prefilter_checked": self._prefilter.total_checks,
                    "calibration_records": self._calibrator.total_records,
                },
                "all_time": {
                    "wins": all_time_wins,
                    "losses": all_time_losses,
                    "win_rate": all_time_win_rate,
                    "total_pnl": all_time_pnl,
                    "total_resolutions": len(all_resolutions),
                    "total_trades": len(all_trades),
                },
                "current_market": current_market,
                "btc": btc_info,
                "positions": positions,
                "trades": all_trades,
                "resolutions": all_resolutions,
                "risk": {
                    "daily_pnl": self._risk.state.daily_pnl,
                    "daily_trades": self._risk.state.daily_trades,
                    "daily_fees": self._risk.state.daily_fees,
                    "max_drawdown": self._risk.state.max_drawdown,
                    "is_halted": self._risk.state.is_halted,
                },
            }

            dashboard_path.write_text(json.dumps(data, indent=2) + "\n")
        except Exception:
            logger.debug("Failed to write dashboard JSON", exc_info=True)

    # --- Pending Bet Resolution ---

    async def _resolve_pending_bets(self) -> None:
        """Check for trades with no matching resolution and resolve them."""
        # Group historical trades by candle_slug
        trades_by_slug: dict[str, list[dict]] = {}
        for t in self._historical_trades:
            slug = t.get("candle_slug", "")
            if not slug or slug == "unknown":
                continue
            trades_by_slug.setdefault(slug, []).append(t)

        # Index resolved slugs
        resolved_slugs = {r.get("slug", "") for r in self._historical_resolutions}

        # Find unresolved slugs that have actual fills (not just HOLDs)
        unresolved = []
        for slug, trades in trades_by_slug.items():
            if slug in resolved_slugs:
                continue
            has_fill = any(
                t.get("action") in ("BUY", "SELL") and t.get("fill_price")
                for t in trades
            )
            if not has_fill:
                continue
            unresolved.append(slug)

        if not unresolved:
            return

        # Sort oldest first (slug ends with Unix timestamp)
        unresolved.sort(key=lambda s: int(s.rsplit("-", 1)[-1]) if s.rsplit("-", 1)[-1].isdigit() else 0)

        logger.info("Found %d unresolved candle(s) with fills: %s", len(unresolved), unresolved)

        for slug in unresolved:
            try:
                await self._resolve_single_pending_bet(slug, trades_by_slug[slug])
            except Exception:
                logger.exception("Failed to resolve pending bet: %s", slug)

    async def _resolve_single_pending_bet(self, slug: str, trades: list[dict]) -> None:
        """Resolve a single pending bet by looking up the actual outcome."""
        from datetime import datetime, timezone

        # Fetch market info from Gamma API
        market = await self._discovery.fetch_market_by_slug(slug)
        if market is None:
            logger.warning("Could not fetch market for pending bet: %s (may be delisted)", slug)
            return

        # Skip if candle hasn't ended yet
        now = time.time()
        if market.end_time > now:
            logger.info("Skipping pending bet %s — candle still live (ends in %.0fs)", slug, market.end_time - now)
            return

        # Get BTC open and close prices from Binance historical API
        btc_open = await self._market_data.btc_feed.get_price_at(market.start_time)
        btc_close = await self._market_data.btc_feed.get_price_at(market.end_time)

        if btc_open is None or btc_close is None:
            logger.warning("Could not fetch BTC prices for pending bet: %s (open=%s close=%s)", slug, btc_open, btc_close)
            return

        # Resolve via the resolution tracker (handles BTC comparison + Polymarket verification)
        resolution = await self._resolution_tracker.resolve(market, btc_close)
        # The resolver may not have the open price cached, so override with our fetched values
        resolution.btc_open = btc_open
        resolution.btc_close = btc_close

        # Compute PnL from logged trades
        pnl = _compute_pnl_from_trades(trades, resolution.winner)
        resolution.total_pnl = pnl

        # Write to resolution log
        self._trade_log.write_resolution(resolution)

        # Append to historical resolutions for dashboard
        self._historical_resolutions.append({
            "timestamp": datetime.fromtimestamp(resolution.timestamp, tz=timezone.utc).isoformat(),
            "slug": resolution.slug,
            "winner": resolution.winner,
            "btc_open": resolution.btc_open,
            "btc_close": resolution.btc_close,
            "btc_move": resolution.btc_close - resolution.btc_open,
            "pnl": resolution.total_pnl,
        })

        logger.info(
            "Resolving pending bet: %s — winner=%s, pnl=%.4f (open=$%.2f close=$%.2f)",
            slug, resolution.winner, pnl, btc_open, btc_close,
        )

    # --- Agent State Persistence ---

    def _load_agent_state(self) -> None:
        """Load persisted state (resolution counter + history) from disk."""
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text())
                self._resolutions_since_reflection = data.get("resolutions_since_reflection", 0)
                logger.info("Loaded agent state: resolutions_since_reflection=%d", self._resolutions_since_reflection)
        except Exception:
            logger.warning("Could not load agent state, starting fresh")

        # Load historical resolutions from JSONL log
        self._historical_resolutions: list[dict] = []
        self._historical_trades: list[dict] = []
        self._load_history_from_logs()

    def _load_history_from_logs(self) -> None:
        """Load past resolutions and trades from JSONL log files for dashboard history."""
        from datetime import datetime, timezone

        log_dir = Path(self._config.logging.log_dir)

        # Load all resolution JSONL files
        for res_file in sorted(log_dir.glob("resolutions_*.jsonl")):
            try:
                for line in res_file.read_text().strip().split("\n"):
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    self._historical_resolutions.append({
                        "timestamp": datetime.fromtimestamp(
                            r.get("timestamp", 0), tz=timezone.utc
                        ).isoformat(),
                        "slug": r.get("slug", ""),
                        "winner": r.get("winner", ""),
                        "btc_open": r.get("btc_open", 0),
                        "btc_close": r.get("btc_close", 0),
                        "btc_move": r.get("btc_close", 0) - r.get("btc_open", 0),
                        "pnl": r.get("total_pnl", 0),
                    })
            except Exception:
                logger.debug("Could not load resolution file %s", res_file, exc_info=True)

        # Load all trade JSONL files
        for trade_file in sorted(log_dir.glob("trades_*.jsonl")):
            try:
                for line in trade_file.read_text().strip().split("\n"):
                    if not line.strip():
                        continue
                    t = json.loads(line)
                    self._historical_trades.append({
                        "timestamp": datetime.fromtimestamp(
                            t.get("timestamp", 0), tz=timezone.utc
                        ).isoformat(),
                        "cycle": t.get("cycle_number", 0),
                        "action": t.get("action", "HOLD"),
                        "token_side": t.get("token_side", "up"),
                        "size": t.get("decision_size", 0),
                        "fill_price": t.get("fill_price"),
                        "confidence": t.get("confidence", 0),
                        "reasoning": t.get("reasoning", ""),
                        "market_view": t.get("market_view", ""),
                        "candle_slug": t.get("candle_slug", ""),
                        "polymarket_url": (
                            f"https://polymarket.com/event/{t.get('candle_slug', '')}"
                            if t.get("candle_slug") else ""
                        ),
                        "time_remaining_at_trade": t.get("extra", {}).get("time_remaining", 0),
                        "risk_blocked": t.get("risk_blocked", False),
                        "risk_block_reason": t.get("risk_block_reason", ""),
                        # Per-trade financial state
                        "cash": t.get("cash"),
                        "portfolio_value": t.get("portfolio_value"),
                        "fee": t.get("fee_amount", 0),
                        "realized_pnl": t.get("realized_pnl", 0),
                        "unrealized_pnl": t.get("unrealized_pnl", 0),
                        "ai_cost": t.get("ai_cost", 0),
                    })
            except Exception:
                logger.debug("Could not load trade file %s", trade_file, exc_info=True)

        if self._historical_resolutions:
            logger.info("Loaded %d historical resolutions from logs", len(self._historical_resolutions))
        if self._historical_trades:
            logger.info("Loaded %d historical trades from logs", len(self._historical_trades))

    def _save_agent_state(self) -> None:
        """Save agent state to disk after each market transition."""
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({
                "resolutions_since_reflection": self._resolutions_since_reflection,
            }, indent=2) + "\n")
        except Exception:
            logger.warning("Could not save agent state")

    # --- Rich Dashboard ---

    def _build_dashboard(self, cycle: int, snapshot) -> Table:
        grid = Table(title="Polymarket BTC 5-Min Candle Bot", show_header=False, expand=True)
        grid.add_column("Section", style="bold cyan", width=22)
        grid.add_column("Details", style="white")

        # Candle market info
        if self._current_market:
            remaining = self._current_market.time_remaining()
            market_title = f"{self._current_market.title} ({remaining:.0f}s remaining)"
        else:
            market_title = "Discovering market..."
        grid.add_row("Candle Market", market_title)
        grid.add_row("Cycle", str(cycle))

        # Up token orderbook
        if snapshot and snapshot.orderbook.midpoint is not None:
            up_ob = snapshot.orderbook
            up_info = (
                f"Bid: {up_ob.best_bid:.4f}  Ask: {up_ob.best_ask:.4f}  "
                f"Mid: {up_ob.midpoint:.4f}  Spread: {up_ob.spread_pct:.2%}"
            )
        else:
            up_info = "Waiting for data..."
        grid.add_row("Up Token", up_info)

        # Down token orderbook
        if snapshot and snapshot.down_orderbook.midpoint is not None:
            down_ob = snapshot.down_orderbook
            down_info = (
                f"Bid: {down_ob.best_bid:.4f}  Ask: {down_ob.best_ask:.4f}  "
                f"Mid: {down_ob.midpoint:.4f}  Spread: {down_ob.spread_pct:.2%}"
            )
        else:
            down_info = "Waiting for data..."
        grid.add_row("Down Token", down_info)

        # Up position
        up_pos = self._portfolio.up_position
        if up_pos.shares > 0:
            up_pos_info = (
                f"Shares: {up_pos.shares:.2f}  Avg: {up_pos.avg_entry_price:.4f}  "
                f"UnrPnL: {up_pos.unrealized_pnl:+.2f}"
            )
        else:
            up_pos_info = "Flat"
        grid.add_row("Up Position", up_pos_info)

        # Down position
        down_pos = self._portfolio.down_position
        if down_pos.shares > 0:
            down_pos_info = (
                f"Shares: {down_pos.shares:.2f}  Avg: {down_pos.avg_entry_price:.4f}  "
                f"UnrPnL: {down_pos.unrealized_pnl:+.2f}"
            )
        else:
            down_pos_info = "Flat"
        grid.add_row("Down Position", down_pos_info)

        # Portfolio
        up_mid = snapshot.orderbook.midpoint if snapshot else None
        down_mid = snapshot.down_orderbook.midpoint if snapshot else None
        total = self._portfolio.total_value_at_market(up_mid or 0.5, down_mid)
        pnl = total - self._config.agent.initial_cash
        portfolio_info = (
            f"Cash: ${self._portfolio.cash:,.2f}  "
            f"Total: ${total:,.2f}  "
            f"PnL: {pnl:+,.2f}"
        )
        grid.add_row("Portfolio", portfolio_info)

        # Last action
        grid.add_row("Last Action", self._last_action)
        grid.add_row("Reasoning", self._last_reasoning or "—")

        # Risk
        risk_style = "red" if self._last_risk_status != "OK" else "green"
        grid.add_row("Risk Status", Text(self._last_risk_status, style=risk_style))

        # Resolution stats
        res_info = f"W: {self._session_wins}  L: {self._session_losses}  PnL: {self._session_resolution_pnl:+,.4f}"
        if self._last_resolution:
            r = self._last_resolution
            res_info += f"  | Last: {r.slug} → {r.winner} (${r.btc_open:.0f}→${r.btc_close:.0f})"
        grid.add_row("Resolutions", res_info)

        # AI Costs + Pre-filter stats
        ai_cost_info = (
            f"Session: ${self._total_api_cost:.4f}  "
            f"Last Cycle: ${self._last_cycle_api_cost:.4f}  "
            f"Pre-filter: {self._prefilter.total_skipped}/{self._prefilter.total_checks} skipped "
            f"({self._prefilter.skip_rate:.0%})"
        )
        grid.add_row("AI Costs", ai_cost_info)

        # Pending orders
        pending = self._orderbook.pending_orders
        if pending:
            orders_info = ", ".join(
                f"{o.side.value} {o.size:.1f}@{o.limit_price:.4f}" for o in pending
            )
        else:
            orders_info = "None"
        grid.add_row("Pending Orders", orders_info)

        return grid

    async def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep that can be interrupted by shutdown signal."""
        try:
            end = time.monotonic() + seconds
            while not self._shutdown and time.monotonic() < end:
                await asyncio.sleep(min(0.5, end - time.monotonic()))
        except asyncio.CancelledError:
            pass

    async def _shutdown_components(self) -> None:
        logger.info("Shutting down components...")
        await self._discovery.close()
        await self._market_data.close()
        self._trade_log.close()
        cancelled = self._orderbook.cancel_all()
        if cancelled:
            logger.info("Cancelled %d pending limit orders", cancelled)
        logger.info(
            "Final state — cash=%.2f up_shares=%.2f down_shares=%.2f total=%.2f",
            self._portfolio.cash,
            self._portfolio.up_position.shares,
            self._portfolio.down_position.shares,
            self._portfolio.total_value,
        )
