"""Row dataclasses — built by MarketMonitor / AIDecision, queued for insert."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketSnapshotRow:
    """One per-second market state for the persistent market history DB."""

    candle_id: int
    timestamp: float
    time_remaining: float

    # Orderbook — UP token
    up_best_bid: float | None = None
    up_best_ask: float | None = None
    up_mid: float | None = None
    up_spread_pct: float | None = None
    up_bid_depth: float = 0.0
    up_ask_depth: float = 0.0

    # Orderbook — DOWN token
    down_best_bid: float | None = None
    down_best_ask: float | None = None
    down_mid: float | None = None
    down_spread_pct: float | None = None
    down_bid_depth: float = 0.0
    down_ask_depth: float = 0.0

    # Risk/reward
    rr_up: float = 0.0
    rr_down: float = 0.0

    # BTC
    btc_price: float = 0.0
    btc_move_from_open: float = 0.0

    # Streak
    streak: int = 0
    streak_direction: str = ""


@dataclass
class SnapshotRow:
    """One per-second market state record."""

    candle_id: int
    timestamp: float
    time_remaining: float

    # Orderbook — UP token
    up_best_bid: float | None = None
    up_best_ask: float | None = None
    up_mid: float | None = None
    up_spread_pct: float | None = None
    up_bid_depth: float = 0.0
    up_ask_depth: float = 0.0

    # Orderbook — DOWN token
    down_best_bid: float | None = None
    down_best_ask: float | None = None
    down_mid: float | None = None
    down_spread_pct: float | None = None
    down_bid_depth: float = 0.0
    down_ask_depth: float = 0.0

    # Risk/reward
    rr_up: float = 0.0
    rr_down: float = 0.0

    # BTC
    btc_price: float = 0.0
    btc_move_from_open: float = 0.0

    # Streak
    streak: int = 0
    streak_direction: str = ""

    # Prefilter
    prefilter_passed: bool = False
    prefilter_reasons: str = ""

    # Indicators (JSON blob)
    indicators_json: str = "{}"


@dataclass
class DecisionRow:
    """One AI decision record."""

    candle_id: int
    timestamp: float
    cycle: int
    trigger_type: str = "entry"  # "entry" or "exit"

    # AI decision
    action: str = "HOLD"
    token_side: str = "up"
    confidence: float = 0.0
    reasoning: str = ""
    market_view: str = ""
    decision_size: float = 0.0

    # Execution
    fill_price: float | None = None
    fill_size: float | None = None
    slippage_bps: float | None = None
    fee_amount: float = 0.0

    # Risk
    risk_blocked: bool = False
    risk_reason: str = ""

    # Portfolio state at decision time
    cash: float = 0.0
    portfolio_value: float = 0.0
    up_shares: float = 0.0
    down_shares: float = 0.0

    # API cost
    ai_cost: float = 0.0
    ai_latency_ms: float = 0.0

    # Indicators (JSON blob)
    indicators_json: str = "{}"

    # Live order telemetry (JSON blob, empty in paper mode)
    live_order_json: str = ""
