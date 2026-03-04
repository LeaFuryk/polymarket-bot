"""Polybot forensics — offline execution analysis system.

Re-exports public names so callers can do::

    from polybot.forensics import ForensicsReport, build_report
"""

from __future__ import annotations

from .aggregate import build_report
from .blocked import analyze_blocked
from .context import analyze_context
from .costs import analyze_costs
from .execution import analyze_orders
from .protocols import Investigator
from .roundtrips import analyze_roundtrips
from .ttl import analyze_ttl
from .types import (
    AggregateMetrics,
    BlockedAggregate,
    BlockedOrder,
    CostAggregate,
    CostBreakdown,
    DecisionContext,
    ForensicsReport,
    OrderMetrics,
    RoundTrip,
    TTLAggregate,
    TTLCounterfactual,
)

__all__ = [
    # Protocol
    "Investigator",
    # Report builder
    "build_report",
    # Feature analyses
    "analyze_blocked",
    "analyze_context",
    "analyze_costs",
    "analyze_orders",
    "analyze_roundtrips",
    "analyze_ttl",
    # Models
    "AggregateMetrics",
    "BlockedAggregate",
    "BlockedOrder",
    "CostAggregate",
    "CostBreakdown",
    "DecisionContext",
    "ForensicsReport",
    "OrderMetrics",
    "RoundTrip",
    "TTLAggregate",
    "TTLCounterfactual",
]
