"""Builds typed WS messages from agent state for the dashboard."""

from __future__ import annotations

import time
from datetime import UTC
from typing import TYPE_CHECKING

from polybot.ws.protocol import (
    MSG_MARKET,
    MSG_POSITION,
    MSG_RESOLUTION,
    MSG_STATUS,
    MSG_TRADE,
    make_message,
)

if TYPE_CHECKING:
    from polybot.agent.context import AgentContext
    from polybot.tasks.ai_decision import AIDecision


class DashboardMessageBuilder:
    """Builds typed WS messages from agent state.

    Stateless — all data is extracted from *ctx* or event objects passed to
    each method.  The class exists as a clear namespace; it holds no
    per-instance state.
    """

    def build_market_update(self, ctx: AgentContext) -> str:
        """Lightweight market price + countdown update (every 1s)."""
        snapshot = ctx.shared.latest_snapshot
        market = ctx.current_market

        data: dict = {"timestamp": time.time()}

        if market:
            up_mid = snapshot.orderbook.midpoint if snapshot else None
            down_mid = snapshot.down_orderbook.midpoint if snapshot else None
            data["time_remaining"] = market.time_remaining()
            data["up_mid"] = up_mid
            data["down_mid"] = down_mid
            data["slug"] = market.slug

        if snapshot and snapshot.btc_price:
            data["btc_price"] = snapshot.btc_price.price_usd
            data["chainlink_price"] = snapshot.btc_price.chainlink_price
            data["price_source"] = snapshot.btc_price.price_source

        return make_message(MSG_MARKET, data)

    def build_position_update(self, ctx: AgentContext) -> str:
        """Position shares + P&L update (every 1s)."""
        portfolio = ctx.portfolio
        data = {
            "timestamp": time.time(),
            "up_shares": portfolio.up_position.shares,
            "up_avg_entry": portfolio.up_position.avg_entry_price,
            "down_shares": portfolio.down_position.shares,
            "down_avg_entry": portfolio.down_position.avg_entry_price,
            "cash": portfolio.cash,
            "position_pnl": dict(ctx.shared.position_pnl_pct),
            "dynamic_sl": dict(ctx.shared.dynamic_sl),
            "dynamic_tp": dict(ctx.shared.dynamic_tp),
        }
        return make_message(MSG_POSITION, data)

    def build_status_update(
        self,
        ctx: AgentContext,
        ai_decision: AIDecision | None = None,
        ws_client_count: int = 0,
    ) -> str:
        """Tech metrics: monitor, risk, latencies (every 2s)."""
        data = {
            "timestamp": time.time(),
            "monitor": {
                "prefilter_snapshots": len(ctx.shared.prefilter_history),
                "ai_cooldown_remaining": max(
                    0,
                    ctx.config.monitor.ai_cooldown_seconds - (time.time() - ctx.shared.ai_last_call_time),
                ),
                "last_trigger_reason": ctx.shared.ai_trigger_reason,
                "status": ctx.shared.monitor_status,
            },
            "risk": {
                "daily_pnl": ctx.risk.state.daily_pnl,
                "daily_trades": ctx.risk.state.daily_trades,
                "daily_fees": ctx.risk.state.daily_fees,
                "max_drawdown": ctx.risk.state.max_drawdown,
                "is_halted": ctx.risk.state.is_halted,
            },
            "api_latencies": ctx.shared.api_latencies,
            "ws_clients": ws_client_count,
            "sqlite_queue_depth": ctx.shared.sqlite_queue_depth,
            "prefilter": {
                "skip_rate": ctx.prefilter.skip_rate,
                "skipped": ctx.prefilter.total_skipped,
                "checked": ctx.prefilter.total_checks,
            },
            "ensemble": {
                "screen_calls": ai_decision._screen_calls if ai_decision else 0,
                "screen_passes": ai_decision._screen_passes if ai_decision else 0,
            },
        }
        return make_message(MSG_STATUS, data)

    def build_trade_event(self, trade) -> str:
        """Immediate push on trade execution."""
        from datetime import datetime

        data = {
            "timestamp": datetime.fromtimestamp(trade.timestamp, tz=UTC).isoformat(),
            "action": trade.action.value,
            "token_side": trade.token_side.value,
            "size": trade.decision_size,
            "fill_price": trade.fill_price,
            "confidence": trade.confidence,
            "reasoning": trade.reasoning,
            "candle_slug": trade.candle_slug,
            "risk_blocked": trade.risk_blocked,
            "cash": trade.cash,
            "portfolio_value": trade.portfolio_value,
            "fee": trade.fee_amount,
            "ai_cost": trade.ai_cost,
            "live_order": trade.extra.get("live_order"),
        }
        return make_message(MSG_TRADE, data)

    def build_resolution_event(self, resolution) -> str:
        """Immediate push on candle resolution."""
        data = {
            "slug": resolution.slug,
            "winner": resolution.winner,
            "btc_open": resolution.btc_open,
            "btc_close": resolution.btc_close,
            "btc_move": resolution.btc_close - resolution.btc_open,
            "pnl": resolution.total_pnl,
        }
        return make_message(MSG_RESOLUTION, data)
