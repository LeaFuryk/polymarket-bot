"""Tests for PolymarketAdapter."""

import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from polybot.adapters.polymarket import PolymarketAdapter
from polybot.domain.models import Market, OrderBook
from polybot.ports.market_feed import MarketFeed

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ORDERBOOK = {
    "bids": [
        {"price": "0.55", "size": "100"},
        {"price": "0.54", "size": "200"},
    ],
    "asks": [
        {"price": "0.57", "size": "150"},
        {"price": "0.58", "size": "100"},
    ],
}

SAMPLE_GAMMA_EVENT = {
    "title": "Will Bitcoin go up in the next 5 minutes?",
    "endDate": "2024-03-20T12:05:00Z",
    "markets": [
        {
            "conditionId": "0xabc123",
            "clobTokenIds": '["token_up_123", "token_down_456"]',
        }
    ],
}

SAMPLE_MARKET = Market(
    condition_id="0xabc123",
    up_token_id="token_up_123",
    down_token_id="token_down_456",
    slug="test-slug",
    question="Will Bitcoin go up?",
    end_time=time.time() + 300,
)


def _mock_response(json_data):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _make_adapter(gamma_data=None, clob_data=None, error=None) -> PolymarketAdapter:
    """Create adapter with mocked HTTP clients."""
    adapter = PolymarketAdapter()
    if error:
        adapter._gamma_client.get = AsyncMock(side_effect=error)
        adapter._clob_client.get = AsyncMock(side_effect=error)
    else:
        if gamma_data is not None:
            adapter._gamma_client.get = AsyncMock(return_value=_mock_response(gamma_data))
        if clob_data is not None:
            adapter._clob_client.get = AsyncMock(return_value=_mock_response(clob_data))
    return adapter


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPolymarketAdapter:
    def test_satisfies_protocol(self):
        adapter = PolymarketAdapter()
        assert isinstance(adapter, MarketFeed)


class TestOrderbookParsing:
    def test_parse_orderbook(self):
        book = PolymarketAdapter._parse_orderbook(SAMPLE_ORDERBOOK)
        assert isinstance(book, OrderBook)
        assert len(book.bids) == 2
        assert len(book.asks) == 2
        assert book.best_bid == pytest.approx(0.55)
        assert book.best_ask == pytest.approx(0.57)

    def test_parse_empty_orderbook(self):
        book = PolymarketAdapter._parse_orderbook({})
        assert len(book.bids) == 0
        assert len(book.asks) == 0

    def test_parse_unsorted_orderbook(self):
        """CLOB returns levels unsorted — parser must sort them."""
        unsorted = {
            "bids": [
                {"price": "0.01", "size": "10000"},
                {"price": "0.50", "size": "100"},
                {"price": "0.30", "size": "500"},
            ],
            "asks": [
                {"price": "0.99", "size": "10000"},
                {"price": "0.51", "size": "100"},
                {"price": "0.70", "size": "500"},
            ],
        }
        book = PolymarketAdapter._parse_orderbook(unsorted)
        assert book.best_bid == pytest.approx(0.50)
        assert book.best_ask == pytest.approx(0.51)

    async def test_fetch_orderbook(self):
        adapter = _make_adapter(clob_data=SAMPLE_ORDERBOOK)
        book = await adapter._fetch_orderbook("token_123")
        assert book.best_bid == pytest.approx(0.55)
        assert book.best_ask == pytest.approx(0.57)

    async def test_fetch_orderbook_error_returns_empty(self):
        adapter = _make_adapter(error=Exception("network error"))
        book = await adapter._fetch_orderbook("token_123")
        assert len(book.bids) == 0
        assert len(book.asks) == 0


class TestMarketDiscovery:
    def test_parse_end_time(self):
        ts = PolymarketAdapter._parse_end_time("2024-03-20T12:05:00Z")
        assert ts > 0

    def test_parse_end_time_empty(self):
        assert PolymarketAdapter._parse_end_time("") == 0.0

    async def test_discover_market(self):
        adapter = _make_adapter(gamma_data=[SAMPLE_GAMMA_EVENT])
        market = await adapter.discover_market("will-bitcoin-go-up-5-min")
        assert market is not None
        assert market.condition_id == "0xabc123"
        assert market.up_token_id == "token_up_123"
        assert market.down_token_id == "token_down_456"

    async def test_discover_market_not_found(self):
        adapter = _make_adapter(gamma_data=[])
        market = await adapter.discover_market("nonexistent-series")
        assert market is None

    async def test_discover_tries_all_boundaries(self):
        """If current and next return empty, previous boundary should be tried."""
        adapter = PolymarketAdapter()
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.json.return_value = [] if call_count <= 2 else [SAMPLE_GAMMA_EVENT]
            resp.raise_for_status = MagicMock()
            return resp

        adapter._gamma_client.get = mock_get
        market = await adapter.discover_market("btc-updown-5m")
        assert market is not None
        assert market.condition_id == "0xabc123"
        assert call_count == 3

    async def test_discover_order_is_current_next_previous(self):
        """Discovery probes current, then next, then previous boundary."""
        import time

        from polybot.adapters.polymarket import CANDLE_INTERVAL

        adapter = PolymarketAdapter()
        slugs_tried: list[str] = []

        async def capture_get(*args, **kwargs):
            slug = kwargs.get("params", {}).get("slug", "")
            slugs_tried.append(slug)
            resp = MagicMock()
            resp.json.return_value = []
            resp.raise_for_status = MagicMock()
            return resp

        adapter._gamma_client.get = capture_get
        await adapter.discover_market("btc-updown-5m")

        now = time.time()
        boundary = int(now - (now % CANDLE_INTERVAL))

        assert len(slugs_tried) == 3
        assert slugs_tried[0] == f"btc-updown-5m-{boundary}"
        assert slugs_tried[1] == f"btc-updown-5m-{boundary + CANDLE_INTERVAL}"
        assert slugs_tried[2] == f"btc-updown-5m-{boundary - CANDLE_INTERVAL}"


class TestMarketCache:
    def _future_event(self):
        """SAMPLE_GAMMA_EVENT with end_time in the future."""
        return {
            **SAMPLE_GAMMA_EVENT,
            "endDate": "2099-01-01T00:00:00Z",
            "markets": [{**SAMPLE_GAMMA_EVENT["markets"][0], "endDate": "2099-01-01T00:00:00Z"}],
        }

    async def test_cached_within_interval(self):
        """Second call reuses cached market, no API call."""
        adapter = _make_adapter(gamma_data=[self._future_event()])
        await adapter.discover_market("btc-updown-5m")
        await adapter.discover_market("btc-updown-5m")
        # Only 1 API call — second was served from cache
        assert adapter._gamma_client.get.await_count == 1

    async def test_rediscovered_after_expiry(self):
        """Expired market triggers a new API call."""
        adapter = _make_adapter(gamma_data=[SAMPLE_GAMMA_EVENT])
        # First discovery
        await adapter.discover_market("btc-updown-5m")
        # Force expiry
        adapter._cached_market = Market(
            condition_id="0xold",
            up_token_id="up",
            down_token_id="down",
            slug="old",
            question="old",
            end_time=time.time() - 1,
        )
        await adapter.discover_market("btc-updown-5m")
        assert adapter._gamma_client.get.await_count == 2

    async def test_no_cache_on_failure(self):
        """If discovery fails, no stale cache is stored."""
        adapter = _make_adapter(gamma_data=[])
        await adapter.discover_market("btc-updown-5m")
        assert adapter._cached_market is None


class TestLastTradePrice:
    async def test_get_last_trade_price(self):
        adapter = _make_adapter(clob_data={"price": "0.57"})
        price = await adapter.get_last_trade_price("token_123")
        assert price == pytest.approx(0.57)

    async def test_get_last_trade_price_none(self):
        adapter = _make_adapter(clob_data={"price": None})
        price = await adapter.get_last_trade_price("token_123")
        assert price is None

    async def test_get_last_trade_price_error(self):
        adapter = _make_adapter(error=Exception("timeout"))
        price = await adapter.get_last_trade_price("token_123")
        assert price is None


class TestGetSnapshot:
    async def test_get_snapshot(self):
        adapter = PolymarketAdapter()
        up_book = PolymarketAdapter._parse_orderbook(SAMPLE_ORDERBOOK)
        down_book = PolymarketAdapter._parse_orderbook(SAMPLE_ORDERBOOK)
        adapter.get_orderbooks = AsyncMock(return_value=(up_book, down_book))
        adapter.get_last_trade_price = AsyncMock(side_effect=[0.57, 0.43])
        adapter.get_market_volume = AsyncMock(return_value=12345.0)

        snapshot = await adapter.get_snapshot(SAMPLE_MARKET)

        assert snapshot.market == SAMPLE_MARKET
        assert snapshot.up_book.best_bid == pytest.approx(0.55)
        assert snapshot.down_book.best_ask == pytest.approx(0.57)
        assert snapshot.last_trade_price == pytest.approx(0.57)
        assert snapshot.down_last_trade_price == pytest.approx(0.43)
        assert snapshot.volume == pytest.approx(12345.0)


class TestGetMarketVolume:
    async def test_get_market_volume(self):
        adapter = _make_adapter(gamma_data=[{"markets": [{"volumeClob": "9999.5"}]}])
        vol = await adapter.get_market_volume("some-slug")
        assert vol == pytest.approx(9999.5)

    async def test_get_market_volume_fallback_to_volume(self):
        adapter = _make_adapter(gamma_data=[{"markets": [{"volume": "500.0"}]}])
        vol = await adapter.get_market_volume("some-slug")
        assert vol == pytest.approx(500.0)

    async def test_get_market_volume_empty_events(self):
        adapter = _make_adapter(gamma_data=[])
        vol = await adapter.get_market_volume("some-slug")
        assert vol == 0.0

    async def test_get_market_volume_error(self):
        adapter = _make_adapter(error=Exception("timeout"))
        vol = await adapter.get_market_volume("some-slug")
        assert vol == 0.0
