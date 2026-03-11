"""Core trading agent — orchestrates concurrent tasks with dynamic market discovery."""

from __future__ import annotations

import asyncio
import signal

from polybot.agent.factory import ContextFactory
from polybot.agent.helpers import resolve_pending_bets
from polybot.agent.rotation import RotationManager
from polybot.agent.startup_loader import StartupLoader
from polybot.config import AppConfig
from polybot.logging import create_logger
from polybot.tasks.ai_decision import AIDecision
from polybot.tasks.market_monitor import MarketMonitor
from polybot.tasks.position_monitor import PositionMonitor
from polybot.ws.server import DashboardWSServer


class TradingAgent:
    """Orchestrator — launches concurrent tasks for market monitoring, AI decisions, and position management."""

    def __init__(self, config: AppConfig) -> None:
        self._log = create_logger(config)

        # Load persisted state before building context
        startup_data = StartupLoader(config, log=self._log).load()

        # Build AgentContext via factory (all sub-component wiring)
        factory = ContextFactory(config, startup_data, logger=self._log)
        self._ctx = factory.build()

        # WebSocket server — lifecycle owned by TradingAgent, not shared context
        self._ws_server = DashboardWSServer(
            broadcaster=self._ctx.ws_broadcaster,
            port=config.logging.ws_port,
            ctx=self._ctx,
        )

    async def run(self) -> None:
        """Main entry point — launches concurrent tasks."""
        ctx = self._ctx
        self._log.info("TradingAgent starting — v%s, cash=%.2f", ctx.bot_version, ctx.config.agent.initial_cash)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

        # TODO: This will refactor to a single store which contains data specifically oriented for finetuning
        # Open SQLite analytics store
        if ctx.datastore is not None:
            ctx.datastore.open()
        # Open persistent market history store
        ctx.market_history.open()

        # Live trading startup validation
        if ctx.live_mode and ctx.live_engine:
            tc = ctx.config.trading
            if not tc.private_key:
                self._log.critical("LIVE MODE: no private_key configured — aborting")
                return
            if not (tc.api_key and tc.api_secret and tc.api_passphrase):
                self._log.critical("LIVE MODE: missing API credentials — run scripts/generate_api_key.py first")
                return
            initial_balance = await ctx.live_engine.sync_balance()
            if initial_balance <= 0 and not tc.dry_run:
                self._log.critical(
                    "LIVE MODE: wallet balance is $%.2f — aborting (fund wallet or use dry_run=true)", initial_balance
                )
                return
            self._log.info(
                "LIVE MODE: wallet balance $%.2f, max_order=$%.0f, kill_switch=-$%.0f, dry_run=%s",
                initial_balance,
                tc.max_order_size_usd,
                tc.max_session_loss_usd,
                tc.dry_run,
            )

        # Parallel startup: all three are independent network calls
        await asyncio.gather(
            ctx.market_data.btc_feed.load_candle_history(200),
            ctx.adaptive_entry.bootstrap_from_binance(),
            resolve_pending_bets(ctx, log=self._log),
        )

        # Create task objects — AIDecision first (monitors reference it)
        ai_decision = AIDecision(ctx)
        rotation_manager = RotationManager(ctx, ai_decision=ai_decision, logger=self._log)
        market_monitor = MarketMonitor(ctx, ai_decision=ai_decision, rotation_manager=rotation_manager)
        position_monitor = PositionMonitor(ctx, ai_decision=ai_decision)

        # Start WebSocket server
        if ctx.config.logging.ws_enabled:
            await self._ws_server.start()

        # Launch monitor tasks (datastore writers self-start in open())
        tasks = [
            asyncio.create_task(market_monitor.run(), name="market_monitor"),
            asyncio.create_task(position_monitor.run(), name="position_monitor"),
        ]

        try:
            # Wait until shutdown
            while not ctx.shared.shutdown:
                await asyncio.sleep(0.5)

            # Signal all tasks to stop
            self._log.info("Shutdown: waiting for tasks to complete...")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self._shutdown_components()

    def _handle_signal(self) -> None:
        self._log.info("Shutdown signal received")
        self._ctx.shared.shutdown = True

    async def _shutdown_components(self) -> None:
        ctx = self._ctx
        self._log.info("Shutting down components...")
        await self._ws_server.stop()
        if ctx.datastore is not None:
            await ctx.datastore.close()
        await ctx.market_history.close()
        await ctx.discovery.close()
        await ctx.market_data.close()
        ctx.trade_log.close()
        cancelled = ctx.orderbook.cancel_all()
        if cancelled:
            self._log.info("Cancelled %d pending limit orders", cancelled)
        self._log.info(
            "Final state — cash=%.2f up_shares=%.2f down_shares=%.2f total=%.2f",
            ctx.portfolio.cash,
            ctx.portfolio.up_position.shares,
            ctx.portfolio.down_position.shares,
            ctx.portfolio.total_value,
        )
