# server/

FastAPI application serving the Polybot forensics dashboard API.

## Architecture

```
run.py          CLI entry point (argparse → uvicorn)
app.py          FastAPI app, route handlers, SSE stream
constants.py    Magic numbers and configuration defaults
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/forensics` | Full forensics report |
| GET | `/api/forensics/execution` | Execution metrics (Feature A) |
| GET | `/api/forensics/ttl` | TTL counterfactuals (Feature B) |
| GET | `/api/forensics/costs` | Cost breakdown (Feature C) |
| GET | `/api/forensics/blocked` | Blocked orders (Feature D) |
| GET | `/api/forensics/roundtrips` | Round-trips (Feature E) |
| GET | `/api/forensics/context` | Decision contexts (Feature F) |
| GET | `/api/sse` | SSE stream — polls DB, emits on change |

## SSE Stream

The `/api/sse` endpoint polls the SQLite database file every 2 seconds.
When the file's mtime changes, it builds a fresh `ForensicsReport` and
emits it as a Server-Sent Event. The dashboard-next frontend consumes
this stream for real-time updates.

## Running

```bash
# Install server extras
uv pip install -e '.[server]'

# Start server
polybot-server --db logs/polybot.db --host 0.0.0.0 --port 8888
```

## Dependencies

FastAPI and uvicorn are **optional** (`[server]` extras). The rest of
the polybot package works without them.
