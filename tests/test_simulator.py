"""Tests for polybot.simulator — execution, orderbook, and portfolio."""

from __future__ import annotations

import time

import pytest

from polybot.config import SimulatorConfig
from polybot.models import (
    Action,
    OrderbookLevel,
    OrderbookSnapshot,
    OrderType,
    Side,
    SimulatedFill,
    TokenSide,
    TradingDecision,
)
from polybot.simulator.constants import (
    BPS_DIVISOR,
    DOWN_PRICE_FLOOR,
    FILL_PRICE_MAX,
    FILL_PRICE_MIN,
    LOSING_TOKEN_PAYOUT,
    OVERSELL_TOLERANCE,
    THIN_BOOK_PENALTY_FACTOR,
    WINNING_TOKEN_PAYOUT,
)
from polybot.simulator.engine import ExecutionSimulator
from polybot.simulator.orderbook import SimulatedOrderBook
from polybot.simulator.portfolio import Portfolio

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _config(**overrides) -> SimulatorConfig:
    return SimulatorConfig(**overrides)


def _ob(
    best_bid: float | None = 0.50,
    best_ask: float | None = 0.55,
    bid_size: float = 200.0,
    ask_size: float = 200.0,
) -> OrderbookSnapshot:
    """Build an OrderbookSnapshot from top-of-book prices and sizes."""
    bids = [OrderbookLevel(price=best_bid, size=bid_size)] if best_bid is not None else []
    asks = [OrderbookLevel(price=best_ask, size=ask_size)] if best_ask is not None else []
    return OrderbookSnapshot(bids=bids, asks=asks)


def _decision(
    action: Action = Action.BUY,
    size: float = 10.0,
    order_type: OrderType = OrderType.MARKET,
    limit_price: float | None = None,
    ttl_seconds: int = 300,
) -> TradingDecision:
    return TradingDecision(
        action=action,
        size=size,
        order_type=order_type,
        limit_price=limit_price,
        ttl_seconds=ttl_seconds,
    )


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_bps_divisor(self):
        assert BPS_DIVISOR == 10_000.0

    def test_fill_price_bounds(self):
        assert FILL_PRICE_MIN == 0.001
        assert FILL_PRICE_MAX == 0.999

    def test_thin_book_penalty(self):
        assert THIN_BOOK_PENALTY_FACTOR == 3.0

    def test_portfolio_constants(self):
        assert DOWN_PRICE_FLOOR == 0.01
        assert OVERSELL_TOLERANCE == 1e-9
        assert WINNING_TOKEN_PAYOUT == 1.0
        assert LOSING_TOKEN_PAYOUT == 0.0


# ---------------------------------------------------------------------------
# ExecutionSimulator
# ---------------------------------------------------------------------------


class TestExecutionSimulator:
    def test_hold_returns_none(self):
        sim = ExecutionSimulator(_config())
        result = sim.execute(_decision(Action.HOLD), _ob())
        assert result is None

    def test_market_buy_fills(self):
        sim = ExecutionSimulator(_config())
        fill = sim.simulate_market_order(_decision(Action.BUY, size=10), _ob())

        assert fill is not None
        assert fill.side == Side.BUY
        assert fill.size == 10.0
        assert fill.fill_price >= 0.55  # ask + slippage
        assert fill.fee_amount > 0
        assert fill.total_cost > 0

    def test_market_sell_fills(self):
        sim = ExecutionSimulator(_config())
        fill = sim.simulate_market_order(_decision(Action.SELL, size=10), _ob())

        assert fill is not None
        assert fill.side == Side.SELL
        assert fill.fill_price <= 0.50  # bid - slippage
        assert fill.total_cost < 0  # cash inflow

    def test_no_asks_returns_none(self):
        sim = ExecutionSimulator(_config())
        fill = sim.simulate_market_order(_decision(Action.BUY), _ob(best_ask=None))
        assert fill is None

    def test_no_bids_returns_none(self):
        sim = ExecutionSimulator(_config())
        fill = sim.simulate_market_order(_decision(Action.SELL), _ob(best_bid=None))
        assert fill is None

    def test_zero_size_returns_none(self):
        sim = ExecutionSimulator(_config())
        fill = sim.simulate_market_order(_decision(size=0), _ob())
        assert fill is None

    def test_slippage_thin_book(self):
        sim = ExecutionSimulator(_config(base_slippage_bps=5.0))
        # Zero-size levels → bid_depth=ask_depth=0
        ob = OrderbookSnapshot(
            bids=[OrderbookLevel(price=0.50, size=0)],
            asks=[OrderbookLevel(price=0.55, size=0)],
        )
        slippage = sim.calculate_slippage_bps(10, ob)
        assert slippage == 5.0 * THIN_BOOK_PENALTY_FACTOR

    def test_slippage_no_book(self):
        sim = ExecutionSimulator(_config(base_slippage_bps=5.0))
        slippage = sim.calculate_slippage_bps(10, _ob(best_bid=None, best_ask=None))
        assert slippage == 5.0

    def test_slippage_proportional(self):
        sim = ExecutionSimulator(_config(base_slippage_bps=5.0, proportional_factor=0.5))
        # bid_depth = 0.50*200=100, ask_depth = 0.55*200=110, total=210
        # size=100, ratio=100/210, prop = (100/210)*0.5*10000
        ob = _ob()  # default: bid=0.50@200, ask=0.55@200
        total_liq = 0.50 * 200 + 0.55 * 200  # 210
        expected = 5.0 + (100 / total_liq) * 0.5 * BPS_DIVISOR
        slippage = sim.calculate_slippage_bps(100, ob)
        assert slippage == pytest.approx(expected)

    def test_fill_price_clamped(self):
        sim = ExecutionSimulator(_config(base_slippage_bps=50000.0))
        fill = sim.simulate_market_order(_decision(Action.BUY, size=1), _ob())
        assert fill is not None
        assert fill.fill_price == FILL_PRICE_MAX

    def test_execute_dispatches_market(self):
        sim = ExecutionSimulator(_config())
        fill = sim.execute(_decision(Action.BUY, order_type=OrderType.MARKET), _ob())
        assert fill is not None

    def test_execute_limit_returns_none(self):
        sim = ExecutionSimulator(_config())
        fill = sim.execute(
            _decision(Action.BUY, order_type=OrderType.LIMIT, limit_price=0.50),
            _ob(),
        )
        assert fill is None

    def test_injectable_logger(self):
        import logging

        custom = logging.getLogger("test.engine")
        sim = ExecutionSimulator(_config(), logger=custom)
        assert sim._logger is custom


# ---------------------------------------------------------------------------
# SimulatedOrderBook
# ---------------------------------------------------------------------------


class TestSimulatedOrderBook:
    def test_add_limit_order(self):
        book = SimulatedOrderBook(_config())
        order = book.add_order(_decision(Action.BUY, order_type=OrderType.LIMIT, limit_price=0.50))
        assert order is not None
        assert order.side == Side.BUY
        assert order.limit_price == 0.50
        assert len(book.pending_orders) == 1

    def test_add_market_order_returns_none(self):
        book = SimulatedOrderBook(_config())
        order = book.add_order(_decision(Action.BUY, order_type=OrderType.MARKET))
        assert order is None

    def test_add_hold_returns_none(self):
        book = SimulatedOrderBook(_config())
        order = book.add_order(_decision(Action.HOLD, order_type=OrderType.LIMIT, limit_price=0.50))
        assert order is None

    def test_buy_limit_fills_when_ask_below(self):
        book = SimulatedOrderBook(_config())
        book.add_order(_decision(Action.BUY, size=10, order_type=OrderType.LIMIT, limit_price=0.55))
        fills = book.check_fills(_ob(best_ask=0.54))

        assert len(fills) == 1
        assert fills[0].side == Side.BUY
        assert fills[0].fill_price == 0.55  # fills at limit
        assert len(book.pending_orders) == 0

    def test_buy_limit_no_fill_when_ask_above(self):
        book = SimulatedOrderBook(_config())
        book.add_order(_decision(Action.BUY, size=10, order_type=OrderType.LIMIT, limit_price=0.50))
        fills = book.check_fills(_ob(best_ask=0.55))

        assert len(fills) == 0
        assert len(book.pending_orders) == 1

    def test_sell_limit_fills_when_bid_above(self):
        book = SimulatedOrderBook(_config())
        book.add_order(_decision(Action.SELL, size=10, order_type=OrderType.LIMIT, limit_price=0.45))
        fills = book.check_fills(_ob(best_bid=0.50))

        assert len(fills) == 1
        assert fills[0].side == Side.SELL

    def test_sell_limit_no_fill_when_bid_below(self):
        book = SimulatedOrderBook(_config())
        book.add_order(_decision(Action.SELL, size=10, order_type=OrderType.LIMIT, limit_price=0.55))
        fills = book.check_fills(_ob(best_bid=0.50))

        assert len(fills) == 0

    def test_expired_orders_removed(self):
        book = SimulatedOrderBook(_config())
        book.add_order(_decision(Action.BUY, size=10, order_type=OrderType.LIMIT, limit_price=0.55, ttl_seconds=1))
        # Manually expire the order
        book._orders[0].created_at = time.time() - 10
        fills = book.check_fills(_ob(best_ask=0.50))

        assert len(fills) == 0
        assert len(book.pending_orders) == 0

    def test_cancel_all(self):
        book = SimulatedOrderBook(_config())
        book.add_order(_decision(Action.BUY, size=10, order_type=OrderType.LIMIT, limit_price=0.55))
        book.add_order(_decision(Action.SELL, size=5, order_type=OrderType.LIMIT, limit_price=0.60))
        count = book.cancel_all()

        assert count == 2
        assert len(book.pending_orders) == 0

    def test_fill_fee_calculation(self):
        book = SimulatedOrderBook(_config(fee_bps=20.0))
        book.add_order(_decision(Action.BUY, size=100, order_type=OrderType.LIMIT, limit_price=0.50))
        fills = book.check_fills(_ob(best_ask=0.45))

        assert len(fills) == 1
        expected_fee = 0.50 * 100 * (20.0 / BPS_DIVISOR)
        assert fills[0].fee_amount == pytest.approx(expected_fee)

    def test_injectable_logger(self):
        import logging

        custom = logging.getLogger("test.orderbook")
        book = SimulatedOrderBook(_config(), logger=custom)
        assert book._logger is custom


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


class TestPortfolio:
    def test_initial_state(self):
        p = Portfolio(1000.0)
        assert p.cash == 1000.0
        assert p.initial_cash == 1000.0
        assert p.total_fees == 0.0
        assert p.up_position.shares == 0.0
        assert p.down_position.shares == 0.0

    def test_buy_increases_position(self):
        p = Portfolio(1000.0)
        fill = SimulatedFill(side=Side.BUY, size=10, fill_price=0.50, slippage_bps=0, fee_amount=0.1, total_cost=5.1)
        p.apply_fill(fill, TokenSide.UP)

        assert p.up_position.shares == 10.0
        assert p.up_position.avg_entry_price == 0.50
        assert p.cash == pytest.approx(1000.0 - 5.1)

    def test_sell_decreases_position(self):
        p = Portfolio(1000.0)
        buy = SimulatedFill(side=Side.BUY, size=10, fill_price=0.50, slippage_bps=0, fee_amount=0, total_cost=5.0)
        p.apply_fill(buy, TokenSide.UP)

        sell = SimulatedFill(side=Side.SELL, size=5, fill_price=0.60, slippage_bps=0, fee_amount=0, total_cost=-3.0)
        p.apply_fill(sell, TokenSide.UP)

        assert p.up_position.shares == 5.0
        assert p.up_position.realized_pnl == pytest.approx(0.50)  # (0.60 - 0.50) * 5

    def test_sell_more_than_held_clamps(self):
        p = Portfolio(1000.0)
        buy = SimulatedFill(side=Side.BUY, size=5, fill_price=0.50, slippage_bps=0, fee_amount=0, total_cost=2.5)
        p.apply_fill(buy, TokenSide.UP)

        sell = SimulatedFill(side=Side.SELL, size=10, fill_price=0.60, slippage_bps=0, fee_amount=0, total_cost=-6.0)
        p.apply_fill(sell, TokenSide.UP)

        # Should have clamped to 5 shares
        assert p.up_position.shares == 0.0

    def test_mark_to_market(self):
        p = Portfolio(1000.0)
        buy = SimulatedFill(side=Side.BUY, size=10, fill_price=0.50, slippage_bps=0, fee_amount=0, total_cost=5.0)
        p.apply_fill(buy, TokenSide.UP)

        p.mark_to_market(0.60)
        assert p.up_position.unrealized_pnl == pytest.approx(1.0)  # (0.60 - 0.50) * 10

    def test_mark_to_market_infers_down_price(self):
        p = Portfolio(1000.0)
        buy = SimulatedFill(side=Side.BUY, size=10, fill_price=0.40, slippage_bps=0, fee_amount=0, total_cost=4.0)
        p.apply_fill(buy, TokenSide.DOWN)

        p.mark_to_market(0.60)  # down = max(0.01, 1.0 - 0.60) = 0.40
        assert p.down_position.unrealized_pnl == pytest.approx(0.0)

    def test_total_value_at_market(self):
        p = Portfolio(1000.0)
        buy = SimulatedFill(side=Side.BUY, size=10, fill_price=0.50, slippage_bps=0, fee_amount=0, total_cost=5.0)
        p.apply_fill(buy, TokenSide.UP)

        value = p.total_value_at_market(0.60)
        assert value == pytest.approx(995.0 + 10 * 0.60)

    def test_resolve_market_winner_up(self):
        p = Portfolio(1000.0)
        buy = SimulatedFill(side=Side.BUY, size=10, fill_price=0.50, slippage_bps=0, fee_amount=0, total_cost=5.0)
        p.apply_fill(buy, TokenSide.UP)

        pnl = p.resolve_market("up")
        # payout = 10 * 1.0 = 10, cost = 10 * 0.50 = 5, pnl = 5
        assert pnl == pytest.approx(5.0)
        assert p.up_position.shares == 0.0

    def test_resolve_market_winner_down(self):
        p = Portfolio(1000.0)
        buy = SimulatedFill(side=Side.BUY, size=10, fill_price=0.50, slippage_bps=0, fee_amount=0, total_cost=5.0)
        p.apply_fill(buy, TokenSide.UP)

        pnl = p.resolve_market("down")
        # up token worthless: cost = 10 * 0.50 = 5, pnl = -5
        assert pnl == pytest.approx(-5.0)

    def test_resolve_market_dual_positions(self):
        p = Portfolio(1000.0)
        buy_up = SimulatedFill(side=Side.BUY, size=10, fill_price=0.55, slippage_bps=0, fee_amount=0, total_cost=5.5)
        buy_down = SimulatedFill(side=Side.BUY, size=10, fill_price=0.45, slippage_bps=0, fee_amount=0, total_cost=4.5)
        p.apply_fill(buy_up, TokenSide.UP)
        p.apply_fill(buy_down, TokenSide.DOWN)

        pnl = p.resolve_market("up")
        # up wins: payout=10, cost=5.5 → pnl=4.5. down loses: cost=4.5 → pnl=-4.5. total=0
        assert pnl == pytest.approx(0.0)

    def test_get_position(self):
        p = Portfolio(1000.0)
        assert p.get_position(TokenSide.UP) is p.up_position
        assert p.get_position(TokenSide.DOWN) is p.down_position

    def test_combined_position_property(self):
        p = Portfolio(1000.0)
        buy_up = SimulatedFill(side=Side.BUY, size=10, fill_price=0.50, slippage_bps=0, fee_amount=0, total_cost=5.0)
        buy_down = SimulatedFill(side=Side.BUY, size=5, fill_price=0.40, slippage_bps=0, fee_amount=0, total_cost=2.0)
        p.apply_fill(buy_up, TokenSide.UP)
        p.apply_fill(buy_down, TokenSide.DOWN)

        combined = p.position
        assert combined.shares == 15.0

    def test_fees_tracked(self):
        p = Portfolio(1000.0)
        fill = SimulatedFill(side=Side.BUY, size=10, fill_price=0.50, slippage_bps=5.0, fee_amount=0.1, total_cost=5.1)
        p.apply_fill(fill, TokenSide.UP)

        assert p.total_fees == 0.1
        assert p.total_slippage_cost == 5.0

    def test_reset_positions(self):
        p = Portfolio(1000.0)
        buy = SimulatedFill(side=Side.BUY, size=10, fill_price=0.50, slippage_bps=0, fee_amount=0, total_cost=5.0)
        p.apply_fill(buy, TokenSide.UP)

        p.reset_positions()
        assert p.up_position.shares == 0.0
        assert p.down_position.shares == 0.0
        assert p.market_trading_pnl == 0.0

    def test_injectable_logger(self):
        import logging

        custom = logging.getLogger("test.portfolio")
        p = Portfolio(1000.0, logger=custom)
        assert p._logger is custom
