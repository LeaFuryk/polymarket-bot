"""Portfolio state: dual-position tracking, cash management, PnL calculation."""

from __future__ import annotations

import logging

from polybot.models import PositionState, SimulatedFill, Side, TokenSide

logger = logging.getLogger(__name__)


class Portfolio:
    """Tracks Up/Down positions, cash, and realized/unrealized PnL."""

    def __init__(self, initial_cash: float) -> None:
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.up_position = PositionState()
        self.down_position = PositionState()
        self.total_fees = 0.0
        self.total_slippage_cost = 0.0
        # Accumulated realized PnL from trades closed during current market
        self._market_trading_pnl: float = 0.0

    @property
    def position(self) -> PositionState:
        """Legacy accessor — returns combined position summary."""
        combined_shares = self.up_position.shares + self.down_position.shares
        combined_realized = self.up_position.realized_pnl + self.down_position.realized_pnl
        combined_unrealized = self.up_position.unrealized_pnl + self.down_position.unrealized_pnl
        avg_entry = 0.0
        if combined_shares > 0:
            avg_entry = (
                self.up_position.shares * self.up_position.avg_entry_price
                + self.down_position.shares * self.down_position.avg_entry_price
            ) / combined_shares
        return PositionState(
            shares=combined_shares,
            avg_entry_price=avg_entry,
            realized_pnl=combined_realized,
            unrealized_pnl=combined_unrealized,
        )

    def get_position(self, token_side: TokenSide) -> PositionState:
        """Get position for a specific token side."""
        return self.up_position if token_side == TokenSide.UP else self.down_position

    @property
    def total_value(self) -> float:
        """Total portfolio value = cash + positions at entry cost."""
        return (
            self.cash
            + self.up_position.shares * self.up_position.avg_entry_price
            + self.down_position.shares * self.down_position.avg_entry_price
        )

    def mark_to_market(self, up_price: float, down_price: float | None = None) -> None:
        """Update unrealized PnL based on current market prices."""
        if down_price is None:
            down_price = max(0.01, 1.0 - up_price)

        if self.up_position.shares > 0:
            self.up_position.unrealized_pnl = (
                (up_price - self.up_position.avg_entry_price) * self.up_position.shares
            )
        else:
            self.up_position.unrealized_pnl = 0.0

        if self.down_position.shares > 0:
            self.down_position.unrealized_pnl = (
                (down_price - self.down_position.avg_entry_price) * self.down_position.shares
            )
        else:
            self.down_position.unrealized_pnl = 0.0

    def total_value_at_market(self, up_price: float, down_price: float | None = None) -> float:
        """Portfolio value using current market prices for positions."""
        if down_price is None:
            down_price = max(0.01, 1.0 - up_price)
        return (
            self.cash
            + self.up_position.shares * up_price
            + self.down_position.shares * down_price
        )

    def apply_fill(self, fill: SimulatedFill, token_side: TokenSide = TokenSide.UP) -> None:
        """Apply a simulated fill to update position and cash."""
        pos = self.up_position if token_side == TokenSide.UP else self.down_position

        if fill.side == Side.BUY:
            self._apply_buy(fill, pos, token_side)
        else:
            self._apply_sell(fill, pos, token_side)

        self.total_fees += fill.fee_amount
        self.total_slippage_cost += fill.slippage_bps

    def _apply_buy(self, fill: SimulatedFill, pos: PositionState, token_side: TokenSide) -> None:
        """Buy shares: increase position, decrease cash."""
        total_shares = pos.shares + fill.size
        if total_shares > 0:
            total_cost = pos.shares * pos.avg_entry_price + fill.size * fill.fill_price
            pos.avg_entry_price = total_cost / total_shares

        pos.shares = total_shares
        self.cash -= fill.total_cost

        logger.info(
            "BUY %s %.2f shares @ %.4f | cash=%.2f | shares=%.2f",
            token_side.value, fill.size, fill.fill_price, self.cash, pos.shares,
        )

    def _apply_sell(self, fill: SimulatedFill, pos: PositionState, token_side: TokenSide) -> None:
        """Sell shares: decrease position, increase cash."""
        if fill.size > pos.shares + 1e-9:
            logger.warning("Attempted to sell more %s shares than held, clamping", token_side.value)
            fill.size = pos.shares

        pnl = (fill.fill_price - pos.avg_entry_price) * fill.size
        pos.realized_pnl += pnl
        self._market_trading_pnl += pnl

        pos.shares -= fill.size
        self.cash -= fill.total_cost

        if pos.is_flat():
            pos.shares = 0.0
            pos.avg_entry_price = 0.0

        logger.info(
            "SELL %s %.2f shares @ %.4f | pnl=%.4f | cash=%.2f | shares=%.2f",
            token_side.value, fill.size, fill.fill_price, pnl, self.cash, pos.shares,
        )

    def resolve_market(self, winner: str) -> float:
        """Settle positions at resolution: winning token = $1, losing = $0.

        Returns total PnL for this market (closed trades + resolution settlement).
        """
        # Start with PnL from trades closed during this market
        resolution_pnl = self._market_trading_pnl

        if winner == "up":
            # Up token pays $1
            if self.up_position.shares > 0:
                payout = self.up_position.shares * 1.0
                cost_basis = self.up_position.shares * self.up_position.avg_entry_price
                pnl = payout - cost_basis
                self.up_position.realized_pnl += pnl
                self.cash += payout
                resolution_pnl += pnl
            # Down token pays $0
            if self.down_position.shares > 0:
                cost_basis = self.down_position.shares * self.down_position.avg_entry_price
                self.down_position.realized_pnl -= cost_basis
                resolution_pnl -= cost_basis
        else:
            # Down token pays $1
            if self.down_position.shares > 0:
                payout = self.down_position.shares * 1.0
                cost_basis = self.down_position.shares * self.down_position.avg_entry_price
                pnl = payout - cost_basis
                self.down_position.realized_pnl += pnl
                self.cash += payout
                resolution_pnl += pnl
            # Up token pays $0
            if self.up_position.shares > 0:
                cost_basis = self.up_position.shares * self.up_position.avg_entry_price
                self.up_position.realized_pnl -= cost_basis
                resolution_pnl -= cost_basis

        logger.info(
            "Market resolved: winner=%s, resolution_pnl=%.4f (trading=%.4f, settlement=%.4f)",
            winner, resolution_pnl, self._market_trading_pnl,
            resolution_pnl - self._market_trading_pnl,
        )
        self.reset_positions()
        return resolution_pnl

    def reset_positions(self) -> None:
        """Clear both positions for a new market."""
        self.up_position = PositionState()
        self.down_position = PositionState()
        self._market_trading_pnl = 0.0
