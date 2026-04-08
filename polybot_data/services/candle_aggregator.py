"""Service: aggregates Chainlink ticks into OHLCV candles."""

from __future__ import annotations

import asyncio
import logging
import time

from pyee.asyncio import AsyncIOEventEmitter

from polybot_data.domain.models import (
    BtcTick,
    Candle,
    PartialCandle,
)
from polybot_data.ports.price_stream import PriceStream
from polybot_data.ports.volume_feed import VolumeFeed

CANDLE_INTERVAL = 300  # 5 minutes


class CandleAggregator:
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
        logger: logging.Logger | None = None,
        events: AsyncIOEventEmitter | None = None,
    ) -> None:
        self._price_stream = price_stream
        self._volume_feed = volume_feed
        self._log = logger or logging.getLogger(__name__)
        self._interval = interval
        self._partial: PartialCandle | None = None
        self._latest_tick: BtcTick | None = None
        self._first_candle_complete = False
        self._last_closed_end: float = 0.0
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
            return  # future interval — don't update latest_tick

        # Reject ticks for an interval we already closed
        if candle_end <= self._last_closed_end:
            return  # already closed — don't update latest_tick

        # Reject out-of-order ticks within the same interval
        if self._partial is not None and ts <= self._partial.last_tick_time:
            return

        self._latest_tick = tick  # only accepted, in-order ticks update latest_tick

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
        """Close the partial candle and emit candle_close event."""
        if self._partial is None:
            return

        if not self._first_candle_complete:
            self._log.info(
                "⏭️ Discarding incomplete startup candle (O=%.2f C=%.2f ticks=%d)",
                self._partial.open,
                self._partial.last_price,
                self._partial.tick_count,
            )
            self._first_candle_complete = True
            self._last_closed_end = self._partial.end_time
            self._partial = None
            return

        # Snapshot fields before any await
        p_open = self._partial.open
        p_high = self._partial.high
        p_low = self._partial.low
        p_close = self._partial.last_price
        p_start = self._partial.start_time
        p_end = self._partial.end_time

        self._partial = None
        self._last_closed_end = p_end

        # Once partial is consumed, we MUST emit — even if cancelled
        cancelled = False
        try:
            volume = await asyncio.wait_for(self._volume_feed.get_volume(p_start, p_end), timeout=10.0)
        except asyncio.CancelledError:
            volume = 0.0
            cancelled = True
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
        self.events.emit("candle_close", candle)

        # Re-raise so the task actually terminates on shutdown
        if cancelled:
            raise asyncio.CancelledError

    # -- Public read interface ---------------------------------------------

    @property
    def latest_tick(self) -> BtcTick | None:
        return self._latest_tick

    @property
    def partial(self) -> PartialCandle | None:
        return self._partial

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
