"""Feature D: Blocked order analysis — classification and recoverability."""

from __future__ import annotations

import sqlite3

from .db import load_orders, load_snapshots_in_window
from .types import BlockedAggregate, BlockedOrder

# Risk reason → category mapping
_CATEGORY_MAP: list[tuple[str, str]] = [
    ("kill switch", "kill_switch"),
    ("no token_id", "no_token_id"),
    ("no ask", "no_book"),
    ("no bid", "no_book"),
    ("no orderbook", "no_book"),
    ("exceeds max", "max_size"),
    ("wallet below min", "low_balance"),
    ("insufficient balance", "low_balance"),
    ("limit order timeout", "timeout"),
    ("no on-chain token balance", "no_token_balance"),
    ("execution error", "error"),
    ("dry run", "dry_run"),
]


def _classify(reason: str) -> str:
    """Classify a risk_reason string into a category."""
    lower = reason.lower()
    for pattern, category in _CATEGORY_MAP:
        if pattern in lower:
            return category
    return "other"


def analyze_blocked(conn: sqlite3.Connection) -> tuple[list[BlockedOrder], BlockedAggregate]:
    """Classify blocked orders and assess recoverability."""
    rows = load_orders(conn)
    blocked: list[BlockedOrder] = []
    by_category: dict[str, int] = {}
    rescuable_ttl = 0
    rescuable_reprice = 0

    for d in rows:
        risk_blocked = d.get("risk_blocked")
        if not risk_blocked:
            continue

        action = d.get("action", "HOLD")
        if action == "HOLD":
            continue

        risk_reason = d.get("risk_reason") or "unknown"
        category = _classify(risk_reason)
        candle_id = d.get("candle_id", 0)

        by_category[category] = by_category.get(category, 0) + 1

        # Check TTL rescuability for timeout blocks
        ttl_rescuable = False
        if category == "timeout":
            lo = d.get("_live_order")
            if lo:
                limit_price = lo.get("limit_price", 0.0)
                submit_ts = lo.get("submit_ts", 0.0)
                token_side = d.get("token_side", "")
                if submit_ts and limit_price:
                    snaps = load_snapshots_in_window(conn, candle_id, submit_ts, submit_ts + 60)
                    for snap in snaps:
                        if token_side == "UP":
                            ask = snap.get("up_best_ask")
                        elif token_side == "DOWN":
                            ask = snap.get("down_best_ask")
                        else:
                            ask = None
                        if ask is not None and ask <= limit_price:
                            ttl_rescuable = True
                            break

        # Check reprice rescuability — would a different price have worked?
        reprice_rescuable = False
        decision_ts = d.get("timestamp", 0.0)
        if decision_ts and candle_id:
            snaps = load_snapshots_in_window(conn, candle_id, decision_ts, decision_ts + 10)
            token_side = d.get("token_side", "")
            for snap in snaps:
                if action == "BUY":
                    if token_side == "UP":
                        ask = snap.get("up_best_ask")
                    elif token_side == "DOWN":
                        ask = snap.get("down_best_ask")
                    else:
                        ask = None
                    if ask is not None and ask < 0.95:  # Reasonable price available
                        reprice_rescuable = True
                        break
                elif action == "SELL":
                    if token_side == "UP":
                        bid = snap.get("up_best_bid")
                    elif token_side == "DOWN":
                        bid = snap.get("down_best_bid")
                    else:
                        bid = None
                    if bid is not None and bid > 0.05:
                        reprice_rescuable = True
                        break

        if ttl_rescuable:
            rescuable_ttl += 1
        if reprice_rescuable:
            rescuable_reprice += 1

        blocked.append(
            BlockedOrder(
                candle_id=candle_id,
                action=action,
                risk_reason=risk_reason,
                category=category,
                ttl_rescuable=ttl_rescuable,
                reprice_rescuable=reprice_rescuable,
            )
        )

    agg = BlockedAggregate(
        total_blocked=len(blocked),
        by_category=by_category,
        rescuable_ttl=rescuable_ttl,
        rescuable_reprice=rescuable_reprice,
    )

    return blocked, agg
