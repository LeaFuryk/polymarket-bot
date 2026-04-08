"""Tests for PortfolioService."""

import pytest

from polybot.services.portfolio_service import TAKER_FEE_RATE, PortfolioService


def _fee(shares: float, price: float) -> float:
    """Helper: compute expected taker fee."""
    return shares * TAKER_FEE_RATE * price * (1.0 - price)


class TestBuy:
    def test_buy_up_deducts_cash(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        assert svc.state.cash == 900.0

    def test_buy_up_adds_shares_minus_fee(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        gross = 100.0 / 0.50  # 200
        fee_shares = _fee(gross, 0.50)
        assert svc.state.up_position.shares == pytest.approx(gross - fee_shares)

    def test_buy_down_minus_fee(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("DOWN", amount_usd=50.0, price=0.25)
        gross = 50.0 / 0.25  # 200
        fee_shares = _fee(gross, 0.25)
        assert svc.state.down_position.shares == pytest.approx(gross - fee_shares)
        assert svc.state.cash == 950.0

    def test_buy_insufficient_cash_raises(self):
        svc = PortfolioService(initial_cash=100.0)
        with pytest.raises(ValueError, match="Insufficient cash"):
            svc.buy("UP", amount_usd=200.0, price=0.50)

    def test_buy_tracks_fees(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        gross = 100.0 / 0.50
        expected_fee_usd = _fee(gross, 0.50) * 0.50
        summary = svc.session_summary()
        assert summary["total_fees"] == pytest.approx(expected_fee_usd)


class TestSell:
    def test_sell_credits_cash_minus_fee(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        shares = svc.state.up_position.shares
        svc.sell("UP", shares=shares, price=0.60)
        gross_proceeds = shares * 0.60
        fee_usd = _fee(shares, 0.60)
        assert svc.state.cash == pytest.approx(900.0 + gross_proceeds - fee_usd)

    def test_sell_insufficient_shares_raises(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        with pytest.raises(ValueError, match="Insufficient shares"):
            svc.sell("UP", shares=300.0, price=0.60)


class TestSettle:
    def test_settle_up_wins_no_fee(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        shares = svc.state.up_position.shares
        svc.settle("UP")
        # Winning payout = shares * $1, no settlement fee
        assert svc.state.cash == pytest.approx(900.0 + shares)
        assert svc.state.up_position.shares == 0.0
        assert svc.state.wins == 1

    def test_settle_down_wins_up_loses(self):
        svc = PortfolioService(initial_cash=1000.0)
        svc.buy("UP", amount_usd=100.0, price=0.50)
        svc.buy("DOWN", amount_usd=50.0, price=0.40)
        down_shares = svc.state.down_position.shares
        svc.settle("DOWN")
        # UP worthless, DOWN pays $1 each
        assert svc.state.cash == pytest.approx(850.0 + down_shares)
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
        assert "total_fees" in summary
        assert "total_return_pct" in summary
