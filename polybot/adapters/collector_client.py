"""Adapter: connects to collector's local WebSocket for live market data."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

import websockets

WS_URL = "ws://localhost:8765"
RECONNECT_DELAY = 3

OnMessage = Callable[[dict], Coroutine[Any, Any, None]]


class CollectorClient:
    """Receives snapshots and candle_close events from the collector server."""

    def __init__(
        self,
        ws_url: str = WS_URL,
        on_message: OnMessage | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ws_url = ws_url
        self._log = logger or logging.getLogger(__name__)
        self._on_message = on_message
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
                        await self._handle_message(raw)
            except (websockets.ConnectionClosed, ConnectionRefusedError, OSError):
                self._log.warning("Collector connection lost, retrying in %ds...", RECONNECT_DELAY)
                await asyncio.sleep(RECONNECT_DELAY)

    async def _handle_message(self, raw: str) -> None:
        """Parse raw WebSocket message, update state, and dispatch to handler."""
        msg = json.loads(raw)
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            self._latest_snapshot = msg
        elif msg_type == "candle_close":
            self._latest_candle_close = msg
        if self._on_message is not None:
            try:
                await self._on_message(msg)
            except Exception:
                self._log.exception("on_message handler failed")

    async def stop(self) -> None:
        """Stop the run loop."""
        self._running = False

    @property
    def snapshot(self) -> dict | None:
        return self._latest_snapshot

    @property
    def candle_close(self) -> dict | None:
        return self._latest_candle_close
