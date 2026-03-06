# ws/

WebSocket dashboard server — pushes live trading state to the Next.js frontend.

## Architecture

```
protocol.py     Message types (snapshot, trade, resolution, market, position, status)
broadcaster.py  Client set management + message builders from agent state
server.py       WebSocket server lifecycle (start, stop, handler)
constants.py    Default host, port, ping settings
```

## Message Types

| Type | Direction | Description |
|------|-----------|-------------|
| `snapshot` | server → client | Full agent state on connect |
| `trade` | server → client | Immediate push on trade execution |
| `resolution` | server → client | Immediate push on candle resolution |
| `market` | server → client | Market price + countdown (every 1s) |
| `position` | server → client | Position shares + P&L (every 1s) |
| `status` | server → client | Tech metrics, risk state (every 2s) |

## Protocol

All messages are JSON with the structure:
```json
{"type": "<message_type>", "data": { ... }}
```

## Connection Lifecycle

1. Client connects via `ws://host:8765`
2. Server sends initial `snapshot` message
3. Server pushes `market` and `position` updates every second
4. Server pushes `status` updates every 2 seconds
5. `trade` and `resolution` events are pushed immediately when they occur
6. Dead connections are automatically cleaned up during broadcasts
