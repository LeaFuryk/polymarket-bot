"""Tests for OrderBook domain model."""

import pytest
from polybot.domain.models import OrderBook, OrderBookLevel


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
            bids=(OrderBookLevel(0.50, 100),),  # depth = 50
            asks=(OrderBookLevel(0.50, 300),),  # depth = 150
            timestamp=0.0,
        )
        # (50 - 150) / (50 + 150) = -100/200 = -0.5
        assert book.imbalance == pytest.approx(-0.5)

    def test_empty_book(self):
        book = OrderBook(bids=(), asks=(), timestamp=0.0)
        assert book.best_bid is None
        assert book.best_ask is None
        assert book.midpoint is None
        assert book.spread_pct is None
        assert book.bid_depth == 0.0
        assert book.ask_depth == 0.0
        assert book.imbalance == 0.0

    def test_frozen(self):
        book = OrderBook(bids=(), asks=(), timestamp=0.0)
        with pytest.raises(AttributeError):
            book.timestamp = 1.0  # type: ignore[misc]
