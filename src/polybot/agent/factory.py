"""ContextFactory — builds a fully-wired AgentContext from AppConfig."""

from __future__ import annotations

import logging
from pathlib import Path

from polybot import __version__
from polybot.adaptive_entry import AdaptiveEntryTracker
from polybot.agent.context import AgentContext
from polybot.agent.startup_loader import StartupData
from polybot.calibration import ConfidenceCalibrator
from polybot.config import AppConfig
from polybot.datastore import DataStore, MarketHistoryStore
from polybot.decision_engine.engine import DecisionEngine
from polybot.execution.live import LiveExecutionEngine
from polybot.exit_tracker import ExitTracker
from polybot.indicators import FeatureConfig
from polybot.indicators.catalog import all_indicators
from polybot.indicators.processor import IndicatorsProcessor
from polybot.knowledge import KnowledgeManager
from polybot.logging.trade_log import TradeLog
from polybot.market_data.discovery import MarketDiscovery
from polybot.market_data.provider import MarketDataProvider
from polybot.ml_scorer import MLScorer
from polybot.prefilter import PreFilter
from polybot.resolution import MarketDataResolutionRepo, ResolutionTracker
from polybot.risk.manager import RiskManager
from polybot.shared_state import SharedState
from polybot.simulator.engine import ExecutionSimulator
from polybot.simulator.orderbook import SimulatedOrderBook
from polybot.simulator.portfolio import Portfolio
from polybot.ws.broadcaster import Broadcaster


class ContextFactory:
    """Creates all sub-components and assembles an AgentContext.

    Extracts the pure wiring logic that was previously in TradingAgent.__init__,
    making construction independently testable and keeping the agent focused on
    orchestration.
    """

    def __init__(
        self,
        config: AppConfig,
        startup_data: StartupData | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._startup_data = startup_data or StartupData()
        self._log = logger or logging.getLogger(__name__)

    def build(self) -> AgentContext:
        """Create all components and return a populated AgentContext."""
        config = self._config
        sd = self._startup_data

        discovery = MarketDiscovery(config)
        market_data = MarketDataProvider(config)
        decision_engine = DecisionEngine(config.ai)
        execution_sim = ExecutionSimulator(config.simulator)
        orderbook = SimulatedOrderBook(config.simulator)
        portfolio = Portfolio(config.agent.initial_cash)
        risk = RiskManager(config.risk, config.agent.initial_cash)

        # Live trading engine (created if mode == "live")
        live_mode = config.trading.mode == "live"
        live_engine: LiveExecutionEngine | None = None
        shadow_portfolio: Portfolio | None = None

        if live_mode:
            live_engine = LiveExecutionEngine(config.trading, config.api)
            shadow_portfolio = Portfolio(config.agent.initial_cash)
            self._log.warning(
                "LIVE TRADING MODE — real CLOB orders will be placed%s",
                " (DRY RUN)" if config.trading.dry_run else "",
            )

        trade_log = TradeLog(config.logging)
        resolution_tracker = ResolutionTracker(
            MarketDataResolutionRepo(market_data._btc, market_data._rest),
        )
        prefilter = PreFilter()
        calibrator = ConfidenceCalibrator(data_dir=Path(config.logging.log_dir))
        exit_tracker = ExitTracker(data_dir=Path(config.logging.log_dir))
        adaptive_entry = AdaptiveEntryTracker(
            data_dir=Path(config.logging.log_dir),
            window=config.monitor.adaptive_entry_window,
        )
        ml_scorer = MLScorer(data_dir=Path(config.logging.log_dir))
        knowledge_manager = KnowledgeManager(config.logging.knowledge_dir, config.ai)
        feature_config = FeatureConfig(Path(config.logging.knowledge_dir).parent / "feature_config.json")
        processor = IndicatorsProcessor(all_indicators(), feature_config)

        # WebSocket broadcaster (server owned by TradingAgent)
        broadcaster = Broadcaster()

        # SQLite analytics store
        datastore: DataStore | None = None
        if config.logging.sqlite_enabled:
            datastore = DataStore(config.logging.sqlite_db_path)

        # Persistent market history store (never deleted by archive)
        iteration_label = sd.iteration_label
        market_history = MarketHistoryStore(
            config.logging.market_history_db_path,
            iteration=iteration_label,
        )

        shared = SharedState()

        if sd.knowledge_state:
            knowledge_manager.load_state(sd.knowledge_state)

        ctx = AgentContext(
            config=config,
            discovery=discovery,
            market_data=market_data,
            decision_engine=decision_engine,
            execution_sim=execution_sim,
            orderbook=orderbook,
            portfolio=portfolio,
            risk=risk,
            trade_log=trade_log,
            resolution_tracker=resolution_tracker,
            prefilter=prefilter,
            calibrator=calibrator,
            exit_tracker=exit_tracker,
            adaptive_entry=adaptive_entry,
            ml_scorer=ml_scorer,
            knowledge_manager=knowledge_manager,
            feature_config=feature_config,
            processor=processor,
            shared=shared,
            live_mode=live_mode,
            live_engine=live_engine,
            shadow_portfolio=shadow_portfolio,
            broadcaster=broadcaster,
            datastore=datastore,
            market_history=market_history,
            bot_version=__version__,
            state_path=Path(config.logging.log_dir) / "agent_state.json",
        )

        ctx.resolutions_since_reflection = sd.resolutions_since_reflection
        ctx.historical_resolutions = sd.historical_resolutions
        ctx.historical_trades = sd.historical_trades
        ctx.iteration_summaries = sd.iteration_summaries

        return ctx
