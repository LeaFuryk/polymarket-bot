"""Pre-trade and post-trade risk checks."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from polybot.config import RiskConfig
from polybot.models import (
    Action,
    MarketSnapshot,
    PositionState,
    RiskCheckResult,
    RiskState,
    TokenSide,
    TradingDecision,
)

logger = logging.getLogger(__name__)


class RiskManager:
    """Two-stage risk management: pre-trade (saves API cost) and post-trade."""

    def __init__(self, config: RiskConfig, initial_cash: float) -> None:
        self._config = config
        self._initial_cash = initial_cash
        self.state = RiskState(peak_portfolio_value=initial_cash)
        self._day_start: str = self._today()

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _maybe_reset_daily(self) -> None:
        """Reset daily counters if a new UTC day has started."""
        today = self._today()
        if today != self._day_start:
            logger.info("New trading day, resetting daily counters")
            self.state.daily_pnl = 0.0
            self.state.daily_trades = 0
            self.state.daily_fees = 0.0
            self.state.is_halted = False
            self.state.halt_reason = ""
            self._day_start = today

    def update_portfolio_peak(self, portfolio_value: float) -> None:
        """Track peak portfolio value for drawdown calculation."""
        if portfolio_value > self.state.peak_portfolio_value:
            self.state.peak_portfolio_value = portfolio_value
        drawdown = self.state.peak_portfolio_value - portfolio_value
        if drawdown > self.state.max_drawdown:
            self.state.max_drawdown = drawdown

    def pre_trade_checks(self, snapshot: MarketSnapshot) -> list[RiskCheckResult]:
        """Run checks BEFORE calling the AI (saves API cost on obvious skips)."""
        self._maybe_reset_daily()
        results: list[RiskCheckResult] = []

        # Check if halted
        if self.state.is_halted:
            results.append(RiskCheckResult(
                passed=False,
                check_name="halt_check",
                reason=f"Trading halted: {self.state.halt_reason}",
            ))
            return results

        # Daily loss limit
        loss_limit = self._initial_cash * self._config.daily_loss_limit_pct
        if self.state.daily_pnl < -loss_limit:
            self.state.is_halted = True
            self.state.halt_reason = (
                f"Daily loss limit breached: {self.state.daily_pnl:.2f} < -{loss_limit:.2f}"
            )
            results.append(RiskCheckResult(
                passed=False,
                check_name="daily_loss_limit",
                reason=self.state.halt_reason,
            ))
            return results

        # Check both orderbooks — at least one should be tradeable
        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook

        up_depth = up_ob.bid_depth + up_ob.ask_depth
        down_depth = down_ob.bid_depth + down_ob.ask_depth

        # If both orderbooks lack liquidity, block
        if up_depth < self._config.min_liquidity and down_depth < self._config.min_liquidity:
            results.append(RiskCheckResult(
                passed=False,
                check_name="min_liquidity",
                reason=f"Both orderbooks thin: up={up_depth:.2f}, down={down_depth:.2f} < min {self._config.min_liquidity:.2f}",
            ))

        if not results:
            results.append(RiskCheckResult(passed=True, check_name="pre_trade"))

        return results

    def post_trade_checks(
        self,
        decision: TradingDecision,
        position: PositionState,
        cash: float,
        portfolio_value: float,
        snapshot: MarketSnapshot,
    ) -> list[RiskCheckResult]:
        """Validate AI decision BEFORE execution.

        `position` should be the position for the specific token_side being traded.
        """
        results: list[RiskCheckResult] = []

        if decision.action == Action.HOLD:
            results.append(RiskCheckResult(passed=True, check_name="hold_passthrough"))
            return results

        # Select the correct orderbook based on token_side
        if decision.token_side == TokenSide.DOWN:
            ob = snapshot.down_orderbook
        else:
            ob = snapshot.orderbook

        # Spread check on the specific orderbook
        if ob.spread_pct is not None and ob.spread_pct > self._config.max_spread_pct:
            results.append(RiskCheckResult(
                passed=False,
                check_name="max_spread",
                reason=f"{decision.token_side.value} spread {ob.spread_pct:.2%} > max {self._config.max_spread_pct:.2%}",
            ))

        # Max position size
        if decision.action == Action.BUY:
            fill_price = ob.best_ask or 0.5
            notional_cost = decision.size * fill_price
            position_value = position.shares * position.avg_entry_price + notional_cost
            max_position = portfolio_value * self._config.max_position_pct
            if position_value > max_position:
                results.append(RiskCheckResult(
                    passed=False,
                    check_name="max_position_size",
                    reason=f"Position {position_value:.2f} would exceed max {max_position:.2f}",
                ))

        # Concentration limit (combined across both tokens)
        if decision.action == Action.BUY:
            fill_price = ob.best_ask or 0.5
            new_position_value = (position.shares + decision.size) * fill_price
            max_concentration = portfolio_value * self._config.max_concentration_pct
            if new_position_value > max_concentration:
                results.append(RiskCheckResult(
                    passed=False,
                    check_name="concentration_limit",
                    reason=f"Concentration {new_position_value:.2f} would exceed {max_concentration:.2f}",
                ))

        # Cash sufficiency
        if decision.action == Action.BUY:
            fill_price = ob.best_ask or 0.5
            required_cash = decision.size * fill_price * 1.005
            if required_cash > cash:
                results.append(RiskCheckResult(
                    passed=False,
                    check_name="cash_sufficiency",
                    reason=f"Need {required_cash:.2f} but only have {cash:.2f}",
                ))

        # Short-sell prevention
        if decision.action == Action.SELL:
            if decision.size > position.shares + 1e-9:
                results.append(RiskCheckResult(
                    passed=False,
                    check_name="short_sell_prevention",
                    reason=f"Cannot sell {decision.size:.2f} {decision.token_side.value}, only hold {position.shares:.2f}",
                ))

        # Risk/reward ratio gate (BUY only)
        if decision.action == Action.BUY:
            est_fill = ob.best_ask or 0.5
            reward = 1.0 - est_fill  # winning token pays $1
            risk = est_fill          # losing token pays $0
            rr_ratio = reward / risk if risk > 0 else 0
            if rr_ratio < self._config.min_reward_risk_ratio:
                results.append(RiskCheckResult(
                    passed=False,
                    check_name="reward_risk_ratio",
                    reason=f"R/R ratio {rr_ratio:.2f} < min {self._config.min_reward_risk_ratio:.2f} "
                           f"(entry {est_fill:.4f}, reward {reward:.4f}, risk {risk:.4f})",
                ))

        # Order size vs depth check
        if decision.action == Action.BUY and ob.ask_depth > 0:
            fill_price = ob.best_ask or 0.5
            order_notional = decision.size * fill_price
            if order_notional > ob.ask_depth * 0.5:
                results.append(RiskCheckResult(
                    passed=False,
                    check_name="order_vs_depth",
                    reason=f"Order {order_notional:.2f} > 50% of ask depth {ob.ask_depth:.2f}",
                ))
        elif decision.action == Action.SELL and ob.bid_depth > 0:
            fill_price = ob.best_bid or 0.5
            order_notional = decision.size * fill_price
            if order_notional > ob.bid_depth * 0.5:
                results.append(RiskCheckResult(
                    passed=False,
                    check_name="order_vs_depth",
                    reason=f"Order {order_notional:.2f} > 50% of bid depth {ob.bid_depth:.2f}",
                ))

        if not results:
            results.append(RiskCheckResult(passed=True, check_name="post_trade"))

        return results

    def record_trade(self, pnl: float, fees: float) -> None:
        """Update daily tracking after a trade executes."""
        self.state.daily_pnl += pnl
        self.state.daily_trades += 1
        self.state.daily_fees += fees
