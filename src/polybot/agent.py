"""Core trading agent — orchestrates concurrent tasks with dynamic market discovery."""

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

from polybot.adaptive_entry import AdaptiveEntryTracker
from polybot.calibration import ConfidenceCalibrator
from polybot.config import AppConfig
from polybot.datastore import DataStore, MarketHistoryStore
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
from polybot.market_data.chainlink_ws import ChainlinkWSFeed
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
from polybot.shared_state import SharedState
from polybot.simulator.engine import ExecutionSimulator
from polybot.simulator.orderbook import SimulatedOrderBook
from polybot.simulator.portfolio import Portfolio
from polybot.tasks.market_monitor import MarketMonitor
from polybot.tasks.ai_decision import AIDecision
from polybot.tasks.position_monitor import PositionMonitor

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
    """Orchestrator — launches concurrent tasks for market monitoring, AI decisions, and position management."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

        # Sub-components
        self._chainlink_ws = ChainlinkWSFeed(config.api.polymarket_rtds_url)
        self._discovery = MarketDiscovery(config)
        self._market_data = MarketDataProvider(config, chainlink_ws=self._chainlink_ws)
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
        self._resolutions_since_reflection: int = 0

        # Restore persisted state
        self._state_path = Path(config.logging.log_dir) / "agent_state.json"
        self._load_agent_state()

        # Current candle market
        self._current_market: CandleMarket | None = None

        # Outage tracking
        self._discovery_failures: int = 0
        self._outage_start: float | None = None  # epoch when outage began
        self._outage_recovered: float | None = None  # epoch when recovered (shown briefly)
        self._last_outage_duration: float = 0.0  # seconds of last outage

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
        self._pending_ml_features: dict[str, dict[str, float]] = {}

        # SQLite analytics store
        self._datastore: DataStore | None = None
        if config.logging.sqlite_enabled:
            self._datastore = DataStore(config.logging.sqlite_db_path)

        # Persistent market history store (never deleted by archive)
        iteration_label = self._compute_iteration_label()
        self._market_history = MarketHistoryStore(
            config.logging.market_history_db_path,
            iteration=iteration_label,
        )

        # Load archived iteration summaries for dashboard
        self._iteration_summaries = self._load_iteration_summaries()

        # Shared state for concurrent tasks
        self._shared = SharedState()

        # Task objects (created in run())
        self._ai_decision: AIDecision | None = None
        self._position_monitor: PositionMonitor | None = None

    async def run(self) -> None:
        """Main entry point — launches concurrent tasks."""
        _setup_logging(self._config)
        logger.info("TradingAgent starting — cash=%.2f", self._config.agent.initial_cash)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

        # Open SQLite analytics store
        if self._datastore is not None:
            self._datastore.open()

        # Open persistent market history store
        self._market_history.open()

        # Start Chainlink WebSocket feed (primary BTC price — matches resolution)
        await self._chainlink_ws.start()

        # Load BTC 5-min candle history
        await self._market_data.btc_feed.load_candle_history(200)

        # Bootstrap adaptive entry from Binance if insufficient history
        await self._adaptive_entry.bootstrap_from_binance()

        # Resolve any pending bets from previous sessions
        await self._resolve_pending_bets()

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
        )

        if self._datastore is not None:
            self._ai_decision._datastore = self._datastore

        self._position_monitor = PositionMonitor(
            config=self._config,
            shared=self._shared,
            portfolio=self._portfolio,
        )

        # Launch all tasks concurrently
        tasks = [
            asyncio.create_task(market_monitor.run(), name="market_monitor"),
            asyncio.create_task(self._ai_decision.run(), name="ai_decision"),
            asyncio.create_task(self._position_monitor.run(), name="position_monitor"),
            asyncio.create_task(self._rotation_loop(), name="rotation_loop"),
            asyncio.create_task(self._dashboard_loop(), name="dashboard_loop"),
        ]
        if self._datastore is not None:
            tasks.append(
                asyncio.create_task(self._datastore.writer_loop(), name="datastore_writer")
            )
        tasks.append(
            asyncio.create_task(self._market_history.writer_loop(), name="market_history_writer")
        )

        try:
            # Wait until shutdown
            while not self._shared.shutdown:
                await asyncio.sleep(0.5)

            # Signal all tasks to stop
            logger.info("Shutdown: waiting for tasks to complete...")
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await self._shutdown_components()

    def _load_iteration_summaries(self) -> list[dict]:
        """Load archived iteration summaries enriched with analysis data."""
        archive_dir = Path.cwd() / "archive"
        summaries = []
        if not archive_dir.exists():
            return summaries
        for summary_path in sorted(archive_dir.glob("*/summary.json")):
            try:
                data = json.loads(summary_path.read_text())
                iter_dir = summary_path.parent
                # Enrich with data from archived dashboard_data.json
                dash_path = iter_dir / "logs" / "dashboard_data.json"
                if dash_path.exists():
                    dd = json.loads(dash_path.read_text())
                    self._enrich_iteration_summary(data, dd, iter_dir)
                summaries.append(data)
            except Exception:
                logger.debug("Could not load summary: %s", summary_path, exc_info=True)
        if summaries:
            logger.info("Loaded %d iteration summaries from archive", len(summaries))
        return summaries

    @staticmethod
    def _enrich_iteration_summary(summary: dict, dd: dict, archive_dir: Path | None = None) -> None:
        """Add calibration, exit, trade, and resolution analysis to a summary."""
        # Calibration
        cal = dd.get("calibration", {})
        summary["calibration"] = {
            "total_records": cal.get("total_records", 0),
            "shadow_accuracy": cal.get("shadow_accuracy"),
            "shadow_total": cal.get("shadow_total", 0),
            "bins": cal.get("bins", []),
        }

        # Exit analysis
        ex = dd.get("exit_analysis", {})
        summary["exit_analysis"] = {
            "total_exits": ex.get("total_exits", 0),
            "good_exit_rate": ex.get("good_exit_rate", 0),
            "good_exits": ex.get("good_exits", 0),
            "total_saved": ex.get("total_saved", 0),
            "total_missed": ex.get("total_missed", 0),
        }

        # ML model
        ml = dd.get("ml_model", {})
        summary["ml_model"] = {
            "training_samples": ml.get("training_samples", 0),
            "model_trained": ml.get("model_trained", False),
        }

        # Trade analysis
        trades = dd.get("trades", [])
        buys = [t for t in trades if t.get("action") == "BUY" and not t.get("risk_blocked")]
        sells = [t for t in trades if t.get("action") == "SELL" and not t.get("risk_blocked")]
        holds = [t for t in trades if t.get("action") == "HOLD"]
        fills = [t["fill_price"] for t in buys if t.get("fill_price")]
        confs = [t["confidence"] for t in buys if t.get("confidence")]

        avg_fill = sum(fills) / len(fills) if fills else 0
        avg_conf = sum(confs) / len(confs) if confs else 0

        summary["trade_analysis"] = {
            "total_buys": len(buys),
            "total_sells": len(sells),
            "total_holds": len(holds),
            "avg_fill_price": round(avg_fill, 4),
            "cheap_entries": len([f for f in fills if f < 0.40]),
            "mid_entries": len([f for f in fills if 0.40 <= f < 0.60]),
            "expensive_entries": len([f for f in fills if f >= 0.60]),
            "avg_confidence": round(avg_conf, 4),
            "hold_rate": round(len(holds) / len(trades), 3) if trades else 0,
        }

        # Resolution analysis
        ress = dd.get("resolutions", [])
        btc_moves = [abs(r.get("btc_move", 0)) for r in ress]
        pnls = [r.get("pnl", 0) for r in ress]
        win_pnls = [p for p in pnls if p > 0.001]
        loss_pnls = [p for p in pnls if p < -0.001]

        summary["resolution_analysis"] = {
            "total": len(ress),
            "avg_btc_move": round(sum(btc_moves) / len(btc_moves), 1) if btc_moves else 0,
            "max_btc_move": round(max(btc_moves), 1) if btc_moves else 0,
            "avg_win_pnl": round(sum(win_pnls) / len(win_pnls), 4) if win_pnls else 0,
            "avg_loss_pnl": round(sum(loss_pnls) / len(loss_pnls), 4) if loss_pnls else 0,
            "biggest_win": round(max(win_pnls), 4) if win_pnls else 0,
            "biggest_loss": round(min(loss_pnls), 4) if loss_pnls else 0,
            "cumulative_pnl": [round(sum(pnls[:i + 1]), 4) for i in range(len(pnls))],
        }

        # Per-resolution detail for table view
        summary["resolutions_detail"] = [{
            "slug": r.get("slug", ""),
            "pnl": r.get("pnl", 0),
            "btc_move": r.get("btc_move", 0),
            "resolution": r.get("resolution", ""),
        } for r in ress]

        # Observations from knowledge base
        if archive_dir:
            obs_file = archive_dir / "data" / "knowledge" / "observations.jsonl"
            if obs_file.exists():
                observations = []
                for line in obs_file.read_text().splitlines():
                    if line.strip():
                        try:
                            rec = json.loads(line)
                            observations.append({
                                "category": rec.get("category", ""),
                                "text": rec.get("text", ""),
                                "timestamp": rec.get("timestamp", ""),
                            })
                        except json.JSONDecodeError:
                            pass
                summary["observations"] = observations

            # Session history markdown
            sh_file = archive_dir / "data" / "knowledge" / "session_history.md"
            if sh_file.exists():
                summary["session_history"] = sh_file.read_text()

    def _compute_iteration_label(self) -> str:
        """Determine current iteration label from archive count."""
        archive_dir = Path.cwd() / "archive"
        if not archive_dir.exists():
            return "iter_001"
        existing = sorted(
            d.name for d in archive_dir.iterdir()
            if d.is_dir() and d.name.startswith("iter_")
        )
        if not existing:
            return "iter_001"
        last_num = max(int(d.split("_")[1]) for d in existing)
        return f"iter_{last_num + 1:03d}"

    def _handle_signal(self) -> None:
        logger.info("Shutdown signal received")
        self._shared.shutdown = True

    async def _rotation_loop(self) -> None:
        """Discovers markets and handles candle transitions (every 5s)."""
        logger.info("RotationLoop started")
        while not self._shared.shutdown:
            try:
                await self._discover_market()
            except Exception:
                logger.exception("RotationLoop error")
            await asyncio.sleep(5.0)
        logger.info("RotationLoop stopped")

    async def _dashboard_loop(self) -> None:
        """Writes dashboard JSON from shared state (every 2s)."""
        logger.info("DashboardLoop started")
        while not self._shared.shutdown:
            try:
                self._sync_from_ai_decision()
                snapshot = self._shared.latest_snapshot
                if snapshot is not None:
                    self._write_dashboard_json(0, snapshot)
            except Exception:
                logger.debug("DashboardLoop error", exc_info=True)
            await asyncio.sleep(2.0)
        logger.info("DashboardLoop stopped")

    def _sync_from_ai_decision(self) -> None:
        """Sync dashboard state from the AIDecision task."""
        if self._ai_decision is None:
            return
        self._last_action = self._ai_decision.last_action
        self._last_reasoning = self._ai_decision.last_reasoning
        self._last_risk_status = self._ai_decision.last_risk_status
        self._last_token_side = self._ai_decision.last_token_side
        self._session_wins = self._ai_decision.session_wins
        self._session_losses = self._ai_decision.session_losses
        self._session_resolution_pnl = self._ai_decision.session_resolution_pnl
        self._total_api_cost = self._ai_decision.total_api_cost
        self._last_cycle_api_cost = self._ai_decision.last_cycle_api_cost

    async def _discover_market(self) -> CandleMarket | None:
        """Discover the current candle market, handling rotation and outages."""
        new_market = await self._discovery.get_current_market()
        if new_market is None:
            new_market = await self._discovery.get_next_market()

        if new_market is None:
            self._discovery_failures += 1
            if self._discovery_failures >= 3 and self._outage_start is None:
                self._outage_start = time.time()
                logger.warning(
                    "Polymarket outage detected: %d consecutive discovery failures",
                    self._discovery_failures,
                )
            elif self._outage_start is not None:
                elapsed = time.time() - self._outage_start
                if self._discovery_failures % 12 == 0:  # every ~60s
                    logger.warning(
                        "Polymarket outage ongoing: %.0fs elapsed (%d failures)",
                        elapsed, self._discovery_failures,
                    )
            return self._current_market

        # Market found — clear outage state
        recovering_from_outage = self._outage_start is not None
        if recovering_from_outage:
            duration = time.time() - self._outage_start
            self._last_outage_duration = duration
            self._outage_recovered = time.time()
            logger.info(
                "Polymarket outage recovered after %.0fs (%d failures)",
                duration, self._discovery_failures,
            )
        self._discovery_failures = 0
        self._outage_start = None
        # Clear recovery banner after 60s
        if self._outage_recovered and time.time() - self._outage_recovered > 60:
            self._outage_recovered = None

        # Check if market has rotated
        if self._current_market and new_market.condition_id != self._current_market.condition_id:
            if recovering_from_outage:
                # After outage: skip resolution of missed candles — just jump to new market
                logger.info(
                    "Post-outage recovery: skipping resolution of %s, jumping to %s",
                    self._current_market.slug, new_market.slug,
                )
                # Cancel any stale orders from the pre-outage market
                cancelled = self._orderbook.cancel_all()
                if cancelled:
                    logger.info("Cancelled %d stale orders from pre-outage market", cancelled)
            else:
                logger.info(
                    "Market rotation: %s → %s",
                    self._current_market.slug, new_market.slug,
                )
                await self._handle_market_transition()

        if self._current_market is None or new_market.condition_id != self._current_market.condition_id:
            self._current_market = new_market
            self._market_data.set_market(new_market)

            # Update shared state
            self._shared.current_market = new_market

            logger.info("Active market: %s (ends in %.0fs)", new_market.title, new_market.time_remaining())

            # Record BTC price at candle open
            btc_snapshot = await self._market_data.btc_feed.get_price()
            if btc_snapshot:
                self._resolution_tracker.record_candle_open(new_market, btc_snapshot.price_usd)
                self._shared.candle_open_btc = btc_snapshot.price_usd

                # Begin candle in SQLite analytics
                if self._datastore is not None:
                    self._datastore.begin_candle(
                        condition_id=new_market.condition_id,
                        slug=new_market.slug,
                        title=new_market.title,
                        start_time=new_market.start_time,
                        end_time=new_market.end_time,
                        btc_open=btc_snapshot.price_usd,
                    )

                # Begin candle in persistent market history
                self._market_history.begin_candle(
                    condition_id=new_market.condition_id,
                    slug=new_market.slug,
                    start_time=new_market.start_time,
                    end_time=new_market.end_time,
                    btc_open=btc_snapshot.price_usd,
                )

        return self._current_market

    async def _handle_market_transition(self) -> None:
        """Handle transition between candle markets — resolve winner via BTC price."""
        # Pause other tasks during rotation
        self._shared.rotation_in_progress = True

        try:
            # Cancel pending limit orders
            cancelled = self._orderbook.cancel_all()
            if cancelled:
                logger.info("Cancelled %d pending orders on market rotation", cancelled)

            # Resolve candle winner
            if self._current_market is not None:
                btc_snapshot = await self._market_data.btc_feed.get_price()
                btc_price = btc_snapshot.price_usd if btc_snapshot else 0.0

                resolution = await self._resolution_tracker.resolve(
                    self._current_market, btc_price,
                )

                resolution_pnl = self._portfolio.resolve_market(resolution.winner)
                resolution.total_pnl = resolution_pnl
                resolution.up_pnl = self._portfolio.up_position.realized_pnl
                resolution.down_pnl = self._portfolio.down_position.realized_pnl

                self._trade_log.write_resolution(resolution)
                self._last_resolution = resolution

                self._calibrator.record_outcome(resolution.slug, resolution.winner)
                self._exit_tracker.record_outcome(resolution.slug, resolution.winner)
                self._adaptive_entry.record_outcome(
                    slug=resolution.slug,
                    winner=resolution.winner,
                    btc_open=resolution.btc_open,
                    btc_close=resolution.btc_close,
                    prefilter_history=list(self._shared.prefilter_history),
                )

                # Train ML model
                ml_feats = self._pending_ml_features.pop(resolution.slug, None)
                if ml_feats:
                    self._ml_scorer.train(ml_feats, up_won=(resolution.winner == "up"))

                # Update session stats
                had_position = resolution_pnl != 0.0
                if had_position:
                    if resolution_pnl > 0:
                        self._session_wins += 1
                    else:
                        self._session_losses += 1
                    self._session_resolution_pnl += resolution_pnl

                # Resolve candle in SQLite analytics
                if self._datastore is not None and self._datastore.current_candle_id is not None:
                    self._datastore.resolve_candle(
                        candle_id=self._datastore.current_candle_id,
                        btc_close=resolution.btc_close,
                        winner=resolution.winner,
                        resolution_pnl=resolution_pnl,
                    )

                # Resolve candle in persistent market history
                if self._market_history.current_candle_id is not None:
                    self._market_history.resolve_candle(
                        candle_id=self._market_history.current_candle_id,
                        btc_close=resolution.btc_close,
                        winner=resolution.winner,
                    )

                # Sync stats to AI decision task
                if self._ai_decision:
                    self._ai_decision.session_wins = self._session_wins
                    self._ai_decision.session_losses = self._session_losses
                    self._ai_decision.session_resolution_pnl = self._session_resolution_pnl

                # Sync stats to SharedState for indicator computation in MarketMonitor
                self._shared.session_wins = self._session_wins
                self._shared.session_losses = self._session_losses

                logger.info(
                    "Resolution: %s winner=%s pnl=%.4f | Session: W%d/L%d total_pnl=%.4f",
                    resolution.slug, resolution.winner, resolution_pnl,
                    self._session_wins, self._session_losses, self._session_resolution_pnl,
                )

                self._recent_resolutions.append(resolution)
                self._session_resolutions.append(resolution)  # uncapped — for dashboard
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
                    reflection_cost = self._knowledge_manager.last_reflection_cost
                    if reflection_cost > 0:
                        self._portfolio.cash -= reflection_cost
                        self._total_api_cost += reflection_cost
                        if self._ai_decision:
                            self._ai_decision.total_api_cost = self._total_api_cost
                        logger.info("Reflection API cost: $%.4f (session total: $%.4f)", reflection_cost, self._total_api_cost)

            # Reset positions and triggers for new market
            self._portfolio.reset_positions()
            if self._position_monitor:
                self._position_monitor.reset_triggers()

            # Clear exit trigger queue
            while not self._shared.exit_trigger_queue.empty():
                try:
                    self._shared.exit_trigger_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            # Reset shared state for new candle
            self._shared.candle_open_btc = None
            self._shared.position_pnl_pct.clear()
            self._shared.prefilter_history.clear()

        finally:
            self._shared.rotation_in_progress = False

    # --- Dashboard Data Writer ---

    def _compute_market_trend(self, snapshot) -> dict:
        """Compute market trend data for dashboard. Returns empty dict if not enough data."""
        if snapshot is None or len(snapshot.btc_candles) < 50:
            return {}
        from polybot.indicators import _ema

        closes = [c.close for c in snapshot.btc_candles]
        ema20 = _ema(closes, 20)
        ema50 = _ema(closes, 50)
        price = closes[-1]

        ema_sig = max(-1, min(1, (ema20 - ema50) / 100))
        price_sig = max(-1, min(1, (price - ema50) / 150))
        last12 = snapshot.btc_candles[-12:]
        up_r = sum(1 for c in last12 if c.direction == "up") / len(last12)
        candle_sig = (up_r - 0.5) * 2
        score = max(-1, min(1, 0.4 * ema_sig + 0.35 * price_sig + 0.25 * candle_sig))

        if score >= 0.5:
            label = "STRONG BULL"
        elif score >= 0.2:
            label = "BULL"
        elif score > -0.2:
            label = "NEUTRAL"
        elif score > -0.5:
            label = "BEAR"
        else:
            label = "STRONG BEAR"

        return {
            "market_trend": round(score, 3),
            "market_trend_label": label,
        }

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
                    "chainlink_price": snapshot.btc_price.chainlink_price,
                    "price_divergence": snapshot.btc_price.price_divergence,
                    "price_source": snapshot.btc_price.price_source,
                    "candle_sources": {
                        "chainlink": sum(1 for c in snapshot.btc_candles if c.source == "chainlink_ws"),
                        "binance": sum(1 for c in snapshot.btc_candles if c.source == "binance"),
                        "total": len(snapshot.btc_candles),
                    },
                }

            # Positions
            positions = {
                "up_shares": self._portfolio.up_position.shares,
                "up_avg_entry": self._portfolio.up_position.avg_entry_price,
                "down_shares": self._portfolio.down_position.shares,
                "down_avg_entry": self._portfolio.down_position.avg_entry_price,
            }

            # Position P&L from position monitor
            position_pnl = dict(self._shared.position_pnl_pct)

            # Trades list
            trades = []
            for t in self._session_trades:
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
                    "cash": t.cash,
                    "portfolio_value": t.portfolio_value,
                    "fee": t.fee_amount,
                    "realized_pnl": t.realized_pnl,
                    "unrealized_pnl": t.unrealized_pnl,
                    "ai_cost": t.ai_cost,
                }
                trades.append(trade_entry)

            # Resolutions list (use uncapped session list, not the reflection window)
            resolutions = []
            for r in self._session_resolutions:
                resolutions.append({
                    "timestamp": datetime.fromtimestamp(r.timestamp, tz=timezone.utc).isoformat(),
                    "slug": r.slug,
                    "winner": r.winner,
                    "btc_open": r.btc_open,
                    "btc_close": r.btc_close,
                    "btc_move": r.btc_close - r.btc_open,
                    "pnl": r.total_pnl,
                })

            # Merge historical + current session data (dedup resolutions by slug)
            all_trades = self._historical_trades + trades
            seen_slugs: set[str] = set()
            all_resolutions: list[dict] = []
            for r in self._historical_resolutions + resolutions:
                slug = r.get("slug", "")
                if slug and slug not in seen_slugs:
                    seen_slugs.add(slug)
                    all_resolutions.append(r)
                elif not slug:
                    all_resolutions.append(r)

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
                    "cycles_run": self._ai_decision._cycle_count if self._ai_decision else 0,
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
                "position_pnl": position_pnl,
                "trades": all_trades,
                "resolutions": all_resolutions,
                "risk": {
                    "daily_pnl": self._risk.state.daily_pnl,
                    "daily_trades": self._risk.state.daily_trades,
                    "daily_fees": self._risk.state.daily_fees,
                    "max_drawdown": self._risk.state.max_drawdown,
                    "is_halted": self._risk.state.is_halted,
                },
                "ml_model": {
                    "training_samples": self._ml_scorer._training_samples,
                    "model_trained": self._ml_scorer._training_samples >= self._ml_scorer._min_samples,
                },
                "calibration": {
                    "total_records": self._calibrator.total_records,
                    "shadow_correct": self._calibrator._shadow_correct,
                    "shadow_total": self._calibrator._shadow_total,
                    "shadow_accuracy": round(
                        self._calibrator._shadow_correct / self._calibrator._shadow_total, 3
                    ) if self._calibrator._shadow_total > 0 else None,
                    "bins": [
                        {
                            "range": f"{b.bin_lower:.0%}-{b.bin_upper:.0%}",
                            "wins": b.wins,
                            "losses": b.losses,
                            "win_rate": round(b.win_rate, 3),
                            "reliable": b.is_reliable,
                        }
                        for b in self._calibrator._bins.values()
                        if b.total > 0
                    ],
                },
                "exit_analysis": {
                    "total_exits": self._exit_tracker._total_exits,
                    "good_exits": self._exit_tracker._exits_better_than_hold,
                    "good_exit_rate": round(self._exit_tracker.good_exit_rate, 3),
                    "total_saved": round(self._exit_tracker._total_saved, 4),
                    "total_missed": round(self._exit_tracker._total_missed, 4),
                },
                "monitor": {
                    "prefilter_snapshots": len(self._shared.prefilter_history),
                    "ai_cooldown_remaining": max(0, self._config.monitor.ai_cooldown_seconds - (time.time() - self._shared.ai_last_call_time)),
                    "last_trigger_reason": self._shared.ai_trigger_reason,
                },
                "adaptive_entry": {
                    "enabled": self._config.monitor.adaptive_entry_enabled,
                    "btc_threshold": self._adaptive_entry.btc_threshold,
                    "max_entry_price": round(self._adaptive_entry.max_entry_price, 4),
                    "reversal_rate": round(self._adaptive_entry.rolling_reversal_rate, 4),
                    "regime": self._adaptive_entry.regime,
                    "signal_type": self._adaptive_entry.signal_type,
                    "has_enough_history": self._adaptive_entry.has_enough_history,
                    "window_size": self._adaptive_entry._window,
                    "history_count": len(self._adaptive_entry._history),
                    **self._compute_market_trend(snapshot),
                },
                "outage": {
                    "is_down": self._outage_start is not None,
                    "since": self._outage_start,
                    "duration": (time.time() - self._outage_start) if self._outage_start else 0,
                    "failures": self._discovery_failures,
                    "recovered": self._outage_recovered is not None,
                    "last_outage_duration": self._last_outage_duration,
                },
                "iterations": self._iteration_summaries,
            }

            dashboard_path.write_text(json.dumps(data, indent=2) + "\n")

            # Write iterations sidecar for dashboard (separate file so it works
            # even when the bot is running old code)
            if self._iteration_summaries:
                iter_path = dashboard_path.parent / "iterations.json"
                iter_path.write_text(json.dumps(self._iteration_summaries, indent=2) + "\n")
        except Exception:
            logger.debug("Failed to write dashboard JSON", exc_info=True)

    # --- Pending Bet Resolution ---

    async def _resolve_pending_bets(self) -> None:
        """Check for trades with no matching resolution and resolve them."""
        trades_by_slug: dict[str, list[dict]] = {}
        for t in self._historical_trades:
            slug = t.get("candle_slug", "")
            if not slug or slug == "unknown":
                continue
            trades_by_slug.setdefault(slug, []).append(t)

        resolved_slugs = {r.get("slug", "") for r in self._historical_resolutions}

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

        market = await self._discovery.fetch_market_by_slug(slug)
        if market is None:
            logger.warning("Could not fetch market for pending bet: %s (may be delisted)", slug)
            return

        now = time.time()
        if market.end_time > now:
            logger.info("Skipping pending bet %s — candle still live (ends in %.0fs)", slug, market.end_time - now)
            return

        btc_open = await self._market_data.btc_feed.get_price_at(market.start_time)
        btc_close = await self._market_data.btc_feed.get_price_at(market.end_time)

        if btc_open is None or btc_close is None:
            logger.warning("Could not fetch BTC prices for pending bet: %s (open=%s close=%s)", slug, btc_open, btc_close)
            return

        resolution = await self._resolution_tracker.resolve(market, btc_close)
        resolution.btc_open = btc_open
        resolution.btc_close = btc_close

        pnl = _compute_pnl_from_trades(trades, resolution.winner)
        resolution.total_pnl = pnl

        self._trade_log.write_resolution(resolution)

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
        """Load persisted state from disk."""
        try:
            if self._state_path.exists():
                data = json.loads(self._state_path.read_text())
                self._resolutions_since_reflection = data.get("resolutions_since_reflection", 0)
                self._knowledge_manager.load_state(data.get("knowledge", {}))
                logger.info("Loaded agent state: resolutions_since_reflection=%d", self._resolutions_since_reflection)
        except Exception:
            logger.warning("Could not load agent state, starting fresh")

        self._historical_resolutions: list[dict] = []
        self._historical_trades: list[dict] = []
        self._load_history_from_logs()

    def _load_history_from_logs(self) -> None:
        """Load past resolutions and trades from JSONL log files."""
        from datetime import datetime, timezone

        log_dir = Path(self._config.logging.log_dir)

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
                "knowledge": self._knowledge_manager.save_state(),
            }, indent=2) + "\n")
        except Exception:
            logger.warning("Could not save agent state")

    async def _shutdown_components(self) -> None:
        logger.info("Shutting down components...")
        await self._chainlink_ws.stop()
        if self._datastore is not None:
            await self._datastore.close()
        await self._market_history.close()
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
