"""Feature C: Cost breakdown — fees, slippage, and decision-drift cost analysis."""

from __future__ import annotations

import sqlite3

from .db import load_candles, load_orders
from .types import CostAggregate, CostBreakdown


def analyze_costs(conn: sqlite3.Connection) -> tuple[list[CostBreakdown], CostAggregate]:
    """Break down fees, slippage, and decision-drift cost per filled order."""
    rows = load_orders(conn)

    # Build candle_id → winner map for outcome grouping
    candles = load_candles(conn)
    candle_winner: dict[int, str | None] = {c["candle_id"]: c.get("winner") for c in candles}

    breakdowns: list[CostBreakdown] = []
    total_fees = 0.0
    total_slippage_cost = 0.0
    total_drift_cost = 0.0
    by_outcome: dict[str, float] = {}
    by_side: dict[str, float] = {}

    for d in rows:
        lo = d.get("_live_order")
        if lo is None:
            continue

        action = d.get("action", "")
        if action not in ("BUY", "SELL"):
            continue

        fill_source = lo.get("fill_source", "")
        if not fill_source:
            continue  # Only analyze filled orders

        order_id = lo.get("order_id", "")
        fee = d.get("fee_amount") or 0.0
        slippage = d.get("slippage_bps") or 0.0
        fill_size = d.get("fill_size") or 0.0

        # Drift cost: price moved between decision and submission
        decision_ask = lo.get("decision_ob_ask")
        ob_at_submit = lo.get("ob_at_submit") or {}
        submit_ask = ob_at_submit.get("best_ask")

        drift_cost = 0.0
        if decision_ask and submit_ask and fill_size > 0:
            drift_cost = (submit_ask - decision_ask) * fill_size

        total_cost = fee + abs(drift_cost)

        breakdowns.append(CostBreakdown(
            order_id=order_id,
            fee_amount=fee,
            slippage_bps=slippage,
            drift_cost=drift_cost,
            total_cost=total_cost,
        ))

        total_fees += fee
        total_slippage_cost += abs(slippage * fill_size / 10000) if fill_size else 0.0
        total_drift_cost += abs(drift_cost)

        # Outcome grouping
        candle_id = d.get("candle_id", 0)
        winner = candle_winner.get(candle_id)
        token_side = d.get("token_side", "")
        if winner and token_side:
            outcome = "win" if winner.upper() == token_side.upper() else "loss"
        else:
            outcome = "unknown"
        by_outcome[outcome] = by_outcome.get(outcome, 0.0) + total_cost

        # Side grouping
        by_side[action] = by_side.get(action, 0.0) + total_cost

    agg = CostAggregate(
        total_fees=total_fees,
        total_slippage_cost=total_slippage_cost,
        total_drift_cost=total_drift_cost,
        by_outcome=by_outcome,
        by_side=by_side,
    )

    return breakdowns, agg
