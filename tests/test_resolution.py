"""Tests for the resolution package."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from polybot.models import CandleMarket
from polybot.resolution import (
    ResolutionRepository,
    ResolutionTracker,
    determine_btc_winner,
    determine_polymarket_winner,
    verify_winner,
)
from polybot.resolution.constants import (
    LOSER_HIGH_CONFIDENCE,
    LOSER_LOW_CONFIDENCE,
    VERIFICATION_DELAY,
    WINNER_HIGH_CONFIDENCE,
    WINNER_LOW_CONFIDENCE,
)

# ── Helpers ──────────────────────────────────────────────────────────


def _market(
    condition_id: str = "cond_1",
    slug: str = "btc-5m-up-down",
    up_token: str = "up_tok",
    down_token: str = "down_tok",
    start: float = 1000.0,
    end: float = 1300.0,
) -> CandleMarket:
    return CandleMarket(
        condition_id=condition_id,
        up_token_id=up_token,
        down_token_id=down_token,
        slug=slug,
        title="BTC 5m",
        start_time=start,
        end_time=end,
    )


def _repo(
    btc_price: float | None = 65000.0,
    trade_prices: list[float | None] | None = None,
) -> AsyncMock:
    """Build a mock ResolutionRepository."""
    repo = AsyncMock(spec=ResolutionRepository)
    repo.get_btc_price_at = AsyncMock(return_value=btc_price)
    if trade_prices is not None:
        repo.get_last_trade_price = AsyncMock(side_effect=trade_prices)
    else:
        repo.get_last_trade_price = AsyncMock(side_effect=[0.95, 0.05])
    return repo


# ── Constants ────────────────────────────────────────────────────────


class TestConstants:
    def test_high_confidence_thresholds(self):
        assert WINNER_HIGH_CONFIDENCE == 0.85
        assert LOSER_HIGH_CONFIDENCE == 0.15

    def test_low_confidence_thresholds(self):
        assert WINNER_LOW_CONFIDENCE == 0.65
        assert LOSER_LOW_CONFIDENCE == 0.35

    def test_verification_delay(self):
        assert VERIFICATION_DELAY == 3.0


# ── Pure checker functions ───────────────────────────────────────────


class TestDetermineBtcWinner:
    def test_up_when_close_higher(self):
        assert determine_btc_winner(65000.0, 65100.0) == "up"

    def test_down_when_close_lower(self):
        assert determine_btc_winner(65100.0, 65000.0) == "down"

    def test_up_on_tie(self):
        """Polymarket rule: 'greater than or equal to' → UP wins on tie."""
        assert determine_btc_winner(65000.0, 65000.0) == "up"


class TestDeterminePolymarketWinner:
    def test_strong_up_signal(self):
        assert determine_polymarket_winner(0.95, 0.05) == "up"

    def test_strong_down_signal(self):
        assert determine_polymarket_winner(0.05, 0.95) == "down"

    def test_clear_up_signal(self):
        assert determine_polymarket_winner(0.70, 0.30) == "up"

    def test_clear_down_signal(self):
        assert determine_polymarket_winner(0.30, 0.70) == "down"

    def test_ambiguous_prices(self):
        assert determine_polymarket_winner(0.50, 0.50) is None

    def test_none_up_price(self):
        assert determine_polymarket_winner(None, 0.95) is None

    def test_none_down_price(self):
        assert determine_polymarket_winner(0.95, None) is None

    def test_both_none(self):
        assert determine_polymarket_winner(None, None) is None


# ── Verifier ─────────────────────────────────────────────────────────


class TestVerifyWinner:
    async def test_agreement(self):
        repo = _repo(trade_prices=[0.95, 0.05])
        with patch("polybot.resolution.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await verify_winner(_market(), "up", repo)
        assert result == "up"

    async def test_mismatch_uses_polymarket(self):
        repo = _repo(trade_prices=[0.05, 0.95])
        with patch("polybot.resolution.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await verify_winner(_market(), "up", repo)
        assert result == "down"

    async def test_ambiguous_uses_btc(self):
        repo = _repo(trade_prices=[0.50, 0.50])
        with patch("polybot.resolution.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await verify_winner(_market(), "down", repo)
        assert result == "down"

    async def test_api_error_uses_btc(self):
        repo = _repo()
        repo.get_last_trade_price = AsyncMock(side_effect=RuntimeError("API down"))
        with patch("polybot.resolution.verifier.asyncio.sleep", new_callable=AsyncMock):
            result = await verify_winner(_market(), "up", repo)
        assert result == "up"


# ── Tracker ──────────────────────────────────────────────────────────


class TestResolutionTracker:
    @pytest.fixture
    def repo(self):
        return _repo()

    @pytest.fixture
    def tracker(self, repo):
        return ResolutionTracker(repo)

    def test_record_and_get_open(self, tracker):
        market = _market()
        tracker.record_candle_open(market, 65000.0)
        assert tracker.get_candle_open("cond_1") == 65000.0

    def test_get_open_missing(self, tracker):
        assert tracker.get_candle_open("missing") is None

    async def test_resolve_up(self, tracker, repo):
        market = _market()
        tracker.record_candle_open(market, 65000.0)
        repo.get_last_trade_price = AsyncMock(side_effect=[0.95, 0.05])
        with patch("polybot.resolution.verifier.asyncio.sleep", new_callable=AsyncMock):
            record = await tracker.resolve(market, 65100.0)
        assert record.winner == "up"
        assert record.btc_open == 65000.0
        assert record.btc_close == 65100.0
        assert tracker.get_candle_open("cond_1") is None

    async def test_resolve_down(self, tracker, repo):
        market = _market()
        tracker.record_candle_open(market, 65100.0)
        repo.get_last_trade_price = AsyncMock(side_effect=[0.05, 0.95])
        with patch("polybot.resolution.verifier.asyncio.sleep", new_callable=AsyncMock):
            record = await tracker.resolve(market, 65000.0)
        assert record.winner == "down"

    async def test_resolve_no_open_falls_back_to_repo(self, tracker, repo):
        repo.get_btc_price_at = AsyncMock(return_value=65000.0)
        repo.get_last_trade_price = AsyncMock(side_effect=[0.95, 0.05])
        with patch("polybot.resolution.verifier.asyncio.sleep", new_callable=AsyncMock):
            record = await tracker.resolve(_market(), 65100.0)
        assert record.btc_open == 65000.0
        assert record.winner == "up"
        repo.get_btc_price_at.assert_called_once_with(1000.0)

    async def test_resolve_no_open_no_feed_defaults_to_close(self, tracker, repo):
        repo.get_btc_price_at = AsyncMock(return_value=None)
        repo.get_last_trade_price = AsyncMock(side_effect=[0.95, 0.05])
        with patch("polybot.resolution.verifier.asyncio.sleep", new_callable=AsyncMock):
            record = await tracker.resolve(_market(), 65100.0)
        assert record.btc_open == 65100.0
        assert record.winner == "up"

    async def test_resolve_returns_resolution_record_fields(self, tracker, repo):
        market = _market()
        tracker.record_candle_open(market, 65000.0)
        repo.get_last_trade_price = AsyncMock(side_effect=[0.95, 0.05])
        with patch("polybot.resolution.verifier.asyncio.sleep", new_callable=AsyncMock):
            record = await tracker.resolve(market, 65100.0)
        assert record.slug == "btc-5m-up-down"
        assert record.condition_id == "cond_1"
        assert record.start_time == 1000.0
        assert record.end_time == 1300.0
        assert record.up_pnl == 0.0
        assert record.down_pnl == 0.0
        assert record.total_pnl == 0.0

    def test_backward_compatible_import(self):
        from polybot.resolution import ResolutionTracker as RT

        assert RT is ResolutionTracker
