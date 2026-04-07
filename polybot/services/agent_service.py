"""Service: orchestrates message processing — indicators, portfolio, prediction, trading."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from polybot_data.domain.collection import CandleRecord
from polybot_data.services.indicator_engine import IndicatorSnapshot

if TYPE_CHECKING:
    from polybot.ports.predictor import Predictor
    from polybot.services.indicator_service import IndicatorService
    from polybot.services.portfolio_service import PortfolioService

# ---------------------------------------------------------------------------
# Scaling-in strategy configuration (from notebook 10)
# ---------------------------------------------------------------------------

ENTRY_CHECKPOINTS = [(0.05, 3), (0.50, 3)]  # (min_elapsed, n_consecutive)
BET_AMOUNT = 10.0
MAX_BID = 0.85


class AgentService:
    """Single entry point for all collector messages. Orchestrates indicator
    computation, prediction, scaling-in strategy, and portfolio management."""

    def __init__(
        self,
        indicators: IndicatorService,
        portfolio: PortfolioService,
        predictor: Predictor,
        logger: logging.Logger | None = None,
    ) -> None:
        self._indicators = indicators
        self._portfolio = portfolio
        self._predictor = predictor
        self._log = logger or logging.getLogger(__name__)

        # Per-candle trading state
        self._predictions: list[int] = []
        self._first_direction: str | None = None
        self._entries_made: int = 0
        self._next_checkpoint: int = 0

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
        """Compute indicators, update portfolio, evaluate entry."""
        row = self._indicators.on_snapshot(snapshot)
        if row is None:
            return None

        # Update portfolio prices
        if snapshot.up_bids and snapshot.up_asks and snapshot.down_bids and snapshot.down_asks:
            up_mid = (snapshot.up_bids[0][0] + snapshot.up_asks[0][0]) / 2
            down_mid = (snapshot.down_bids[0][0] + snapshot.down_asks[0][0]) / 2
            self._portfolio.update_prices(up_mid, down_mid)

        # Evaluate scaling-in entry
        self._evaluate_entry(snapshot, row)

        return row

    def _evaluate_entry(self, snapshot: IndicatorSnapshot, row: dict) -> None:
        """Check if the current snapshot triggers a scaling-in entry."""
        if self._next_checkpoint >= len(ENTRY_CHECKPOINTS):
            return

        min_elapsed, n_consecutive = ENTRY_CHECKPOINTS[self._next_checkpoint]

        if snapshot.elapsed_pct < min_elapsed:
            return

        # Only predict once elapsed crosses the checkpoint threshold
        p_up = self._predictor.predict(row)
        pred = 1 if p_up >= 0.5 else 0
        self._predictions.append(pred)

        if len(self._predictions) < n_consecutive:
            return

        # Check n-consecutive agreement
        recent = self._predictions[-n_consecutive:]
        if not all(p == recent[0] for p in recent):
            return

        direction = "UP" if pred == 1 else "DOWN"

        # First entry sets direction; subsequent must agree
        if self._first_direction is None:
            self._first_direction = direction
        elif direction != self._first_direction:
            return

        # Get ask price for the predicted side
        if direction == "UP" and snapshot.up_asks:
            ask = snapshot.up_asks[0][0]
        elif direction == "DOWN" and snapshot.down_asks:
            ask = snapshot.down_asks[0][0]
        else:
            return

        if ask <= 0 or ask >= MAX_BID:
            return

        if self._portfolio.state.cash < BET_AMOUNT:
            return

        # Place the bet
        self._portfolio.buy(direction, amount_usd=BET_AMOUNT, price=ask)
        self._entries_made += 1
        self._next_checkpoint += 1

        self._log.info(
            "🎯 ENTRY %d/%d | %s @ $%.4f | candle %s | elapsed %.0f%%",
            self._entries_made,
            len(ENTRY_CHECKPOINTS),
            direction,
            ask,
            snapshot.candle_id,
            snapshot.elapsed_pct * 100,
        )

    async def _on_candle_close(self, candle: CandleRecord) -> None:
        """Settle portfolio, log result, reset per-candle state, update indicators."""
        had_position = self._entries_made > 0

        self._portfolio.settle(candle.outcome)

        if had_position:
            state = self._portfolio.state
            self._log.info(
                "🕯️ RESOLVED %s | %s | entries=%d | W=%d L=%d | cash=$%.2f",
                candle.candle_id,
                candle.outcome,
                self._entries_made,
                state.wins,
                state.losses,
                state.cash,
            )

        # Reset per-candle state
        self._predictions = []
        self._first_direction = None
        self._entries_made = 0
        self._next_checkpoint = 0

        await self._indicators.on_candle_close(candle)
