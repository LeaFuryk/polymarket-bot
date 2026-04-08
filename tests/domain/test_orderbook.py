"""Tests for OrderBook domain model."""

import pytest
from polybot_data.domain.models import OrderBook, OrderBookLevel


class TestOrderBook:
    def test_best_bid_ask(self):
        book = OrderBook(
            bids=(OrderBookLevel(0.55, 100), OrderBookLevel(0.54, 200)),
            asks=(OrderBookLevel(0.57, 150), OrderBookLevel(0.58, 100)),
            timestamp=1700000000.0,
        )
        assert book.best_bid == 0.55
        assert book.best_ask == 0.57

    def test_midpoint(self):
        book = OrderBook(
            bids=(OrderBookLevel(0.55, 100),),
            asks=(OrderBookLevel(0.57, 150),),
            timestamp=0.0,
        )
        assert book.midpoint == pytest.approx(0.56)

    def test_spread_pct(self):
        book = OrderBook(
            bids=(OrderBookLevel(0.50, 100),),
            asks=(OrderBookLevel(0.52, 100),),
            timestamp=0.0,
        )
        # (0.52 - 0.50) / 0.50 * 100 = 4.0%
        assert book.spread_pct == pytest.approx(4.0)

    def test_depth(self):
        book = OrderBook(
            bids=(OrderBookLevel(0.55, 100), OrderBookLevel(0.54, 200)),
            asks=(OrderBookLevel(0.57, 150),),
            timestamp=0.0,
        )
        # bid_depth = 0.55*100 + 0.54*200 = 55 + 108 = 163
        assert book.bid_depth == pytest.approx(163.0)
        # ask_depth = 0.57*150 = 85.5
        assert book.ask_depth == pytest.approx(85.5)

    def test_imbalance(self):
        book = OrderBook(
            bids=(OrderBookLevel(0.50, 100),),  # volume = 100
            asks=(OrderBookLevel(0.50, 300),),  # volume = 300
            timestamp=0.0,
        )
        # (100 - 300) / (100 + 300) = -200/400 = -0.5
        assert book.imbalance == pytest.approx(-0.5)

    def test_bid_ask_volume(self):
        book = OrderBook(
            bids=(OrderBookLevel(0.55, 100), OrderBookLevel(0.54, 200)),
            asks=(OrderBookLevel(0.57, 150), OrderBookLevel(0.58, 50)),
            timestamp=0.0,
        )
        assert book.bid_volume == pytest.approx(300.0)
        assert book.ask_volume == pytest.approx(200.0)

    def test_imbalance_uses_raw_volume(self):
        """Imbalance uses raw size, not price-weighted depth."""
        book = OrderBook(
            bids=(OrderBookLevel(0.90, 100),),  # depth=90, volume=100
            asks=(OrderBookLevel(0.10, 100),),  # depth=10, volume=100
            timestamp=0.0,
        )
        # Raw volumes equal → imbalance = 0, even though depths differ
        assert book.imbalance == pytest.approx(0.0)
        # But depths are unequal
        assert book.bid_depth != pytest.approx(book.ask_depth)

    def test_empty_book(self):
        book = OrderBook(bids=(), asks=(), timestamp=0.0)
        assert book.best_bid is None
        assert book.best_ask is None
        assert book.midpoint is None
        assert book.spread_pct is None
        assert book.bid_depth == 0.0
        assert book.ask_depth == 0.0
        assert book.bid_volume == 0.0
        assert book.ask_volume == 0.0
        assert book.imbalance == 0.0

    def test_frozen(self):
        book = OrderBook(bids=(), asks=(), timestamp=0.0)
        with pytest.raises(AttributeError):
            book.timestamp = 1.0  # type: ignore[misc]
