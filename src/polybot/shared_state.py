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

        # Shutdown flag
        self.shutdown: bool = False
