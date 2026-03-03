"""Shared state hub for multi-task architecture.

Provides a typed :class:`SharedState` container that coordinates data flow
between MarketMonitor, AIDecision, and PositionMonitor tasks.  The state
object is created once in :class:`~polybot.agent.Agent` and injected into
each task — it is **not** a module-level global.
"""

from polybot.shared_state.candle_microstructure import CandleMicrostructure
from polybot.shared_state.entry_context import EntryContext
from polybot.shared_state.prefilter_snapshot import PreFilterSnapshot
from polybot.shared_state.state import SharedState
from polybot.shared_state.stop_loss_record import StopLossRecord

__all__ = [
    "CandleMicrostructure",
    "EntryContext",
    "PreFilterSnapshot",
    "SharedState",
    "StopLossRecord",
]
