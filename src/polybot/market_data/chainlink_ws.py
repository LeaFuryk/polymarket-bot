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

logger = logging.getLogger(__name__)

# Price is considered stale if no update in this many seconds
_STALE_THRESHOLD = 30.0

# Reconnect delay on failure
_RECONNECT_DELAY = 5.0

# Keepalive ping interval
_PING_INTERVAL = 5.0


class ChainlinkWSFeed:
    """Async WebSocket client for Polymarket RTDS Chainlink BTC/USD price."""

    # 5-minute bucket width in seconds
    _BUCKET_SECONDS = 300

    def __init__(self, url: str = "wss://ws-live-data.polymarket.com") -> None:
        self._url = url
        self._price: float | None = None
        self._last_update: float = 0.0
        self._connected: bool = False
        self._task: asyncio.Task | None = None
        # Candle building from ticks
        self._completed_candles: list[BtcCandle] = []  # completed 5-min candles (max 200)
        self._current_bucket: dict | None = None  # in-progress candle accumulator

    @property
    def price(self) -> float | None:
        """Latest Chainlink BTC/USD price, or None if stale (>30s) or not connected."""
        if self._price is None:
            return None
        if time.time() - self._last_update > _STALE_THRESHOLD:
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
        logger.info("Chainlink WS: background task started")

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
        logger.info("Chainlink WS: stopped")

    async def _run(self) -> None:
        """Reconnect loop — retries every 5s on failure."""
        while True:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Chainlink WS: connection error, reconnecting in %.0fs", _RECONNECT_DELAY)
            finally:
                self._connected = False
            await asyncio.sleep(_RECONNECT_DELAY)

    async def _connect_and_listen(self) -> None:
        """Connect, subscribe to btc/usd, and process messages."""
        logger.info("Chainlink WS: connecting to %s", self._url)

        async with websockets.connect(self._url, ping_interval=None) as ws:
            # Subscribe to Chainlink BTC/USD
            subscribe_msg = json.dumps({
                "action": "subscribe",
                "subscriptions": [{
                    "topic": "crypto_prices_chainlink",
                    "type": "*",
                    "filters": json.dumps({"symbol": "btc/usd"}),
                }],
            })
            await ws.send(subscribe_msg)
            logger.info("Chainlink WS: subscribed to btc/usd")
            self._connected = True

            # Start keepalive ping loop
            ping_task = asyncio.create_task(self._ping_loop(ws))

            try:
                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)
                        self._handle_message(msg)
                    except (json.JSONDecodeError, KeyError, TypeError):
                        logger.debug("Chainlink WS: unparseable message: %s", raw_msg[:200])
            finally:
                ping_task.cancel()
                try:
                    await ping_task
                except asyncio.CancelledError:
                    pass

    async def _ping_loop(self, ws) -> None:
        """Send PING frames every 5s to keep the connection alive."""
        try:
            while True:
                await asyncio.sleep(_PING_INTERVAL)
                await ws.ping()
        except asyncio.CancelledError:
            pass

    def _handle_message(self, msg: dict) -> None:
        """Extract price from an RTDS message payload."""
        # The RTDS sends messages with varying structure;
        # look for the price value in common locations
        data = msg

        # Some messages wrap data in a "data" key
        if "data" in msg and isinstance(msg["data"], dict):
            data = msg["data"]

        # Look for btc/usd price value
        value = data.get("value") or data.get("price")
        symbol = data.get("symbol", "")

        if value is not None and ("btc" in symbol.lower() or not symbol):
            try:
                price = float(value)
                if price > 0:
                    now = time.time()
                    self._price = price
                    self._last_update = now
                    self._record_tick(price, now)
                    logger.debug("Chainlink WS: BTC/USD = $%.2f", price)
            except (ValueError, TypeError):
                pass

    def _record_tick(self, price: float, ts: float) -> None:
        """Accumulate a tick into the current 5-min candle bucket."""
        bucket_start = ts - (ts % self._BUCKET_SECONDS)
        bucket_end = bucket_start + self._BUCKET_SECONDS

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
        # Cap at 200
        if len(self._completed_candles) > 200:
            self._completed_candles = self._completed_candles[-200:]
        self._current_bucket = None
        logger.info(
            "Chainlink WS: completed candle %s → $%.2f (ticks=%d, dir=%s)",
            candle.open_time, candle.close, b["tick_count"], candle.direction,
        )
