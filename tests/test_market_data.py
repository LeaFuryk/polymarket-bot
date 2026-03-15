"""Tests for the market_data package — constants, injectable loggers, repos, pure functions."""

from __future__ import annotations

import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from polybot.market_data.constants import (
    BTC_CANDLE_REFRESH_INTERVAL,
    BTC_CANDLE_WINDOW_SIZE,
    BTC_PRICE_CACHE_TTL,
    CANDLE_INTERVAL_SECONDS,
    CHAINLINK_DECIMALS,
    CHAINLINK_LATEST_ROUND_SELECTOR,
    COINGECKO_REFRESH_INTERVAL,
    GAMMA_API_BASE,
    PRICE_HISTORY_SIZE,
)
from polybot.models.core import (
    BtcCandle,
    BtcPrice,
    CandleMarket,
    OrderbookLevel,
    OrderbookSnapshot,
)

# ── Constants ──────────────────────────────────────────────────────────


class TestConstants:
    """Verify constants have expected types and reasonable values."""

    def test_btc_price_cache_ttl(self):
        assert isinstance(BTC_PRICE_CACHE_TTL, float)
        assert BTC_PRICE_CACHE_TTL > 0

    def test_chainlink_selector_is_hex(self):
        assert CHAINLINK_LATEST_ROUND_SELECTOR.startswith("0x")
        assert len(CHAINLINK_LATEST_ROUND_SELECTOR) == 10  # 4 bytes = 8 hex + "0x"

    def test_chainlink_decimals(self):
        assert CHAINLINK_DECIMALS == 8

    def test_candle_refresh_interval(self):
        assert BTC_CANDLE_REFRESH_INTERVAL == 600

    def test_candle_window_size(self):
        assert BTC_CANDLE_WINDOW_SIZE == 200

    def test_coingecko_refresh(self):
        assert COINGECKO_REFRESH_INTERVAL == 300

    def test_price_history_size(self):
        assert PRICE_HISTORY_SIZE == 60

    def test_gamma_api_base(self):
        assert GAMMA_API_BASE.startswith("https://")

    def test_candle_interval_seconds(self):
        assert CANDLE_INTERVAL_SECONDS == 300


# ── Discovery: _boundary_ts ───────────────────────────────────────────


class TestBoundaryTs:
    """Test the module-level _boundary_ts helper."""

    def test_current_boundary(self):
        from polybot.market_data.discovery import _boundary_ts

        result = _boundary_ts(offset=0)
        now = int(time.time())
        assert result <= now
        assert result % CANDLE_INTERVAL_SECONDS == 0

    def test_next_boundary(self):
        from polybot.market_data.discovery import _boundary_ts

        current = _boundary_ts(offset=0)
        next_b = _boundary_ts(offset=1)
        assert next_b == current + CANDLE_INTERVAL_SECONDS


# ── Discovery: _parse_iso_timestamp ───────────────────────────────────


class TestParseIsoTimestamp:
    """Test MarketDiscovery._parse_iso_timestamp."""

    def _make_discovery(self):
        config = MagicMock()
        config.market.series_slug = "test-series"
        from polybot.market_data.discovery import MarketDiscovery

        return MarketDiscovery(config)

    def test_iso_with_z_suffix(self):
        d = self._make_discovery()
        result = d._parse_iso_timestamp("2026-01-01T00:00:00Z")
        assert result > 0

    def test_iso_with_timezone(self):
        d = self._make_discovery()
        result = d._parse_iso_timestamp("2026-01-01T00:00:00+00:00")
        assert result > 0

    def test_invalid_returns_zero(self):
        d = self._make_discovery()
        result = d._parse_iso_timestamp("not-a-date")
        assert result == 0.0


# ── Injectable logger tests across modules ────────────────────────────


class TestInjectableLoggers:
    """Verify all modules accept and use an injectable logger."""

    def test_discovery_injectable_logger(self):
        from polybot.market_data.discovery import MarketDiscovery

        config = MagicMock()
        config.market.series_slug = "test"
        custom = logging.getLogger("test.discovery")
        d = MarketDiscovery(config, logger=custom)
        assert d._log is custom

    def test_discovery_default_logger(self):
        from polybot.market_data.discovery import MarketDiscovery

        config = MagicMock()
        config.market.series_slug = "test"
        d = MarketDiscovery(config)
        assert d._log.name == "polybot.market_data.discovery"

    @patch("polybot.market_data.client.ClobClient")
    def test_client_injectable_logger(self, mock_clob):
        from polybot.market_data.client import PolymarketRestClient

        market_cfg = MagicMock()
        api_cfg = MagicMock()
        custom = logging.getLogger("test.client")
        c = PolymarketRestClient(market_cfg, api_cfg, logger=custom)
        assert c._log is custom

    @patch("polybot.market_data.client.ClobClient")
    def test_provider_injectable_logger(self, mock_clob):
        from polybot.market_data.provider import MarketDataProvider

        config = MagicMock()
        config.monitor.btc_price_cache_ttl = 30
        custom = logging.getLogger("test.provider")
        p = MarketDataProvider(config, logger=custom)
        assert p._log is custom

    def test_btc_price_injectable_logger(self):
        from polybot.market_data.btc_price import BtcPriceFeed

        api_cfg = MagicMock()
        api_cfg.coingecko_url = "https://api.coingecko.com/api/v3"
        api_cfg.ethereum_rpc_url = "https://eth.example.com"
        api_cfg.chainlink_btcusd_address = "0x1234"
        custom = logging.getLogger("test.btc")
        feed = BtcPriceFeed(api_cfg, logger=custom)
        assert feed._log is custom


# ── Package re-exports ────────────────────────────────────────────────


class TestPackageExports:
    """Verify __init__.py re-exports all public names."""

    def test_import_market_data_provider(self):
        from polybot.market_data import MarketDataProvider

        assert MarketDataProvider is not None

    def test_import_btc_price_feed(self):
        from polybot.market_data import BtcPriceFeed

        assert BtcPriceFeed is not None

    def test_import_market_discovery(self):
        from polybot.market_data import MarketDiscovery

        assert MarketDiscovery is not None

    def test_import_rest_client(self):
        from polybot.market_data import PolymarketRestClient

        assert PolymarketRestClient is not None

    def test_import_btc_repository(self):
        from polybot.market_data import BtcRepository

        assert BtcRepository is not None

    def test_import_polymarket_repository(self):
        from polybot.market_data import PolymarketRepository

        assert PolymarketRepository is not None


# ── BtcRepository ─────────────────────────────────────────────────────


def _make_btc_feed():
    feed = AsyncMock()
    feed.get_price = AsyncMock(return_value=BtcPrice(price_usd=65000.0))
    feed.append_latest_candle = AsyncMock()
    feed.candles = [
        BtcCandle(
            open_time=1.0,
            open=64000.0,
            high=65500.0,
            low=63900.0,
            close=65000.0,
            volume=100.0,
            close_time=301.0,
        )
    ]
    feed.get_price_at = AsyncMock(return_value=64500.0)
    feed.load_candle_history = AsyncMock()
    feed.close = AsyncMock()
    return feed


class TestBtcRepository:
    """Tests for BtcRepository."""

    @pytest.mark.asyncio
    async def test_fetch_returns_btc_data(self):
        from polybot.market_data.btc_repository import BtcRepository

        feed = _make_btc_feed()
        repo = BtcRepository(feed)

        result = await repo.fetch()

        assert result.price is not None
        assert result.price.price_usd == 65000.0
        assert len(result.candles) == 1
        feed.get_price.assert_awaited_once()
        feed.append_latest_candle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_with_none_price(self):
        from polybot.market_data.btc_repository import BtcRepository

        feed = _make_btc_feed()
        feed.get_price.return_value = None
        repo = BtcRepository(feed)

        result = await repo.fetch()

        assert result.price is None
        assert len(result.candles) == 1

    @pytest.mark.asyncio
    async def test_delegate_get_price(self):
        from polybot.market_data.btc_repository import BtcRepository

        feed = _make_btc_feed()
        repo = BtcRepository(feed)

        price = await repo.get_price()
        assert price.price_usd == 65000.0

    @pytest.mark.asyncio
    async def test_delegate_get_price_at(self):
        from polybot.market_data.btc_repository import BtcRepository

        feed = _make_btc_feed()
        repo = BtcRepository(feed)

        price = await repo.get_price_at(1000.0)
        assert price == 64500.0

    @pytest.mark.asyncio
    async def test_delegate_load_history(self):
        from polybot.market_data.btc_repository import BtcRepository

        feed = _make_btc_feed()
        repo = BtcRepository(feed)

        await repo.load_history(100)
        feed.load_candle_history.assert_awaited_once_with(100)

    @pytest.mark.asyncio
    async def test_delegate_close(self):
        from polybot.market_data.btc_repository import BtcRepository

        feed = _make_btc_feed()
        repo = BtcRepository(feed)

        await repo.close()
        feed.close.assert_awaited_once()

    def test_injectable_logger(self):
        from polybot.market_data.btc_repository import BtcRepository

        feed = _make_btc_feed()
        custom = logging.getLogger("test.btc_repo")
        repo = BtcRepository(feed, logger=custom)
        assert repo._log is custom


# ── PolymarketRepository ──────────────────────────────────────────────


def _make_candle_market(condition_id="cond_1", remaining=120.0):
    return CandleMarket(
        condition_id=condition_id,
        up_token_id="up_tok_1",
        down_token_id="down_tok_1",
        slug="btc-5min-candle-123",
        title="BTC 5min candle",
        start_time=time.time() - 180,
        end_time=time.time() + remaining,
    )


def _make_orderbook(best_bid=0.48, best_ask=0.52):
    return OrderbookSnapshot(
        bids=[OrderbookLevel(price=best_bid, size=100.0)],
        asks=[OrderbookLevel(price=best_ask, size=100.0)],
    )


class TestPolymarketRepository:
    """Tests for PolymarketRepository."""

    @pytest.mark.asyncio
    async def test_fetch_with_set_market(self):
        from polybot.market_data.polymarket_repository import PolymarketRepository

        rest = AsyncMock()
        rest.get_orderbook = AsyncMock(return_value=_make_orderbook())
        rest.get_last_trade_price = AsyncMock(return_value=0.50)
        discovery = AsyncMock()

        repo = PolymarketRepository(rest, discovery)
        market = _make_candle_market()
        repo.set_market(market)

        result = await repo.fetch()

        assert result is not None
        assert result.market is market
        assert result.last_trade_price == 0.50
        assert result.orderbook.best_bid == 0.48
        assert result.down_orderbook.best_bid == 0.48

    @pytest.mark.asyncio
    async def test_fetch_discovers_when_no_market(self):
        from polybot.market_data.polymarket_repository import PolymarketRepository

        rest = AsyncMock()
        rest.get_orderbook = AsyncMock(return_value=_make_orderbook())
        rest.get_last_trade_price = AsyncMock(return_value=0.50)

        market = _make_candle_market()
        discovery = AsyncMock()
        discovery.get_current_market = AsyncMock(return_value=market)

        repo = PolymarketRepository(rest, discovery)

        result = await repo.fetch()

        assert result is not None
        assert result.market is market
        discovery.get_current_market.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_returns_none_when_discovery_fails(self):
        from polybot.market_data.polymarket_repository import PolymarketRepository

        rest = AsyncMock()
        discovery = AsyncMock()
        discovery.get_current_market = AsyncMock(return_value=None)
        discovery.get_next_market = AsyncMock(return_value=None)

        repo = PolymarketRepository(rest, discovery)

        result = await repo.fetch()

        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_fallback_to_next_market(self):
        from polybot.market_data.polymarket_repository import PolymarketRepository

        rest = AsyncMock()
        rest.get_orderbook = AsyncMock(return_value=_make_orderbook())
        rest.get_last_trade_price = AsyncMock(return_value=0.50)

        market = _make_candle_market()
        discovery = AsyncMock()
        discovery.get_current_market = AsyncMock(return_value=None)
        discovery.get_next_market = AsyncMock(return_value=market)

        repo = PolymarketRepository(rest, discovery)

        result = await repo.fetch()

        assert result is not None
        discovery.get_current_market.assert_awaited_once()
        discovery.get_next_market.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fetch_uses_ws_cache(self):
        from polybot.market_data.polymarket_repository import PolymarketRepository

        rest = AsyncMock()
        rest.get_orderbook = AsyncMock(return_value=_make_orderbook())
        rest.get_last_trade_price = AsyncMock(return_value=0.50)
        discovery = AsyncMock()

        ws_ob = _make_orderbook(best_bid=0.55, best_ask=0.60)
        repo = PolymarketRepository(rest, discovery)
        repo.set_market(_make_candle_market())
        repo.update_from_ws(orderbook=ws_ob, last_price=0.57)

        result = await repo.fetch()

        assert result is not None
        assert result.orderbook.best_bid == 0.55  # WS cache used for UP
        assert result.last_trade_price == 0.57  # WS cache used for price

    @pytest.mark.asyncio
    async def test_fetch_rediscovers_expired_market(self):
        from polybot.market_data.polymarket_repository import PolymarketRepository

        rest = AsyncMock()
        rest.get_orderbook = AsyncMock(return_value=_make_orderbook())
        rest.get_last_trade_price = AsyncMock(return_value=0.50)

        expired_market = _make_candle_market(remaining=-1.0)
        new_market = _make_candle_market(condition_id="cond_2", remaining=120.0)

        discovery = AsyncMock()
        discovery.get_current_market = AsyncMock(return_value=new_market)

        repo = PolymarketRepository(rest, discovery)
        repo.set_market(expired_market)

        result = await repo.fetch()

        assert result is not None
        assert result.market.condition_id == "cond_2"
        discovery.get_current_market.assert_awaited_once()

    def test_market_property(self):
        from polybot.market_data.polymarket_repository import PolymarketRepository

        repo = PolymarketRepository(AsyncMock(), AsyncMock())
        assert repo.market is None

        market = _make_candle_market()
        repo.set_market(market)
        assert repo.market is market

    def test_injectable_logger(self):
        from polybot.market_data.polymarket_repository import PolymarketRepository

        custom = logging.getLogger("test.poly_repo")
        repo = PolymarketRepository(AsyncMock(), AsyncMock(), logger=custom)
        assert repo._log is custom


# ── Provider parallel fetch ───────────────────────────────────────────


class TestProviderParallelFetch:
    """Tests that MarketDataProvider.get_snapshot() runs repos in parallel."""

    @patch("polybot.market_data.client.ClobClient")
    @pytest.mark.asyncio
    async def test_get_snapshot_merges_bet_and_btc_data(self, mock_clob):
        from polybot.market_data.provider import MarketDataProvider

        config = MagicMock()
        config.monitor.btc_price_cache_ttl = 30
        provider = MarketDataProvider(config)

        # Mock the repos
        market = _make_candle_market()
        from polybot.models import BetData, BtcData

        bet_data = BetData(
            market=market,
            orderbook=_make_orderbook(0.48, 0.52),
            down_orderbook=_make_orderbook(0.46, 0.50),
            last_trade_price=0.50,
        )
        btc_data = BtcData(
            price=BtcPrice(price_usd=65000.0),
            candles=[],
        )

        provider._polymarket.fetch = AsyncMock(return_value=bet_data)
        provider._btc_repo.fetch = AsyncMock(return_value=btc_data)

        snapshot = await provider.get_snapshot()

        assert snapshot.condition_id == market.condition_id
        assert snapshot.orderbook.best_bid == 0.48
        assert snapshot.down_orderbook.best_bid == 0.46
        assert snapshot.btc_price.price_usd == 65000.0
        assert snapshot.last_trade_price == 0.50
        assert snapshot.time_remaining > 0

    @patch("polybot.market_data.client.ClobClient")
    @pytest.mark.asyncio
    async def test_get_snapshot_returns_none_on_discovery_failure(self, mock_clob):
        from polybot.market_data.provider import MarketDataProvider

        config = MagicMock()
        config.monitor.btc_price_cache_ttl = 30
        provider = MarketDataProvider(config)

        from polybot.models import BtcData

        btc_data = BtcData(price=BtcPrice(price_usd=65000.0), candles=[])
        provider._polymarket.fetch = AsyncMock(return_value=None)
        provider._btc_repo.fetch = AsyncMock(return_value=btc_data)

        snapshot = await provider.get_snapshot()

        assert snapshot is None

    @patch("polybot.market_data.client.ClobClient")
    @pytest.mark.asyncio
    async def test_price_history_tracked(self, mock_clob):
        from polybot.market_data.provider import MarketDataProvider

        config = MagicMock()
        config.monitor.btc_price_cache_ttl = 30
        provider = MarketDataProvider(config)

        market = _make_candle_market()
        from polybot.models import BetData, BtcData

        bet_data = BetData(
            market=market,
            orderbook=_make_orderbook(0.48, 0.52),
            down_orderbook=_make_orderbook(0.46, 0.50),
            last_trade_price=0.50,
        )
        btc_data = BtcData(price=BtcPrice(price_usd=65000.0), candles=[])

        provider._polymarket.fetch = AsyncMock(return_value=bet_data)
        provider._btc_repo.fetch = AsyncMock(return_value=btc_data)

        snapshot = await provider.get_snapshot()

        assert len(snapshot.price_history) == 1
        assert len(snapshot.btc_price_history) == 1

    @patch("polybot.market_data.client.ClobClient")
    @pytest.mark.asyncio
    async def test_fetched_market_available_after_get_snapshot(self, mock_clob):
        from polybot.market_data.provider import MarketDataProvider

        config = MagicMock()
        config.monitor.btc_price_cache_ttl = 30
        provider = MarketDataProvider(config)

        market = _make_candle_market()
        from polybot.models import BetData, BtcData

        bet_data = BetData(
            market=market,
            orderbook=_make_orderbook(0.48, 0.52),
            down_orderbook=_make_orderbook(0.46, 0.50),
            last_trade_price=0.50,
        )
        btc_data = BtcData(price=BtcPrice(price_usd=65000.0), candles=[])

        provider._polymarket.fetch = AsyncMock(return_value=bet_data)
        provider._polymarket._market = market  # simulates what fetch() does internally
        provider._btc_repo.fetch = AsyncMock(return_value=btc_data)

        await provider.get_snapshot()

        assert provider.fetched_market is market

    @patch("polybot.market_data.client.ClobClient")
    def test_set_market_syncs_repo_and_clears_history(self, mock_clob):
        from polybot.market_data.provider import MarketDataProvider

        config = MagicMock()
        config.monitor.btc_price_cache_ttl = 30
        provider = MarketDataProvider(config)

        # Seed some price history
        provider._price_history.append(0.50)
        assert len(provider._price_history) == 1

        market = _make_candle_market()
        provider.set_market(market)

        assert provider._polymarket.market is market
        assert len(provider._price_history) == 0


# ── Model data objects ────────────────────────────────────────────────


class TestDataObjects:
    """Tests for BetData and BtcData models."""

    def test_bet_data_construction(self):
        from polybot.models import BetData

        market = _make_candle_market()
        data = BetData(
            market=market,
            orderbook=_make_orderbook(),
            down_orderbook=_make_orderbook(),
            last_trade_price=0.50,
        )
        assert data.market is market
        assert data.last_trade_price == 0.50

    def test_btc_data_construction(self):
        from polybot.models import BtcData

        data = BtcData(price=BtcPrice(price_usd=65000.0), candles=[])
        assert data.price.price_usd == 65000.0
        assert data.candles == []

    def test_btc_data_none_price(self):
        from polybot.models import BtcData

        data = BtcData(price=None, candles=[])
        assert data.price is None
