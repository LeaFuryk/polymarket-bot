"""Agent package — orchestrates concurrent trading tasks."""

from polybot.agent.context import AgentContext
from polybot.agent.core import TradingAgent
from polybot.agent.dashboard import (
    assemble_dashboard_data,
    sync_from_ai_decision,
    write_dashboard_json,
)
from polybot.agent.factory import ContextFactory
from polybot.agent.helpers import (
    StartupData,
    compute_pnl_from_trades,
    enrich_iteration_summary,
    load_startup_data,
)
from polybot.logging import create_logger

__all__ = [
    "AgentContext",
    "ContextFactory",
    "StartupData",
    "TradingAgent",
    "assemble_dashboard_data",
    "compute_pnl_from_trades",
    "enrich_iteration_summary",
    "load_startup_data",
    "create_logger",
    "sync_from_ai_decision",
    "write_dashboard_json",
]
