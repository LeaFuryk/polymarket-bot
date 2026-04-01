"""Tests for PolymarketAdapter."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

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


def _mock_http(json_data=None, status_code=200):
    """Create a mock httpx.AsyncClient context manager."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = json_data or {}
    mock_resp.raise_for_status = MagicMock()

    client = AsyncMock()
    client.get = AsyncMock(return_value=mock_resp)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


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

    async def test_fetch_orderbook(self):
        adapter = PolymarketAdapter()

        with patch("polybot.adapters.polymarket.httpx.AsyncClient", return_value=_mock_http(SAMPLE_ORDERBOOK)):
            book = await adapter._fetch_orderbook("token_123")

        assert book.best_bid == pytest.approx(0.55)
        assert book.best_ask == pytest.approx(0.57)

    async def test_fetch_orderbook_error_returns_empty(self):
        adapter = PolymarketAdapter()
        mock = _mock_http()
        mock.__aenter__ = AsyncMock(side_effect=Exception("network error"))

        with patch("polybot.adapters.polymarket.httpx.AsyncClient", return_value=mock):
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
        adapter = PolymarketAdapter()

        with patch("polybot.adapters.polymarket.httpx.AsyncClient", return_value=_mock_http([SAMPLE_GAMMA_EVENT])):
            market = await adapter.discover_market("will-bitcoin-go-up-5-min")

        assert market is not None
        assert market.condition_id == "0xabc123"
        assert market.up_token_id == "token_up_123"
        assert market.down_token_id == "token_down_456"
        assert market.question == "Will Bitcoin go up in the next 5 minutes?"

    async def test_discover_market_not_found(self):
        adapter = PolymarketAdapter()

        with patch("polybot.adapters.polymarket.httpx.AsyncClient", return_value=_mock_http([])):
            market = await adapter.discover_market("nonexistent-series")

        assert market is None


class TestLastTradePrice:
    async def test_get_last_trade_price(self):
        adapter = PolymarketAdapter()

        with patch("polybot.adapters.polymarket.httpx.AsyncClient", return_value=_mock_http({"price": "0.57"})):
            price = await adapter.get_last_trade_price("token_123")

        assert price == pytest.approx(0.57)

    async def test_get_last_trade_price_none(self):
        adapter = PolymarketAdapter()

        with patch("polybot.adapters.polymarket.httpx.AsyncClient", return_value=_mock_http({"price": None})):
            price = await adapter.get_last_trade_price("token_123")

        assert price is None

    async def test_get_last_trade_price_error(self):
        adapter = PolymarketAdapter()
        mock = _mock_http()
        mock.__aenter__ = AsyncMock(side_effect=Exception("timeout"))

        with patch("polybot.adapters.polymarket.httpx.AsyncClient", return_value=mock):
            price = await adapter.get_last_trade_price("token_123")

        assert price is None


class TestGetSnapshot:
    async def test_get_snapshot(self):
        adapter = PolymarketAdapter()

        # Mock returns orderbook for get calls, but we need different responses
        # for orderbook vs last trade price. Simplify: mock the high-level methods.
        with (
            patch.object(adapter, "get_orderbooks", new_callable=AsyncMock) as mock_books,
            patch.object(adapter, "get_last_trade_price", new_callable=AsyncMock) as mock_price,
        ):
            up_book = PolymarketAdapter._parse_orderbook(SAMPLE_ORDERBOOK)
            down_book = PolymarketAdapter._parse_orderbook(SAMPLE_ORDERBOOK)
            mock_books.return_value = (up_book, down_book)
            mock_price.return_value = 0.57

            snapshot = await adapter.get_snapshot(SAMPLE_MARKET)

        assert snapshot.market == SAMPLE_MARKET
        assert snapshot.up_book.best_bid == pytest.approx(0.55)
        assert snapshot.down_book.best_ask == pytest.approx(0.57)
        assert snapshot.last_trade_price == pytest.approx(0.57)
