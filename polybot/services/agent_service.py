"""Service: maintains bot state and computes technical indicators."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from polybot_data.domain.collection import CandleRecord
from polybot_data.services.indicator_engine import IndicatorSnapshot, compute_all

if TYPE_CHECKING:
    from polybot.ports.candle_repository import CandleRepository

MINIMUM_CANDLES = 21  # max lookback across all indicators


class AgentService:
    """Maintains prior candles + current snapshots, computes 56 indicators per tick."""

    def __init__(
        self,
        candle_repo: CandleRepository,
        logger: logging.Logger | None = None,
    ) -> None:
        self._repo = candle_repo
        self._log = logger or logging.getLogger(__name__)
        self._prior_candles: list[CandleRecord] = []
        self._snapshots_so_far: list[IndicatorSnapshot] = []
        self._candle_open: float | None = None
        self._current_candle_id: str | None = None
        self._synced = False

    @property
    def synced(self) -> bool:
        return self._synced

    def on_snapshot(self, msg: dict) -> dict | None:
        """Process a snapshot message. Returns the model row, or None if not synced."""
        if not self._synced:
            return None

        candle_id = msg.get("candle_id")
        if candle_id != self._current_candle_id:
            self._snapshots_so_far = []
            if self._candle_open is None:
                self._candle_open = msg["btc_price"]  # fallback if no prior close
            self._current_candle_id = candle_id

        snapshot = IndicatorSnapshot(
            timestamp=msg["timestamp"],
            elapsed_pct=msg["elapsed_pct"],
            btc_price=msg["btc_price"],
            btc_bid=msg["btc_bid"],
            btc_ask=msg["btc_ask"],
            up_bids=msg["up_bids"],
            up_asks=msg["up_asks"],
            down_bids=msg["down_bids"],
            down_asks=msg["down_asks"],
            market_volume=msg["market_volume"],
        )
        self._snapshots_so_far.append(snapshot)

        indicators = compute_all(
            self._prior_candles,
            self._candle_open,
            self._snapshots_so_far,
        )

        return {
            "candle_id": msg.get("candle_id"),
            "timestamp": msg.get("timestamp"),
            "elapsed_pct": msg.get("elapsed_pct"),
            "btc_price": msg.get("btc_price"),
            "up_best_bid": msg["up_bids"][0][0] if msg.get("up_bids") else None,
            "up_best_ask": msg["up_asks"][0][0] if msg.get("up_asks") else None,
            "up_bid_depth": msg["up_bids"][0][1] if msg.get("up_bids") else None,
            "up_ask_depth": msg["up_asks"][0][1] if msg.get("up_asks") else None,
            "down_best_bid": msg["down_bids"][0][0] if msg.get("down_bids") else None,
            "down_best_ask": msg["down_asks"][0][0] if msg.get("down_asks") else None,
            "down_bid_depth": msg["down_bids"][0][1] if msg.get("down_bids") else None,
            "down_ask_depth": msg["down_asks"][0][1] if msg.get("down_asks") else None,
            "market_volume": msg.get("market_volume"),
            **indicators,
        }

    async def on_candle_close(self, msg: dict) -> None:
        """Process a candle_close message. Syncs on first call."""
        candle = CandleRecord(
            candle_id=msg.get("candle_id", ""),
            start_time=0.0,
            end_time=0.0,
            open=msg["open"],
            high=msg["high"],
            low=msg["low"],
            close=msg["close"],
            volume=msg["volume"],
            outcome=msg["outcome"],
            final_ret=msg["final_ret"],
        )

        if not self._synced:
            self._prior_candles = await self._repo.get_recent_candles(MINIMUM_CANDLES)
            self._synced = True
            self._log.info(
                "🔄 Synced — loaded %d prior candles from DB",
                len(self._prior_candles),
            )
            # Skip appending if the DB already contains this candle
            if self._prior_candles and self._prior_candles[-1].candle_id == candle.candle_id:
                self._candle_open = candle.close
                return

        self._prior_candles.append(candle)

        self._snapshots_so_far = []
        self._candle_open = candle.close  # next candle opens at previous close
        self._current_candle_id = None
