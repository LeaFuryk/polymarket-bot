"""All Pydantic models — single source of truth for data contracts."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from polybot.models.constants import (
    DEFAULT_CONFIDENCE,
    DEFAULT_OBSERVATION_EXPIRY,
    DEFAULT_TTL_SECONDS,
    FLAT_POSITION_THRESHOLD,
)

# --- Enums ---


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TokenSide(str, Enum):
    UP = "up"
    DOWN = "down"


# --- Candle Market Discovery ---


class CandleMarket(BaseModel):
    """A BTC 5-min candle market discovered from the Gamma API."""

    condition_id: str
    up_token_id: str
    down_token_id: str
    slug: str
    title: str
    start_time: float  # Unix timestamp — start of 5-min window
    end_time: float  # Unix timestamp — end of 5-min window

    def time_remaining(self) -> float:
        """Seconds until resolution."""
        return max(0.0, self.end_time - time.time())


# --- Market Data ---


class BtcPrice(BaseModel):
    price_usd: float
    timestamp: float = Field(default_factory=time.time)
    change_24h_pct: float = 0.0
    chainlink_price: float | None = None  # On-chain Chainlink BTC/USD (resolution source)
    price_divergence: float | None = None  # Binance - Chainlink divergence ($)
    price_source: str = "binance"  # "binance" | "chainlink_ws" | "coingecko"


class BtcCandle(BaseModel):
    """A single 5-minute OHLCV candle."""

    open_time: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: float
    source: str = "binance"  # "binance" | "chainlink_ws"

    @property
    def direction(self) -> str:
        return "up" if self.close >= self.open else "down"

    @property
    def body_pct(self) -> float:
        if self.open == 0:
            return 0.0
        return (self.close - self.open) / self.open * 100


class OrderbookLevel(BaseModel):
    price: float
    size: float


class OrderbookSnapshot(BaseModel):
    bids: list[OrderbookLevel] = Field(default_factory=list)
    asks: list[OrderbookLevel] = Field(default_factory=list)
    timestamp: float = Field(default_factory=time.time)

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
    def spread(self) -> float | None:
        if self.best_bid is not None and self.best_ask is not None:
            return self.best_ask - self.best_bid
        return None

    @property
    def spread_pct(self) -> float | None:
        if self.midpoint and self.spread is not None:
            return self.spread / self.midpoint
        return None

    @property
    def bid_depth(self) -> float:
        return sum(level.price * level.size for level in self.bids)

    @property
    def ask_depth(self) -> float:
        return sum(level.price * level.size for level in self.asks)


class MarketSnapshot(BaseModel):
    condition_id: str
    token_id: str = ""
    orderbook: OrderbookSnapshot = Field(default_factory=OrderbookSnapshot)
    last_trade_price: float | None = None
    volume_24h: float = 0.0
    timestamp: float = Field(default_factory=time.time)
    btc_price: BtcPrice | None = None

    # Price history for trend analysis
    price_history: list[float] = Field(default_factory=list)

    # BTC price history for BTC-based indicators (momentum, volatility)
    btc_price_history: list[float] = Field(default_factory=list)

    # BTC 5-min candle history for micro-trend analysis
    btc_candles: list[BtcCandle] = Field(default_factory=list)

    # Dual-token fields for candle markets
    up_token_id: str = ""
    down_token_id: str = ""
    down_orderbook: OrderbookSnapshot = Field(default_factory=OrderbookSnapshot)
    time_remaining: float = 0.0  # seconds until resolution


# --- AI Decision ---


class TradingDecision(BaseModel):
    action: Action
    order_type: OrderType = OrderType.MARKET
    size: float = 0.0  # in shares
    limit_price: float | None = None
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    confidence: float = Field(ge=0.0, le=1.0, default=DEFAULT_CONFIDENCE)
    reasoning: str = ""
    market_view: str = ""  # bull/bear/neutral + brief thesis
    token_side: TokenSide = TokenSide.UP  # which token to trade (up or down)
    hypothetical_direction: str = ""  # shadow prediction: "up" or "down"
    confidence_drivers: str = ""  # what would increase confidence


# --- Simulator ---


class SimulatedFill(BaseModel):
    side: Side
    size: float
    fill_price: float
    slippage_bps: float
    fee_amount: float
    total_cost: float  # positive = cash outflow, negative = cash inflow
    timestamp: float = Field(default_factory=time.time)


class LiveOrderResult(BaseModel):
    """Rich metadata from a live CLOB limit order attempt."""

    fill: SimulatedFill | None = None
    order_id: str = ""
    limit_price: float = 0.0
    submit_ts: float = 0.0
    fill_ts: float | None = None
    cancel_ts: float | None = None
    fill_source: str = ""  # "status_poll" / "size_matched" / "post_cancel" / "stealth_balance" / ""
    ttl_used: int = 3
    polls: list[dict[str, Any]] = Field(default_factory=list)
    ob_at_submit: dict[str, Any] = Field(default_factory=dict)
    ob_at_end: dict[str, Any] = Field(default_factory=dict)
    ob_post_cancel: dict[str, Any] | None = None
    pre_balance: float | None = None
    post_balance: float | None = None
    final_order_status: str = ""
    size_matched: float = 0.0
    decision_ob_ask: float | None = None
    decision_ob_bid: float | None = None


class PendingLimitOrder(BaseModel):
    order_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    side: Side
    size: float
    limit_price: float
    created_at: float = Field(default_factory=time.time)
    ttl_seconds: int = DEFAULT_TTL_SECONDS

    @property
    def expires_at(self) -> float:
        return self.created_at + self.ttl_seconds

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) >= self.expires_at


# --- Portfolio ---


class PositionState(BaseModel):
    shares: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def market_value(self) -> float:
        return self.shares * self.avg_entry_price  # updated at mark-to-market

    def is_flat(self) -> bool:
        return abs(self.shares) < FLAT_POSITION_THRESHOLD


# --- Risk ---


class RiskCheckResult(BaseModel):
    passed: bool
    reason: str = ""
    check_name: str = ""


class RiskState(BaseModel):
    daily_pnl: float = 0.0
    daily_trades: int = 0
    daily_fees: float = 0.0
    max_drawdown: float = 0.0
    peak_portfolio_value: float = 0.0
    is_halted: bool = False
    halt_reason: str = ""


# --- Feature Vector (input to AI) ---


class FeatureVector(BaseModel):
    """All data passed to Claude for a trading decision."""

    market: MarketSnapshot
    position: PositionState
    up_position: PositionState = Field(default_factory=PositionState)
    down_position: PositionState = Field(default_factory=PositionState)
    risk: RiskState
    portfolio_cash: float
    portfolio_total_value: float
    cycle_number: int = 0
    time_remaining: float = 0.0  # seconds until candle resolution
    timestamp: float = Field(default_factory=time.time)


# --- Trade Record (logging) ---


class TradeRecord(BaseModel):
    """Complete record of one decision cycle — the audit trail."""

    cycle_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    timestamp: float = Field(default_factory=time.time)

    # Market state at decision time
    midpoint: float | None = None
    spread: float | None = None
    spread_pct: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    bid_depth: float = 0.0
    ask_depth: float = 0.0
    last_trade_price: float | None = None
    btc_price_usd: float | None = None
    volume_24h: float = 0.0

    # AI decision
    action: Action = Action.HOLD
    order_type: OrderType = OrderType.MARKET
    token_side: TokenSide = TokenSide.UP
    decision_size: float = 0.0
    limit_price: float | None = None
    confidence: float = 0.5
    reasoning: str = ""
    market_view: str = ""
    ai_latency_ms: float = 0.0
    ai_cost: float = 0.0

    # Execution result
    fill_price: float | None = None
    fill_size: float = 0.0
    slippage_bps: float = 0.0
    fee_amount: float = 0.0

    # Post-trade state
    position_shares: float = 0.0
    position_avg_entry: float = 0.0
    cash: float = 0.0
    portfolio_value: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    daily_pnl: float = 0.0

    # Risk
    risk_halted: bool = False
    risk_blocked: bool = False
    risk_block_reason: str = ""

    # Metadata
    cycle_number: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)

    # Shadow paper fill (populated in live mode for comparison)
    paper_fill_price: float | None = None
    paper_total_cost: float | None = None

    # Resolution fields (populated after candle resolves)
    candle_slug: str = ""
    candle_winner: str = ""
    resolution_pnl: float = 0.0


# --- Resolution Record ---


class ResolutionRecord(BaseModel):
    """Record of a candle market resolution — who won and PnL impact."""

    slug: str
    condition_id: str
    start_time: float
    end_time: float
    btc_open: float
    btc_close: float
    winner: str  # "up" or "down"
    up_pnl: float
    down_pnl: float
    total_pnl: float
    timestamp: float = Field(default_factory=time.time)


# --- Structured Reflection ---


class ObservationCategory(str, Enum):
    PATTERN = "pattern"
    BIAS = "bias"
    EDGE = "edge"
    REGIME = "regime"


class Observation(BaseModel):
    """A single descriptive observation from reflection — append-only with decay."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    category: ObservationCategory
    text: str
    based_on_resolutions: int  # how many resolutions were in the batch
    resolution_count_at_creation: int  # global resolution counter when created
    expires_after_resolutions: int = DEFAULT_OBSERVATION_EXPIRY


class Scorecard(BaseModel):
    """Quantitative summary of a batch of resolutions."""

    resolutions: int = 0
    trades_taken: int = 0
    win_rate: float = 0.0
    avg_pnl_per_trade: float = 0.0
    avg_win_size: float = 0.0
    avg_loss_size: float = 0.0
    hold_rate: float = 0.0


class ScorecardDelta(BaseModel):
    """Current scorecard vs previous batch for the reflection prompt."""

    current: Scorecard
    previous: Scorecard | None = None
