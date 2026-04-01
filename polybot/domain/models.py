"""Core domain models — pure data, no external dependencies."""

from __future__ import annotations

import dataclasses
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
# Candles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candle:
    """A closed 5-minute OHLCV candle."""

    open: float
    high: float
    low: float
    close: float
    volume: float  # BTC volume from Binance
    start_time: float
    end_time: float


@dataclass
class PartialCandle:
    """In-progress candle built from streaming ticks. Mutable."""

    open: float
    high: float
    low: float
    last_price: float
    start_time: float
    end_time: float  # expected close time
    tick_count: int = 0
    last_tick_time: float = 0.0

    def update(self, tick: BtcTick) -> None:
        """Incorporate a new tick."""
        if tick.price > self.high:
            self.high = tick.price
        if tick.price < self.low:
            self.low = tick.price
        self.last_price = tick.price
        self.last_tick_time = tick.timestamp
        self.tick_count += 1


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
    volume: float = 0.0  # cumulative market volume (USD)

    @property
    def time_remaining(self) -> float:
        return max(0.0, self.end_time - time.time())


@dataclass(frozen=True)
class MarketSnapshot:
    market: Market
    up_book: OrderBook
    down_book: OrderBook
    last_trade_price: float | None


# ---------------------------------------------------------------------------
# Prompt state (1:1 with fine-tune model input schema)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandleData:
    t: int  # relative index (-19 to -1)
    open: float
    high: float
    low: float
    close: float
    volume: float
    log_ret: float | None
    vol_pace: float | None


@dataclass(frozen=True)
class CurrentCandleData:
    open: float | None
    high_so_far: float | None
    low_so_far: float | None
    last_price: float | None
    partial_ret: float | None
    volume_so_far: float
    volume_pace: float | None
    elapsed_sec: float
    elapsed_pct: float
    time_remaining_sec: float
    chainlink_heartbeat_age_sec: float


@dataclass(frozen=True)
class Technicals:
    rsi14: float | None
    macd_hist: float | None
    bb_pct_b: float | None
    atr14_norm: float | None


@dataclass(frozen=True)
class Microstructure:
    spread_bps: float
    ob_imbalance: float
    polymarket_yes_price: float | None
    polymarket_yes_delta: float | None
    polymarket_vol_delta: float | None


@dataclass(frozen=True)
class BetState:
    bet_open_price: float | None
    unrealised_ret: float | None
    hold_count: int
    time_remaining_sec: float


@dataclass(frozen=True)
class PromptState:
    candles: tuple[CandleData, ...]
    current_candle: CurrentCandleData
    technicals: Technicals
    microstructure: Microstructure
    bet_state: BetState

    def to_dict(self) -> dict:
        """Serialize to the exact JSON structure the model expects."""
        return dataclasses.asdict(self)
