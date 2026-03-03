"""WebSocket message types and helpers for the dashboard protocol."""

from __future__ import annotations

import json

# Message types — server → client
MSG_SNAPSHOT = "snapshot"
MSG_TRADE = "trade"
MSG_RESOLUTION = "resolution"
MSG_MARKET = "market"
MSG_POSITION = "position"
MSG_STATUS = "status"

ALL_TYPES = frozenset({
    MSG_SNAPSHOT, MSG_TRADE, MSG_RESOLUTION,
    MSG_MARKET, MSG_POSITION, MSG_STATUS,
})


def make_message(msg_type: str, data: dict) -> str:
    """Serialize a typed message for transmission over WebSocket."""
    return json.dumps({"type": msg_type, "data": data})
