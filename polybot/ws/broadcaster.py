"""Adapter: WebSocket broadcaster — implements MessageRelay port."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import websockets

from polybot.ports.message_relay import MessageRelay

if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol


class Broadcaster(MessageRelay):
    """Manages connected WS clients and broadcasts messages.

    Implements the MessageRelay protocol. Injectable into any service
    that needs to push data to downstream consumers.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._clients: set[WebSocketServerProtocol] = set()
        self._log = logger or logging.getLogger(__name__)

    def add_client(self, ws: WebSocketServerProtocol) -> None:
        self._clients.add(ws)
        self._log.info("WS client connected (%d total)", len(self._clients))

    def remove_client(self, ws: WebSocketServerProtocol) -> None:
        self._clients.discard(ws)
        self._log.info("WS client disconnected (%d total)", len(self._clients))

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast(self, msg: str) -> None:
        if not self._clients:
            return
        dead: list[WebSocketServerProtocol] = []
        for ws in self._clients.copy():
            try:
                await ws.send(msg)
            except websockets.ConnectionClosed:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    async def broadcast_json(self, data: dict) -> None:
        await self.broadcast(json.dumps(data))
