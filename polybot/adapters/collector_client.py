"""Adapter: connects to collector's local WebSocket for live market data."""

from __future__ import annotations

import asyncio
import json
import logging

import websockets

WS_URL = "ws://localhost:8765"
RECONNECT_DELAY = 3


class CollectorClient:
    """Receives snapshots and candle_close events from the collector server."""

    def __init__(
        self,
        ws_url: str = WS_URL,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ws_url = ws_url
        self._log = logger or logging.getLogger(__name__)
        self._latest_snapshot: dict | None = None
        self._latest_candle_close: dict | None = None
        self._running = False

    async def run(self) -> None:
        """Connect to collector WS and process messages."""
        self._running = True
        while self._running:
            try:
                async with websockets.connect(self._ws_url) as ws:
                    self._log.info("Connected to collector at %s", self._ws_url)
                    async for raw in ws:
                        msg = json.loads(raw)
                        msg_type = msg.get("type")
                        if msg_type == "snapshot":
                            self._latest_snapshot = msg
                        elif msg_type == "candle_close":
                            self._latest_candle_close = msg
                            self._log.info(
                                "Candle closed: %s outcome=%s",
                                msg.get("candle_id"),
                                msg.get("outcome"),
                            )
            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError):
                self._log.warning("Collector connection lost, retrying in %ds...", RECONNECT_DELAY)
                await asyncio.sleep(RECONNECT_DELAY)

    async def stop(self) -> None:
        self._running = False

    @property
    def snapshot(self) -> dict | None:
        return self._latest_snapshot

    @property
    def candle_close(self) -> dict | None:
        return self._latest_candle_close
