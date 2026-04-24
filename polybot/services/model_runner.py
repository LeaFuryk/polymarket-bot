"""Service: per-model trading lifecycle — predict, enter, settle, broadcast."""

from __future__ import annotations

import logging
import time as _time
from dataclasses import asdict
from typing import TYPE_CHECKING

from polybot.domain.bet_record import BetEntry, BetRecord

if TYPE_CHECKING:
    from polybot_data.domain.collection import CandleRecord
    from polybot_data.services.indicator_engine import IndicatorSnapshot

    from polybot.domain.trading_strategy import TradingStrategy
    from polybot.ports.bet_store import BetStore
    from polybot.ports.message_relay import MessageRelay
    from polybot.ports.predictor import Predictor
    from polybot.services.portfolio_service import PortfolioService

MAX_BID = 0.85
BET_PCT = 0.02


class ModelRunner:
    """Owns one model's complete trading lifecycle.

    Signal-only: waits for BTC to move >= min_btc_move from candle open,
    then evaluates model predictions against entry checkpoints and
    confidence thresholds.
    """

    def __init__(
        self,
        name: str,
        predictor: Predictor,
        portfolio: PortfolioService,
        strategy: TradingStrategy,
        bet_store: BetStore,
        broadcaster: MessageRelay,
        logger: logging.Logger | None = None,
    ) -> None:
        self._name = name
        self._predictor = predictor
        self._portfolio = portfolio
        self._strategy = strategy
        self._bet_store = bet_store
        self._broadcaster = broadcaster
        self._log = logger or logging.getLogger(f"{__name__}.{name}")

        # Equity history: balance after each settlement (for dashboard chart)
        self._equity_history: list[float] = [portfolio.state.cash]

        # Per-candle state
        self._predictions: list[int] = []
        self._first_direction: str | None = None
        self._entries_made: int = 0
        self._next_checkpoint: int = 0
        self._bet_entries: list[BetEntry] = []
        self._current_candle_id: str | None = None
        self._cash_before_bet: float = 0.0
        self._candle_open: float | None = None
        self._signal_active: bool = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def portfolio(self) -> PortfolioService:
        return self._portfolio

    @property
    def equity_history(self) -> list[float]:
        return self._equity_history

    @property
    def current_entries(self) -> list[dict]:
        return [
            {
                "type": "model_entry",
                "model": self._name,
                "candle_id": self._current_candle_id or "",
                "direction": self._first_direction or "",
                "price": e.price,
                "amount_usd": e.amount_usd,
                "confidence": e.confidence,
                "inference_ms": 0,
                "checkpoint": e.checkpoint,
                "elapsed_pct": e.elapsed_pct,
                "timestamp": 0,
            }
            for e in self._bet_entries
        ]

    async def handle_snapshot(self, row: dict, snapshot: IndicatorSnapshot) -> None:
        """Predict, evaluate entry, broadcast if triggered."""
        if snapshot.up_bids and snapshot.up_asks and snapshot.down_bids and snapshot.down_asks:
            up_mid = (snapshot.up_bids[0][0] + snapshot.up_asks[0][0]) / 2
            down_mid = (snapshot.down_bids[0][0] + snapshot.down_asks[0][0]) / 2
            self._portfolio.update_prices(up_mid, down_mid)

        # Track candle open price from first snapshot
        if self._candle_open is None:
            self._candle_open = snapshot.btc_price

        # Activate signal mode once BTC has moved enough from candle open
        if not self._signal_active:
            btc_move = abs(snapshot.btc_price - self._candle_open) / self._candle_open if self._candle_open > 0 else 0
            if btc_move >= self._strategy.min_btc_move:
                self._signal_active = True

        if self._signal_active:
            await self._evaluate_signal_entry(snapshot, row)

    async def _evaluate_signal_entry(self, snapshot: IndicatorSnapshot, row: dict) -> None:
        """Standard model-based entry with checkpoints and confidence."""
        if self._next_checkpoint >= len(self._strategy.entry_points):
            return

        min_elapsed, n_consecutive = self._strategy.entry_points[self._next_checkpoint]

        if snapshot.elapsed_pct < min_elapsed:
            return

        t0 = _time.perf_counter()
        p_up = self._predictor.predict(row)
        inference_ms = (_time.perf_counter() - t0) * 1000

        pred = 1 if p_up >= 0.5 else 0
        self._predictions.append(pred)

        if len(self._predictions) < n_consecutive:
            return

        recent = self._predictions[-n_consecutive:]
        if not all(p == recent[0] for p in recent):
            return

        confidence = max(p_up, 1.0 - p_up)
        if confidence < self._strategy.min_confidence:
            return

        direction = "UP" if pred == 1 else "DOWN"

        if self._first_direction is None:
            self._first_direction = direction
        elif direction != self._first_direction:
            return

        if direction == "UP" and snapshot.up_asks:
            ask = snapshot.up_asks[0][0]
        elif direction == "DOWN" and snapshot.down_asks:
            ask = snapshot.down_asks[0][0]
        else:
            return

        if ask <= 0 or ask >= MAX_BID:
            return

        await self._place_entry(snapshot, direction, ask, confidence, inference_ms, mode="signal")

    async def _place_entry(
        self,
        snapshot: IndicatorSnapshot,
        direction: str,
        ask: float,
        confidence: float,
        inference_ms: float,
        mode: str,
    ) -> None:
        """Place a bet entry and broadcast."""
        bet_amount = self._portfolio.state.cash * BET_PCT
        if bet_amount < 0.01:
            return

        if self._entries_made == 0:
            self._cash_before_bet = self._portfolio.state.cash
            self._current_candle_id = snapshot.candle_id

        if self._first_direction is None:
            self._first_direction = direction

        self._portfolio.buy(direction, amount_usd=bet_amount, price=ask)
        self._entries_made += 1
        self._next_checkpoint += 1

        entry = BetEntry(
            price=ask,
            amount_usd=bet_amount,
            elapsed_pct=snapshot.elapsed_pct,
            confidence=confidence,
            checkpoint=self._entries_made,
        )
        self._bet_entries.append(entry)

        self._log.info(
            "🎯 %s ENTRY %d | %s @ $%.4f | candle %s | elapsed %.0f%% | conf=%.2f",
            mode.upper(),
            self._entries_made,
            direction,
            ask,
            snapshot.candle_id,
            snapshot.elapsed_pct * 100,
            confidence,
        )

        await self._broadcaster.broadcast_json(
            {
                "type": "model_entry",
                "model": self._name,
                "candle_id": snapshot.candle_id,
                "direction": direction,
                "price": ask,
                "amount_usd": round(bet_amount, 4),
                "confidence": round(confidence, 4),
                "inference_ms": round(inference_ms, 3),
                "checkpoint": self._entries_made,
                "elapsed_pct": round(snapshot.elapsed_pct, 4),
                "timestamp": snapshot.timestamp,
                "mode": mode,
            }
        )

    async def handle_candle_close(self, candle: CandleRecord) -> None:
        """Settle portfolio, record bet, broadcast settlement, reset state."""
        had_position = self._entries_made > 0

        self._portfolio.settle(candle.outcome, candle_id=candle.candle_id)

        if had_position:
            state = self._portfolio.state
            # Calculate PnL from entries directly, not cash difference.
            # Cash difference can be corrupted by corrections to previous candles
            # that change portfolio cash mid-candle.
            won = self._first_direction == candle.outcome
            total_cost = sum(e.amount_usd for e in self._bet_entries)
            if won:
                total_net_shares = 0.0
                for e in self._bet_entries:
                    gross = e.amount_usd / e.price
                    fee = gross * 0.072 * e.price * (1.0 - e.price)
                    total_net_shares += gross - fee
                pnl = total_net_shares - total_cost  # shares pay $1 each
            else:
                pnl = -total_cost

            record = BetRecord(
                candle_id=self._current_candle_id or candle.candle_id,
                direction=self._first_direction or "",
                outcome=candle.outcome,
                won=self._first_direction == candle.outcome,
                entries=self._bet_entries,
                pnl=round(pnl, 4),
                timestamp=_time.time(),
            )
            await self._bet_store.save_bet(record)

            self._log.info(
                "🕯️ RESOLVED %s | %s | entries=%d | pnl=$%+.2f | W=%d L=%d | cash=$%.2f",
                candle.candle_id,
                candle.outcome,
                self._entries_made,
                pnl,
                state.wins,
                state.losses,
                state.cash,
            )

            await self._broadcaster.broadcast_json(
                {
                    "type": "model_settlement",
                    "model": self._name,
                    "candle_id": candle.candle_id,
                    "outcome": candle.outcome,
                    "direction": self._first_direction or "",
                    "won": self._first_direction == candle.outcome,
                    "entries": [asdict(e) for e in self._bet_entries],
                    "pnl": round(pnl, 4),
                    "cash": round(state.cash, 4),
                    "wins": state.wins,
                    "losses": state.losses,
                    "timestamp": _time.time(),
                }
            )

        # Track equity history
        self._equity_history.append(self._portfolio.state.cash)

        self._reset_candle_state()

    def handle_correction(self, corrected: CandleRecord) -> None:
        """Reverse and re-settle if outcome changed."""
        self._portfolio.reverse_and_resettle(corrected.candle_id, corrected.outcome)

    def _reset_candle_state(self) -> None:
        self._predictions = []
        self._first_direction = None
        self._entries_made = 0
        self._next_checkpoint = 0
        self._bet_entries = []
        self._current_candle_id = None
        self._cash_before_bet = 0.0
        self._candle_open = None
        self._signal_active = False
