"""Tests for tasks/trade_logger.py — trade record and decision row builders."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from polybot.models import Action, OrderType, TokenSide, TradingDecision
from polybot.tasks.trade_logger import build_trade_record


def _snapshot(
    *,
    mid: float = 0.55,
    best_bid: float = 0.54,
    best_ask: float = 0.56,
    spread: float = 0.02,
    btc_price: float = 60000.0,
):
    """Minimal snapshot-like namespace for testing."""
    ob = SimpleNamespace(
        midpoint=mid,
        best_bid=best_bid,
        best_ask=best_ask,
        spread=spread,
        spread_pct=spread / mid * 100 if mid else 0,
        bid_depth=100.0,
        ask_depth=100.0,
    )
    down_ob = SimpleNamespace(
        midpoint=1.0 - mid,
        best_bid=1.0 - best_ask,
        best_ask=1.0 - best_bid,
        spread=spread,
        spread_pct=spread / (1.0 - mid) * 100 if mid < 1.0 else 0,
        bid_depth=80.0,
        ask_depth=80.0,
    )
    return SimpleNamespace(
        orderbook=ob,
        down_orderbook=down_ob,
        last_trade_price=mid,
        btc_price=SimpleNamespace(price_usd=btc_price),
        volume_24h=50000.0,
    )


def _portfolio(cash: float = 1000.0, shares: float = 50.0, avg_entry: float = 0.50):
    """Minimal portfolio-like namespace."""
    pos = SimpleNamespace(
        shares=shares,
        avg_entry_price=avg_entry,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
    )
    p = MagicMock()
    p.position = pos
    p.up_position = pos
    p.down_position = SimpleNamespace(shares=0.0)
    p.cash = cash
    p.total_value_at_market = MagicMock(return_value=cash + shares * 0.55)
    p.total_value = cash + shares * 0.55
    return p


def _risk_state(daily_pnl: float = 0.0, is_halted: bool = False):
    return SimpleNamespace(daily_pnl=daily_pnl, is_halted=is_halted)


def _decision(
    action=Action.BUY,
    side=TokenSide.UP,
    size=50.0,
    confidence=0.75,
):
    return TradingDecision(
        action=action,
        order_type=OrderType.MARKET,
        size=size,
        confidence=confidence,
        reasoning="test decision",
        market_view="neutral",
        token_side=side,
    )


def _fill(price: float = 0.56, size: float = 50.0):
    return SimpleNamespace(
        fill_price=price,
        size=size,
        slippage_bps=1.5,
        fee_amount=0.02,
    )


# ---------------------------------------------------------------------------
# build_trade_record — basic assembly
# ---------------------------------------------------------------------------


class TestBuildTradeRecord:
    def test_minimal_no_decision(self):
        """Record without a decision should have basic market data."""
        snap = _snapshot()
        port = _portfolio()
        record = build_trade_record(
            cycle=1,
            snapshot=snap,
            portfolio=port,
            risk_state=_risk_state(),
        )
        assert record.cycle_number == 1
        assert record.midpoint == 0.55
        assert record.btc_price_usd == 60000.0
        assert record.action == Action.HOLD
        assert record.fill_price is None

    def test_with_decision(self):
        """Record with a BUY decision should populate action fields."""
        snap = _snapshot()
        port = _portfolio()
        dec = _decision()
        record = build_trade_record(
            cycle=2,
            snapshot=snap,
            portfolio=port,
            risk_state=_risk_state(),
            decision=dec,
            latency_ms=150.0,
            last_cycle_api_cost=0.01,
        )
        assert record.action == Action.BUY
        assert record.token_side == TokenSide.UP
        assert record.decision_size == 50.0
        assert record.confidence == 0.75
        assert record.ai_latency_ms == 150.0
        assert record.ai_cost == 0.01

    def test_with_fill(self):
        """Fill data should be applied to the record."""
        snap = _snapshot()
        port = _portfolio()
        dec = _decision()
        fill = _fill()
        record = build_trade_record(
            cycle=3,
            snapshot=snap,
            portfolio=port,
            risk_state=_risk_state(),
            decision=dec,
            fill=fill,
        )
        assert record.fill_price == 0.56
        assert record.fill_size == 50.0
        assert record.slippage_bps == 1.5
        assert record.fee_amount == 0.02

    def test_with_paper_fill(self):
        """Paper fill data should populate shadow fields."""
        snap = _snapshot()
        port = _portfolio()
        pf = SimpleNamespace(fill_price=0.55, total_cost=27.5)
        record = build_trade_record(
            cycle=4,
            snapshot=snap,
            portfolio=port,
            risk_state=_risk_state(),
            paper_fill=pf,
        )
        assert record.paper_fill_price == 0.55
        assert record.paper_total_cost == 27.5

    def test_with_market(self):
        """Market sets candle_slug and time_remaining extra."""
        snap = _snapshot()
        port = _portfolio()
        mkt = SimpleNamespace(slug="test-market-slug")
        mkt.time_remaining = MagicMock(return_value=120.0)
        record = build_trade_record(
            cycle=5,
            snapshot=snap,
            portfolio=port,
            risk_state=_risk_state(),
            market=mkt,
        )
        assert record.candle_slug == "test-market-slug"
        assert record.extra["time_remaining"] == 120.0

    def test_risk_blocked(self):
        record = build_trade_record(
            cycle=6,
            snapshot=_snapshot(),
            portfolio=_portfolio(),
            risk_state=_risk_state(),
            risk_blocked=True,
            risk_reason="drawdown limit",
        )
        assert record.risk_blocked is True
        assert record.risk_block_reason == "drawdown limit"

    def test_risk_halted(self):
        record = build_trade_record(
            cycle=7,
            snapshot=_snapshot(),
            portfolio=_portfolio(),
            risk_state=_risk_state(is_halted=True),
        )
        assert record.risk_halted is True

    def test_screen_passed(self):
        record = build_trade_record(
            cycle=8,
            snapshot=_snapshot(),
            portfolio=_portfolio(),
            risk_state=_risk_state(),
            screen_passed=True,
            screen_input="some screen context",
        )
        assert record.extra["screen_passed"] is True
        assert record.extra["screen_input"] == "some screen context"

    def test_buy_captures_opposite_ask(self):
        """BUY decision should capture opposite side ask price."""
        snap = _snapshot(best_bid=0.54, best_ask=0.56)
        port = _portfolio()
        dec = _decision(action=Action.BUY, side=TokenSide.UP)
        record = build_trade_record(
            cycle=9,
            snapshot=snap,
            portfolio=port,
            risk_state=_risk_state(),
            decision=dec,
            signal_type="momentum",
            reversal_rate=0.35,
        )
        assert "opposite_ask" in record.extra
        assert record.extra["signal_type"] == "momentum"
        assert record.extra["reversal_rate"] == 0.35

    def test_sell_no_opposite_ask(self):
        """SELL decision should NOT capture opposite_ask or signal fields."""
        snap = _snapshot()
        port = _portfolio()
        dec = _decision(action=Action.SELL, side=TokenSide.UP)
        record = build_trade_record(
            cycle=10,
            snapshot=snap,
            portfolio=port,
            risk_state=_risk_state(),
            decision=dec,
        )
        assert "opposite_ask" not in record.extra
        assert "signal_type" not in record.extra

    def test_live_result(self):
        """Live result should override limit_price and store telemetry."""
        snap = _snapshot()
        port = _portfolio()
        dec = _decision()
        lr = MagicMock()
        lr.limit_price = 0.57
        lr.model_dump = MagicMock(return_value={"order_id": "abc", "status": "filled"})
        record = build_trade_record(
            cycle=11,
            snapshot=snap,
            portfolio=port,
            risk_state=_risk_state(),
            decision=dec,
            live_result=lr,
        )
        assert record.limit_price == 0.57
        assert record.extra["live_order"]["order_id"] == "abc"

    def test_hypothetical_direction(self):
        """Hypothetical direction should be stored in extra."""
        snap = _snapshot()
        port = _portfolio()
        dec = TradingDecision(
            action=Action.HOLD,
            order_type=OrderType.MARKET,
            size=0.0,
            confidence=0.6,
            reasoning="testing",
            market_view="neutral",
            token_side=TokenSide.UP,
            hypothetical_direction="down",
        )
        record = build_trade_record(
            cycle=12,
            snapshot=snap,
            portfolio=port,
            risk_state=_risk_state(),
            decision=dec,
        )
        assert record.extra["hypothetical_direction"] == "down"

    def test_no_btc_price(self):
        """Should handle None btc_price gracefully."""
        snap = _snapshot()
        snap.btc_price = None
        port = _portfolio()
        record = build_trade_record(
            cycle=13,
            snapshot=snap,
            portfolio=port,
            risk_state=_risk_state(),
        )
        assert record.btc_price_usd is None
