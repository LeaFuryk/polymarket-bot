"""Agent package — orchestrates concurrent trading tasks."""

from polybot.agent.context import AgentContext
from polybot.agent.core import TradingAgent
from polybot.agent.dashboard import (
    assemble_dashboard_data,
    enrich_iteration_summary,
    sync_from_ai_decision,
    write_dashboard_json,
)
from polybot.agent.factory import ContextFactory
from polybot.agent.helpers import compute_pnl_from_trades, setup_logging
from polybot.agent.state import StatePersistence

__all__ = [
    "AgentContext",
    "ContextFactory",
    "StatePersistence",
    "TradingAgent",
    "assemble_dashboard_data",
    "compute_pnl_from_trades",
    "enrich_iteration_summary",
    "setup_logging",
    "sync_from_ai_decision",
    "write_dashboard_json",
]
