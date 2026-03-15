"""Client set management and message broadcast over WebSocket."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol


class Broadcaster:
    """Manages connected WS clients and broadcasts messages."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._clients: set[WebSocketServerProtocol] = set()
        self._logger = logger or logging.getLogger(__name__)

    # --- Client management ---

    def add_client(self, ws: WebSocketServerProtocol) -> None:
        self._clients.add(ws)
        self._logger.info("WS client connected (%d total)", len(self._clients))

    def remove_client(self, ws: WebSocketServerProtocol) -> None:
        self._clients.discard(ws)
        self._logger.info("WS client disconnected (%d total)", len(self._clients))

    @property
    def has_clients(self) -> bool:
        return len(self._clients) > 0

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def broadcast(self, msg: str) -> None:
        """Send a message to all connected clients, removing dead connections."""
        if not self._clients:
            return
        dead: list[WebSocketServerProtocol] = []
        for ws in self._clients.copy():
            try:
                await ws.send(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)
