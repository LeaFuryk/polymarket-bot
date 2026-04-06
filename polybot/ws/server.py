"""WebSocket server for polybot — serves downstream consumers (dashboard)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import websockets

from polybot.ws.broadcaster import Broadcaster

if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol

WS_HOST = "localhost"
WS_PORT = 8766


class PolybotServer:
    """WS server that delegates client management to an injected Broadcaster."""

    def __init__(
        self,
        broadcaster: Broadcaster,
        host: str = WS_HOST,
        port: int = WS_PORT,
        logger: logging.Logger | None = None,
    ) -> None:
        self._broadcaster = broadcaster
        self._host = host
        self._port = port
        self._log = logger or logging.getLogger(__name__)
        self._server: websockets.WebSocketServer | None = None

    @property
    def port(self) -> int:
        if self._server is not None:
            for sock in self._server.sockets:
                return sock.getsockname()[1]
        return self._port

    async def start(self) -> None:
        self._server = await websockets.serve(self._handler, self._host, self._port)
        self._log.info("📡 Polybot WS server listening on ws://%s:%d", self._host, self.port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handler(self, ws: WebSocketServerProtocol, path: str = "/") -> None:
        self._broadcaster.add_client(ws)
        try:
            await ws.wait_closed()
        finally:
            self._broadcaster.remove_client(ws)
