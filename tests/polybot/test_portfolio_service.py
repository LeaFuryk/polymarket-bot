"""Tests for PortfolioService."""

import pytest

from polybot.services.portfolio_service import PortfolioService


class TestBuy:
    def test_buy_up_deducts_cash(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        assert svc.state.cash == 900.0

    def test_buy_up_adds_shares(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        assert svc.state.up_position.shares == 200.0

    def test_buy_down(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("DOWN", amount_usd=50.0, price=0.25)
        assert svc.state.down_position.shares == 200.0
        assert svc.state.cash == 950.0

    def test_buy_updates_avg_entry_price(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        svc.buy("UP", amount_usd=100.0, price=0.60)
        expected_avg = (100.0 + 100.0) / (200.0 + 100.0 / 0.60)
        assert svc.state.up_position.avg_entry_price == pytest.approx(expected_avg, rel=1e-4)

    def test_buy_insufficient_cash_raises(self):
        svc = PortfolioService(initial_cash=100.0)
        with pytest.raises(ValueError, match="Insufficient cash"):
            svc.buy("UP", amount_usd=200.0, price=0.50)


class TestSell:
    def test_sell_credits_cash(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        svc.sell("UP", shares=100.0, price=0.60)
        assert svc.state.cash == pytest.approx(960.0)

    def test_sell_reduces_shares(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        svc.sell("UP", shares=50.0, price=0.60)
        assert svc.state.up_position.shares == 150.0

    def test_sell_updates_realized_pnl(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        svc.sell("UP", shares=100.0, price=0.60)
        assert svc.state.up_position.realized_pnl == pytest.approx(10.0)

    def test_sell_insufficient_shares_raises(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        with pytest.raises(ValueError, match="Insufficient shares"):
            svc.sell("UP", shares=300.0, price=0.60)


class TestSettle:
    def test_settle_up_wins(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        svc.settle("UP")
        assert svc.state.cash == pytest.approx(1100.0)
        assert svc.state.up_position.shares == 0.0
        assert svc.state.wins == 1

    def test_settle_down_wins_up_loses(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        svc.buy("DOWN", amount_usd=50.0, price=0.40)
        svc.settle("DOWN")
        assert svc.state.cash == pytest.approx(975.0)
        assert svc.state.up_position.shares == 0.0
        assert svc.state.down_position.shares == 0.0
        assert svc.state.wins == 1
        assert svc.state.losses == 1

    def test_settle_no_positions_is_safe(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.settle("UP")
        assert svc.state.cash == 1000.0
        assert svc.state.wins == 0

    def test_settle_clears_avg_entry(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        svc.settle("UP")
        assert svc.state.up_position.avg_entry_price == 0.0


class TestSessionSummary:
    def test_session_summary_fields(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        svc.settle("UP")
        svc.update_prices(0.50, 0.50)
        summary = svc.session_summary()
        assert summary["wins"] == 1
        assert summary["losses"] == 0
        assert summary["initial_cash"] == 1000.0
        assert "final_balance" in summary
        assert "net_pnl" in summary
        assert "total_return_pct" in summary
