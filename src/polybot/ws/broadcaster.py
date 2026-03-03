"""Client set management and message builders for the WS dashboard."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from polybot.ws.protocol import (
    MSG_MARKET,
    MSG_POSITION,
    MSG_RESOLUTION,
    MSG_SNAPSHOT,
    MSG_STATUS,
    MSG_TRADE,
    make_message,
)

if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol

    from polybot.agent import TradingAgent

logger = logging.getLogger(__name__)


class DashboardBroadcaster:
    """Manages connected WS clients and builds typed messages from agent state."""

    def __init__(self) -> None:
        self._clients: set[WebSocketServerProtocol] = set()

    # --- Client management ---

    def add_client(self, ws: WebSocketServerProtocol) -> None:
        self._clients.add(ws)
        logger.info("WS client connected (%d total)", len(self._clients))

    def remove_client(self, ws: WebSocketServerProtocol) -> None:
        self._clients.discard(ws)
        logger.info("WS client disconnected (%d total)", len(self._clients))

    @property
    def has_clients(self) -> bool:
        return len(self._clients) > 0

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast(self, msg: str) -> None:
        """Send a message to all connected clients, removing dead connections."""
        if not self._clients:
            return
        dead: list[WebSocketServerProtocol] = []
        for ws in self._clients.copy():
            try:
                await ws.send(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    # --- Message builders ---

    def build_snapshot(self, agent: TradingAgent) -> str:
        """Build a full snapshot message from agent._assemble_dashboard_data()."""
        data = agent._assemble_dashboard_data()
        data["ws_clients"] = self.client_count
        return make_message(MSG_SNAPSHOT, data)

    def build_market_update(self, agent: TradingAgent) -> str:
        """Lightweight market price + countdown update (every 1s)."""
        snapshot = agent._shared.latest_snapshot
        market = agent._current_market

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

    def build_position_update(self, agent: TradingAgent) -> str:
        """Position shares + P&L update (every 1s)."""
        portfolio = agent._portfolio
        data = {
            "timestamp": time.time(),
            "up_shares": portfolio.up_position.shares,
            "up_avg_entry": portfolio.up_position.avg_entry_price,
            "down_shares": portfolio.down_position.shares,
            "down_avg_entry": portfolio.down_position.avg_entry_price,
            "cash": portfolio.cash,
            "position_pnl": dict(agent._shared.position_pnl_pct),
            "dynamic_sl": dict(agent._shared.dynamic_sl),
            "dynamic_tp": dict(agent._shared.dynamic_tp),
        }
        return make_message(MSG_POSITION, data)

    def build_status_update(self, agent: TradingAgent) -> str:
        """Tech metrics: monitor, risk, latencies (every 2s)."""
        data = {
            "timestamp": time.time(),
            "monitor": {
                "prefilter_snapshots": len(agent._shared.prefilter_history),
                "ai_cooldown_remaining": max(
                    0,
                    agent._config.monitor.ai_cooldown_seconds
                    - (time.time() - agent._shared.ai_last_call_time),
                ),
                "last_trigger_reason": agent._shared.ai_trigger_reason,
                "status": agent._shared.monitor_status,
            },
            "risk": {
                "daily_pnl": agent._risk.state.daily_pnl,
                "daily_trades": agent._risk.state.daily_trades,
                "daily_fees": agent._risk.state.daily_fees,
                "max_drawdown": agent._risk.state.max_drawdown,
                "is_halted": agent._risk.state.is_halted,
            },
            "api_latencies": agent._shared.api_latencies,
            "ws_clients": self.client_count,
            "sqlite_queue_depth": agent._shared.sqlite_queue_depth,
            "prefilter": {
                "skip_rate": agent._prefilter.skip_rate,
                "skipped": agent._prefilter.total_skipped,
                "checked": agent._prefilter.total_checks,
            },
            "ensemble": {
                "screen_calls": agent._ai_decision._screen_calls if agent._ai_decision else 0,
                "screen_passes": agent._ai_decision._screen_passes if agent._ai_decision else 0,
            },
        }
        return make_message(MSG_STATUS, data)

    def build_trade_event(self, trade) -> str:
        """Immediate push on trade execution."""
        from datetime import datetime, timezone

        data = {
            "timestamp": datetime.fromtimestamp(trade.timestamp, tz=timezone.utc).isoformat(),
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
