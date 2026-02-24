"""Position monitor task — tracks P&L, triggers stop-loss/take-profit exits.

Runs every 1 second. Uses cached snapshot data (no API calls).
Pushes exit signals to the exit_trigger_queue when SL/TP thresholds are hit.
"""

from __future__ import annotations

import asyncio
import logging

from polybot.config import AppConfig
from polybot.shared_state import SharedState
from polybot.simulator.portfolio import Portfolio

logger = logging.getLogger(__name__)


class PositionMonitor:
    """Monitors open positions and triggers SL/TP exits."""

    def __init__(
        self,
        config: AppConfig,
        shared: SharedState,
        portfolio: Portfolio,
    ) -> None:
        self._config = config
        self._shared = shared
        self._portfolio = portfolio
        self._interval = config.monitor.position_monitor_interval
        self._stop_loss_pct = config.monitor.stop_loss_pct
        self._take_profit_pct = config.monitor.take_profit_pct

        # Track which positions have already triggered (avoid re-triggering)
        self._triggered: dict[str, str] = {}  # token_side -> trigger_type

    async def run(self) -> None:
        """Main loop — checks positions every second."""
        logger.info(
            "PositionMonitor started (SL=%.0f%%, TP=+%.0f%%)",
            self._stop_loss_pct * 100, self._take_profit_pct * 100,
        )
        while not self._shared.shutdown:
            if self._shared.rotation_in_progress:
                await asyncio.sleep(0.2)
                continue

            try:
                await self._tick()
            except Exception:
                logger.debug("PositionMonitor tick error", exc_info=True)

            await asyncio.sleep(self._interval)

        logger.info("PositionMonitor stopped")

    def reset_triggers(self) -> None:
        """Reset triggered state on candle rotation."""
        self._triggered.clear()

    async def _tick(self) -> None:
        """Check P&L on open positions."""
        snapshot = self._shared.latest_snapshot
        if snapshot is None:
            return

        up_mid = snapshot.orderbook.midpoint
        down_mid = snapshot.down_orderbook.midpoint

        # Update mark-to-market
        if up_mid is not None:
            self._portfolio.mark_to_market(up_mid, down_mid)

        # Check UP position
        up_pos = self._portfolio.up_position
        if up_pos.shares > 0 and up_pos.avg_entry_price > 0:
            current_price = up_mid or 0.5
            pnl_pct = (current_price - up_pos.avg_entry_price) / up_pos.avg_entry_price
            self._shared.position_pnl_pct["up"] = pnl_pct
            await self._check_thresholds("up", pnl_pct)
        else:
            self._shared.position_pnl_pct.pop("up", None)
            self._triggered.pop("up", None)

        # Check DOWN position
        down_pos = self._portfolio.down_position
        if down_pos.shares > 0 and down_pos.avg_entry_price > 0:
            current_price = down_mid or 0.5
            pnl_pct = (current_price - down_pos.avg_entry_price) / down_pos.avg_entry_price
            self._shared.position_pnl_pct["down"] = pnl_pct
            await self._check_thresholds("down", pnl_pct)
        else:
            self._shared.position_pnl_pct.pop("down", None)
            self._triggered.pop("down", None)

    async def _check_thresholds(self, token_side: str, pnl_pct: float) -> None:
        """Check if P&L has hit stop-loss or take-profit thresholds."""
        if token_side in self._triggered:
            return  # Already triggered for this position

        if pnl_pct <= self._stop_loss_pct:
            logger.warning(
                "STOP-LOSS triggered: %s position P&L=%.1f%% <= %.1f%%",
                token_side.upper(), pnl_pct * 100, self._stop_loss_pct * 100,
            )
            self._triggered[token_side] = "stop_loss"
            await self._shared.exit_trigger_queue.put({
                "token_side": token_side,
                "reason": f"stop_loss ({pnl_pct:+.1%})",
                "pnl_pct": pnl_pct,
                "trigger_type": "stop_loss",
            })

        elif pnl_pct >= self._take_profit_pct:
            logger.info(
                "TAKE-PROFIT triggered: %s position P&L=+%.1f%% >= +%.1f%%",
                token_side.upper(), pnl_pct * 100, self._take_profit_pct * 100,
            )
            self._triggered[token_side] = "take_profit"
            await self._shared.exit_trigger_queue.put({
                "token_side": token_side,
                "reason": f"take_profit ({pnl_pct:+.1%})",
                "pnl_pct": pnl_pct,
                "trigger_type": "take_profit",
            })
