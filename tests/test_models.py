"""Tests for the models module — computed properties, validation, edge cases."""

from __future__ import annotations

import time

import pytest

from polybot.models import (
    Action,
    BtcCandle,
    CandleMarket,
    OrderbookLevel,
    OrderbookSnapshot,
    OrderType,
    PendingLimitOrder,
    PositionState,
    RiskCheckResult,
    Scorecard,
    ScorecardDelta,
    Side,
    SimulatedFill,
    TokenSide,
    TradingDecision,
)
from polybot.models.constants import (
    DEFAULT_CONFIDENCE,
    DEFAULT_OBSERVATION_EXPIRY,
    DEFAULT_TTL_SECONDS,
    FLAT_POSITION_THRESHOLD,
)

# ── Constants ──────────────────────────────────────────────────────────


class TestConstants:
    def test_flat_threshold(self):
        assert FLAT_POSITION_THRESHOLD == 1e-9

    def test_default_confidence(self):
        assert DEFAULT_CONFIDENCE == 0.5

    def test_default_ttl(self):
        assert DEFAULT_TTL_SECONDS == 300

    def test_default_observation_expiry(self):
        assert DEFAULT_OBSERVATION_EXPIRY == 30


# ── Enums ──────────────────────────────────────────────────────────────


class TestEnums:
    def test_side_values(self):
        assert Side.BUY.value == "BUY"
        assert Side.SELL.value == "SELL"

    def test_action_values(self):
        assert Action.BUY.value == "BUY"
        assert Action.SELL.value == "SELL"
        assert Action.HOLD.value == "HOLD"

    def test_order_type_values(self):
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"

    def test_token_side_values(self):
        assert TokenSide.UP.value == "up"
        assert TokenSide.DOWN.value == "down"


# ── BtcCandle ──────────────────────────────────────────────────────────


class TestBtcCandle:
    def _candle(self, **kwargs) -> BtcCandle:
        defaults = dict(
            open_time=0.0,
            open=85000.0,
            high=85100.0,
            low=84900.0,
            close=85050.0,
            volume=100.0,
            close_time=300.0,
        )
        defaults.update(kwargs)
        return BtcCandle(**defaults)

    def test_direction_up(self):
        c = self._candle(open=85000.0, close=85050.0)
        assert c.direction == "up"

    def test_direction_down(self):
        c = self._candle(open=85000.0, close=84950.0)
        assert c.direction == "down"

    def test_direction_flat(self):
        c = self._candle(open=85000.0, close=85000.0)
        assert c.direction == "up"  # >= means up

    def test_body_pct_positive(self):
        c = self._candle(open=85000.0, close=85850.0)
        assert c.body_pct == pytest.approx(1.0)

    def test_body_pct_negative(self):
        c = self._candle(open=85000.0, close=84150.0)
        assert c.body_pct == pytest.approx(-1.0)

    def test_body_pct_zero_open(self):
        c = self._candle(open=0.0, close=100.0)
        assert c.body_pct == 0.0


# ── OrderbookSnapshot ──────────────────────────────────────────────────


class TestOrderbookSnapshot:
    def test_empty_orderbook(self):
        ob = OrderbookSnapshot()
        assert ob.best_bid is None
        assert ob.best_ask is None
        assert ob.midpoint is None
        assert ob.spread is None
        assert ob.spread_pct is None
        assert ob.bid_depth == 0.0
        assert ob.ask_depth == 0.0

    def test_full_orderbook(self):
        ob = OrderbookSnapshot(
            bids=[OrderbookLevel(price=0.50, size=100.0)],
            asks=[OrderbookLevel(price=0.55, size=200.0)],
        )
        assert ob.best_bid == 0.50
        assert ob.best_ask == 0.55
        assert ob.midpoint == pytest.approx(0.525)
        assert ob.spread == pytest.approx(0.05)
        assert ob.spread_pct == pytest.approx(0.05 / 0.525)
        assert ob.bid_depth == pytest.approx(50.0)
        assert ob.ask_depth == pytest.approx(110.0)

    def test_bids_only(self):
        ob = OrderbookSnapshot(
            bids=[OrderbookLevel(price=0.50, size=100.0)],
        )
        assert ob.best_bid == 0.50
        assert ob.best_ask is None
        assert ob.midpoint is None
        assert ob.spread is None

    def test_asks_only(self):
        ob = OrderbookSnapshot(
            asks=[OrderbookLevel(price=0.55, size=200.0)],
        )
        assert ob.best_bid is None
        assert ob.best_ask == 0.55
        assert ob.midpoint is None

    def test_multi_level_depth(self):
        ob = OrderbookSnapshot(
            bids=[
                OrderbookLevel(price=0.50, size=100.0),
                OrderbookLevel(price=0.49, size=200.0),
            ],
            asks=[
                OrderbookLevel(price=0.55, size=150.0),
            ],
        )
        assert ob.best_bid == 0.50  # first level
        assert ob.bid_depth == pytest.approx(0.50 * 100 + 0.49 * 200)
        assert ob.ask_depth == pytest.approx(0.55 * 150)


# ── CandleMarket ──────────────────────────────────────────────────────


class TestCandleMarket:
    def test_time_remaining_future(self):
        m = CandleMarket(
            condition_id="c1",
            up_token_id="u1",
            down_token_id="d1",
            slug="test",
            title="Test",
            start_time=time.time(),
            end_time=time.time() + 300,
        )
        assert m.time_remaining() > 0

    def test_time_remaining_past(self):
        m = CandleMarket(
            condition_id="c1",
            up_token_id="u1",
            down_token_id="d1",
            slug="test",
            title="Test",
            start_time=0.0,
            end_time=1.0,
        )
        assert m.time_remaining() == 0.0


# ── PendingLimitOrder ──────────────────────────────────────────────────


class TestPendingLimitOrder:
    def test_expires_at(self):
        o = PendingLimitOrder(
            side=Side.BUY,
            size=10.0,
            limit_price=0.50,
            created_at=1000.0,
            ttl_seconds=300,
        )
        assert o.expires_at == 1300.0

    def test_is_expired_not_yet(self):
        o = PendingLimitOrder(
            side=Side.BUY,
            size=10.0,
            limit_price=0.50,
            created_at=time.time(),
            ttl_seconds=300,
        )
        assert not o.is_expired()

    def test_is_expired_past(self):
        o = PendingLimitOrder(
            side=Side.BUY,
            size=10.0,
            limit_price=0.50,
            created_at=0.0,
            ttl_seconds=1,
        )
        assert o.is_expired()

    def test_is_expired_with_now(self):
        o = PendingLimitOrder(
            side=Side.BUY,
            size=10.0,
            limit_price=0.50,
            created_at=1000.0,
            ttl_seconds=300,
        )
        assert not o.is_expired(now=1200.0)
        assert o.is_expired(now=1300.0)

    def test_default_ttl(self):
        o = PendingLimitOrder(side=Side.BUY, size=10.0, limit_price=0.50)
        assert o.ttl_seconds == DEFAULT_TTL_SECONDS

    def test_auto_order_id(self):
        o = PendingLimitOrder(side=Side.BUY, size=10.0, limit_price=0.50)
        assert len(o.order_id) == 12


# ── PositionState ──────────────────────────────────────────────────────


class TestPositionState:
    def test_market_value(self):
        p = PositionState(shares=10.0, avg_entry_price=0.50)
        assert p.market_value == pytest.approx(5.0)

    def test_is_flat_zero(self):
        p = PositionState(shares=0.0)
        assert p.is_flat()

    def test_is_flat_tiny(self):
        p = PositionState(shares=1e-10)
        assert p.is_flat()

    def test_is_flat_nonzero(self):
        p = PositionState(shares=0.01)
        assert not p.is_flat()


# ── TradingDecision ───────────────────────────────────────────────────


class TestTradingDecision:
    def test_defaults(self):
        d = TradingDecision(action=Action.HOLD)
        assert d.confidence == DEFAULT_CONFIDENCE
        assert d.ttl_seconds == DEFAULT_TTL_SECONDS
        assert d.order_type == OrderType.MARKET
        assert d.token_side == TokenSide.UP

    def test_confidence_validation(self):
        with pytest.raises(ValueError):
            TradingDecision(action=Action.BUY, confidence=1.5)

    def test_confidence_validation_negative(self):
        with pytest.raises(ValueError):
            TradingDecision(action=Action.BUY, confidence=-0.1)


# ── Simple model construction ─────────────────────────────────────────


class TestModelConstruction:
    def test_risk_check_result(self):
        r = RiskCheckResult(passed=True, check_name="test")
        assert r.passed
        assert r.reason == ""

    def test_simulated_fill(self):
        f = SimulatedFill(
            side=Side.BUY,
            size=10.0,
            fill_price=0.50,
            slippage_bps=5.0,
            fee_amount=0.10,
            total_cost=5.10,
        )
        assert f.total_cost == 5.10

    def test_scorecard_defaults(self):
        s = Scorecard()
        assert s.resolutions == 0
        assert s.win_rate == 0.0

    def test_scorecard_delta(self):
        sd = ScorecardDelta(current=Scorecard(win_rate=0.6))
        assert sd.previous is None
        assert sd.current.win_rate == 0.6


# ── __init__.py re-exports ─────────────────────────────────────────────


class TestReExports:
    def test_all_models_importable(self):
        from polybot.models import (
            Action,
            TradeRecord,
        )

        # Just verify they're all importable
        assert Action is not None
        assert TradeRecord is not None

    def test_constants_importable(self):
        from polybot.models import DEFAULT_CONFIDENCE, FLAT_POSITION_THRESHOLD

        assert DEFAULT_CONFIDENCE == 0.5
        assert FLAT_POSITION_THRESHOLD == 1e-9
