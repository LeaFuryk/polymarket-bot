"""Cross-feature aggregation — assemble a complete ForensicsReport."""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime

from .blocked import analyze_blocked
from .context import analyze_context
from .costs import analyze_costs
from .execution import analyze_orders
from .roundtrips import analyze_roundtrips
from .ttl import analyze_ttl
from .types import ForensicsReport


def build_report(
    conn: sqlite3.Connection,
    db_path: str,
    *,
    logger: logging.Logger | None = None,
) -> ForensicsReport:
    """Run all 6 feature analyses and return a complete ForensicsReport."""
    logger = logger or logging.getLogger(__name__)
    order_metrics, aggregate_metrics = analyze_orders(conn, logger=logger)
    ttl_cfs, ttl_agg = analyze_ttl(conn, logger=logger)
    cost_bds, cost_agg = analyze_costs(conn, logger=logger)
    blocked_orders, blocked_agg = analyze_blocked(conn, logger=logger)
    round_trips = analyze_roundtrips(conn, logger=logger)
    decision_contexts = analyze_context(conn, logger=logger)

    return ForensicsReport(
        generated_at=datetime.now(UTC).isoformat(),
        db_path=db_path,
        order_metrics=order_metrics,
        aggregate_metrics=aggregate_metrics,
        ttl_counterfactuals=ttl_cfs,
        ttl_aggregate=ttl_agg,
        cost_breakdowns=cost_bds,
        cost_aggregate=cost_agg,
        blocked_orders=blocked_orders,
        blocked_aggregate=blocked_agg,
        round_trips=round_trips,
        decision_contexts=decision_contexts,
    )
