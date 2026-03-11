"""AgentContext — typed container for sub-component references.

Extracted modules receive AgentContext instead of importing TradingAgent,
breaking the circular dependency between the agent and its consumers
(e.g. broadcaster, dashboard assembler).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.adaptive_entry import AdaptiveEntryTracker
    from polybot.calibration import ConfidenceCalibrator
    from polybot.config import AppConfig
    from polybot.datastore import DataStore, MarketHistoryStore
    from polybot.decision_engine.engine import DecisionEngine
    from polybot.execution.live import LiveExecutionEngine
    from polybot.exit_tracker import ExitTracker
    from polybot.indicators import FeatureConfig
    from polybot.knowledge import KnowledgeManager
    from polybot.logging.trade_log import TradeLog
    from polybot.market_data.discovery import MarketDiscovery
    from polybot.market_data.provider import MarketDataProvider
    from polybot.ml_scorer import MLScorer
    from polybot.models import CandleMarket, ResolutionRecord, TradeRecord
    from polybot.prefilter import PreFilter
    from polybot.resolution import ResolutionTracker
    from polybot.risk.manager import RiskManager
    from polybot.shared_state import SharedState
    from polybot.simulator.engine import ExecutionSimulator
    from polybot.simulator.orderbook import SimulatedOrderBook
    from polybot.simulator.portfolio import Portfolio
    from polybot.ws.broadcaster import DashboardBroadcaster


@dataclass
class AgentContext:
    """Typed references to all sub-components used by extracted agent modules."""

    # Core configuration
    config: AppConfig

    # Sub-components
    discovery: MarketDiscovery
    market_data: MarketDataProvider
    decision_engine: DecisionEngine
    execution_sim: ExecutionSimulator
    orderbook: SimulatedOrderBook
    portfolio: Portfolio
    risk: RiskManager
    trade_log: TradeLog
    resolution_tracker: ResolutionTracker
    prefilter: PreFilter
    calibrator: ConfidenceCalibrator
    exit_tracker: ExitTracker
    adaptive_entry: AdaptiveEntryTracker
    ml_scorer: MLScorer
    knowledge_manager: KnowledgeManager
    feature_config: FeatureConfig
    shared: SharedState

    # WebSocket dashboard
    ws_broadcaster: DashboardBroadcaster

    # Market history store
    market_history: MarketHistoryStore

    # Live trading
    live_mode: bool = False
    live_engine: LiveExecutionEngine | None = None
    shadow_portfolio: Portfolio | None = None

    # Datastores (optional)
    datastore: DataStore | None = None

    # Current state
    current_market: CandleMarket | None = None
    bot_version: str = "unknown"
    state_path: Path = field(default_factory=lambda: Path("logs/agent_state.json"))

    # Outage tracking
    discovery_failures: int = 0
    outage_start: float | None = None
    outage_recovered: float | None = None
    last_outage_duration: float = 0.0

    # Dashboard display state
    last_action: str = "\u2014"
    last_reasoning: str = ""
    last_risk_status: str = "OK"
    last_token_side: str = ""

    # Session stats
    session_wins: int = 0
    session_losses: int = 0
    session_resolution_pnl: float = 0.0
    last_resolution: ResolutionRecord | None = None

    # AI cost tracking
    total_api_cost: float = 0.0
    last_cycle_api_cost: float = 0.0

    # ML features for training after resolution
    pending_ml_features: dict[str, dict[str, float]] = field(default_factory=dict)

    # History (loaded from logs)
    historical_resolutions: list[dict] = field(default_factory=list)
    historical_trades: list[dict] = field(default_factory=list)

    # Session lists
    recent_resolutions: list[ResolutionRecord] = field(default_factory=list)
    session_resolutions: list[ResolutionRecord] = field(default_factory=list)
    recent_trades: list[TradeRecord] = field(default_factory=list)
    session_trades: list[TradeRecord] = field(default_factory=list)
    resolutions_since_reflection: int = 0

    # Iteration summaries (loaded from archive)
    iteration_summaries: list[dict] = field(default_factory=list)
