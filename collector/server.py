"""Local WebSocket server — thin broadcaster. Does NOT fetch data itself."""

from __future__ import annotations

import json
import logging

import websockets

WS_HOST = "localhost"
WS_PORT = 8765


class CollectorServer:
    """Broadcasts messages to connected WebSocket clients.

    Does not fetch any data. Receives messages to broadcast via send().
    """

    def __init__(
        self,
        host: str = WS_HOST,
        port: int = WS_PORT,
        logger: logging.Logger | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._log = logger or logging.getLogger(__name__)
        self._clients: set[websockets.WebSocketServerProtocol] = set()
        self._server: websockets.WebSocketServer | None = None

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._server = await websockets.serve(self._handler, self._host, self._port)
        self._log.info("📡 WebSocket server listening on ws://%s:%d", self._host, self._port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def broadcast(self, message: str) -> None:
        """Send a message to all connected clients."""
        if not self._clients:
            return
        dead = set()
        for ws in self._clients:
            try:
                await ws.send(message)
            except websockets.ConnectionClosed:
                dead.add(ws)
        self._clients -= dead

    async def broadcast_json(self, data: dict) -> None:
        """Serialize dict to JSON and broadcast."""
        await self.broadcast(json.dumps(data))

    async def _handler(self, ws: websockets.WebSocketServerProtocol, path: str = "/") -> None:
        self._clients.add(ws)
        self._log.info("Client connected (%d total)", len(self._clients))
        try:
            await ws.wait_closed()
        finally:
            self._clients.discard(ws)
            self._log.info("Client disconnected (%d total)", len(self._clients))
