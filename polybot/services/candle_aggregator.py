"""Service: aggregates Chainlink ticks into OHLCV candles."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque

from pyee.asyncio import AsyncIOEventEmitter

from polybot.domain.models import (
    BtcTick,
    Candle,
    CandleData,
    PartialCandle,
)
from polybot.ports.candle_source import CandleSource
from polybot.ports.price_stream import PriceStream
from polybot.ports.volume_feed import VolumeFeed

CANDLE_INTERVAL = 300  # 5 minutes
HISTORY_SIZE = 40  # needs 35+ for MACD, keep extra buffer
VOL_PACE_WINDOW = 20  # trailing bars for volume pace


class CandleAggregator(CandleSource):
    """Consumes Chainlink ticks and builds 5-minute OHLCV candles.

    Single-authority design:
    - _consume_ticks() only updates the current partial (never closes)
    - _expiry_loop() is the sole authority that closes candles at boundary time
    - Ticks arriving for a future interval are dropped (at most 1 per boundary)
    """

    def __init__(
        self,
        price_stream: PriceStream,
        volume_feed: VolumeFeed,
        interval: int = CANDLE_INTERVAL,
        history_size: int = HISTORY_SIZE,
        logger: logging.Logger | None = None,
        events: AsyncIOEventEmitter | None = None,
    ) -> None:
        self._price_stream = price_stream
        self._volume_feed = volume_feed
        self._log = logger or logging.getLogger(__name__)
        self._interval = interval
        self._history: deque[Candle] = deque(maxlen=history_size)
        self._partial: PartialCandle | None = None
        self._latest_tick: BtcTick | None = None
        self._first_candle_complete = False
        self.events = events or AsyncIOEventEmitter()

    # -- Background tasks --------------------------------------------------

    async def run(self) -> None:
        """Consume ticks and manage candle expiry. Fully self-contained."""
        await asyncio.gather(
            self._consume_ticks(),
            self._expiry_loop(),
        )

    async def _consume_ticks(self) -> None:
        """Read ticks from the price stream. Only updates partials — never closes.

        Raises RuntimeError when the tick stream ends (e.g. reconnect exhaustion)
        so asyncio.gather propagates the failure and shuts down _expiry_loop.
        """
        async for tick in self._price_stream.ticks():
            self._latest_tick = tick
            self._update_partial(tick)

        raise RuntimeError("Price stream ended unexpectedly")

    def _update_partial(self, tick: BtcTick) -> None:
        """Route a tick into the current partial candle.

        If the tick belongs to a future interval, it is dropped. The expiry
        loop will close the current candle and set _partial = None, so the
        next tick will start a fresh partial naturally. At most 1 tick is
        lost per boundary (Chainlink heartbeat ~27s).
        """
        ts = tick.timestamp
        candle_start = ts - (ts % self._interval)
        candle_end = candle_start + self._interval

        if self._partial is not None and candle_start >= self._partial.end_time:
            # Tick belongs to a future interval — drop it.
            # The expiry loop will close the current candle shortly.
            return

        if self._partial is None:
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

    async def _expiry_loop(self) -> None:
        """Sole authority for closing candles. Sleeps until boundary, then closes."""
        while True:
            if self._partial is not None:
                delay = self._partial.end_time - time.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                await self._close_current_candle()
            else:
                await asyncio.sleep(1)

    async def _close_current_candle(self) -> None:
        """Close the partial candle and add to history."""
        if self._partial is None:
            return

        if not self._first_candle_complete:
            self._log.info("Discarding incomplete startup candle, backfilling history")
            self._first_candle_complete = True
            self._partial = None
            await self._backfill()
            return

        # Snapshot fields before any await
        p_open = self._partial.open
        p_high = self._partial.high
        p_low = self._partial.low
        p_close = self._partial.last_price
        p_start = self._partial.start_time
        p_end = self._partial.end_time

        # Clear partial — ticks arriving during the await are dropped (future interval),
        # and the next tick after close starts a fresh partial naturally.
        self._partial = None

        try:
            volume = await self._volume_feed.get_volume(p_start, p_end)
        except Exception:
            self._log.exception("Failed to fetch volume for candle, using 0.0")
            volume = 0.0

        candle = Candle(
            open=p_open,
            high=p_high,
            low=p_low,
            close=p_close,
            volume=volume,
            start_time=p_start,
            end_time=p_end,
        )
        self._history.append(candle)
        self._log.info(
            "Candle closed: O=%.2f H=%.2f L=%.2f C=%.2f V=%.2f",
            candle.open,
            candle.high,
            candle.low,
            candle.close,
            candle.volume,
        )

        self.events.emit("candle_close", candle)

    async def _backfill(self) -> None:
        """Load historical candles from VolumeFeed to warm up indicators."""
        try:
            candles = await self._volume_feed.get_candles(self._history.maxlen, self._interval)
            if not candles:
                return
            now = time.time()
            if candles[-1].end_time > now:
                candles = candles[:-1]
            for candle in candles:
                self._history.append(candle)
            self._log.info("Backfilled %d candles from volume feed", len(self._history))
        except Exception:
            self._log.exception("Backfill failed")

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

    async def get_partial_volume(self, start_time: float = 0, end_time: float = 0) -> float:
        """Get BTC volume for a candle interval.

        If start_time/end_time are provided, uses those (for snapshot consistency).
        Otherwise reads from the current partial candle.
        """
        if start_time and end_time:
            s, e = start_time, end_time
        elif self._partial is not None:
            s = self._partial.start_time
            e = min(time.time(), self._partial.end_time)
        else:
            return 0.0

        try:
            return await self._volume_feed.get_volume(s, min(e, time.time()))
        except Exception:
            self._log.exception("Failed to fetch partial volume")
            return 0.0

    def candle_data(self) -> tuple[CandleData, ...]:
        """Closed candles as CandleData with log_ret and vol_pace (causal)."""
        candles = tuple(self._history)
        if not candles:
            return ()

        result: list[CandleData] = []
        count = len(candles)

        for i, candle in enumerate(candles):
            if i > 0 and candles[i - 1].close > 0:
                log_ret = math.log(candle.close / candles[i - 1].close)
            else:
                log_ret = None

            trailing = candles[max(0, i - VOL_PACE_WINDOW + 1) : i + 1]
            avg_vol = sum(c.volume for c in trailing) / len(trailing)
            vol_pace = candle.volume / avg_vol if avg_vol > 0 else None

            result.append(
                CandleData(
                    t=i - count,
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
