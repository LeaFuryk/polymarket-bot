"""Tests for the market_data package — constants, injectable loggers, pure functions."""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock, patch

from polybot.market_data.constants import (
    BTC_CANDLE_REFRESH_INTERVAL,
    BTC_CANDLE_WINDOW_SIZE,
    BTC_PRICE_CACHE_TTL,
    CANDLE_INTERVAL_SECONDS,
    CHAINLINK_DECIMALS,
    CHAINLINK_LATEST_ROUND_SELECTOR,
    CHAINLINK_WS_BUCKET_SECONDS,
    CHAINLINK_WS_DEFAULT_URL,
    CHAINLINK_WS_PING_INTERVAL,
    CHAINLINK_WS_RECONNECT_DELAY,
    CHAINLINK_WS_STALE_THRESHOLD,
    CHAINLINK_WS_WATCHDOG_INTERVAL,
    COINGECKO_REFRESH_INTERVAL,
    GAMMA_API_BASE,
    PRICE_HISTORY_SIZE,
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

    def test_ws_stale_threshold(self):
        assert CHAINLINK_WS_STALE_THRESHOLD == 30.0

    def test_ws_reconnect_delay(self):
        assert CHAINLINK_WS_RECONNECT_DELAY == 5.0

    def test_ws_ping_interval(self):
        assert CHAINLINK_WS_PING_INTERVAL == 5.0

    def test_ws_bucket_seconds(self):
        assert CHAINLINK_WS_BUCKET_SECONDS == 300

    def test_ws_default_url(self):
        assert CHAINLINK_WS_DEFAULT_URL.startswith("wss://")

    def test_ws_watchdog_interval(self):
        assert CHAINLINK_WS_WATCHDOG_INTERVAL == 10.0

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


# ── ChainlinkWSFeed ──────────────────────────────────────────────────


class TestChainlinkWSFeed:
    """Test ChainlinkWSFeed pure methods."""

    def _make_feed(self, **kwargs):
        from polybot.market_data.chainlink_ws import ChainlinkWSFeed

        return ChainlinkWSFeed(**kwargs)

    def test_default_url(self):
        feed = self._make_feed()
        assert feed._url == CHAINLINK_WS_DEFAULT_URL

    def test_custom_url(self):
        feed = self._make_feed(url="wss://custom.example.com")
        assert feed._url == "wss://custom.example.com"

    def test_injectable_logger(self):
        custom_logger = logging.getLogger("test.chainlink")
        feed = self._make_feed(logger=custom_logger)
        assert feed._log is custom_logger

    def test_default_logger(self):
        feed = self._make_feed()
        assert feed._log.name == "polybot.market_data.chainlink_ws"

    def test_price_none_when_no_data(self):
        feed = self._make_feed()
        assert feed.price is None

    def test_price_none_when_stale(self):
        feed = self._make_feed()
        feed._price = 50000.0
        feed._last_update = time.time() - CHAINLINK_WS_STALE_THRESHOLD - 1
        assert feed.price is None

    def test_price_returns_when_fresh(self):
        feed = self._make_feed()
        feed._price = 50000.0
        feed._last_update = time.time()
        assert feed.price == 50000.0

    def test_is_active_false_when_disconnected(self):
        feed = self._make_feed()
        feed._connected = False
        assert feed.is_active is False

    def test_record_tick_creates_bucket(self):
        feed = self._make_feed()
        now = time.time()
        feed._record_tick(50000.0, now)
        assert feed._current_bucket is not None
        assert feed._current_bucket["open"] == 50000.0

    def test_record_tick_updates_ohlc(self):
        feed = self._make_feed()
        now = time.time()
        feed._record_tick(50000.0, now)
        feed._record_tick(51000.0, now + 1)
        feed._record_tick(49000.0, now + 2)
        assert feed._current_bucket["high"] == 51000.0
        assert feed._current_bucket["low"] == 49000.0
        assert feed._current_bucket["close"] == 49000.0

    def test_extract_price_payload_data(self):
        feed = self._make_feed()
        msg = {"payload": {"data": [{"value": "50000.5", "timestamp": 1234}]}}
        assert feed._extract_price(msg) == 50000.5

    def test_extract_price_direct_value(self):
        feed = self._make_feed()
        msg = {"value": "42000.0"}
        assert feed._extract_price(msg) == 42000.0

    def test_extract_price_returns_none_on_empty(self):
        feed = self._make_feed()
        assert feed._extract_price({}) is None


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

    def test_import_chainlink_ws_feed(self):
        from polybot.market_data import ChainlinkWSFeed

        assert ChainlinkWSFeed is not None

    def test_import_market_discovery(self):
        from polybot.market_data import MarketDiscovery

        assert MarketDiscovery is not None

    def test_import_rest_client(self):
        from polybot.market_data import PolymarketRestClient

        assert PolymarketRestClient is not None
