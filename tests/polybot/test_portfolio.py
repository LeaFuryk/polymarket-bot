"""Tests for portfolio domain models."""

import pytest
from polybot.domain.portfolio import PortfolioState, Position


class TestPosition:
    def test_default_position(self):
        p = Position(side="UP")
        assert p.shares == 0.0
        assert p.avg_entry_price == 0.0
        assert p.realized_pnl == 0.0

    def test_position_with_values(self):
        p = Position(side="DOWN", shares=10.0, avg_entry_price=0.45, realized_pnl=2.5)
        assert p.shares == 10.0
        assert p.avg_entry_price == 0.45
        assert p.realized_pnl == 2.5


class TestPortfolioState:
    def test_total_value_no_positions(self):
        state = PortfolioState(
            cash=1000.0,
            up_position=Position(side="UP"),
            down_position=Position(side="DOWN"),
        )
        assert state.total_value(0.55, 0.45) == 1000.0

    def test_total_value_with_positions(self):
        state = PortfolioState(
            cash=900.0,
            up_position=Position(side="UP", shares=20.0, avg_entry_price=0.50),
            down_position=Position(side="DOWN", shares=10.0, avg_entry_price=0.40),
        )
        assert state.total_value(0.55, 0.45) == 915.5

    def test_unrealized_pnl(self):
        state = PortfolioState(
            cash=900.0,
            up_position=Position(side="UP", shares=20.0, avg_entry_price=0.50),
            down_position=Position(side="DOWN"),
        )
        assert state.unrealized_pnl(0.60, 0.40) == pytest.approx(2.0)

    def test_unrealized_pnl_no_positions(self):
        state = PortfolioState(
            cash=1000.0,
            up_position=Position(side="UP"),
            down_position=Position(side="DOWN"),
        )
        assert state.unrealized_pnl(0.55, 0.45) == 0.0

    def test_net_pnl(self):
        state = PortfolioState(
            cash=900.0,
            up_position=Position(side="UP", shares=20.0, avg_entry_price=0.50, realized_pnl=5.0),
            down_position=Position(side="DOWN", shares=10.0, avg_entry_price=0.40, realized_pnl=-2.0),
        )
        assert state.net_pnl(0.55, 0.45) == pytest.approx(4.5)
