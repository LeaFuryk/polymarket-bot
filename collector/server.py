"""Local WebSocket server broadcasting market data to connected clients."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import websockets
from polybot_data.domain.models import Candle
from polybot_data.ports.candle_source import CandleSource
from polybot_data.ports.market_feed import MarketFeed
from pyee.asyncio import AsyncIOEventEmitter

BROADCAST_INTERVAL = 1  # seconds
WS_HOST = "localhost"
WS_PORT = 8765
MAX_OB_LEVELS = 10
CANDLE_INTERVAL = 300


class CollectorServer:
    """Broadcasts snapshots via local WebSocket. Clients receive market data in real-time."""

    def __init__(
        self,
        candle_source: CandleSource,
        market_feed: MarketFeed,
        events: AsyncIOEventEmitter,
        host: str = WS_HOST,
        port: int = WS_PORT,
        series_slug: str = "btc-updown-5m",
        logger: logging.Logger | None = None,
    ) -> None:
        self._candles = candle_source
        self._market_feed = market_feed
        self._host = host
        self._port = port
        self._series_slug = series_slug
        self._log = logger or logging.getLogger(__name__)
        self._clients: set[websockets.WebSocketServerProtocol] = set()
        self._server: websockets.WebSocketServer | None = None

        events.on("candle_close", self._on_candle_close)

    async def run(self) -> None:
        """Start WS server and broadcast loop."""
        self._server = await websockets.serve(self._handler, self._host, self._port)
        self._log.info("WebSocket server listening on ws://%s:%d", self._host, self._port)
        await self._broadcast_loop()

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handler(self, ws: websockets.WebSocketServerProtocol, path: str = "/") -> None:
        self._clients.add(ws)
        self._log.info("Client connected (%d total)", len(self._clients))
        try:
            await ws.wait_closed()
        finally:
            self._clients.discard(ws)
            self._log.info("Client disconnected (%d total)", len(self._clients))

    async def _broadcast_loop(self) -> None:
        """Every ~1s, build a snapshot and broadcast to all connected clients."""
        while True:
            if self._clients:
                msg = await self._build_snapshot_message()
                if msg:
                    await self._broadcast(msg)
            await asyncio.sleep(BROADCAST_INTERVAL)

    async def _build_snapshot_message(self) -> str | None:
        tick = self._candles.latest_tick
        if tick is None:
            return None

        partial = self._candles.partial
        now = time.time()

        market = await self._market_feed.discover_market(self._series_slug)
        if market is None:
            return None

        snapshot = await self._market_feed.get_snapshot(market)

        candle_start = partial.start_time if partial else now - (now % CANDLE_INTERVAL)
        elapsed_pct = max(0.0, min((now - candle_start) / CANDLE_INTERVAL, 1.0))
        boundary = int(candle_start - (candle_start % CANDLE_INTERVAL))
        candle_id = f"{self._series_slug}-{boundary}"

        data = {
            "type": "snapshot",
            "timestamp": now,
            "tick_timestamp": tick.timestamp,
            "candle_id": candle_id,
            "elapsed_pct": round(elapsed_pct, 4),
            "btc_price": tick.price,
            "btc_bid": tick.bid,
            "btc_ask": tick.ask,
            "up_bids": [(lvl.price, lvl.size) for lvl in snapshot.up_book.bids[:MAX_OB_LEVELS]],
            "up_asks": [(lvl.price, lvl.size) for lvl in snapshot.up_book.asks[:MAX_OB_LEVELS]],
            "down_bids": [(lvl.price, lvl.size) for lvl in snapshot.down_book.bids[:MAX_OB_LEVELS]],
            "down_asks": [(lvl.price, lvl.size) for lvl in snapshot.down_book.asks[:MAX_OB_LEVELS]],
            "up_last_trade": snapshot.last_trade_price,
            "down_last_trade": snapshot.down_last_trade_price,
            "market_volume": snapshot.volume,
        }
        return json.dumps(data)

    async def _on_candle_close(self, candle: Candle) -> None:
        import math

        outcome = "UP" if candle.close >= candle.open else "DOWN"
        final_ret = math.log(candle.close / candle.open) if candle.open > 0 else 0.0
        data = {
            "type": "candle_close",
            "candle_id": f"{self._series_slug}-{int(candle.start_time - (candle.start_time % CANDLE_INTERVAL))}",
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "outcome": outcome,
            "final_ret": final_ret,
        }
        msg = json.dumps(data)
        self._log.info("Broadcasting candle_close: %s outcome=%s", data["candle_id"], outcome)
        await self._broadcast(msg)

    async def _broadcast(self, message: str) -> None:
        if not self._clients:
            return
        dead = set()
        for ws in self._clients:
            try:
                await ws.send(message)
            except websockets.ConnectionClosed:
                dead.add(ws)
        self._clients -= dead
