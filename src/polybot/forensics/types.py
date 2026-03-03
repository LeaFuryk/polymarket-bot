"""Pydantic models for all forensics output."""

from __future__ import annotations

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Feature A: Order Execution Metrics
# ---------------------------------------------------------------------------


class OrderMetrics(BaseModel):
    """Per-order execution metrics extracted from live_order_json."""

    order_id: str
    candle_id: int
    side: str  # "BUY" / "SELL"
    decision_ts: float
    submit_ts: float
    decision_to_submit_ms: float  # (submit_ts - decision_ts) * 1000
    decision_ask: float | None = None
    submit_ask: float | None = None
    ask_drift_bps: float | None = None  # (submit - decision) / decision * 10000
    filled: bool
    fill_source: str
    fill_ts: float | None = None
    fill_latency_ms: float | None = None  # (fill_ts - submit_ts) * 1000
    ttl_used: int
    polls: list[dict] = []
    balance_delta: float | None = None  # post_balance - pre_balance


class AggregateMetrics(BaseModel):
    """Aggregate execution metrics across all orders."""

    total_orders: int
    filled_count: int
    fill_rate: float
    p50_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    max_latency_ms: float | None = None
    p50_drift_bps: float | None = None
    p95_drift_bps: float | None = None
    by_fill_source: dict[str, int] = {}


# ---------------------------------------------------------------------------
# Feature B: TTL Counterfactuals
# ---------------------------------------------------------------------------


class TTLCounterfactual(BaseModel):
    """Per-order TTL counterfactual analysis."""

    order_id: str
    candle_id: int
    actual_ttl: int
    grid: dict[int, bool] = {}  # {ttl_seconds: would_have_filled}
    rescue_ttl: int | None = None  # min TTL that would rescue


class TTLAggregate(BaseModel):
    """Aggregate TTL rescue curve."""

    grid_ttls: list[int] = []
    rescued_at: dict[int, int] = {}  # {ttl: count_rescued}
    total_timeouts: int = 0


# ---------------------------------------------------------------------------
# Feature C: Cost Breakdown
# ---------------------------------------------------------------------------


class CostBreakdown(BaseModel):
    """Per-order cost decomposition."""

    order_id: str
    fee_amount: float
    slippage_bps: float
    drift_cost: float  # (submit_ask - decision_ask) * size
    total_cost: float


class CostAggregate(BaseModel):
    """Aggregate cost summary."""

    total_fees: float = 0.0
    total_slippage_cost: float = 0.0
    total_drift_cost: float = 0.0
    by_outcome: dict[str, float] = {}  # "win"/"loss" → total cost
    by_side: dict[str, float] = {}  # "BUY"/"SELL" → total cost


# ---------------------------------------------------------------------------
# Feature D: Blocked Order Analysis
# ---------------------------------------------------------------------------


class BlockedOrder(BaseModel):
    """Per-blocked-order classification."""

    candle_id: int
    action: str
    risk_reason: str
    category: str
    ttl_rescuable: bool = False
    reprice_rescuable: bool = False


class BlockedAggregate(BaseModel):
    """Aggregate blocked-order summary."""

    total_blocked: int = 0
    by_category: dict[str, int] = {}
    rescuable_ttl: int = 0
    rescuable_reprice: int = 0


# ---------------------------------------------------------------------------
# Feature E: Round-trips
# ---------------------------------------------------------------------------


class RoundTrip(BaseModel):
    """Entry-to-exit pair with PnL and excursion analysis."""

    entry_candle_id: int
    exit_candle_id: int
    side: str  # token side
    entry_price: float
    exit_price: float
    size: float
    hold_duration_s: float
    realized_pnl: float
    mfe: float  # max favorable excursion (best mid during hold)
    mae: float  # max adverse excursion (worst mid during hold)
    entry_to_mfe_s: float  # time to reach MFE
    exit_efficiency: float  # realized_pnl / mfe_potential


# ---------------------------------------------------------------------------
# Feature F: Decision Context
# ---------------------------------------------------------------------------


class DecisionContext(BaseModel):
    """Decision-time context with indicators and outcome."""

    candle_id: int
    action: str
    confidence: float
    rr_ratio: float
    indicators: dict[str, float] = {}
    ml_score: float | None = None
    outcome: str | None = None  # "win" / "loss"


# ---------------------------------------------------------------------------
# Top-level report
# ---------------------------------------------------------------------------


class ForensicsReport(BaseModel):
    """Complete forensics report combining all 6 feature analyses."""

    generated_at: str
    db_path: str
    order_metrics: list[OrderMetrics] = []
    aggregate_metrics: AggregateMetrics
    ttl_counterfactuals: list[TTLCounterfactual] = []
    ttl_aggregate: TTLAggregate
    cost_breakdowns: list[CostBreakdown] = []
    cost_aggregate: CostAggregate
    blocked_orders: list[BlockedOrder] = []
    blocked_aggregate: BlockedAggregate
    round_trips: list[RoundTrip] = []
    decision_contexts: list[DecisionContext] = []
