"""SharedState — central coordination hub for concurrent tasks.

Created once in :class:`~polybot.agent.Agent` and injected into each task.
Groups related state into logical sections for clarity.  All tasks run as
``asyncio.Task`` instances in a single event loop, so attribute access is
safe without locks.
"""

from __future__ import annotations

from typing import Any

from polybot.indicators.results import IndicatorResults
from polybot.models import CandleMarket, MarketSnapshot
from polybot.shared_state.candle_microstructure import CandleMicrostructure
from polybot.shared_state.constants import (
    DEFAULT_REGIME,
    DEFAULT_SIGNAL_TYPE,
)
from polybot.shared_state.entry_context import EntryContext
from polybot.shared_state.stop_loss_record import StopLossRecord


class SharedState:
    """Central coordination hub for concurrent tasks.

    Created once in :class:`~polybot.agent.Agent` and passed to each task.
    Groups related state into logical sections for clarity.
    """

    def __init__(self) -> None:
        # -- Market data --
        self.latest_snapshot: MarketSnapshot | None = None
        self.snapshot_timestamp: float = 0.0

        # -- Current candle --
        self.current_market: CandleMarket | None = None
        self.candle_open_btc: float | None = None

        # -- Per-tick spread tracking (for microstructure computation at rotation) --
        self.tick_spreads_up: list[float] = []
        self.tick_spreads_down: list[float] = []

        # -- AI trigger coordination --
        self.ai_trigger_reason: str = ""
        self.ai_last_call_time: float = 0.0

        # -- Real-time P&L for dashboard --
        self.position_pnl_pct: dict[str, float] = {}

        # -- Candle rotation coordination --
        self.rotation_in_progress: bool = False

        # -- Session resolution stats --
        self.session_wins: int = 0
        self.session_losses: int = 0

        # -- Cross-candle microstructure memory (last 5 candles) --
        self.microstructure_history: list[CandleMicrostructure] = []

        # -- Stop-loss cooldown --
        self.last_stop_loss: StopLossRecord | None = None

        # -- Dynamic SL/TP context --
        self.entry_context: dict[str, EntryContext] = {}
        self.reversal_rate: float = 0.0
        self.signal_type: str = DEFAULT_SIGNAL_TYPE
        self.regime: str = DEFAULT_REGIME
        self.dynamic_sl: dict[str, float] = {}
        self.dynamic_tp: dict[str, float] = {}

        # -- Monitor status (updated every tick by MarketMonitor) --
        self.monitor_status: dict[str, Any] = {}

        # -- Tech metrics for WS status updates --
        self.api_latencies: dict[str, float] = {}
        self.ws_client_count: int = 0
        self.sqlite_queue_depth: int = 0

        # -- Latest indicator results (computed once per tick by MarketMonitor) --
        self.latest_indicator_results: IndicatorResults | None = None

        # -- Lifecycle --
        self.shutdown: bool = False
