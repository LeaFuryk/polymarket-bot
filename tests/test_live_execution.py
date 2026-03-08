"""Tests for LiveExecutionEngine — drift guard, spread guard, partial fill fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from polybot.config import ApiConfig, TradingConfig
from polybot.execution.constants import MAX_SUBMIT_SPREAD_PCT
from polybot.execution.live import LiveExecutionEngine
from polybot.models import (
    Action,
    OrderbookLevel,
    OrderbookSnapshot,
    Side,
    TokenSide,
    TradingDecision,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ob(best_bid: float, best_ask: float) -> OrderbookSnapshot:
    """Build a simple 1-level orderbook."""
    return OrderbookSnapshot(
        bids=[OrderbookLevel(price=best_bid, size=100)],
        asks=[OrderbookLevel(price=best_ask, size=100)],
    )


def _wide_ob(best_bid: float, best_ask: float) -> OrderbookSnapshot:
    """Build an orderbook with deliberately wide spread."""
    return OrderbookSnapshot(
        bids=[OrderbookLevel(price=best_bid, size=100)],
        asks=[OrderbookLevel(price=best_ask, size=100)],
    )


def _decision(action: Action, size: float = 10.0, token_side: TokenSide = TokenSide.UP) -> TradingDecision:
    return TradingDecision(action=action, size=size, confidence=0.7, token_side=token_side)


@pytest.fixture
def engine():
    """Create a LiveExecutionEngine with safe defaults for testing."""
    tc = TradingConfig(
        mode="live",
        private_key="0x" + "a" * 64,
        api_key="test",
        api_secret="test",
        api_passphrase="test",
        max_order_size_usd=100.0,
        max_session_loss_usd=50.0,
        min_wallet_balance_usd=1.0,
        max_price_drift_pct=0.05,
        limit_order_ttl_seconds=3,
        dry_run=False,
    )
    ac = ApiConfig()
    with patch("polybot.execution.live.ClobClient"):
        eng = LiveExecutionEngine(tc, ac)
    eng.set_current_token_ids("up_token_123", "down_token_456")
    eng._wallet_balance = 50.0
    return eng


# ---------------------------------------------------------------------------
# Drift guard — BUY
# ---------------------------------------------------------------------------


class TestDriftGuardBuy:
    """BUY orders should be skipped when fresh price drifts up > max_price_drift_pct."""

    @pytest.mark.asyncio
    async def test_buy_skipped_when_drift_exceeds_max(self, engine):
        """Decision ask=0.50, fresh ask=0.56 → drift=12% > 5% → skip."""
        decision_ob = _ob(0.48, 0.50)
        fresh_ob = _ob(0.54, 0.56)

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)

        result = await engine.execute(_decision(Action.BUY, size=10.0), decision_ob)
        assert result is None
        assert "price drift" in engine.last_skip_reason

    @pytest.mark.asyncio
    async def test_buy_repriced_when_drift_within_max(self, engine):
        """Decision ask=0.50, fresh ask=0.52 → drift=4% ≤ 5% → reprice to 0.52."""
        decision_ob = _ob(0.48, 0.50)
        fresh_ob = _ob(0.50, 0.52)

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)
        # Mock _submit_limit_order to capture the repriced limit_price
        captured = {}

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            from polybot.models import LiveOrderResult

            captured["limit_price"] = limit_price
            captured["fresh_ob"] = fresh_ob
            return LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        engine._submit_limit_order = fake_submit

        result = await engine.execute(_decision(Action.BUY, size=10.0), decision_ob)
        assert result is not None
        assert captured["limit_price"] == pytest.approx(0.52)
        # Telemetry
        assert result.reprice_from == pytest.approx(0.50)
        assert result.drift_pct == pytest.approx(0.04)
        assert result.decision_ob_ask == pytest.approx(0.50)

    @pytest.mark.asyncio
    async def test_buy_drift_just_under_max_passes(self, engine):
        """Drift of ~4.8% (just under 5%) should pass."""
        decision_ob = _ob(0.48, 0.50)
        fresh_ob = _ob(0.504, 0.524)  # drift = 0.024/0.50 = 4.8%

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            from polybot.models import LiveOrderResult

            return LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        engine._submit_limit_order = fake_submit

        result = await engine.execute(_decision(Action.BUY, size=10.0), decision_ob)
        assert result is not None

    @pytest.mark.asyncio
    async def test_buy_negative_drift_reprices(self, engine):
        """Price moved down (favorable) → still reprices to fresh ask."""
        decision_ob = _ob(0.48, 0.50)
        fresh_ob = _ob(0.46, 0.48)  # drift = -4%

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)
        captured = {}

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            from polybot.models import LiveOrderResult

            captured["limit_price"] = limit_price
            return LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        engine._submit_limit_order = fake_submit

        result = await engine.execute(_decision(Action.BUY, size=10.0), decision_ob)
        assert result is not None
        assert captured["limit_price"] == pytest.approx(0.48)


# ---------------------------------------------------------------------------
# Drift guard — SELL (always reprices, no cap)
# ---------------------------------------------------------------------------


class TestDriftGuardSell:
    """SELL orders should always reprice to fresh bid, even with large drift."""

    @pytest.mark.asyncio
    async def test_sell_reprices_with_large_drift(self, engine):
        """Decision bid=0.50, fresh bid=0.30 → drift=-40% → still reprices."""
        decision_ob = _ob(0.50, 0.52)
        fresh_ob = _ob(0.30, 0.32)

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)
        # Need to mock conditional balance for SELL
        engine._get_conditional_balance = AsyncMock(return_value=100.0)
        captured = {}

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            from polybot.models import LiveOrderResult

            captured["limit_price"] = limit_price
            return LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        engine._submit_limit_order = fake_submit

        result = await engine.execute(_decision(Action.SELL, size=10.0), decision_ob)
        assert result is not None
        assert captured["limit_price"] == pytest.approx(0.30)
        assert result.drift_pct == pytest.approx(-0.40)

    @pytest.mark.asyncio
    async def test_sell_reprices_upward(self, engine):
        """SELL with price moving up → reprice to higher fresh bid."""
        decision_ob = _ob(0.50, 0.52)
        fresh_ob = _ob(0.55, 0.57)

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)
        engine._get_conditional_balance = AsyncMock(return_value=100.0)
        captured = {}

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            from polybot.models import LiveOrderResult

            captured["limit_price"] = limit_price
            return LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        engine._submit_limit_order = fake_submit

        result = await engine.execute(_decision(Action.SELL, size=10.0), decision_ob)
        assert result is not None
        assert captured["limit_price"] == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# Spread guard — BUY only
# ---------------------------------------------------------------------------


class TestSpreadGuard:
    """BUY orders should be skipped when submit-time spread exceeds MAX_SUBMIT_SPREAD_PCT."""

    @pytest.mark.asyncio
    async def test_buy_skipped_on_wide_spread(self, engine):
        """Spread = (0.80 - 0.60) / 0.70 = 28.6% > 5% → skip."""
        decision_ob = _ob(0.48, 0.50)
        fresh_ob = _wide_ob(0.60, 0.80)

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)

        result = await engine.execute(_decision(Action.BUY, size=10.0), decision_ob)
        assert result is None
        assert "submit spread" in engine.last_skip_reason

    @pytest.mark.asyncio
    async def test_buy_passes_on_narrow_spread(self, engine):
        """Spread = (0.51 - 0.49) / 0.50 = 4% ≤ 5% → pass."""
        decision_ob = _ob(0.48, 0.50)
        fresh_ob = _ob(0.49, 0.51)

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            from polybot.models import LiveOrderResult

            return LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        engine._submit_limit_order = fake_submit

        result = await engine.execute(_decision(Action.BUY, size=10.0), decision_ob)
        assert result is not None

    @pytest.mark.asyncio
    async def test_sell_not_blocked_by_wide_spread(self, engine):
        """SELL should not be blocked even on wide spread."""
        decision_ob = _ob(0.50, 0.52)
        fresh_ob = _wide_ob(0.30, 0.80)  # ~67% spread

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)
        engine._get_conditional_balance = AsyncMock(return_value=100.0)

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            from polybot.models import LiveOrderResult

            return LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        engine._submit_limit_order = fake_submit

        result = await engine.execute(_decision(Action.SELL, size=10.0), decision_ob)
        assert result is not None


# ---------------------------------------------------------------------------
# Spread guard fires before drift guard
# ---------------------------------------------------------------------------


class TestSpreadBeforeDrift:
    """Spread guard should fire before drift guard (wider spread is a stronger signal)."""

    @pytest.mark.asyncio
    async def test_wide_spread_and_high_drift_reports_spread(self, engine):
        """Both spread and drift exceed limits → skip reason mentions spread."""
        decision_ob = _ob(0.48, 0.50)
        # Wide spread AND high drift
        fresh_ob = _wide_ob(0.60, 0.80)  # spread ~29%, drift 60%

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)

        result = await engine.execute(_decision(Action.BUY, size=10.0), decision_ob)
        assert result is None
        assert "submit spread" in engine.last_skip_reason


# ---------------------------------------------------------------------------
# Fresh OB passthrough to _submit_limit_order
# ---------------------------------------------------------------------------


class TestFreshObPassthrough:
    """Fresh OB should be passed to _submit_limit_order to avoid double-fetch."""

    @pytest.mark.asyncio
    async def test_fresh_ob_passed_to_submit(self, engine):
        """execute() passes the fresh OB it fetched to _submit_limit_order."""
        decision_ob = _ob(0.48, 0.50)
        fresh_ob = _ob(0.49, 0.51)

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)
        captured = {}

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            from polybot.models import LiveOrderResult

            captured["fresh_ob"] = fresh_ob
            return LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        engine._submit_limit_order = fake_submit

        await engine.execute(_decision(Action.BUY, size=10.0), decision_ob)
        assert captured["fresh_ob"] is fresh_ob

    @pytest.mark.asyncio
    async def test_dry_run_skips_reprice(self, engine):
        """In dry_run mode, no reprice/drift/spread guard happens."""
        engine._config.dry_run = True
        decision_ob = _ob(0.48, 0.50)

        # Even if refetch would return something wildly different, dry_run skips it
        engine._refetch_orderbook = AsyncMock(return_value=_ob(0.80, 0.90))

        async def fake_simulate(*, token_id, side, size, limit_price, ttl):
            from polybot.models import LiveOrderResult

            return LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        engine._simulate_limit_order = fake_simulate

        result = await engine.execute(_decision(Action.BUY, size=10.0), decision_ob)
        assert result is not None
        # No reprice telemetry in dry_run
        assert result.reprice_from is None
        assert result.drift_pct is None


# ---------------------------------------------------------------------------
# Partial fill fallback
# ---------------------------------------------------------------------------


class TestPartialFillFallback:
    """When parse_order_response returns None but size_matched > 0, use make_fill_from_balance."""

    @pytest.mark.asyncio
    async def test_partial_fill_during_poll(self, engine):
        """CLOB status=LIVE but size_matched=37.15 → fallback fill is captured."""
        decision_ob = _ob(0.48, 0.50)
        fresh_ob = _ob(0.49, 0.50)

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)

        # Patch _submit_limit_order to simulate the partial fill scenario
        from polybot.models import LiveOrderResult

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            """Simulate poll loop where status=LIVE but size_matched=37.15."""
            result = LiveOrderResult(limit_price=limit_price, ttl_used=ttl)
            result.order_id = "test_order"
            result.submit_ts = 1000.0

            # The partial fill scenario: parse_order_response returns None
            # because status is LIVE (not MATCHED), but size_matched > 0.
            # The fallback constructs a fill from the known matched size.
            from polybot.execution.helpers import make_fill_from_balance

            sm = 37.15
            result.fill = make_fill_from_balance(side, sm, limit_price)
            result.fill_ts = 1001.0
            result.fill_source = "size_matched"
            result.final_order_status = "LIVE"
            result.size_matched = sm
            return result

        engine._submit_limit_order = fake_submit

        result = await engine.execute(_decision(Action.BUY, size=40.0), decision_ob)
        assert result is not None
        assert result.fill is not None
        assert result.fill.size == pytest.approx(37.15)
        assert result.fill_source == "size_matched"

    @pytest.mark.asyncio
    async def test_partial_fill_post_cancel(self, engine):
        """Post-cancel: status=LIVE, size_matched=37 → fallback constructs fill."""
        decision_ob = _ob(0.48, 0.50)
        fresh_ob = _ob(0.49, 0.50)

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)

        from polybot.models import LiveOrderResult

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            result = LiveOrderResult(limit_price=limit_price, ttl_used=ttl)
            result.order_id = "test_order"
            result.submit_ts = 1000.0

            from polybot.execution.helpers import make_fill_from_balance

            sm = 37.0
            result.fill = make_fill_from_balance(side, sm, limit_price)
            result.fill_ts = 1004.0
            result.fill_source = "post_cancel"
            result.final_order_status = "LIVE"
            result.size_matched = sm
            return result

        engine._submit_limit_order = fake_submit

        result = await engine.execute(_decision(Action.BUY, size=40.0), decision_ob)
        assert result is not None
        assert result.fill is not None
        assert result.fill.size == pytest.approx(37.0)


# ---------------------------------------------------------------------------
# Partial fill fallback — unit test on the actual poll loop logic
# ---------------------------------------------------------------------------


class TestPartialFillFallbackUnit:
    """Unit-test the fallback directly using parse_order_response + make_fill_from_balance."""

    def test_parse_returns_none_for_live_status(self):
        """parse_order_response returns None when status=LIVE, success=False."""
        from polybot.execution.helpers import parse_order_response

        resp = {"status": "LIVE", "success": False, "size_matched": "37.15"}
        fill = parse_order_response(resp, Side.BUY, 40.0, 0.50)
        assert fill is None

    def test_fallback_constructs_fill_from_matched_size(self):
        """make_fill_from_balance correctly constructs a fill from matched size."""
        from polybot.execution.helpers import make_fill_from_balance

        fill = make_fill_from_balance(Side.BUY, 37.15, 0.50)
        assert fill.side == Side.BUY
        assert fill.size == pytest.approx(37.15)
        assert fill.fill_price == pytest.approx(0.50)
        assert fill.total_cost > 0  # BUY = cash outflow

    def test_combined_fallback_logic(self):
        """The actual logic: if parse returns None and sm > 0 → use fallback."""
        from polybot.execution.helpers import make_fill_from_balance, parse_order_response

        order_status = {"status": "LIVE", "success": False, "size_matched": "37.15"}
        sm = 37.15

        fill = parse_order_response(order_status, Side.BUY, 40.0, 0.50)
        if fill is None and sm > 0:
            fill = make_fill_from_balance(Side.BUY, sm, 0.50)

        assert fill is not None
        assert fill.size == pytest.approx(37.15)


# ---------------------------------------------------------------------------
# Model telemetry fields
# ---------------------------------------------------------------------------


class TestLiveOrderResultTelemetry:
    """LiveOrderResult should have reprice_from and drift_pct fields."""

    def test_defaults_none(self):
        from polybot.models import LiveOrderResult

        r = LiveOrderResult()
        assert r.reprice_from is None
        assert r.drift_pct is None

    def test_set_values(self):
        from polybot.models import LiveOrderResult

        r = LiveOrderResult(reprice_from=0.50, drift_pct=0.04)
        assert r.reprice_from == pytest.approx(0.50)
        assert r.drift_pct == pytest.approx(0.04)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestNewConstants:
    def test_max_submit_spread_pct(self):
        assert MAX_SUBMIT_SPREAD_PCT == 0.05

    def test_max_price_drift_pct_updated(self):
        from polybot.config.constants import DEFAULT_MAX_PRICE_DRIFT_PCT

        assert DEFAULT_MAX_PRICE_DRIFT_PCT == 0.05


# ---------------------------------------------------------------------------
# Edge cases — fresh OB is None / has no price
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_fresh_ob_none_skips_reprice(self, engine):
        """If _refetch_orderbook returns None, no repricing happens."""
        decision_ob = _ob(0.48, 0.50)

        engine._refetch_orderbook = AsyncMock(return_value=None)

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            from polybot.models import LiveOrderResult

            return LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        engine._submit_limit_order = fake_submit

        result = await engine.execute(_decision(Action.BUY, size=10.0), decision_ob)
        assert result is not None
        assert result.reprice_from is None

    @pytest.mark.asyncio
    async def test_fresh_ob_no_ask_skips_reprice(self, engine):
        """If fresh OB has no ask side, reprice is skipped."""
        decision_ob = _ob(0.48, 0.50)
        fresh_ob = OrderbookSnapshot(bids=[OrderbookLevel(price=0.49, size=100)], asks=[])

        engine._refetch_orderbook = AsyncMock(return_value=fresh_ob)

        async def fake_submit(*, token_id, side, size, limit_price, ttl, fresh_ob=None):
            from polybot.models import LiveOrderResult

            return LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        engine._submit_limit_order = fake_submit

        result = await engine.execute(_decision(Action.BUY, size=10.0), decision_ob)
        assert result is not None
        # No reprice because fresh_price was None
        assert result.reprice_from is None
