"""Core domain models — pure data, no external dependencies."""

from __future__ import annotations

import time
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# BTC price
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BtcTick:
    """A single BTC/USD price observation from Chainlink Data Streams."""

    price: float
    bid: float
    ask: float
    timestamp: float  # observationsTimestamp (seconds since epoch)


# ---------------------------------------------------------------------------
# BTC volume
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BtcVolume:
    """BTC trading volume for a candle interval."""

    volume: float  # base asset volume (BTC)
    start_time: float
    end_time: float


# ---------------------------------------------------------------------------
# Polymarket orderbook
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderBookLevel:
    price: float
    size: float


@dataclass(frozen=True)
class OrderBook:
    bids: tuple[OrderBookLevel, ...]
    asks: tuple[OrderBookLevel, ...]
    timestamp: float

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def midpoint(self) -> float | None:
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2
        return None

    @property
    def spread_pct(self) -> float | None:
        if self.best_bid is not None and self.best_ask is not None and self.best_bid > 0:
            return (self.best_ask - self.best_bid) / self.best_bid * 100
        return None

    @property
    def bid_depth(self) -> float:
        return sum(level.price * level.size for level in self.bids)

    @property
    def ask_depth(self) -> float:
        return sum(level.price * level.size for level in self.asks)

    @property
    def imbalance(self) -> float:
        """(bid_depth - ask_depth) / (bid_depth + ask_depth). Range [-1, 1]."""
        total = self.bid_depth + self.ask_depth
        if total == 0:
            return 0.0
        return (self.bid_depth - self.ask_depth) / total


# ---------------------------------------------------------------------------
# Polymarket market
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Market:
    condition_id: str
    up_token_id: str
    down_token_id: str
    slug: str
    question: str
    end_time: float  # resolution timestamp (epoch seconds)

    @property
    def time_remaining(self) -> float:
        return max(0.0, self.end_time - time.time())


@dataclass(frozen=True)
class MarketSnapshot:
    market: Market
    up_book: OrderBook
    down_book: OrderBook
    last_trade_price: float | None
