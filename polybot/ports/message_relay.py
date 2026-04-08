"""Port: message relay interface for broadcasting to downstream consumers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MessageRelay(Protocol):
    """Broadcasts messages to downstream consumers (e.g. dashboard)."""

    async def broadcast_json(self, data: dict) -> None: ...
