"""Service: collects raw market snapshots, writes candle records on close."""

from __future__ import annotations

import asyncio
import logging
import math
import time

from pyee.asyncio import AsyncIOEventEmitter

from polybot_data.domain.collection import CandleRecord, Snapshot
from polybot_data.domain.models import Candle
from polybot_data.ports.candle_source import CandleSource
from polybot_data.ports.data_store import DataStore
from polybot_data.ports.market_feed import MarketFeed

CANDLE_INTERVAL = 300
COLLECT_INTERVAL = 5
MAX_OB_LEVELS = 10


class DataCollector:
    """Passive recorder: samples market data every 5s, writes candles on close.

    Does NOT maintain candle lifecycle — CandleAggregator is the single authority.
    Subscribes to "candle_close" events via pyee AsyncIOEventEmitter.
    candle_id consistency: snapshots and candle records both derive candle_id
    from the same boundary formula to ensure they join correctly.
    """

    def __init__(
        self,
        candle_source: CandleSource,
        market_feed: MarketFeed,
        store: DataStore,
        events: AsyncIOEventEmitter,
        series_slug: str = "btc-updown-5m",
        logger: logging.Logger | None = None,
    ) -> None:
        self._candles = candle_source
        self._market_feed = market_feed
        self._store = store
        self._series_slug = series_slug
        self._log = logger or logging.getLogger(__name__)
        self._recording = False  # start recording after first candle_close

        events.on("candle_close", self._on_candle_close)

    async def run(self) -> None:
        """Collect snapshots in a loop, sleeping COLLECT_INTERVAL between iterations."""
        while True:
            try:
                await self.collect_once()
            except Exception:
                self._log.exception("Collection error")
            await asyncio.sleep(COLLECT_INTERVAL)

    async def collect_once(self) -> None:
        """Sample market state and write one snapshot to the store."""
        if not self._recording:
            return
        tick = self._candles.latest_tick
        if tick is None:
            return
        partial = self._candles.partial
        now = time.time()

        market = await self._market_feed.discover_market(self._series_slug)
        if market is None:
            return
        snapshot = await self._market_feed.get_snapshot(market)

        candle_start = partial.start_time if partial else now - (now % CANDLE_INTERVAL)
        elapsed_pct = max(0.0, min((now - candle_start) / CANDLE_INTERVAL, 1.0))

        # Derive candle_id from boundary — same formula used in on_candle_close
        boundary = int(candle_start - (candle_start % CANDLE_INTERVAL))
        candle_id = f"{self._series_slug}-{boundary}"

        snap = Snapshot(
            timestamp=now,
            tick_timestamp=tick.timestamp,
            candle_id=candle_id,
            elapsed_pct=elapsed_pct,
            btc_price=tick.price,
            btc_bid=tick.bid,
            btc_ask=tick.ask,
            up_bids=self._levels(snapshot.up_book.bids),
            up_asks=self._levels(snapshot.up_book.asks),
            down_bids=self._levels(snapshot.down_book.bids),
            down_asks=self._levels(snapshot.down_book.asks),
            up_last_trade=snapshot.last_trade_price,
            down_last_trade=snapshot.down_last_trade_price,
            market_volume=snapshot.volume,
        )
        self._log.info(
            "📸 Snapshot saved | candle=%s elapsed=%.0f%% | "
            "BTC $%.2f (bid $%.2f ask $%.2f) | "
            "YES last=%.2f NO last=%.2f | "
            "UP book: %d bids/%d asks | DOWN book: %d bids/%d asks | "
            "mkt_vol=$%.0f",
            snap.candle_id,
            snap.elapsed_pct * 100,
            snap.btc_price,
            snap.btc_bid,
            snap.btc_ask,
            snap.up_last_trade or 0,
            snap.down_last_trade or 0,
            len(snap.up_bids),
            len(snap.up_asks),
            len(snap.down_bids),
            len(snap.down_asks),
            snap.market_volume,
        )
        await self._store.write_snapshot(snap)

    async def _on_candle_close(self, candle: Candle) -> None:
        """Handle candle_close event from CandleAggregator."""
        if not self._recording:
            self._recording = True
            self._log.info("🟢 First valid candle closed — data collection now active")
        outcome = "UP" if candle.close >= candle.open else "DOWN"
        final_ret = math.log(candle.close / candle.open) if candle.open > 0 else 0.0

        # Same boundary formula as collect_once — ensures candle_id matches snapshots
        boundary = int(candle.start_time - (candle.start_time % CANDLE_INTERVAL))
        candle_id = f"{self._series_slug}-{boundary}"

        record = CandleRecord(
            candle_id=candle_id,
            start_time=candle.start_time,
            end_time=candle.end_time,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
            outcome=outcome,
            final_ret=final_ret,
        )
        await self._store.write_candle(record)
        self._log.info(
            "🕯️ Candle closed | %s | O=$%.2f H=$%.2f L=$%.2f C=$%.2f V=%.2f | outcome=%s final_ret=%+.4f",
            candle_id,
            record.open,
            record.high,
            record.low,
            record.close,
            record.volume,
            outcome,
            final_ret,
        )

    @staticmethod
    def _levels(book_levels: tuple, max_n: int = MAX_OB_LEVELS) -> tuple[tuple[float, float], ...]:
        """Extract up to max_n (price, size) pairs from orderbook levels."""
        return tuple((lvl.price, lvl.size) for lvl in book_levels[:max_n])
