"""Agent package — orchestrates concurrent trading tasks."""

from polybot.agent.context import AgentContext
from polybot.agent.core import TradingAgent
from polybot.agent.dashboard import DashboardAssembler, enrich_iteration_summary
from polybot.agent.helpers import compute_pnl_from_trades, setup_logging
from polybot.agent.rotation import RotationManager
from polybot.agent.state import StatePersistence

__all__ = [
    "AgentContext",
    "DashboardAssembler",
    "RotationManager",
    "StatePersistence",
    "TradingAgent",
    "compute_pnl_from_trades",
    "enrich_iteration_summary",
    "setup_logging",
]
