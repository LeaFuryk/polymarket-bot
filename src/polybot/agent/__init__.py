"""Agent package — orchestrates concurrent trading tasks."""

from polybot.agent.context import AgentContext
from polybot.agent.core import TradingAgent
from polybot.agent.dashboard import (
    assemble_dashboard_data,
    sync_from_ai_decision,
    write_dashboard_json,
)
from polybot.agent.factory import ContextFactory
from polybot.agent.helpers import enrich_iteration_summary

__all__ = [
    "AgentContext",
    "ContextFactory",
    "TradingAgent",
    "assemble_dashboard_data",
    "enrich_iteration_summary",
    "sync_from_ai_decision",
    "write_dashboard_json",
]
