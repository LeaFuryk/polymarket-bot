"""Feature D: Blocked order analysis — classification and recoverability."""

from __future__ import annotations

import logging
import sqlite3

from .constants import (
    REPRICE_BUY_MAX_ASK,
    REPRICE_SELL_MIN_BID,
    REPRICE_WINDOW_S,
    RISK_CATEGORY_MAP,
    TTL_RESCUE_WINDOW_S,
)
from .db import load_orders, load_snapshots_in_window
from .types import BlockedAggregate, BlockedOrder


def _classify(reason: str) -> str:
    """Classify a risk_reason string into a category."""
    lower = reason.lower()
    for pattern, category in RISK_CATEGORY_MAP:
        if pattern in lower:
            return category
    return "other"


def analyze_blocked(
    conn: sqlite3.Connection,
    *,
    logger: logging.Logger | None = None,
) -> tuple[list[BlockedOrder], BlockedAggregate]:
    """Classify blocked orders and assess recoverability."""
    logger = logger or logging.getLogger(__name__)
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
                    snaps = load_snapshots_in_window(conn, candle_id, submit_ts, submit_ts + TTL_RESCUE_WINDOW_S)
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
            snaps = load_snapshots_in_window(conn, candle_id, decision_ts, decision_ts + REPRICE_WINDOW_S)
            token_side = d.get("token_side", "")
            for snap in snaps:
                if action == "BUY":
                    if token_side == "UP":
                        ask = snap.get("up_best_ask")
                    elif token_side == "DOWN":
                        ask = snap.get("down_best_ask")
                    else:
                        ask = None
                    if ask is not None and ask < REPRICE_BUY_MAX_ASK:
                        reprice_rescuable = True
                        break
                elif action == "SELL":
                    if token_side == "UP":
                        bid = snap.get("up_best_bid")
                    elif token_side == "DOWN":
                        bid = snap.get("down_best_bid")
                    else:
                        bid = None
                    if bid is not None and bid > REPRICE_SELL_MIN_BID:
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
