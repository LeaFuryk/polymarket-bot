"""WebSocket server lifecycle — start, stop, client handler."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import websockets

from polybot.ws.broadcaster import Broadcaster
from polybot.ws.constants import DEFAULT_WS_HOST, DEFAULT_WS_PORT, PING_INTERVAL_SECONDS, PING_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol

    from polybot.agent.context import AgentContext


class DashboardWSServer:
    """Async WebSocket server for pushing live dashboard state to clients."""

    def __init__(
        self,
        broadcaster: Broadcaster,
        ctx: AgentContext,
        logger: logging.Logger,
        host: str = DEFAULT_WS_HOST,
        port: int = DEFAULT_WS_PORT,
    ) -> None:
        self._broadcaster = broadcaster
        self._host = host
        self._port = port
        self._logger = logger
        self._server: websockets.WebSocketServer | None = None
        self._ctx = ctx

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._server = await websockets.serve(
            self._handler,
            self._host,
            self._port,
            ping_interval=PING_INTERVAL_SECONDS,
            ping_timeout=PING_TIMEOUT_SECONDS,
        )
        self._logger.info("WS server started on port %d", self._port)

    async def stop(self) -> None:
        """Gracefully shut down the server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._logger.info("WS server stopped")

    def _build_initial_snapshot(self) -> str:
        """Build a full dashboard snapshot message for newly connected clients."""
        from polybot.agent.dashboard import build_snapshot_message

        return build_snapshot_message(self._ctx, log=self._logger)

    async def _handler(self, ws: WebSocketServerProtocol, path: str = "") -> None:
        """Handle a single WebSocket client connection."""
        self._broadcaster.add_client(ws)
        try:
            # Send initial full snapshot on connect
            try:
                await ws.send(self._build_initial_snapshot())
            except Exception:
                self._logger.debug("Failed to send initial snapshot", exc_info=True)

            # Keep connection alive — listen for client messages (unused for now)
            async for _msg in ws:
                pass  # clients don't send meaningful messages yet
        except websockets.ConnectionClosed:
            pass
        except Exception:
            self._logger.debug("WS handler error", exc_info=True)
        finally:
            self._broadcaster.remove_client(ws)
