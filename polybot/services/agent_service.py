"""Service: orchestrates message processing — indicators, portfolio, logging."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from polybot_data.domain.collection import CandleRecord
from polybot_data.services.indicator_engine import IndicatorSnapshot

if TYPE_CHECKING:
    from polybot.services.indicator_service import IndicatorService
    from polybot.services.portfolio_service import PortfolioService


class AgentService:
    """Single entry point for all collector messages. Orchestrates indicator
    computation, portfolio updates, and logging."""

    def __init__(
        self,
        indicators: IndicatorService,
        portfolio: PortfolioService,
        logger: logging.Logger | None = None,
    ) -> None:
        self._indicators = indicators
        self._portfolio = portfolio
        self._log = logger or logging.getLogger(__name__)

    async def process(self, msg: dict) -> dict | None:
        """Decode raw WS message into a model and route to the appropriate handler.
        Returns indicator row for snapshots, None otherwise."""
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            snapshot = IndicatorSnapshot.from_dict(msg)
            return self._on_snapshot(snapshot)
        if msg_type == "candle_close":
            candle = CandleRecord.from_ws(msg)
            await self._on_candle_close(candle)
            return None
        return None

    def _on_snapshot(self, snapshot: IndicatorSnapshot) -> dict | None:
        """Compute indicators, update portfolio prices."""
        row = self._indicators.on_snapshot(snapshot)
        if row is None:
            return None

        if snapshot.up_bids and snapshot.up_asks and snapshot.down_bids and snapshot.down_asks:
            up_mid = (snapshot.up_bids[0][0] + snapshot.up_asks[0][0]) / 2
            down_mid = (snapshot.down_bids[0][0] + snapshot.down_asks[0][0]) / 2
            self._portfolio.update_prices(up_mid, down_mid)

        self._log.info(
            "📊 %s | elapsed=%.0f%% | BTC $%.2f | rsi=%s | streak=%s | cash=$%.2f",
            snapshot.candle_id,
            snapshot.elapsed_pct * 100,
            snapshot.btc_price,
            row.get("rsi"),
            row.get("consecutive_streak"),
            self._portfolio.state.cash,
        )
        return row

    async def _on_candle_close(self, candle: CandleRecord) -> None:
        """Settle portfolio, then update indicator history."""
        self._portfolio.settle(candle.outcome)
        await self._indicators.on_candle_close(candle)
