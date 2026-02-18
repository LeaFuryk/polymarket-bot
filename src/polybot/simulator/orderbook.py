"""Simulated limit order book: tracks pending orders, fills on market crosses."""

from __future__ import annotations

import logging
import time

from polybot.config import SimulatorConfig
from polybot.models import (
    Action,
    OrderbookSnapshot,
    OrderType,
    PendingLimitOrder,
    Side,
    SimulatedFill,
    TradingDecision,
)

logger = logging.getLogger(__name__)


class SimulatedOrderBook:
    """Manages pending limit orders and checks for fills against market data."""

    def __init__(self, config: SimulatorConfig) -> None:
        self._config = config
        self._orders: list[PendingLimitOrder] = []

    @property
    def pending_orders(self) -> list[PendingLimitOrder]:
        return list(self._orders)

    def add_order(self, decision: TradingDecision) -> PendingLimitOrder | None:
        """Add a new limit order from a trading decision."""
        if decision.order_type != OrderType.LIMIT or decision.limit_price is None:
            return None
        if decision.action == Action.HOLD or decision.size <= 0:
            return None

        order = PendingLimitOrder(
            side=Side.BUY if decision.action == Action.BUY else Side.SELL,
            size=decision.size,
            limit_price=decision.limit_price,
            ttl_seconds=decision.ttl_seconds or self._config.limit_order_ttl,
        )
        self._orders.append(order)
        logger.info(
            "Limit order added: %s %.2f @ %.4f (TTL %ds)",
            order.side.value, order.size, order.limit_price, order.ttl_seconds,
        )
        return order

    def check_fills(self, orderbook: OrderbookSnapshot) -> list[SimulatedFill]:
        """Check all pending orders for fills against current market."""
        now = time.time()
        fills: list[SimulatedFill] = []
        remaining: list[PendingLimitOrder] = []

        for order in self._orders:
            # Expire old orders
            if order.is_expired(now):
                logger.info("Limit order expired: %s", order.order_id)
                continue

            fill = self._try_fill(order, orderbook)
            if fill:
                fills.append(fill)
                logger.info(
                    "Limit order filled: %s %.2f @ %.4f",
                    order.side.value, fill.size, fill.fill_price,
                )
            else:
                remaining.append(order)

        self._orders = remaining
        return fills

    def _try_fill(
        self, order: PendingLimitOrder, orderbook: OrderbookSnapshot
    ) -> SimulatedFill | None:
        """Check if a limit order can fill against current orderbook."""
        if order.side == Side.BUY:
            # Buy limit fills if ask <= limit_price
            if orderbook.best_ask is None:
                return None
            if orderbook.best_ask > order.limit_price:
                return None
            fill_price = order.limit_price  # fill at limit (conservative)
        else:
            # Sell limit fills if bid >= limit_price
            if orderbook.best_bid is None:
                return None
            if orderbook.best_bid < order.limit_price:
                return None
            fill_price = order.limit_price

        notional = fill_price * order.size
        # Limit orders typically have lower fees, but use same model for simplicity
        fee_amount = notional * (self._config.fee_bps / 10000)

        if order.side == Side.BUY:
            total_cost = notional + fee_amount
        else:
            total_cost = -(notional - fee_amount)

        return SimulatedFill(
            side=order.side,
            size=order.size,
            fill_price=fill_price,
            slippage_bps=0.0,  # limit orders have no slippage
            fee_amount=fee_amount,
            total_cost=total_cost,
        )

    def cancel_all(self) -> int:
        """Cancel all pending orders. Returns count of cancelled orders."""
        count = len(self._orders)
        self._orders.clear()
        return count
