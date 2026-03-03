"""Execution simulator: market order fills with realistic slippage and fees."""

from __future__ import annotations

import logging

from polybot.config import SimulatorConfig
from polybot.models import (
    Action,
    OrderbookSnapshot,
    OrderType,
    Side,
    SimulatedFill,
    TradingDecision,
)

logger = logging.getLogger(__name__)


class ExecutionSimulator:
    """Simulates trade execution against a live orderbook snapshot."""

    def __init__(self, config: SimulatorConfig) -> None:
        self._config = config

    def calculate_slippage_bps(self, size: float, orderbook: OrderbookSnapshot) -> float:
        """Calculate slippage in basis points based on order size vs liquidity."""
        if orderbook.best_bid is None or orderbook.best_ask is None:
            return self._config.base_slippage_bps

        total_liquidity = orderbook.bid_depth + orderbook.ask_depth
        if total_liquidity <= 0:
            return self._config.base_slippage_bps * 3  # thin book penalty

        size_ratio = size / total_liquidity
        # Use higher proportional factor for more realistic slippage modeling
        prop_factor = self._config.proportional_factor
        return self._config.base_slippage_bps + (size_ratio * prop_factor * 10000)

    def simulate_market_order(self, decision: TradingDecision, orderbook: OrderbookSnapshot) -> SimulatedFill | None:
        """Simulate a market order fill with slippage and fees."""
        if decision.action == Action.HOLD or decision.size <= 0:
            return None

        side = Side.BUY if decision.action == Action.BUY else Side.SELL

        if side == Side.BUY and orderbook.best_ask is None:
            logger.warning("No asks available, cannot fill BUY")
            return None
        if side == Side.SELL and orderbook.best_bid is None:
            logger.warning("No bids available, cannot fill SELL")
            return None

        slippage_bps = self.calculate_slippage_bps(decision.size, orderbook)
        slippage_factor = slippage_bps / 10000

        if side == Side.BUY:
            base_price = orderbook.best_ask
            fill_price = base_price * (1 + slippage_factor)
        else:
            base_price = orderbook.best_bid
            fill_price = base_price * (1 - slippage_factor)

        # Ensure fill price is in [0, 1] for prediction markets
        fill_price = max(0.001, min(0.999, fill_price))

        notional = fill_price * decision.size
        fee_amount = notional * (self._config.fee_bps / 10000)

        if side == Side.BUY:
            total_cost = notional + fee_amount  # cash outflow
        else:
            total_cost = -(notional - fee_amount)  # cash inflow (negative cost)

        return SimulatedFill(
            side=side,
            size=decision.size,
            fill_price=fill_price,
            slippage_bps=slippage_bps,
            fee_amount=fee_amount,
            total_cost=total_cost,
        )

    def execute(self, decision: TradingDecision, orderbook: OrderbookSnapshot) -> SimulatedFill | None:
        """Execute a trading decision, dispatching to market or limit logic."""
        if decision.action == Action.HOLD:
            return None

        if decision.order_type == OrderType.MARKET:
            return self.simulate_market_order(decision, orderbook)

        # Limit orders are handled by SimulatedOrderBook
        return None
