"""Tests for polybot.risk — risk manager, constants."""

from __future__ import annotations

import logging

import pytest

from polybot.config import RiskConfig
from polybot.models import (
    Action,
    MarketSnapshot,
    OrderbookLevel,
    OrderbookSnapshot,
    PositionState,
    TokenSide,
    TradingDecision,
)
from polybot.risk.constants import (
    CASH_BUFFER_FACTOR,
    DATE_FORMAT,
    DEFAULT_FILL_PRICE,
    DEPTH_RATIO_LIMIT,
    SHORT_SELL_TOLERANCE,
)
from polybot.risk.manager import RiskManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(
    up_bid: float | None = 0.50,
    up_ask: float | None = 0.55,
    up_size: float = 200.0,
    down_bid: float | None = 0.45,
    down_ask: float | None = 0.50,
    down_size: float = 200.0,
) -> MarketSnapshot:
    up_bids = [OrderbookLevel(price=up_bid, size=up_size)] if up_bid else []
    up_asks = [OrderbookLevel(price=up_ask, size=up_size)] if up_ask else []
    down_bids = [OrderbookLevel(price=down_bid, size=down_size)] if down_bid else []
    down_asks = [OrderbookLevel(price=down_ask, size=down_size)] if down_ask else []
    return MarketSnapshot(
        condition_id="0xtest",
        orderbook=OrderbookSnapshot(bids=up_bids, asks=up_asks),
        down_orderbook=OrderbookSnapshot(bids=down_bids, asks=down_asks),
    )


def _decision(
    action: Action = Action.BUY,
    size: float = 10.0,
    token_side: TokenSide = TokenSide.UP,
) -> TradingDecision:
    return TradingDecision(action=action, size=size, token_side=token_side)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_date_format(self):
        assert DATE_FORMAT == "%Y-%m-%d"

    def test_default_fill_price(self):
        assert DEFAULT_FILL_PRICE == 0.5

    def test_cash_buffer_factor(self):
        assert CASH_BUFFER_FACTOR == 1.005

    def test_short_sell_tolerance(self):
        assert SHORT_SELL_TOLERANCE == 1e-9

    def test_depth_ratio_limit(self):
        assert DEPTH_RATIO_LIMIT == 0.5


# ---------------------------------------------------------------------------
# RiskManager
# ---------------------------------------------------------------------------


class TestRiskManagerInit:
    def test_initial_state(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        assert rm.state.peak_portfolio_value == 1000.0
        assert rm.state.daily_pnl == 0.0
        assert not rm.state.is_halted

    def test_injectable_logger(self):
        custom = logging.getLogger("test.risk")
        rm = RiskManager(RiskConfig(), initial_cash=1000.0, logger=custom)
        assert rm._logger is custom

    def test_default_logger(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        assert rm._logger.name == "polybot.risk.manager"


class TestUpdatePortfolioPeak:
    def test_new_peak(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        rm.update_portfolio_peak(1100.0)
        assert rm.state.peak_portfolio_value == 1100.0

    def test_no_update_below_peak(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        rm.update_portfolio_peak(900.0)
        assert rm.state.peak_portfolio_value == 1000.0

    def test_drawdown_tracked(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        rm.update_portfolio_peak(1100.0)
        rm.update_portfolio_peak(900.0)
        assert rm.state.max_drawdown == 200.0


class TestPreTradeChecks:
    def test_passes_normal_market(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        results = rm.pre_trade_checks(_snapshot())
        assert len(results) == 1
        assert results[0].passed
        assert results[0].check_name == "pre_trade"

    def test_halted_blocks(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        rm.state.is_halted = True
        rm.state.halt_reason = "test halt"
        results = rm.pre_trade_checks(_snapshot())
        assert not results[0].passed
        assert results[0].check_name == "halt_check"

    def test_daily_loss_limit_halts(self):
        rm = RiskManager(RiskConfig(daily_loss_limit_pct=0.10), initial_cash=1000.0)
        rm.state.daily_pnl = -200.0  # > 10% of 1000
        results = rm.pre_trade_checks(_snapshot())
        assert not results[0].passed
        assert results[0].check_name == "daily_loss_limit"
        assert rm.state.is_halted

    def test_thin_books_block(self):
        rm = RiskManager(RiskConfig(min_liquidity=1000.0), initial_cash=1000.0)
        # Small books: up_depth = 0.50*200 + 0.55*200 = 210, down similar
        results = rm.pre_trade_checks(_snapshot(up_size=1.0, down_size=1.0))
        assert any(r.check_name == "min_liquidity" for r in results)

    def test_one_deep_book_passes(self):
        rm = RiskManager(RiskConfig(min_liquidity=100.0), initial_cash=1000.0)
        results = rm.pre_trade_checks(_snapshot())
        assert results[0].passed


class TestPostTradeChecks:
    def test_hold_passes(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        results = rm.post_trade_checks(
            _decision(Action.HOLD),
            PositionState(),
            cash=1000.0,
            portfolio_value=1000.0,
            snapshot=_snapshot(),
        )
        assert results[0].passed
        assert results[0].check_name == "hold_passthrough"

    def test_buy_passes_normal(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        # Tight spread so it doesn't trigger max_spread check
        results = rm.post_trade_checks(
            _decision(Action.BUY, size=5.0),
            PositionState(),
            cash=1000.0,
            portfolio_value=1000.0,
            snapshot=_snapshot(up_bid=0.54, up_ask=0.55),
        )
        assert results[0].passed
        assert results[0].check_name == "post_trade"

    def test_wide_spread_blocks_buy(self):
        rm = RiskManager(RiskConfig(max_spread_pct=0.01), initial_cash=1000.0)
        # spread = 0.55 - 0.50 = 0.05, spread_pct = 0.05/0.525 ≈ 9.5%
        results = rm.post_trade_checks(
            _decision(Action.BUY, size=5.0),
            PositionState(),
            cash=1000.0,
            portfolio_value=1000.0,
            snapshot=_snapshot(),
        )
        assert any(r.check_name == "max_spread" for r in results)

    def test_spread_does_not_block_sell(self):
        rm = RiskManager(RiskConfig(max_spread_pct=0.01), initial_cash=1000.0)
        results = rm.post_trade_checks(
            _decision(Action.SELL, size=5.0),
            PositionState(shares=10.0, avg_entry_price=0.50),
            cash=1000.0,
            portfolio_value=1000.0,
            snapshot=_snapshot(),
        )
        # Spread check only applies to BUY
        assert not any(r.check_name == "max_spread" for r in results)

    def test_max_position_blocks(self):
        rm = RiskManager(RiskConfig(max_position_pct=0.01), initial_cash=1000.0)
        results = rm.post_trade_checks(
            _decision(Action.BUY, size=100.0),
            PositionState(),
            cash=1000.0,
            portfolio_value=1000.0,
            snapshot=_snapshot(),
        )
        assert any(r.check_name == "max_position_size" for r in results)

    def test_concentration_blocks(self):
        rm = RiskManager(RiskConfig(max_concentration_pct=0.01), initial_cash=1000.0)
        results = rm.post_trade_checks(
            _decision(Action.BUY, size=100.0),
            PositionState(),
            cash=1000.0,
            portfolio_value=1000.0,
            snapshot=_snapshot(),
        )
        assert any(r.check_name == "concentration_limit" for r in results)

    def test_cash_insufficiency_blocks(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        results = rm.post_trade_checks(
            _decision(Action.BUY, size=100.0),
            PositionState(),
            cash=1.0,  # not enough
            portfolio_value=1000.0,
            snapshot=_snapshot(),
        )
        assert any(r.check_name == "cash_sufficiency" for r in results)

    def test_short_sell_blocks(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        results = rm.post_trade_checks(
            _decision(Action.SELL, size=100.0),
            PositionState(shares=5.0),
            cash=1000.0,
            portfolio_value=1000.0,
            snapshot=_snapshot(),
        )
        assert any(r.check_name == "short_sell_prevention" for r in results)

    def test_order_vs_depth_buy_blocks(self):
        rm = RiskManager(
            RiskConfig(max_position_pct=1.0, max_concentration_pct=1.0),
            initial_cash=100000.0,
        )
        # ask_depth = 0.55 * 2.0 = 1.1, order = 100 * 0.55 = 55 >> 50% of 1.1
        results = rm.post_trade_checks(
            _decision(Action.BUY, size=100.0),
            PositionState(),
            cash=100000.0,
            portfolio_value=100000.0,
            snapshot=_snapshot(up_size=2.0),
        )
        assert any(r.check_name == "order_vs_depth" for r in results)

    def test_order_vs_depth_sell_blocks(self):
        rm = RiskManager(RiskConfig(), initial_cash=100000.0)
        results = rm.post_trade_checks(
            _decision(Action.SELL, size=100.0),
            PositionState(shares=200.0, avg_entry_price=0.50),
            cash=100000.0,
            portfolio_value=100000.0,
            snapshot=_snapshot(up_size=2.0),
        )
        assert any(r.check_name == "order_vs_depth" for r in results)

    def test_down_token_uses_down_orderbook(self):
        rm = RiskManager(RiskConfig(max_spread_pct=0.001), initial_cash=1000.0)
        # Down orderbook has tight spread, up has wide
        snap = _snapshot(up_bid=0.10, up_ask=0.90, down_bid=0.49, down_ask=0.51)
        results = rm.post_trade_checks(
            _decision(Action.BUY, size=1.0, token_side=TokenSide.DOWN),
            PositionState(),
            cash=1000.0,
            portfolio_value=1000.0,
            snapshot=snap,
        )
        # Down spread = 0.51 - 0.49 = 0.02, pct ≈ 4% > 0.1%
        assert any(r.check_name == "max_spread" for r in results)


class TestRecordTrade:
    def test_accumulates(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        rm.record_trade(pnl=5.0, fees=0.1)
        rm.record_trade(pnl=-2.0, fees=0.05)

        assert rm.state.daily_pnl == pytest.approx(3.0)
        assert rm.state.daily_trades == 2
        assert rm.state.daily_fees == pytest.approx(0.15)


class TestDayReset:
    def test_resets_on_new_day(self):
        rm = RiskManager(RiskConfig(), initial_cash=1000.0)
        rm.state.daily_pnl = -50.0
        rm.state.daily_trades = 10
        rm.state.daily_fees = 1.0
        rm.state.is_halted = True
        rm.state.halt_reason = "test"

        # Force a date mismatch
        rm._day_start = "1970-01-01"
        rm.pre_trade_checks(_snapshot())

        assert rm.state.daily_pnl == 0.0
        assert rm.state.daily_trades == 0
        assert rm.state.daily_fees == 0.0
        assert not rm.state.is_halted
