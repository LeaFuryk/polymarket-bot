"""Pure helper functions extracted from LiveExecutionEngine.

All functions here are stateless and independently testable — no CLOB
client, no ``self``, no async.
"""

from __future__ import annotations

import logging
from typing import Any

from polybot.execution.constants import BPS_DIVISOR, TAKER_FEE_BPS
from polybot.models import OrderbookSnapshot, Side, SimulatedFill

logger = logging.getLogger(__name__)


def snapshot_ob(ob: OrderbookSnapshot | None) -> dict[str, Any]:
    """Convert an ``OrderbookSnapshot`` to a compact telemetry dict.

    Returns an empty dict when *ob* is ``None``.
    """
    if ob is None:
        return {}
    return {
        "best_bid": ob.best_bid,
        "best_ask": ob.best_ask,
        "bid_depth": round(ob.bid_depth, 2),
        "ask_depth": round(ob.ask_depth, 2),
        "spread_pct": round(ob.spread_pct, 4) if ob.spread_pct is not None else None,
    }


def extract_order_fill_info(order_status: Any) -> tuple[str, float]:
    """Extract ``(status, size_matched)`` from a CLOB ``get_order`` response.

    The CLOB API may update ``size_matched`` before the ``status`` field
    transitions to MATCHED, so callers should check both.
    """
    if isinstance(order_status, dict):
        status = order_status.get("status", "").upper()
        raw_sm = order_status.get("size_matched", order_status.get("sizeMatched", "0"))
    else:
        status = getattr(order_status, "status", "").upper()
        raw_sm = getattr(order_status, "size_matched", getattr(order_status, "sizeMatched", "0"))
    try:
        size_matched = float(raw_sm) if raw_sm else 0.0
    except (ValueError, TypeError):
        size_matched = 0.0
    return status, size_matched


def make_fill_from_balance(
    side: Side,
    fill_size: float,
    limit_price: float,
) -> SimulatedFill:
    """Construct a ``SimulatedFill`` from a balance-detected (stealth) fill."""
    notional = limit_price * fill_size
    fee_amount = notional * (TAKER_FEE_BPS / BPS_DIVISOR)
    if side == Side.BUY:
        total_cost = notional + fee_amount
    else:
        total_cost = -(notional - fee_amount)
    return SimulatedFill(
        side=side,
        size=fill_size,
        fill_price=limit_price,
        slippage_bps=0.0,
        fee_amount=fee_amount,
        total_cost=total_cost,
    )


def parse_order_response(
    response: Any,
    side: Side,
    requested_size: float,
    requested_price: float,
) -> SimulatedFill | None:
    """Parse a CLOB order response into a ``SimulatedFill``.

    Returns ``None`` when the response indicates no fill (error, rejected,
    ``None`` response, etc.).
    """
    if response is None:
        logger.warning("CLOB order returned None response")
        return None

    if isinstance(response, dict):
        success = response.get("success", False)
        status = response.get("status", "")
    else:
        success = getattr(response, "success", False)
        status = getattr(response, "status", "")

    if not success and status.upper() not in ("MATCHED", "FILLED"):
        logger.warning("CLOB order not filled: %s", response)
        return None

    fill_price = requested_price
    fill_size = requested_size

    if isinstance(response, dict):
        if "averagePrice" in response:
            fill_price = float(response["averagePrice"])
        if "filledAmount" in response:
            fill_size = float(response["filledAmount"])
    else:
        if hasattr(response, "averagePrice"):
            fill_price = float(response.averagePrice)
        if hasattr(response, "filledAmount"):
            fill_size = float(response.filledAmount)

    slippage_bps = abs(fill_price - requested_price) / requested_price * BPS_DIVISOR if requested_price > 0 else 0
    notional = fill_price * fill_size
    fee_amount = notional * (TAKER_FEE_BPS / BPS_DIVISOR)

    if side == Side.BUY:
        total_cost = notional + fee_amount
    else:
        total_cost = -(notional - fee_amount)

    return SimulatedFill(
        side=side,
        size=fill_size,
        fill_price=fill_price,
        slippage_bps=slippage_bps,
        fee_amount=fee_amount,
        total_cost=total_cost,
    )
