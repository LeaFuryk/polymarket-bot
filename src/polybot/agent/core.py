"""Core trading agent — orchestrates concurrent tasks with dynamic market discovery."""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

from polybot import __version__
from polybot.adaptive_entry import AdaptiveEntryTracker
from polybot.agent.context import AgentContext
from polybot.agent.dashboard import (
    DashboardAssembler,
    load_iteration_summaries,
)
from polybot.agent.helpers import setup_logging
from polybot.agent.rotation import RotationManager
from polybot.agent.state import StatePersistence
from polybot.calibration import ConfidenceCalibrator
from polybot.config import AppConfig
from polybot.datastore import DataStore, MarketHistoryStore
from polybot.decision_engine.engine import DecisionEngine
from polybot.execution.live import LiveExecutionEngine
from polybot.exit_tracker import ExitTracker
from polybot.indicators import (
    FeatureConfig,
)
from polybot.knowledge import KnowledgeManager
from polybot.logging.trade_log import TradeLog
from polybot.market_data.chainlink_ws import ChainlinkWSFeed
from polybot.market_data.discovery import MarketDiscovery
from polybot.market_data.provider import MarketDataProvider
from polybot.ml_scorer import MLScorer
from polybot.models import (
    CandleMarket,
    ResolutionRecord,
    TradeRecord,
)
from polybot.prefilter import PreFilter
from polybot.resolution import MarketDataResolutionRepo, ResolutionTracker
from polybot.risk.manager import RiskManager
from polybot.shared_state import SharedState
from polybot.simulator.engine import ExecutionSimulator
from polybot.simulator.orderbook import SimulatedOrderBook
from polybot.simulator.portfolio import Portfolio
from polybot.tasks.ai_decision import AIDecision
from polybot.tasks.market_monitor import MarketMonitor
from polybot.tasks.position_monitor import PositionMonitor


class TradingAgent:
    """Orchestrator — launches concurrent tasks for market monitoring, AI decisions, and position management."""

    def __init__(self, config: AppConfig, logger: logging.Logger | None = None) -> None:
        self._config = config
        self._log = logger or logging.getLogger(__name__)

        # Sub-components
        self._chainlink_ws = ChainlinkWSFeed(config.api.polymarket_rtds_url)
        self._discovery = MarketDiscovery(config)
        self._market_data = MarketDataProvider(config, chainlink_ws=self._chainlink_ws)
        self._decision_engine = DecisionEngine(config.ai)
        self._execution_sim = ExecutionSimulator(config.simulator)
        self._orderbook = SimulatedOrderBook(config.simulator)
        self._portfolio = Portfolio(config.agent.initial_cash)
        self._risk = RiskManager(config.risk, config.agent.initial_cash)

        # Live trading engine (created if mode == "live")
        self._live_mode = config.trading.mode == "live"
        self._live_engine: LiveExecutionEngine | None = None
        self._shadow_portfolio: Portfolio | None = None

        if self._live_mode:
            self._live_engine = LiveExecutionEngine(config.trading, config.api)
            self._shadow_portfolio = Portfolio(config.agent.initial_cash)
            self._log.warning(
                "LIVE TRADING MODE — real CLOB orders will be placed%s",
                " (DRY RUN)" if config.trading.dry_run else "",
            )
        self._trade_log = TradeLog(config.logging)

        # Resolution tracking
        self._resolution_tracker = ResolutionTracker(
            MarketDataResolutionRepo(self._market_data._btc, self._market_data._rest),
        )

        # Rules-based pre-filter (checks 1-5 only, no R/R gate)
        self._prefilter = PreFilter()

        # Confidence calibration
        self._calibrator = ConfidenceCalibrator(
            data_dir=Path(config.logging.log_dir),
        )

        # Exit strategy tracker
        self._exit_tracker = ExitTracker(
            data_dir=Path(config.logging.log_dir),
        )

        # Adaptive entry threshold tracker
        self._adaptive_entry = AdaptiveEntryTracker(
            data_dir=Path(config.logging.log_dir),
            window=config.monitor.adaptive_entry_window,
        )

        # ML scorer
        self._ml_scorer = MLScorer(
            data_dir=Path(config.logging.log_dir),
        )

        # Knowledge / feedback learning
        self._knowledge_manager = KnowledgeManager(config.logging.knowledge_dir, config.ai)
        self._feature_config = FeatureConfig(Path(config.logging.knowledge_dir).parent / "feature_config.json")
        self._recent_resolutions: list[ResolutionRecord] = []  # for reflection (capped at 20)
        self._session_resolutions: list[ResolutionRecord] = []  # for dashboard (uncapped)
        self._recent_trades: list[TradeRecord] = []
        self._session_trades: list[TradeRecord] = []
        # Bot version (captured once at startup)
        self._bot_version: str = __version__

        # Current candle market
        self._current_market: CandleMarket | None = None

        # WebSocket dashboard server
        from polybot.ws.broadcaster import DashboardBroadcaster
        from polybot.ws.server import DashboardWSServer

        self._ws_broadcaster = DashboardBroadcaster()
        self._ws_server = DashboardWSServer(
            broadcaster=self._ws_broadcaster,
            port=config.logging.ws_port,
        )

        def _build_initial_snapshot() -> str:
            from polybot.ws.protocol import MSG_SNAPSHOT, make_message

            data = self._dashboard_assembler.assemble_dashboard_data(self._ctx)
            data["ws_clients"] = self._ws_broadcaster.client_count
            return make_message(MSG_SNAPSHOT, data)

        self._ws_server._initial_snapshot_builder = _build_initial_snapshot

        # ML features for training after resolution
        self._pending_ml_features: dict[str, dict[str, float]] = {}

        # SQLite analytics store
        self._datastore: DataStore | None = None
        if config.logging.sqlite_enabled:
            self._datastore = DataStore(config.logging.sqlite_db_path)

        # Persistent market history store (never deleted by archive)
        iteration_label = StatePersistence.compute_iteration_label()
        self._market_history = MarketHistoryStore(
            config.logging.market_history_db_path,
            iteration=iteration_label,
        )

        # Shared state for concurrent tasks
        self._shared = SharedState()

        # Task objects (created in run())
        self._ai_decision: AIDecision | None = None
        self._position_monitor: PositionMonitor | None = None

        # State persistence, rotation manager, and dashboard assembler
        self._state_persistence = StatePersistence(logger=self._log)
        self._rotation_manager = RotationManager(logger=self._log)
        self._dashboard_assembler = DashboardAssembler(logger=self._log)

        # Build AgentContext — typed container for extracted modules
        self._state_path = Path(config.logging.log_dir) / "agent_state.json"
        self._ctx = AgentContext(
            config=config,
            chainlink_ws=self._chainlink_ws,
            discovery=self._discovery,
            market_data=self._market_data,
            decision_engine=self._decision_engine,
            execution_sim=self._execution_sim,
            orderbook=self._orderbook,
            portfolio=self._portfolio,
            risk=self._risk,
            trade_log=self._trade_log,
            resolution_tracker=self._resolution_tracker,
            prefilter=self._prefilter,
            calibrator=self._calibrator,
            exit_tracker=self._exit_tracker,
            adaptive_entry=self._adaptive_entry,
            ml_scorer=self._ml_scorer,
            knowledge_manager=self._knowledge_manager,
            feature_config=self._feature_config,
            shared=self._shared,
            live_mode=self._live_mode,
            live_engine=self._live_engine,
            shadow_portfolio=self._shadow_portfolio,
            ws_broadcaster=self._ws_broadcaster,
            ws_server=self._ws_server,
            datastore=self._datastore,
            market_history=self._market_history,
            bot_version=self._bot_version,
            state_path=self._state_path,
            recent_resolutions=self._recent_resolutions,
            session_resolutions=self._session_resolutions,
            recent_trades=self._recent_trades,
            session_trades=self._session_trades,
            pending_ml_features=self._pending_ml_features,
        )

        # Restore persisted state (populates ctx.historical_resolutions/trades)
        self._state_persistence.load_agent_state(self._ctx)
        # Load archived iteration summaries for dashboard
        self._ctx.iteration_summaries = load_iteration_summaries(log=self._log)

    async def run(self) -> None:
        """Main entry point — launches concurrent tasks."""
        setup_logging(self._config)
        self._log.info("TradingAgent starting — v%s, cash=%.2f", self._bot_version, self._config.agent.initial_cash)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

        # Open SQLite analytics store
        if self._datastore is not None:
            self._datastore.open()

        # Open persistent market history store
        self._market_history.open()

        # Live trading startup validation
        if self._live_mode and self._live_engine:
            tc = self._config.trading
            if not tc.private_key:
                self._log.critical("LIVE MODE: no private_key configured — aborting")
                return
            if not (tc.api_key and tc.api_secret and tc.api_passphrase):
                self._log.critical("LIVE MODE: missing API credentials — run scripts/generate_api_key.py first")
                return
            initial_balance = await self._live_engine.sync_balance()
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
        await self._chainlink_ws.start()

        # Load BTC 5-min candle history
        await self._market_data.btc_feed.load_candle_history(200)

        # Bootstrap adaptive entry from Binance if insufficient history
        await self._adaptive_entry.bootstrap_from_binance()

        # Resolve any pending bets from previous sessions
        await self._state_persistence.resolve_pending_bets(self._ctx)

        # Create task objects
        market_monitor = MarketMonitor(
            config=self._config,
            shared=self._shared,
            market_data=self._market_data,
            prefilter=self._prefilter,
            portfolio=self._portfolio,
            resolution_tracker=self._resolution_tracker,
            datastore=self._datastore,
            feature_config=self._feature_config if self._datastore else None,
            market_history=self._market_history,
            adaptive_entry=self._adaptive_entry,
        )

        self._ai_decision = AIDecision(
            config=self._config,
            shared=self._shared,
            decision_engine=self._decision_engine,
            execution_sim=self._execution_sim,
            orderbook=self._orderbook,
            portfolio=self._portfolio,
            risk=self._risk,
            trade_log=self._trade_log,
            prefilter=self._prefilter,
            calibrator=self._calibrator,
            exit_tracker=self._exit_tracker,
            ml_scorer=self._ml_scorer,
            knowledge_manager=self._knowledge_manager,
            feature_config=self._feature_config,
            resolution_tracker=self._resolution_tracker,
            adaptive_entry=self._adaptive_entry,
            recent_resolutions=self._recent_resolutions,
            recent_trades=self._recent_trades,
            session_trades=self._session_trades,
            pending_ml_features=self._pending_ml_features,
            live_engine=self._live_engine,
            shadow_portfolio=self._shadow_portfolio,
        )

        if self._datastore is not None:
            self._ai_decision._datastore = self._datastore

        # Wire up WS trade event push
        async def _on_trade(record):
            if self._ws_broadcaster.has_clients:
                await self._ws_broadcaster.broadcast(self._ws_broadcaster.build_trade_event(record))

        self._ai_decision.on_trade_callback = _on_trade

        self._position_monitor = PositionMonitor(
            config=self._config,
            shared=self._shared,
            portfolio=self._portfolio,
        )

        # Update context with task objects created above
        self._ctx.ai_decision = self._ai_decision
        self._ctx.position_monitor = self._position_monitor

        # Start WebSocket server
        if self._config.logging.ws_enabled:
            await self._ws_server.start()

        # Launch all tasks concurrently
        tasks = [
            asyncio.create_task(market_monitor.run(), name="market_monitor"),
            asyncio.create_task(self._ai_decision.run(), name="ai_decision"),
            asyncio.create_task(self._position_monitor.run(), name="position_monitor"),
            asyncio.create_task(self._rotation_loop(), name="rotation_loop"),
            asyncio.create_task(self._dashboard_loop(), name="dashboard_loop"),
        ]
        if self._config.logging.ws_enabled:
            tasks.append(asyncio.create_task(self._ws_broadcast_loop(), name="ws_broadcast"))
        if self._live_mode and self._live_engine:
            tasks.append(asyncio.create_task(self._balance_sync_loop(), name="balance_sync"))
        if self._datastore is not None:
            tasks.append(asyncio.create_task(self._datastore.writer_loop(), name="datastore_writer"))
        tasks.append(asyncio.create_task(self._market_history.writer_loop(), name="market_history_writer"))

        try:
            # Wait until shutdown
            while not self._shared.shutdown:
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
        self._shared.shutdown = True

    async def _rotation_loop(self) -> None:
        """Delegates to RotationManager.rotation_loop."""
        await self._rotation_manager.rotation_loop(self._ctx)

    async def _dashboard_loop(self) -> None:
        """Delegates to DashboardAssembler.dashboard_loop."""
        await self._dashboard_assembler.dashboard_loop(self._ctx)

    async def _ws_broadcast_loop(self) -> None:
        """Delegates to DashboardAssembler.ws_broadcast_loop."""
        await self._dashboard_assembler.ws_broadcast_loop(self._ctx)

    async def _balance_sync_loop(self) -> None:
        """Periodically syncs wallet balance and checks kill switch (live mode only)."""
        self._log.info("BalanceSyncLoop started")
        while not self._shared.shutdown:
            try:
                if self._live_engine:
                    balance = await self._live_engine.sync_balance()
                    killed = self._live_engine.check_kill_switch(self._ctx.session_resolution_pnl)
                    if killed:
                        self._log.critical("Kill switch triggered — initiating shutdown")
                        self._shared.shutdown = True
                        break
                    self._log.debug("Wallet balance: $%.2f", balance)
            except Exception:
                self._log.exception("BalanceSyncLoop error")
            await asyncio.sleep(60.0)
        self._log.info("BalanceSyncLoop stopped")

    def _assemble_dashboard_data(self) -> dict:
        """Backward-compatible wrapper — delegates to DashboardAssembler."""
        return self._dashboard_assembler.assemble_dashboard_data(self._ctx)

    async def _shutdown_components(self) -> None:
        self._log.info("Shutting down components...")
        await self._ws_server.stop()
        await self._chainlink_ws.stop()
        if self._datastore is not None:
            await self._datastore.close()
        await self._market_history.close()
        await self._discovery.close()
        await self._market_data.close()
        self._trade_log.close()
        cancelled = self._orderbook.cancel_all()
        if cancelled:
            self._log.info("Cancelled %d pending limit orders", cancelled)
        self._log.info(
            "Final state — cash=%.2f up_shares=%.2f down_shares=%.2f total=%.2f",
            self._portfolio.cash,
            self._portfolio.up_position.shares,
            self._portfolio.down_position.shares,
            self._portfolio.total_value,
        )
