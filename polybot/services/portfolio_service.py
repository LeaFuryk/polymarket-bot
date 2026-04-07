"""Service: portfolio state management — buy, sell, settle, summary."""

from __future__ import annotations

import logging

from polybot.domain.portfolio import PortfolioState, Position

# Polymarket crypto taker fee: fee = shares * TAKER_FEE_RATE * price * (1 - price)
TAKER_FEE_RATE = 0.072


def _taker_fee(shares: float, price: float) -> float:
    """Polymarket taker fee for crypto markets."""
    return shares * TAKER_FEE_RATE * price * (1.0 - price)


class PortfolioService:
    """Tracks cash, positions, and PnL. In-memory, resets on restart."""

    def __init__(
        self,
        initial_cash: float = 1000.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._initial_cash = initial_cash
        self._log = logger or logging.getLogger(__name__)
        self._state = PortfolioState(
            cash=initial_cash,
            up_position=Position(side="UP"),
            down_position=Position(side="DOWN"),
        )
        self._last_up_price = 0.50
        self._last_down_price = 0.50
        self._total_fees = 0.0

    @property
    def state(self) -> PortfolioState:
        return self._state

    def _get_position(self, side: str) -> Position:
        if side == "UP":
            return self._state.up_position
        return self._state.down_position

    def buy(self, side: str, amount_usd: float, price: float) -> None:
        """Buy shares. Fee collected in shares (fewer shares received)."""
        if amount_usd > self._state.cash:
            raise ValueError(f"Insufficient cash: need ${amount_usd:.2f}, have ${self._state.cash:.2f}")

        gross_shares = amount_usd / price
        fee_shares = _taker_fee(gross_shares, price)
        net_shares = gross_shares - fee_shares
        fee_usd = fee_shares * price

        pos = self._get_position(side)
        if pos.shares > 0:
            total_cost = pos.shares * pos.avg_entry_price + amount_usd
            total_shares = pos.shares + net_shares
            pos.avg_entry_price = total_cost / total_shares
        else:
            pos.avg_entry_price = amount_usd / net_shares

        pos.shares += net_shares
        self._state.cash -= amount_usd
        self._total_fees += fee_usd

        self._log.info(
            "BUY %s: %.1f shares @ $%.4f ($%.2f, fee=$%.4f) | cash=$%.2f",
            side,
            net_shares,
            price,
            amount_usd,
            fee_usd,
            self._state.cash,
        )

    def sell(self, side: str, shares: float, price: float) -> None:
        """Sell shares. Fee collected in USDC (less cash received)."""
        pos = self._get_position(side)
        if shares > pos.shares:
            raise ValueError(f"Insufficient shares: need {shares:.1f}, have {pos.shares:.1f}")

        gross_proceeds = shares * price
        fee_usd = _taker_fee(shares, price)
        net_proceeds = gross_proceeds - fee_usd

        realized = net_proceeds - (shares * pos.avg_entry_price)
        pos.shares -= shares
        pos.realized_pnl += realized
        self._state.cash += net_proceeds
        self._total_fees += fee_usd

        if pos.shares == 0.0:
            pos.avg_entry_price = 0.0

        self._log.info(
            "SELL %s: %.1f shares @ $%.4f ($%.2f, fee=$%.4f) | realized=$%.2f | cash=$%.2f",
            side,
            shares,
            price,
            net_proceeds,
            fee_usd,
            realized,
            self._state.cash,
        )

    def settle(self, winning_side: str) -> None:
        """Settle the market. Winning shares pay $1 each; losing shares expire worthless. No fees."""
        up = self._state.up_position
        down = self._state.down_position
        has_up = up.shares > 0
        has_down = down.shares > 0
        if not has_up and not has_down:
            return
        if has_up:
            if winning_side == "UP":
                payout = up.shares * 1.0
                up.realized_pnl += payout - (up.shares * up.avg_entry_price)
                self._state.cash += payout
                self._state.wins += 1
            else:
                up.realized_pnl -= up.shares * up.avg_entry_price
                self._state.losses += 1
            up.shares = 0.0
            up.avg_entry_price = 0.0
        if has_down:
            if winning_side == "DOWN":
                payout = down.shares * 1.0
                down.realized_pnl += payout - (down.shares * down.avg_entry_price)
                self._state.cash += payout
                self._state.wins += 1
            else:
                down.realized_pnl -= down.shares * down.avg_entry_price
                self._state.losses += 1
            down.shares = 0.0
            down.avg_entry_price = 0.0
        self._log.info(
            "SETTLE %s wins | cash=$%.2f | W=%d L=%d",
            winning_side,
            self._state.cash,
            self._state.wins,
            self._state.losses,
        )

    def update_prices(self, up_price: float, down_price: float) -> None:
        """Update latest market prices for unrealized PnL calculation."""
        self._last_up_price = up_price
        self._last_down_price = down_price

    def session_summary(self) -> dict:
        """Return a dict summarising the session's performance."""
        s = self._state
        up, down = self._last_up_price, self._last_down_price
        final_balance = s.total_value(up, down)
        net = s.net_pnl(up, down)
        total_bets = s.wins + s.losses
        return {
            "initial_cash": self._initial_cash,
            "final_balance": round(final_balance, 4),
            "wins": s.wins,
            "losses": s.losses,
            "win_rate": round(s.wins / total_bets, 4) if total_bets > 0 else 0.0,
            "realized_pnl": round(s.up_position.realized_pnl + s.down_position.realized_pnl, 4),
            "unrealized_pnl": round(s.unrealized_pnl(up, down), 4),
            "net_pnl": round(net, 4),
            "total_fees": round(self._total_fees, 4),
            "total_return_pct": round((final_balance - self._initial_cash) / self._initial_cash * 100, 2),
        }
