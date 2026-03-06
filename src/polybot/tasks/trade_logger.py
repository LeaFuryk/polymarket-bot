"""Trade logging and analytics helpers for the AI decision task.

Builds TradeRecord and DecisionRow objects from decision outcomes,
applying fill data, risk status, and live-order telemetry. Keeps
all record-assembly logic out of the core decision flow.
"""

from __future__ import annotations

import json
import logging
import time

from polybot.indicators import FeatureConfig, SessionContext, compute_indicators
from polybot.models import (
    Action,
    TradeRecord,
    TradingDecision,
)

logger = logging.getLogger(__name__)


def build_trade_record(
    *,
    cycle: int,
    snapshot,
    portfolio,
    risk_state,
    market=None,
    decision: TradingDecision | None = None,
    latency_ms: float = 0.0,
    fill=None,
    risk_blocked: bool = False,
    risk_reason: str = "",
    paper_fill=None,
    live_result=None,
    screen_passed: bool | None = None,
    screen_input: str | None = None,
    last_cycle_api_cost: float = 0.0,
    signal_type: str = "",
    reversal_rate: float = 0.0,
) -> TradeRecord:
    """Assemble a TradeRecord from decision cycle outputs.

    This is a pure data-assembly function — it reads from its arguments
    and returns a populated TradeRecord without side effects.
    """
    ob = snapshot.orderbook
    pos = portfolio.position
    mid = ob.midpoint
    down_mid = snapshot.down_orderbook.midpoint
    midpoint_gap = round((mid or 0.5) + (down_mid or 0.5) - 1.0, 4)

    record = TradeRecord(
        cycle_number=cycle,
        midpoint=ob.midpoint,
        spread=ob.spread,
        spread_pct=ob.spread_pct,
        best_bid=ob.best_bid,
        best_ask=ob.best_ask,
        bid_depth=ob.bid_depth,
        ask_depth=ob.ask_depth,
        last_trade_price=snapshot.last_trade_price,
        btc_price_usd=snapshot.btc_price.price_usd if snapshot.btc_price else None,
        volume_24h=snapshot.volume_24h,
        position_shares=pos.shares,
        position_avg_entry=pos.avg_entry_price,
        cash=portfolio.cash,
        portfolio_value=portfolio.total_value_at_market(mid or 0.5, down_mid),
        realized_pnl=pos.realized_pnl,
        unrealized_pnl=pos.unrealized_pnl,
        daily_pnl=risk_state.daily_pnl,
        risk_halted=risk_state.is_halted,
        risk_blocked=risk_blocked,
        risk_block_reason=risk_reason,
    )

    if market:
        record.candle_slug = market.slug
        record.extra["time_remaining"] = market.time_remaining()

    record.extra["midpoint_gap"] = midpoint_gap
    record.extra["up_mid"] = round(mid or 0.5, 4)
    record.extra["down_mid"] = round(down_mid or 0.5, 4)
    record.extra["screen_passed"] = screen_passed
    if screen_input:
        record.extra["screen_input"] = screen_input

    if decision:
        _apply_decision_fields(record, decision, latency_ms, last_cycle_api_cost, snapshot, signal_type, reversal_rate)

    if fill:
        record.fill_price = fill.fill_price
        record.fill_size = fill.size
        record.slippage_bps = fill.slippage_bps
        record.fee_amount = fill.fee_amount

    if paper_fill:
        record.paper_fill_price = paper_fill.fill_price
        record.paper_total_cost = paper_fill.total_cost

    if live_result:
        record.limit_price = live_result.limit_price
        record.extra["live_order"] = live_result.model_dump(exclude={"fill"})

    return record


def _apply_decision_fields(
    record: TradeRecord,
    decision: TradingDecision,
    latency_ms: float,
    last_cycle_api_cost: float,
    snapshot,
    signal_type: str,
    reversal_rate: float,
) -> None:
    """Populate decision-related fields on a TradeRecord (mutates in place)."""
    record.action = decision.action
    record.order_type = decision.order_type
    record.token_side = decision.token_side
    record.decision_size = decision.size
    record.limit_price = decision.limit_price
    record.confidence = decision.confidence
    record.reasoning = decision.reasoning
    record.market_view = decision.market_view
    record.ai_latency_ms = latency_ms
    record.ai_cost = last_cycle_api_cost
    if decision.hypothetical_direction:
        record.extra["hypothetical_direction"] = decision.hypothetical_direction
    if decision.confidence_drivers:
        record.extra["confidence_drivers"] = decision.confidence_drivers

    if decision.action == Action.BUY:
        if decision.token_side.value == "up":
            opp_ask = snapshot.down_orderbook.best_ask
        else:
            opp_ask = snapshot.orderbook.best_ask
        if opp_ask is not None:
            record.extra["opposite_ask"] = round(opp_ask, 4)
        record.extra["signal_type"] = signal_type
        record.extra["reversal_rate"] = round(reversal_rate, 2)


def build_decision_row(
    *,
    datastore_candle_id: int,
    cycle: int,
    snapshot,
    portfolio,
    feature_config: FeatureConfig,
    session_wins: int,
    session_losses: int,
    candle_open_btc: float | None,
    decision: TradingDecision | None = None,
    latency_ms: float = 0.0,
    fill=None,
    risk_blocked: bool = False,
    risk_reason: str = "",
    last_cycle_api_cost: float = 0.0,
    live_result=None,
    log: logging.Logger | None = None,
):
    """Build a DecisionRow for SQLite analytics.

    Returns None-safe: imports DecisionRow lazily and returns the row.
    """
    from polybot.datastore import DecisionRow

    _log = log or logger

    indicators_dict: dict = {}
    try:
        feature_config.load()
        session_ctx = SessionContext(
            wins=session_wins,
            losses=session_losses,
            candle_open_btc=candle_open_btc,
        )
        results = compute_indicators(snapshot, feature_config, session_ctx)
        indicators_dict = {r.name: {"value": r.value, "label": r.label} for r in results}
    except Exception:
        _log.debug("Indicator computation failed for decision", exc_info=True)

    return DecisionRow(
        candle_id=datastore_candle_id,
        timestamp=time.time(),
        cycle=cycle,
        trigger_type="entry",
        action=decision.action.value if decision else "HOLD",
        token_side=decision.token_side.value if decision else "up",
        confidence=decision.confidence if decision else 0.0,
        reasoning=decision.reasoning if decision else "",
        market_view=decision.market_view if decision else "",
        decision_size=decision.size if decision else 0.0,
        fill_price=fill.fill_price if fill else None,
        fill_size=fill.size if fill else None,
        slippage_bps=fill.slippage_bps if fill else None,
        fee_amount=fill.fee_amount if fill else 0.0,
        risk_blocked=risk_blocked,
        risk_reason=risk_reason,
        cash=portfolio.cash,
        portfolio_value=portfolio.total_value,
        up_shares=portfolio.up_position.shares,
        down_shares=portfolio.down_position.shares,
        ai_cost=last_cycle_api_cost,
        ai_latency_ms=latency_ms,
        indicators_json=json.dumps(indicators_dict) if indicators_dict else "{}",
        live_order_json=json.dumps(live_result.model_dump(exclude={"fill"})) if live_result else "",
    )
