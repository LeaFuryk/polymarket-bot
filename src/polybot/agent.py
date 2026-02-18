"""Core trading agent — orchestrates the decision loop with dynamic market discovery."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from pathlib import Path

from rich.live import Live
from rich.table import Table
from rich.text import Text

from polybot.config import AppConfig
from polybot.decision_engine.engine import DecisionEngine
from polybot.indicators import (
    FeatureConfig,
    SessionContext,
    compute_indicators,
    format_indicators,
)
from polybot.knowledge import KnowledgeManager
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
        self._resolution_tracker = ResolutionTracker(self._market_data.btc_feed)

        # Knowledge / feedback learning
        self._knowledge_manager = KnowledgeManager(config.logging.knowledge_dir, config.ai)
        self._feature_config = FeatureConfig(Path(config.logging.knowledge_dir).parent / "feature_config.json")
        self._recent_resolutions: list[ResolutionRecord] = []
        self._recent_trades: list[TradeRecord] = []
        self._resolutions_since_reflection: int = 0

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

    async def run(self) -> None:
        """Main entry point — run the trading loop until shutdown."""
        _setup_logging(self._config)
        logger.info("TradingAgent starting — cash=%.2f", self._config.agent.initial_cash)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

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

            # Update session stats
            if resolution_pnl >= 0:
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
            if self._resolutions_since_reflection >= 6:
                logger.info("Triggering reflection after %d resolutions", self._resolutions_since_reflection)
                self._resolutions_since_reflection = 0
                await self._knowledge_manager.reflect(
                    self._recent_resolutions, self._recent_trades,
                )

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

        feedback_context = self._knowledge_manager.build_feedback_context(
            self._recent_resolutions,
            self._session_wins,
            self._session_losses,
            self._session_resolution_pnl,
        )
        logger.debug("Feedback context: %s", feedback_context[:200])

        # Compute dynamic indicators
        self._feature_config.load()
        session_ctx = SessionContext(
            wins=self._session_wins,
            losses=self._session_losses,
        )
        indicator_results = compute_indicators(snapshot, self._feature_config, session_ctx)
        indicators_text = format_indicators(indicator_results)
        if indicators_text:
            logger.debug("Indicators: %s", indicators_text[:200])

        decision, latency_ms = await self._decision_engine.decide(
            features, feedback_context=feedback_context, indicators_text=indicators_text,
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

        if fill:
            record.fill_price = fill.fill_price
            record.fill_size = fill.size
            record.slippage_bps = fill.slippage_bps
            record.fee_amount = fill.fee_amount

        self._trade_log.write(record)

        # Track trades with fills for reflection
        if fill:
            self._recent_trades.append(record)
            if len(self._recent_trades) > 20:
                self._recent_trades = self._recent_trades[-20:]

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
