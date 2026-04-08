"""Service: single fetch loop — builds snapshots, broadcasts, and records."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import asdict

from pyee.asyncio import AsyncIOEventEmitter

from polybot_data.domain.collection import CandleRecord, Snapshot
from polybot_data.domain.models import Candle
from polybot_data.ports.candle_source import CandleSource
from polybot_data.ports.data_store import DataStore
from polybot_data.ports.market_feed import MarketFeed

CANDLE_INTERVAL = 300
FETCH_INTERVAL = 1  # build snapshot every 1s
RECORD_EVERY = 5  # write to SQLite every 5th snapshot
MAX_OB_LEVELS = 10
RESOLUTION_CHECK_INTERVAL = 60  # check pending resolutions every 60s
VOLUME_TIMEOUT = 10  # seconds to wait for volume lookup


class DataCollector:
    """Single fetch loop: builds a Snapshot every ~1s.

    - Broadcasts to WebSocket every iteration (via broadcast_fn callback)
    - Writes to SQLite every RECORD_EVERY iterations
    - Writes CandleRecord on candle_close event
    - Resolution queue: checks Polymarket for authoritative prices

    Does NOT maintain candle lifecycle — CandleAggregator is the single authority.
    """

    def __init__(
        self,
        candle_source: CandleSource,
        market_feed: MarketFeed,
        store: DataStore,
        events: AsyncIOEventEmitter,
        broadcast_fn=None,
        series_slug: str = "btc-updown-5m",
        logger: logging.Logger | None = None,
    ) -> None:
        self._candles = candle_source
        self._market_feed = market_feed
        self._store = store
        self._series_slug = series_slug
        self._log = logger or logging.getLogger(__name__)
        self._broadcast_fn = broadcast_fn
        self._tick_counter = 0
        self._current_candle_id: str | None = None
        self._recording = False

        # Resolution queue: candles pending Polymarket verification
        self._pending_resolutions: list[CandleRecord] = []

        events.on("candle_close", self._on_candle_close)

    async def run(self) -> None:
        """Fetch loop + resolution queue. Run both concurrently."""
        await asyncio.gather(
            self._fetch_loop(),
            self._resolution_loop(),
        )

    async def drain(self) -> None:
        """Process any remaining pending resolutions before shutdown."""
        if not self._pending_resolutions:
            return
        self._log.info("Draining %d pending resolutions...", len(self._pending_resolutions))
        try:
            await self._process_pending_resolutions()
        except Exception:
            self._log.exception("Error during resolution drain")
        if self._pending_resolutions:
            unresolved = [r.candle_id for r in self._pending_resolutions]
            self._log.warning(
                "⚠️ %d candles unresolved at shutdown — run verify_resolutions.py: %s",
                len(unresolved),
                unresolved,
            )

    async def _fetch_loop(self) -> None:
        """Build snapshot every ~1s, broadcast, and optionally record."""
        while True:
            try:
                await self._fetch_and_dispatch()
            except Exception:
                self._log.exception("Collection error")
            await asyncio.sleep(FETCH_INTERVAL)

    async def _resolution_loop(self) -> None:
        """Every minute, check all pending candles against Polymarket."""
        while True:
            await asyncio.sleep(RESOLUTION_CHECK_INTERVAL)
            if not self._pending_resolutions:
                continue
            try:
                await self._process_pending_resolutions()
            except Exception:
                self._log.exception("Resolution check error")

    async def _process_pending_resolutions(self) -> None:
        """Check each pending candle against Polymarket. Remove resolved ones."""
        # Snapshot the queue — new candles appended during processing won't be lost
        to_check = self._pending_resolutions
        self._pending_resolutions = []
        still_pending = []

        processed = 0
        try:
            for original in to_check:
                try:
                    resolved = await self._resolve_single(original)
                    if not resolved:
                        still_pending.append(original)
                except Exception:
                    self._log.exception("Failed to resolve %s — will retry", original.candle_id)
                    still_pending.append(original)
                processed += 1
        except BaseException:
            # On CancelledError or any other interruption, keep unprocessed items
            still_pending.extend(to_check[processed:])
            raise
        finally:
            # Always merge back — never lose candles
            self._pending_resolutions = still_pending + self._pending_resolutions

        if self._pending_resolutions:
            self._log.info("⏳ %d candles still pending resolution", len(self._pending_resolutions))

    async def _resolve_single(self, original: CandleRecord) -> bool:
        """Check one candle against Polymarket. Returns True if resolved."""
        resolution = await self._market_feed.get_resolution(original.candle_id)
        if resolution is None:
            return False

        pm_open = resolution["open"]
        pm_close = resolution["close"]
        pm_outcome = resolution["outcome"]
        chainlink_outcome = original.outcome

        # Adjust high/low if corrected prices fall outside original range
        high = max(original.high, pm_open, pm_close)
        low = min(original.low, pm_open, pm_close)

        final_ret = math.log(pm_close / pm_open) if pm_open > 0 else 0.0
        await self._store.update_candle(
            candle_id=original.candle_id,
            open=pm_open,
            high=high,
            low=low,
            close=pm_close,
            outcome=pm_outcome,
            final_ret=final_ret,
        )

        outcome_changed = pm_outcome != chainlink_outcome
        open_changed = abs(pm_open - original.open) > 0.01
        close_changed = abs(pm_close - original.close) > 0.01

        if outcome_changed or open_changed or close_changed:
            self._log.warning(
                "🔄 Resolution correction | %s | %s→%s | open: $%.2f→$%.2f | close: $%.2f→$%.2f",
                original.candle_id,
                chainlink_outcome,
                pm_outcome,
                original.open,
                pm_open,
                original.close,
                pm_close,
            )
            if self._broadcast_fn is not None:
                corrected = CandleRecord(
                    candle_id=original.candle_id,
                    start_time=original.start_time,
                    end_time=original.end_time,
                    open=pm_open,
                    high=high,
                    low=low,
                    close=pm_close,
                    volume=original.volume,
                    outcome=pm_outcome,
                    final_ret=final_ret,
                )
                msg = asdict(corrected)
                msg["type"] = "candle_correction"
                await self._broadcast_fn(msg)
        else:
            self._log.info("✅ Resolution verified | %s | %s", original.candle_id, pm_outcome)

        return True

    async def _fetch_and_dispatch(self) -> None:
        """Single fetch → broadcast + conditional record."""
        tick = self._candles.latest_tick
        if tick is None:
            return

        partial = self._candles.partial
        if partial is None:
            return  # aggregator is between candles — skip stale data
        now = time.time()

        candle_start = partial.start_time
        elapsed_pct = max(0.0, min((now - candle_start) / CANDLE_INTERVAL, 1.0))

        boundary = int(candle_start - (candle_start % CANDLE_INTERVAL))
        candle_id = f"{self._series_slug}-{boundary}"

        market = await self._market_feed.discover_market(self._series_slug)
        if market is None:
            return

        # Verify market covers our candle interval
        market_start = market.end_time - CANDLE_INTERVAL
        if not (market_start <= candle_start < market.end_time):
            return

        snapshot_data = await self._market_feed.get_snapshot(market)

        # Re-check partial after await — candle may have closed during I/O
        if self._candles.partial is None or self._candles.partial.start_time != candle_start:
            return

        snap = Snapshot(
            timestamp=now,
            tick_timestamp=tick.timestamp,
            candle_id=candle_id,
            elapsed_pct=elapsed_pct,
            btc_price=tick.price,
            btc_bid=tick.bid,
            btc_ask=tick.ask,
            up_bids=self._levels(snapshot_data.up_book.bids),
            up_asks=self._levels(snapshot_data.up_book.asks),
            down_bids=self._levels(snapshot_data.down_book.bids),
            down_asks=self._levels(snapshot_data.down_book.asks),
            up_last_trade=snapshot_data.last_trade_price,
            down_last_trade=snapshot_data.down_last_trade_price,
            market_volume=snapshot_data.volume,
        )

        # Detect candle boundary — start recording when a new candle begins
        if self._current_candle_id is None:
            self._current_candle_id = candle_id
        elif candle_id != self._current_candle_id:
            if not self._recording:
                self._recording = True
                self._log.info("🟢 New candle started — recording active")
            self._current_candle_id = candle_id

        if not self._recording:
            return

        # Record to SQLite BEFORE broadcast — persistence is more important
        self._tick_counter += 1
        if self._tick_counter >= RECORD_EVERY:
            self._tick_counter = 0
            await self._store.write_snapshot(snap)
            self._log.info(
                "📸 Snapshot saved | candle=%s elapsed=%.0f%% | BTC $%.2f | YES=%.2f NO=%.2f | vol=$%.0f",
                snap.candle_id,
                snap.elapsed_pct * 100,
                snap.btc_price,
                snap.up_last_trade or 0,
                snap.down_last_trade or 0,
                snap.market_volume,
            )

        # Broadcast to WS clients
        if self._broadcast_fn is not None:
            msg = asdict(snap)
            msg["type"] = "snapshot"
            await self._broadcast_fn(msg)

    async def _on_candle_close(self, candle: Candle) -> None:
        """Handle candle_close event from CandleAggregator."""
        if not self._recording:
            # First candle_close arms recording for the next candle
            self._recording = True
            self._log.info("🟢 First candle closed — recording active")
            return

        outcome = "UP" if candle.close >= candle.open else "DOWN"
        final_ret = math.log(candle.close / candle.open) if candle.open > 0 else 0.0

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
            "🕯️ Candle closed | %s | O=$%.2f C=$%.2f | outcome=%s ret=%+.4f",
            candle_id,
            record.open,
            record.close,
            outcome,
            final_ret,
        )

        # Add to resolution queue before broadcast — never lose a candle
        self._pending_resolutions.append(record)

        # Broadcast with Chainlink values
        if self._broadcast_fn is not None:
            msg = asdict(record)
            msg["type"] = "candle_close"
            await self._broadcast_fn(msg)

    @staticmethod
    def _levels(book_levels: tuple, max_n: int = MAX_OB_LEVELS) -> tuple[tuple[float, float], ...]:
        """Extract up to max_n (price, size) pairs from orderbook levels."""
        return tuple((lvl.price, lvl.size) for lvl in book_levels[:max_n])
