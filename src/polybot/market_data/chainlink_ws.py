"""Chainlink RTDS WebSocket feed — real-time BTC/USD from Polymarket's data source.

Polymarket resolves BTC 5-minute candles using Chainlink Data Streams.
This WebSocket connects to Polymarket's RTDS endpoint which exposes the
exact Chainlink resolution price — no authentication required.

When active, this becomes the primary price source (aligned with resolution).
Binance is used as fallback when the WebSocket is disconnected or stale.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

import websockets

from polybot.models import BtcCandle

from .constants import (
    BTC_CANDLE_WINDOW_SIZE,
    CHAINLINK_WS_BUCKET_SECONDS,
    CHAINLINK_WS_DEFAULT_URL,
    CHAINLINK_WS_PING_INTERVAL,
    CHAINLINK_WS_RECONNECT_DELAY,
    CHAINLINK_WS_STALE_THRESHOLD,
    CHAINLINK_WS_WATCHDOG_INTERVAL,
)


class ChainlinkWSFeed:
    """Async WebSocket client for Polymarket RTDS Chainlink BTC/USD price."""

    def __init__(
        self,
        url: str = CHAINLINK_WS_DEFAULT_URL,
        logger: logging.Logger | None = None,
    ) -> None:
        self._log = logger or logging.getLogger(__name__)
        self._url = url
        self._price: float | None = None
        self._last_update: float = 0.0
        self._connected: bool = False
        self._task: asyncio.Task | None = None
        # Candle building from ticks
        self._completed_candles: list[BtcCandle] = []  # completed 5-min candles (max 200)
        self._current_bucket: dict | None = None  # in-progress candle accumulator
        self._msg_count: int = 0  # for debug logging first few messages
        self._last_msg_time: float = 0.0  # for staleness watchdog

    @property
    def price(self) -> float | None:
        """Latest Chainlink BTC/USD price, or None if stale (>30s) or not connected."""
        if self._price is None:
            return None
        if time.time() - self._last_update > CHAINLINK_WS_STALE_THRESHOLD:
            return None
        return self._price

    @property
    def is_active(self) -> bool:
        """True when connected AND receiving fresh updates."""
        return self._connected and self.price is not None

    @property
    def last_update(self) -> float:
        """Timestamp of last price update."""
        return self._last_update

    @property
    def completed_candles(self) -> list[BtcCandle]:
        """All completed 5-min candles built from WS ticks."""
        return list(self._completed_candles)

    async def start(self) -> None:
        """Launch the background WebSocket task."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="chainlink_ws")
        self._log.info("Chainlink WS: background task started")

    async def stop(self) -> None:
        """Cancel the background WebSocket task."""
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            self._connected = False
        self._log.info("Chainlink WS: stopped")

    async def _run(self) -> None:
        """Reconnect loop — retries every 5s on failure."""
        while True:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                raise
            except Exception:
                self._log.exception(
                    "Chainlink WS: connection error, reconnecting in %.0fs", CHAINLINK_WS_RECONNECT_DELAY
                )
            finally:
                self._connected = False
            await asyncio.sleep(CHAINLINK_WS_RECONNECT_DELAY)

    async def _connect_and_listen(self) -> None:
        """Connect, subscribe to btc/usd, and process messages."""
        self._log.info("Chainlink WS: connecting to %s", self._url)

        async with websockets.connect(self._url, ping_interval=None) as ws:
            # Subscribe to Chainlink BTC/USD
            subscribe_msg = json.dumps(
                {
                    "action": "subscribe",
                    "subscriptions": [
                        {
                            "topic": "crypto_prices_chainlink",
                            "type": "*",
                            "filters": json.dumps({"symbol": "btc/usd"}),
                        }
                    ],
                }
            )
            await ws.send(subscribe_msg)
            self._log.info("Chainlink WS: subscribed to btc/usd")
            self._connected = True
            self._msg_count = 0  # reset to log first messages after reconnect
            self._last_msg_time = time.time()

            # Start keepalive ping loop and staleness watchdog
            ping_task = asyncio.create_task(self._ping_loop(ws))
            watchdog_task = asyncio.create_task(self._staleness_watchdog(ws))

            try:
                async for raw_msg in ws:
                    self._last_msg_time = time.time()
                    if not raw_msg or not raw_msg.strip():
                        continue  # skip empty keepalive frames
                    try:
                        msg = json.loads(raw_msg)
                        self._handle_message(msg)
                    except (json.JSONDecodeError, KeyError, TypeError):
                        self._log.debug("Chainlink WS: unparseable message: %s", str(raw_msg)[:200])
            finally:
                ping_task.cancel()
                watchdog_task.cancel()
                for t in (ping_task, watchdog_task):
                    try:
                        await t
                    except asyncio.CancelledError:
                        pass

    async def _ping_loop(self, ws) -> None:
        """Send PING frames every 5s to keep the connection alive."""
        try:
            while True:
                await asyncio.sleep(CHAINLINK_WS_PING_INTERVAL)
                await ws.ping()
        except asyncio.CancelledError:
            pass

    async def _staleness_watchdog(self, ws) -> None:
        """Force-close the WebSocket if no messages arrive for >30s.

        The RTDS sends ticks every ~1s. If nothing arrives for 30s the
        connection is silently dead — `async for raw_msg in ws` will hang
        forever. This watchdog breaks the deadlock so the reconnect loop fires.
        """
        try:
            while True:
                await asyncio.sleep(CHAINLINK_WS_WATCHDOG_INTERVAL)
                silence = time.time() - self._last_msg_time
                if silence > CHAINLINK_WS_STALE_THRESHOLD:
                    self._log.warning(
                        "Chainlink WS: no messages for %.0fs — forcing reconnect",
                        silence,
                    )
                    await ws.close()
                    return
        except asyncio.CancelledError:
            pass

    def _handle_message(self, msg: dict) -> None:
        """Extract price(s) from an RTDS message payload.

        RTDS sends batches: {"payload": {"data": [{"timestamp": ms, "value": price}, ...]}}
        We process ALL ticks in the batch for accurate candle OHLC, and set the
        live price to the most recent tick.
        """
        # Log first few messages at INFO to debug format issues
        if self._msg_count < 3:
            self._log.info("Chainlink WS: sample message #%d: %s", self._msg_count, str(msg)[:500])
        self._msg_count += 1

        # Try to extract a batch of ticks from payload.data[]
        payload = msg.get("payload")
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list) and data:
                tick_count = 0
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    val = item.get("value") or item.get("price")
                    ts_ms = item.get("timestamp")
                    if val is None:
                        continue
                    try:
                        price = float(val)
                    except (ValueError, TypeError):
                        continue
                    if price <= 0:
                        continue
                    # Use the tick's own timestamp (ms → s), fall back to now
                    tick_ts = ts_ms / 1000.0 if ts_ms else time.time()
                    self._price = price
                    self._last_update = tick_ts
                    self._record_tick(price, tick_ts)
                    tick_count += 1
                if tick_count > 0:
                    self._log.debug(
                        "Chainlink WS: processed %d ticks, latest $%.2f",
                        tick_count,
                        self._price,
                    )
                    return

        # Fallback: single-value extraction
        price = self._extract_price(msg)
        if price is not None and price > 0:
            now = time.time()
            self._price = price
            self._last_update = now
            self._record_tick(price, now)
            self._log.debug("Chainlink WS: BTC/USD = $%.2f", price)

    def _extract_price(self, msg: dict) -> float | None:
        """Try multiple strategies to extract BTC/USD price from RTDS message.

        Known RTDS format: {"payload": {"data": [{"timestamp": ..., "value": ...}, ...]}, ...}
        Uses the last item in the data array (most recent tick).
        """
        # Strategy 1: payload.data[] — actual Polymarket RTDS format
        payload = msg.get("payload")
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list) and data:
                # Use the last (most recent) tick in the batch
                last_item = data[-1]
                if isinstance(last_item, dict):
                    val = last_item.get("value") or last_item.get("price")
                    if val is not None:
                        try:
                            return float(val)
                        except (ValueError, TypeError):
                            pass

        # Strategy 2: Direct value/price field
        for key in ("value", "price"):
            val = msg.get(key)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass

        # Strategy 3: Nested in "data" dict or list
        data = msg.get("data")
        if isinstance(data, dict):
            for key in ("value", "price"):
                val = data.get(key)
                if val is not None:
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        pass
        elif isinstance(data, list) and data:
            last_item = data[-1]
            if isinstance(last_item, dict):
                val = last_item.get("value") or last_item.get("price")
                if val is not None:
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        pass

        return None

    def _record_tick(self, price: float, ts: float) -> None:
        """Accumulate a tick into the current 5-min candle bucket."""
        bucket_start = ts - (ts % CHAINLINK_WS_BUCKET_SECONDS)
        bucket_end = bucket_start + CHAINLINK_WS_BUCKET_SECONDS

        if self._current_bucket is None or bucket_start > self._current_bucket["open_time"]:
            # Finalize previous bucket if it exists
            self._finalize_bucket()
            # Start new bucket
            self._current_bucket = {
                "open_time": bucket_start,
                "close_time": bucket_end,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "tick_count": 1,
            }
        else:
            # Same bucket — update running stats
            b = self._current_bucket
            b["high"] = max(b["high"], price)
            b["low"] = min(b["low"], price)
            b["close"] = price
            b["tick_count"] += 1

    def _finalize_bucket(self) -> None:
        """Convert the current bucket into a BtcCandle and store it."""
        if self._current_bucket is None:
            return
        b = self._current_bucket
        candle = BtcCandle(
            open_time=b["open_time"],
            close_time=b["close_time"],
            open=b["open"],
            high=b["high"],
            low=b["low"],
            close=b["close"],
            volume=float(b["tick_count"]),  # tick count as proxy volume
            source="chainlink_ws",
        )
        self._completed_candles.append(candle)
        # Cap at BTC_CANDLE_WINDOW_SIZE
        if len(self._completed_candles) > BTC_CANDLE_WINDOW_SIZE:
            self._completed_candles = self._completed_candles[-BTC_CANDLE_WINDOW_SIZE:]
        self._current_bucket = None
        self._log.info(
            "Chainlink WS: completed candle %s → $%.2f (ticks=%d, dir=%s)",
            candle.open_time,
            candle.close,
            b["tick_count"],
            candle.direction,
        )
