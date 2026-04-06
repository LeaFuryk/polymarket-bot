"""Service: maintains candle state and computes technical indicators."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from polybot_data.domain.collection import CandleRecord
from polybot_data.services.indicator_engine import IndicatorSnapshot, compute_all

if TYPE_CHECKING:
    from polybot.ports.candle_repository import CandleRepository

MINIMUM_CANDLES = 21  # max lookback across all indicators


class IndicatorService:
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

    def on_snapshot(self, snapshot: IndicatorSnapshot) -> dict | None:
        """Compute indicators for a snapshot. Returns the model row, or None if not synced."""
        if not self._synced:
            return None

        if snapshot.candle_id != self._current_candle_id:
            self._snapshots_so_far = []
            if self._candle_open is None:
                self._candle_open = snapshot.btc_price  # fallback if no prior close
            self._current_candle_id = snapshot.candle_id

        self._snapshots_so_far.append(snapshot)

        indicators = compute_all(
            self._prior_candles,
            self._candle_open,
            self._snapshots_so_far,
        )

        return {
            "candle_id": snapshot.candle_id,
            "timestamp": snapshot.timestamp,
            "elapsed_pct": snapshot.elapsed_pct,
            "btc_price": snapshot.btc_price,
            "up_best_bid": snapshot.up_bids[0][0] if snapshot.up_bids else None,
            "up_best_ask": snapshot.up_asks[0][0] if snapshot.up_asks else None,
            "up_bid_depth": snapshot.up_bids[0][1] if snapshot.up_bids else None,
            "up_ask_depth": snapshot.up_asks[0][1] if snapshot.up_asks else None,
            "down_best_bid": snapshot.down_bids[0][0] if snapshot.down_bids else None,
            "down_best_ask": snapshot.down_asks[0][0] if snapshot.down_asks else None,
            "down_bid_depth": snapshot.down_bids[0][1] if snapshot.down_bids else None,
            "down_ask_depth": snapshot.down_asks[0][1] if snapshot.down_asks else None,
            "market_volume": snapshot.market_volume,
            **indicators,
        }

    async def on_candle_close(self, candle: CandleRecord) -> None:
        """Update candle history. Syncs from DB on first call."""
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
