"""Feature B: TTL counterfactual analysis — what if we waited longer?"""

from __future__ import annotations

import sqlite3

from .db import load_orders, load_snapshots_in_window
from .types import TTLAggregate, TTLCounterfactual

DEFAULT_GRID = [1, 3, 5, 10, 20, 30, 60]


def analyze_ttl(
    conn: sqlite3.Connection,
    grid: list[int] | None = None,
) -> tuple[list[TTLCounterfactual], TTLAggregate]:
    """For timeout orders, test which TTL values would have rescued them.

    For each timed-out order (has cancel_ts, no fill_ts), loads snapshot data
    and checks if any snapshot's ask ≤ limit_price within each grid TTL window.
    """
    if grid is None:
        grid = list(DEFAULT_GRID)

    rows = load_orders(conn)
    counterfactuals: list[TTLCounterfactual] = []
    rescued_at: dict[int, int] = {t: 0 for t in grid}
    total_timeouts = 0

    for d in rows:
        lo = d.get("_live_order")
        if lo is None:
            continue

        action = d.get("action", "")
        if action not in ("BUY", "SELL"):
            continue

        fill_ts = lo.get("fill_ts")
        cancel_ts = lo.get("cancel_ts")
        fill_source = lo.get("fill_source", "")

        # Only analyze timed-out orders (cancelled but not filled)
        if fill_source != "" or fill_ts is not None:
            continue
        if cancel_ts is None:
            continue

        total_timeouts += 1
        order_id = lo.get("order_id", "")
        limit_price = lo.get("limit_price", 0.0)
        submit_ts = lo.get("submit_ts", 0.0)
        candle_id = d.get("candle_id", 0)
        actual_ttl = lo.get("ttl_used", 3)
        side = action

        # Load snapshots in the extended window
        max_ttl = max(grid)
        snaps = load_snapshots_in_window(conn, candle_id, submit_ts, submit_ts + max_ttl)

        # For BUY: check if ask ≤ limit_price (can buy at or below limit)
        # For SELL: check if bid ≥ limit_price (can sell at or above limit)
        grid_results: dict[int, bool] = {}
        rescue_ttl: int | None = None

        for ttl in sorted(grid):
            window_end = submit_ts + ttl
            would_fill = False
            for snap in snaps:
                if snap["timestamp"] > window_end:
                    break
                if side == "BUY":
                    ask = snap.get("up_best_ask") or snap.get("down_best_ask")
                    # Use the correct token side
                    token_side = d.get("token_side", "")
                    if token_side == "UP":
                        ask = snap.get("up_best_ask")
                    elif token_side == "DOWN":
                        ask = snap.get("down_best_ask")
                    if ask is not None and ask <= limit_price:
                        would_fill = True
                        break
                elif side == "SELL":
                    token_side = d.get("token_side", "")
                    if token_side == "UP":
                        bid = snap.get("up_best_bid")
                    elif token_side == "DOWN":
                        bid = snap.get("down_best_bid")
                    else:
                        bid = snap.get("up_best_bid") or snap.get("down_best_bid")
                    if bid is not None and bid >= limit_price:
                        would_fill = True
                        break

            grid_results[ttl] = would_fill
            if would_fill and rescue_ttl is None:
                rescue_ttl = ttl

        # Count rescues
        for ttl in grid:
            if grid_results.get(ttl, False):
                rescued_at[ttl] += 1

        counterfactuals.append(TTLCounterfactual(
            order_id=order_id,
            candle_id=candle_id,
            actual_ttl=actual_ttl,
            grid=grid_results,
            rescue_ttl=rescue_ttl,
        ))

    agg = TTLAggregate(
        grid_ttls=grid,
        rescued_at=rescued_at,
        total_timeouts=total_timeouts,
    )

    return counterfactuals, agg
