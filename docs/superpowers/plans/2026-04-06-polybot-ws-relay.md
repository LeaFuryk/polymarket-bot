# Polybot WebSocket Relay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polybot connects to the data collector's WS, logs every message to console, and re-broadcasts on its own WS server for downstream consumers (Next.js dashboard).

**Architecture:** Hexagonal — `MessageRelay` protocol (port) defines the broadcast contract. `Broadcaster` (adapter) implements it over WebSocket. `PolybotServer` owns WS lifecycle and delegates client management to `Broadcaster`. `CollectorClient` depends on `MessageRelay` port, not the concrete adapter. `__main__.py` wires them together.

**Tech Stack:** Python 3.11, websockets, asyncio, pytest

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `polybot/ports/message_relay.py` | Create | Protocol defining `broadcast_json()` contract |
| `polybot/ws/__init__.py` | Create | Package init, re-export public names |
| `polybot/ws/broadcaster.py` | Create | `Broadcaster` — implements `MessageRelay`, manages WS clients |
| `polybot/ws/server.py` | Create | `PolybotServer` — WS lifecycle on port 8766, delegates to `Broadcaster` |
| `polybot/adapters/collector_client.py` | Modify | Accept `MessageRelay` port, forward messages + log |
| `polybot/__main__.py` | Modify | Wire broadcaster → server + client |
| `tests/polybot/__init__.py` | Create | Test package init |
| `tests/polybot/test_broadcaster.py` | Create | Test broadcast logic |
| `tests/polybot/test_server.py` | Create | Test server + broadcaster integration |
| `tests/polybot/test_collector_client.py` | Create | Test client forwards to relay |

---

### Task 1: Create MessageRelay port

**Files:**
- Create: `polybot/ports/message_relay.py`

- [ ] **Step 1: Create the port**

```python
"""Port: message relay interface for broadcasting to downstream consumers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MessageRelay(Protocol):
    """Broadcasts messages to downstream consumers (e.g. dashboard)."""

    async def broadcast_json(self, data: dict) -> None: ...
```

- [ ] **Step 2: Update ports __init__.py**

Add re-export in `polybot/ports/__init__.py` if it exists, or leave as-is if the convention is direct imports.

- [ ] **Step 3: Commit**

```bash
git add polybot/ports/message_relay.py
git commit -m "feat(polybot): add MessageRelay port for downstream broadcasting"
```

---

### Task 2: Create Broadcaster adapter

**Files:**
- Create: `polybot/ws/__init__.py`
- Create: `polybot/ws/broadcaster.py`
- Create: `tests/polybot/__init__.py`
- Create: `tests/polybot/test_broadcaster.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for Broadcaster."""

import json

import pytest
from unittest.mock import AsyncMock

from polybot.ports.message_relay import MessageRelay
from polybot.ws.broadcaster import Broadcaster


class TestBroadcaster:
    def test_implements_message_relay(self):
        assert isinstance(Broadcaster(), MessageRelay)

    async def test_broadcast_sends_to_client(self):
        bc = Broadcaster()
        ws = AsyncMock()
        bc.add_client(ws)
        await bc.broadcast("hello")
        ws.send.assert_awaited_once_with("hello")

    async def test_broadcast_sends_to_multiple_clients(self):
        bc = Broadcaster()
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        bc.add_client(ws1)
        bc.add_client(ws2)
        await bc.broadcast("msg")
        ws1.send.assert_awaited_once_with("msg")
        ws2.send.assert_awaited_once_with("msg")

    async def test_broadcast_removes_dead_client(self):
        import websockets
        bc = Broadcaster()
        ws = AsyncMock()
        ws.send.side_effect = websockets.ConnectionClosed(None, None)
        bc.add_client(ws)
        await bc.broadcast("msg")
        assert bc.client_count == 0

    async def test_broadcast_no_clients_is_safe(self):
        bc = Broadcaster()
        await bc.broadcast("msg")  # no error

    async def test_broadcast_json(self):
        bc = Broadcaster()
        ws = AsyncMock()
        bc.add_client(ws)
        await bc.broadcast_json({"type": "snapshot", "btc_price": 69000.0})
        raw = ws.send.call_args[0][0]
        msg = json.loads(raw)
        assert msg["type"] == "snapshot"

    def test_client_count(self):
        bc = Broadcaster()
        ws = AsyncMock()
        assert bc.client_count == 0
        bc.add_client(ws)
        assert bc.client_count == 1
        bc.remove_client(ws)
        assert bc.client_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_broadcaster.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement Broadcaster**

Create `polybot/ws/__init__.py`:
```python
"""WebSocket package — broadcaster and server."""
```

Create `tests/polybot/__init__.py`: empty file.

Create `polybot/ws/broadcaster.py`:
```python
"""Adapter: WebSocket broadcaster — implements MessageRelay port."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import websockets

if TYPE_CHECKING:
    from websockets.server import WebSocketServerProtocol


class Broadcaster:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/polybot/test_broadcaster.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add polybot/ws/ tests/polybot/
git commit -m "feat(polybot): add Broadcaster adapter implementing MessageRelay"
```

---

### Task 3: Create PolybotServer

**Files:**
- Create: `polybot/ws/server.py`
- Create: `tests/polybot/test_server.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for PolybotServer."""

import asyncio
import json

import pytest
import websockets

from polybot.ws.broadcaster import Broadcaster
from polybot.ws.server import PolybotServer


class TestPolybotServer:
    async def test_client_receives_broadcast(self):
        bc = Broadcaster()
        server = PolybotServer(bc, port=0)
        await server.start()
        try:
            async with websockets.connect(f"ws://localhost:{server.port}") as ws:
                await asyncio.sleep(0.05)  # let handler register client
                await bc.broadcast_json({"type": "snapshot", "btc_price": 69000.0})
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                msg = json.loads(raw)
                assert msg["type"] == "snapshot"
                assert msg["btc_price"] == 69000.0
        finally:
            await server.stop()

    async def test_start_stop_no_clients(self):
        bc = Broadcaster()
        server = PolybotServer(bc, port=0)
        await server.start()
        assert server.port > 0
        await server.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_server.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement PolybotServer**

Create `polybot/ws/server.py`:
```python
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
```

Update `polybot/ws/__init__.py`:
```python
"""WebSocket package — broadcaster and server."""

from polybot.ws.broadcaster import Broadcaster
from polybot.ws.server import PolybotServer

__all__ = ["Broadcaster", "PolybotServer"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/polybot/test_server.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add polybot/ws/server.py polybot/ws/__init__.py tests/polybot/test_server.py
git commit -m "feat(polybot): add PolybotServer with injected Broadcaster"
```

---

### Task 4: Inject MessageRelay into CollectorClient

**Files:**
- Modify: `polybot/adapters/collector_client.py`
- Create: `tests/polybot/test_collector_client.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for CollectorClient with MessageRelay integration."""

import json

import pytest
from unittest.mock import AsyncMock

from polybot.adapters.collector_client import CollectorClient


class TestCollectorClientRelay:
    async def test_snapshot_forwarded_to_relay(self):
        relay = AsyncMock()
        client = CollectorClient(relay=relay)
        msg = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(msg))
        relay.broadcast_json.assert_awaited_once_with(msg)

    async def test_candle_close_forwarded_to_relay(self):
        relay = AsyncMock()
        client = CollectorClient(relay=relay)
        msg = {"type": "candle_close", "candle_id": "test-123", "outcome": "UP"}
        await client._handle_message(json.dumps(msg))
        relay.broadcast_json.assert_awaited_once_with(msg)

    async def test_no_relay_still_works(self):
        client = CollectorClient()
        msg = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(msg))
        assert client.snapshot == msg

    async def test_properties_updated_with_relay(self):
        relay = AsyncMock()
        client = CollectorClient(relay=relay)
        snap = {"type": "snapshot", "btc_price": 69000.0}
        await client._handle_message(json.dumps(snap))
        assert client.snapshot == snap

        candle = {"type": "candle_close", "candle_id": "x", "outcome": "DOWN"}
        await client._handle_message(json.dumps(candle))
        assert client.candle_close == candle

    async def test_unknown_message_type_still_relayed(self):
        relay = AsyncMock()
        client = CollectorClient(relay=relay)
        msg = {"type": "unknown", "data": 123}
        await client._handle_message(json.dumps(msg))
        relay.broadcast_json.assert_awaited_once_with(msg)
        assert client.snapshot is None
        assert client.candle_close is None

    async def test_malformed_json_raises(self):
        client = CollectorClient()
        with pytest.raises(json.JSONDecodeError):
            await client._handle_message("not json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/polybot/test_collector_client.py -v`
Expected: FAIL — `_handle_message` does not exist, `relay` param not accepted

- [ ] **Step 3: Implement — refactor CollectorClient to use MessageRelay port**

Update `polybot/adapters/collector_client.py`:
```python
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
        msg = json.loads(raw)
        msg_type = msg.get("type")
        if msg_type == "snapshot":
            self._latest_snapshot = msg
            self._log.info(
                "📊 BTC $%,.2f | YES %.2f | NO %.2f | elapsed %.0f%% | %s",
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
            await self._relay.broadcast_json(msg)

    async def stop(self) -> None:
        self._running = False

    @property
    def snapshot(self) -> dict | None:
        return self._latest_snapshot

    @property
    def candle_close(self) -> dict | None:
        return self._latest_candle_close
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/polybot/test_collector_client.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add polybot/adapters/collector_client.py tests/polybot/test_collector_client.py
git commit -m "feat(polybot): CollectorClient depends on MessageRelay port"
```

---

### Task 5: Wire everything in __main__.py

**Files:**
- Modify: `polybot/__main__.py`

- [ ] **Step 1: Rewrite __main__.py**

```python
"""Bot entry point — connects to collector WS, logs data, re-broadcasts on port 8766."""

import asyncio
import logging

from polybot.adapters.collector_client import CollectorClient
from polybot.ws import Broadcaster, PolybotServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


async def main() -> None:
    broadcaster = Broadcaster()
    server = PolybotServer(broadcaster)
    await server.start()

    client = CollectorClient(relay=broadcaster)

    try:
        await client.run()
    finally:
        await client.stop()
        await server.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All pass

- [ ] **Step 3: Lint**

Run: `uv run ruff check .`
Expected: No errors

- [ ] **Step 4: Manual smoke test**

With the collector running:
```bash
uv run python -m polybot
```

Expected:
- `📡 Polybot WS server listening on ws://localhost:8766`
- `Connected to collector at ws://localhost:8765`
- `Candle closed: ... outcome=UP/DOWN` at 5-min boundaries

Verify relay:
```bash
python -c "import asyncio, websockets, json
async def test():
    async with websockets.connect('ws://localhost:8766') as ws:
        msg = json.loads(await ws.recv())
        print(msg['type'], msg.get('btc_price', ''))
asyncio.run(test())"
```

- [ ] **Step 5: Commit**

```bash
git add polybot/__main__.py
git commit -m "feat(polybot): wire MessageRelay → Broadcaster → server + client"
```
