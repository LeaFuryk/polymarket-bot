"""Service: aggregates Chainlink ticks into OHLCV candles."""

from __future__ import annotations

import logging
import math
from collections import deque

from polybot.domain.models import (
    BtcTick,
    Candle,
    CandleData,
    PartialCandle,
)
from polybot.ports.price_stream import PriceStream
from polybot.ports.volume_feed import VolumeFeed

logger = logging.getLogger(__name__)

CANDLE_INTERVAL = 300  # 5 minutes
HISTORY_SIZE = 20


class CandleAggregator:
    """Consumes Chainlink ticks and builds 5-minute OHLCV candles.

    Depends on PriceStream (ticks) and VolumeFeed (volume on candle close).
    """

    def __init__(
        self,
        price_stream: PriceStream,
        volume_feed: VolumeFeed,
        interval: int = CANDLE_INTERVAL,
        history_size: int = HISTORY_SIZE,
    ) -> None:
        self._price_stream = price_stream
        self._volume_feed = volume_feed
        self._interval = interval
        self._history: deque[Candle] = deque(maxlen=history_size)
        self._partial: PartialCandle | None = None
        self._latest_tick: BtcTick | None = None
        self._first_candle_complete = False  # discard first partial candle on startup

    # -- Background task ---------------------------------------------------

    async def run(self) -> None:
        """Consume ticks, bucket into candles, close on boundary."""
        async for tick in self._price_stream.ticks():
            self._latest_tick = tick
            await self._process_tick(tick)

    async def _process_tick(self, tick: BtcTick) -> None:
        """Route a tick to the correct candle bucket."""
        self._latest_tick = tick
        ts = tick.timestamp
        candle_start = ts - (ts % self._interval)
        candle_end = candle_start + self._interval

        if self._partial is None or candle_start >= self._partial.end_time:
            # New candle boundary — close previous if exists
            if self._partial is not None:
                if self._first_candle_complete:
                    await self._close_candle()
                else:
                    # First candle was incomplete (started mid-interval) — discard
                    logger.info("Discarding incomplete startup candle")
                    self._first_candle_complete = True
            self._partial = PartialCandle(
                open=tick.price,
                high=tick.price,
                low=tick.price,
                last_price=tick.price,
                start_time=candle_start,
                end_time=candle_end,
                tick_count=1,
                last_tick_time=ts,
            )
        else:
            self._partial.update(tick)

    async def _close_candle(self) -> None:
        """Finalize the partial candle with Binance volume, add to history."""
        if self._partial is None:
            return

        volume = await self._volume_feed.get_volume(self._partial.start_time, self._partial.end_time)
        candle = Candle(
            open=self._partial.open,
            high=self._partial.high,
            low=self._partial.low,
            close=self._partial.last_price,
            volume=volume,
            start_time=self._partial.start_time,
            end_time=self._partial.end_time,
        )
        self._history.append(candle)
        logger.info(
            "Candle closed: O=%.2f H=%.2f L=%.2f C=%.2f V=%.2f",
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.volume,
        )

    # -- Public read interface ---------------------------------------------

    @property
    def latest_tick(self) -> BtcTick | None:
        return self._latest_tick

    @property
    def partial(self) -> PartialCandle | None:
        return self._partial

    def closed_candles(self) -> tuple[Candle, ...]:
        """Last N closed candles, oldest first."""
        return tuple(self._history)

    def candle_data(self) -> tuple[CandleData, ...]:
        """Closed candles as CandleData with log_ret and vol_pace."""
        candles = tuple(self._history)
        if not candles:
            return ()

        avg_volume = self._rolling_avg_volume(candles)
        result: list[CandleData] = []
        count = len(candles)

        for i, candle in enumerate(candles):
            # log_ret: ln(close / prev_close), None for first
            if i > 0 and candles[i - 1].close > 0:
                log_ret = math.log(candle.close / candles[i - 1].close)
            else:
                log_ret = None

            # vol_pace: volume / avg_volume, None if avg is 0
            vol_pace = candle.volume / avg_volume if avg_volume > 0 else None

            result.append(
                CandleData(
                    t=i - count,  # -N (oldest) to -1 (most recent)
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                    log_ret=log_ret,
                    vol_pace=vol_pace,
                )
            )

        return tuple(result)

    @staticmethod
    def _rolling_avg_volume(candles: tuple[Candle, ...]) -> float:
        """Average volume across all closed candles."""
        if not candles:
            return 0.0
        return sum(c.volume for c in candles) / len(candles)
