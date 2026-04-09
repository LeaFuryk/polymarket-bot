"""Service: orchestrates message processing — fans out to model runners."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from polybot_data.domain.collection import CandleRecord
from polybot_data.services.indicator_engine import IndicatorSnapshot

if TYPE_CHECKING:
    from polybot.services.indicator_service import IndicatorService
    from polybot.services.model_runner import ModelRunner


class AgentService:
    """Thin orchestrator: computes indicators once, fans out to all model runners."""

    def __init__(
        self,
        indicators: IndicatorService,
        runners: list[ModelRunner],
        logger: logging.Logger | None = None,
    ) -> None:
        self._indicators = indicators
        self._runners = runners
        self._log = logger or logging.getLogger(__name__)

    async def process(self, msg: dict) -> dict | None:
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            snapshot = IndicatorSnapshot.from_dict(msg)
            return await self._on_snapshot(snapshot)
        if msg_type == "candle_close":
            candle = CandleRecord.from_ws(msg)
            await self._on_candle_close(candle)
            return None
        if msg_type == "candle_correction":
            candle = CandleRecord.from_ws(msg)
            self._on_candle_correction(candle)
            return None
        return None

    async def _on_snapshot(self, snapshot: IndicatorSnapshot) -> dict | None:
        row = self._indicators.on_snapshot(snapshot)
        if row is None:
            return None
        for runner in self._runners:
            await runner.handle_snapshot(row, snapshot)
        return row

    async def _on_candle_close(self, candle: CandleRecord) -> None:
        for runner in self._runners:
            await runner.handle_candle_close(candle)
        await self._indicators.on_candle_close(candle)

    def _on_candle_correction(self, corrected: CandleRecord) -> None:
        for i, c in enumerate(self._indicators.prior_candles):
            if c.candle_id == corrected.candle_id:
                old_outcome = c.outcome
                self._indicators.prior_candles[i] = corrected
                if old_outcome != corrected.outcome:
                    for runner in self._runners:
                        runner.handle_correction(corrected)
                    self._log.warning(
                        "🔄 Correction applied | %s | %s→%s",
                        corrected.candle_id,
                        old_outcome,
                        corrected.outcome,
                    )
                break
