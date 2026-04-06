"""Port: session summary persistence."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SessionStore(Protocol):
    """Persists session summaries."""

    async def save_session(self, summary: dict) -> None: ...
