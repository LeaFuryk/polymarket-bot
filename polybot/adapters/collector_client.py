"""Adapter: connects to collector's local WebSocket for live market data."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import websockets

if TYPE_CHECKING:
    from polybot.ports.message_relay import MessageRelay

WS_URL = "ws://localhost:8765"
RECONNECT_DELAY = 3


class CollectorClient:
    """Receives snapshots and candle_close events from the collector server."""

    def __init__(
        self,
        ws_url: str = WS_URL,
        relay: MessageRelay | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._ws_url = ws_url
        self._log = logger or logging.getLogger(__name__)
        self._relay = relay
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
        """Parse raw WebSocket message, update state, and forward to relay."""
        msg = json.loads(raw)
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            self._latest_snapshot = msg
            self._log.info(
                "📊 BTC $%.2f | YES %.2f | NO %.2f | elapsed %.0f%% | %s",
                msg.get("btc_price", 0),
                msg.get("up_last_trade") or 0,
                msg.get("down_last_trade") or 0,
                msg.get("elapsed_pct", 0) * 100,
                msg.get("candle_id", "?"),
            )
        elif msg_type == "candle_close":
            self._latest_candle_close = msg
            self._log.info(
                "🕯️ Candle %s | %s | O=$%.2f C=$%.2f | ret=%+.4f",
                msg.get("candle_id"),
                msg.get("outcome"),
                msg.get("open", 0),
                msg.get("close", 0),
                msg.get("final_ret", 0),
            )
        if self._relay is not None:
            try:
                await self._relay.broadcast_json(msg)
            except Exception:
                self._log.exception("Relay broadcast failed")

    async def stop(self) -> None:
        """Stop the run loop."""
        self._running = False

    @property
    def snapshot(self) -> dict | None:
        return self._latest_snapshot

    @property
    def candle_close(self) -> dict | None:
        return self._latest_candle_close
