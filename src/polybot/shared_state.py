"""Shared state hub for multi-task architecture.

Central coordination between MarketMonitor, AIDecision, and PositionMonitor
tasks. All tasks run as asyncio.Tasks in the same event loop (no OS threads),
so shared state access is safe without locks.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field

from polybot.models import CandleMarket


@dataclass
class EntryContext:
    """Market conditions at entry (fill) time — used by dynamic SL/TP."""

    entry_price: float = 0.0
    entry_time: float = 0.0
    ml_up_probability: float = 0.5
    ml_confidence: str = "neutral"
    btc_move_at_entry: float = 0.0
    reversal_rate_at_entry: float = 0.0
    confidence_at_entry: float = 0.0


@dataclass
class CandleMicrostructure:
    """End-of-candle microstructure summary for cross-candle memory."""

    timestamp: float = 0.0
    avg_spread_up: float = 0.0
    avg_spread_down: float = 0.0
    avg_depth: float = 0.0
    avg_imbalance: float = 1.0  # bid/ask ratio (>1 = bid-heavy)
    btc_range: float = 0.0  # high - low of BTC move within candle
    btc_final_move: float = 0.0


@dataclass
class PreFilterSnapshot:
    """Records market state every second from the market monitor."""

    timestamp: float
    time_remaining: float
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    best_entry_up: float = 1.0
    best_entry_down: float = 1.0
    rr_up: float = 0.0
    rr_down: float = 0.0
    btc_price: float = 0.0
    up_mid: float | None = None
    down_mid: float | None = None
    up_spread_pct: float | None = None
    down_spread_pct: float | None = None
    streak: int = 0
    streak_direction: str = ""
    btc_move_from_open: float = 0.0


class SharedState:
    """Central coordination hub for concurrent tasks."""

    def __init__(self) -> None:
        # Latest market data
        self.latest_snapshot = None  # MarketSnapshot
        self.snapshot_timestamp: float = 0.0

        # Current candle info
        self.current_market: CandleMarket | None = None
        self.candle_open_btc: float | None = None

        # Pre-filter snapshot history (~5 min at 1/s)
        self.prefilter_history: deque[PreFilterSnapshot] = deque(maxlen=300)

        # AI trigger coordination
        self.ai_trigger_event: asyncio.Event = asyncio.Event()
        self.ai_trigger_reason: str = ""
        self.ai_last_call_time: float = 0.0

        # Position monitor → AI exit signals
        self.exit_trigger_queue: asyncio.Queue[dict] = asyncio.Queue()

        # Real-time P&L for dashboard
        self.position_pnl_pct: dict[str, float] = {}

        # Candle rotation coordination
        self.rotation_in_progress: bool = False

        # Session resolution stats (synced from agent for indicator computation)
        self.session_wins: int = 0
        self.session_losses: int = 0

        # Cross-candle microstructure memory (last 5 candles)
        self.microstructure_history: list[CandleMicrostructure] = []

        # Post-stop-loss cooldown: records last stop-loss exit on current candle
        self.last_stop_loss: dict | None = None
        # Format: {"token_side": "up", "pnl_pct": -0.25, "timestamp": 1234.0}

        # Dynamic SL/TP context
        self.entry_context: dict[str, EntryContext] = {}  # "up"/"down" → context
        self.reversal_rate: float = 0.0  # from AdaptiveEntryTracker
        self.signal_type: str = "UNCERTAIN"  # MOMENTUM/UNCERTAIN/CONTRARIAN
        self.regime: str = "MODERATE"  # CALM/MODERATE/CHOPPY
        self.dynamic_sl: dict[str, float] = {}  # for dashboard display
        self.dynamic_tp: dict[str, float] = {}

        # Real-time monitor status (updated every tick by MarketMonitor)
        # Shows the full gate pipeline: prefilter → adaptive → cooldown → trigger
        self.monitor_status: dict = {}

        # Tech metrics for WS status updates
        self.api_latencies: dict[str, float] = {}
        self.ws_client_count: int = 0
        self.sqlite_queue_depth: int = 0

        # Shutdown flag
        self.shutdown: bool = False
