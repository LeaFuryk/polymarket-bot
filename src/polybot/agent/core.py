"""Core trading agent — orchestrates concurrent tasks with dynamic market discovery."""

from __future__ import annotations

import asyncio
import logging
import signal

from polybot.agent.dashboard import (
    assemble_dashboard_data,
    load_iteration_summaries,
    sync_from_ai_decision,
    write_dashboard_json,
)
from polybot.agent.factory import ContextFactory
from polybot.agent.helpers import setup_logging
from polybot.agent.rotation import RotationManager
from polybot.agent.state import StatePersistence
from polybot.config import AppConfig
from polybot.tasks.ai_decision import AIDecision
from polybot.tasks.market_monitor import MarketMonitor
from polybot.tasks.position_monitor import PositionMonitor


class TradingAgent:
    """Orchestrator — launches concurrent tasks for market monitoring, AI decisions, and position management."""

    def __init__(self, config: AppConfig, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger(__name__)

        # Build AgentContext via factory (all sub-component wiring)
        factory = ContextFactory(config, logger=self._log)
        self._ctx = factory.build()

        # Orchestration managers (TradingAgent-only, not in ctx)
        self._state_persistence = StatePersistence(logger=self._log)

        # Snapshot builder (closure called lazily at runtime, self._ctx exists by then)
        def _build_initial_snapshot() -> str:
            from polybot.ws.protocol import MSG_SNAPSHOT, make_message

            data = assemble_dashboard_data(self._ctx, log=self._log)
            data["ws_clients"] = self._ctx.ws_broadcaster.client_count
            return make_message(MSG_SNAPSHOT, data)

        self._ctx.ws_server._initial_snapshot_builder = _build_initial_snapshot

        # Restore persisted state (populates ctx.historical_resolutions/trades)
        self._state_persistence.load_agent_state(self._ctx)
        # Load archived iteration summaries for dashboard
        self._ctx.iteration_summaries = load_iteration_summaries(log=self._log)

    async def run(self) -> None:
        """Main entry point — launches concurrent tasks."""
        ctx = self._ctx
        setup_logging(ctx.config)
        self._log.info("TradingAgent starting — v%s, cash=%.2f", ctx.bot_version, ctx.config.agent.initial_cash)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

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

        # Start Chainlink WebSocket feed (primary BTC price — matches resolution)
        await ctx.chainlink_ws.start()

        # Load BTC 5-min candle history
        await ctx.market_data.btc_feed.load_candle_history(200)

        # Bootstrap adaptive entry from Binance if insufficient history
        await ctx.adaptive_entry.bootstrap_from_binance()

        # Resolve any pending bets from previous sessions
        await self._state_persistence.resolve_pending_bets(ctx)

        # Create task objects — AIDecision first (monitors reference it)
        ctx.ai_decision = AIDecision(
            config=ctx.config,
            shared=ctx.shared,
            decision_engine=ctx.decision_engine,
            execution_sim=ctx.execution_sim,
            orderbook=ctx.orderbook,
            portfolio=ctx.portfolio,
            risk=ctx.risk,
            trade_log=ctx.trade_log,
            prefilter=ctx.prefilter,
            calibrator=ctx.calibrator,
            exit_tracker=ctx.exit_tracker,
            ml_scorer=ctx.ml_scorer,
            knowledge_manager=ctx.knowledge_manager,
            feature_config=ctx.feature_config,
            resolution_tracker=ctx.resolution_tracker,
            adaptive_entry=ctx.adaptive_entry,
            recent_resolutions=ctx.recent_resolutions,
            recent_trades=ctx.recent_trades,
            session_trades=ctx.session_trades,
            pending_ml_features=ctx.pending_ml_features,
            live_engine=ctx.live_engine,
            shadow_portfolio=ctx.shadow_portfolio,
        )

        if ctx.datastore is not None:
            ctx.ai_decision._datastore = ctx.datastore

        # Wire up WS trade event push
        async def _on_trade(record):
            if ctx.ws_broadcaster.has_clients:
                await ctx.ws_broadcaster.broadcast(ctx.ws_broadcaster.build_trade_event(record))

        ctx.ai_decision.on_trade_callback = _on_trade

        # Wire on_cycle_complete: sync dashboard state + broadcast snapshot
        async def _on_cycle_complete():
            from polybot.ws.protocol import MSG_SNAPSHOT, make_message

            sync_from_ai_decision(ctx)
            write_dashboard_json(ctx, log=self._log)
            if ctx.ws_broadcaster and ctx.ws_broadcaster.has_clients:
                data = assemble_dashboard_data(ctx, log=self._log)
                data["ws_clients"] = ctx.ws_broadcaster.client_count
                await ctx.ws_broadcaster.broadcast(make_message(MSG_SNAPSHOT, data))
                await ctx.ws_broadcaster.broadcast(ctx.ws_broadcaster.build_status_update(ctx))

        ctx.ai_decision.on_cycle_complete = _on_cycle_complete

        rotation_manager = RotationManager(ctx, logger=self._log)

        market_monitor = MarketMonitor(
            config=ctx.config,
            shared=ctx.shared,
            market_data=ctx.market_data,
            prefilter=ctx.prefilter,
            portfolio=ctx.portfolio,
            resolution_tracker=ctx.resolution_tracker,
            ai_decision=ctx.ai_decision,
            rotation_manager=rotation_manager,
            datastore=ctx.datastore,
            feature_config=ctx.feature_config if ctx.datastore else None,
            market_history=ctx.market_history,
            adaptive_entry=ctx.adaptive_entry,
            ctx=ctx,
        )

        position_monitor = PositionMonitor(
            config=ctx.config,
            shared=ctx.shared,
            portfolio=ctx.portfolio,
            ai_decision=ctx.ai_decision,
            ctx=ctx,
        )

        # Start WebSocket server
        if ctx.config.logging.ws_enabled:
            await ctx.ws_server.start()

        # Launch all tasks concurrently
        tasks = [
            asyncio.create_task(market_monitor.run(), name="market_monitor"),
            asyncio.create_task(position_monitor.run(), name="position_monitor"),
        ]
        if ctx.live_mode and ctx.live_engine:
            tasks.append(asyncio.create_task(self._balance_sync_loop(), name="balance_sync"))
        if ctx.datastore is not None:
            tasks.append(asyncio.create_task(ctx.datastore.writer_loop(), name="datastore_writer"))
        tasks.append(asyncio.create_task(ctx.market_history.writer_loop(), name="market_history_writer"))

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

    async def _balance_sync_loop(self) -> None:
        """Periodically syncs wallet balance and checks kill switch (live mode only)."""
        self._log.info("BalanceSyncLoop started")
        while not self._ctx.shared.shutdown:
            try:
                if self._ctx.live_engine:
                    balance = await self._ctx.live_engine.sync_balance()
                    killed = self._ctx.live_engine.check_kill_switch(self._ctx.session_resolution_pnl)
                    if killed:
                        self._log.critical("Kill switch triggered — initiating shutdown")
                        self._ctx.shared.shutdown = True
                        break
                    self._log.debug("Wallet balance: $%.2f", balance)
            except Exception:
                self._log.exception("BalanceSyncLoop error")
            await asyncio.sleep(60.0)
        self._log.info("BalanceSyncLoop stopped")

    async def _shutdown_components(self) -> None:
        ctx = self._ctx
        self._log.info("Shutting down components...")
        await ctx.ws_server.stop()
        await ctx.chainlink_ws.stop()
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
