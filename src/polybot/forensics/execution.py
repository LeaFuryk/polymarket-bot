"""Feature A: Order execution metrics — latency, drift, fill source analysis."""

from __future__ import annotations

import logging
import sqlite3

from .constants import BPS_MULTIPLIER
from .db import load_orders
from .types import AggregateMetrics, OrderMetrics


def _percentile(values: list[float], pct: float) -> float | None:
    """Compute percentile from a sorted list."""
    if not values:
        return None
    s = sorted(values)
    idx = int(len(s) * pct)
    idx = min(idx, len(s) - 1)
    return s[idx]


def analyze_orders(
    conn: sqlite3.Connection,
    *,
    logger: logging.Logger | None = None,
) -> tuple[list[OrderMetrics], AggregateMetrics]:
    """Extract per-order execution metrics from live_order_json."""
    logger = logger or logging.getLogger(__name__)
    rows = load_orders(conn)
    metrics: list[OrderMetrics] = []
    latencies: list[float] = []
    drifts: list[float] = []
    source_counts: dict[str, int] = {}

    for d in rows:
        lo = d.get("_live_order")
        if lo is None:
            continue

        action = d.get("action", "")
        if action not in ("BUY", "SELL"):
            continue

        order_id = lo.get("order_id", "")
        if not order_id:
            continue

        decision_ts = d.get("timestamp", 0.0)
        submit_ts = lo.get("submit_ts", 0.0)
        decision_to_submit_ms = (submit_ts - decision_ts) * 1000 if submit_ts and decision_ts else 0.0

        decision_ask = lo.get("decision_ob_ask")
        ob_at_submit = lo.get("ob_at_submit") or {}
        submit_ask = ob_at_submit.get("best_ask")

        ask_drift_bps = None
        if decision_ask and submit_ask and decision_ask > 0:
            ask_drift_bps = (submit_ask - decision_ask) / decision_ask * BPS_MULTIPLIER
            drifts.append(ask_drift_bps)

        fill_ts = lo.get("fill_ts")
        fill_source = lo.get("fill_source", "")
        filled = fill_ts is not None and fill_source != ""

        fill_latency_ms = None
        if filled and fill_ts and submit_ts:
            fill_latency_ms = (fill_ts - submit_ts) * 1000
            latencies.append(fill_latency_ms)

        pre_bal = lo.get("pre_balance")
        post_bal = lo.get("post_balance")
        balance_delta = None
        if pre_bal is not None and post_bal is not None:
            balance_delta = post_bal - pre_bal

        src = fill_source or "timeout"
        source_counts[src] = source_counts.get(src, 0) + 1

        metrics.append(
            OrderMetrics(
                order_id=order_id,
                candle_id=d.get("candle_id", 0),
                side=action,
                decision_ts=decision_ts,
                submit_ts=submit_ts,
                decision_to_submit_ms=decision_to_submit_ms,
                decision_ask=decision_ask,
                submit_ask=submit_ask,
                ask_drift_bps=ask_drift_bps,
                filled=filled,
                fill_source=fill_source,
                fill_ts=fill_ts,
                fill_latency_ms=fill_latency_ms,
                ttl_used=lo.get("ttl_used", 3),
                polls=lo.get("polls", []),
                balance_delta=balance_delta,
            )
        )

    filled_count = sum(1 for m in metrics if m.filled)
    total = len(metrics)

    agg = AggregateMetrics(
        total_orders=total,
        filled_count=filled_count,
        fill_rate=filled_count / total if total > 0 else 0.0,
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        max_latency_ms=max(latencies) if latencies else None,
        p50_drift_bps=_percentile(drifts, 0.50),
        p95_drift_bps=_percentile(drifts, 0.95),
        by_fill_source=source_counts,
    )

    return metrics, agg
