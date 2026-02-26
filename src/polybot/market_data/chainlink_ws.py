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

logger = logging.getLogger(__name__)

# Price is considered stale if no update in this many seconds
_STALE_THRESHOLD = 30.0

# Reconnect delay on failure
_RECONNECT_DELAY = 5.0

# Keepalive ping interval
_PING_INTERVAL = 5.0


class ChainlinkWSFeed:
    """Async WebSocket client for Polymarket RTDS Chainlink BTC/USD price."""

    def __init__(self, url: str = "wss://ws-live-data.polymarket.com") -> None:
        self._url = url
        self._price: float | None = None
        self._last_update: float = 0.0
        self._connected: bool = False
        self._task: asyncio.Task | None = None

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
                    self._price = price
                    self._last_update = time.time()
                    logger.debug("Chainlink WS: BTC/USD = $%.2f", price)
            except (ValueError, TypeError):
                pass
