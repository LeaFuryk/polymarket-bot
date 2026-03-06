"""FastAPI app with forensics endpoints and SSE stream."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from polybot.forensics.aggregate import build_report
from polybot.forensics.blocked import analyze_blocked
from polybot.forensics.context import analyze_context
from polybot.forensics.costs import analyze_costs
from polybot.forensics.db import connect
from polybot.forensics.execution import analyze_orders
from polybot.forensics.roundtrips import analyze_roundtrips
from polybot.forensics.ttl import analyze_ttl
from polybot.server.constants import (
    APP_TITLE,
    DB_ENV_VAR,
    DEFAULT_DB_PATH,
    SSE_HEADERS,
    SSE_MEDIA_TYPE,
    SSE_POLL_INTERVAL_SECONDS,
)

try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse
except ImportError as err:
    raise ImportError("FastAPI not installed. Install with: uv pip install -e '.[server]'") from err

_logger = logging.getLogger(__name__)

app = FastAPI(title=APP_TITLE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_db_path() -> str:
    return os.environ.get(DB_ENV_VAR, DEFAULT_DB_PATH)


def _serialize(obj: object) -> str:
    """Serialize Pydantic models to JSON string."""
    if hasattr(obj, "model_dump"):
        return json.dumps(obj.model_dump(), default=str)
    return json.dumps(obj, default=str)


@app.get("/api/forensics")
def get_full_report():
    """Full ForensicsReport JSON."""
    conn = connect(_get_db_path())
    try:
        report = build_report(conn, _get_db_path())
        return report.model_dump()
    finally:
        conn.close()


@app.get("/api/forensics/execution")
def get_execution():
    """Feature A: execution metrics."""
    conn = connect(_get_db_path())
    try:
        metrics, agg = analyze_orders(conn)
        return {
            "aggregate": agg.model_dump(),
            "orders": [m.model_dump() for m in metrics],
        }
    finally:
        conn.close()


@app.get("/api/forensics/ttl")
def get_ttl():
    """Feature B: TTL counterfactuals."""
    conn = connect(_get_db_path())
    try:
        cfs, agg = analyze_ttl(conn)
        return {
            "aggregate": agg.model_dump(),
            "counterfactuals": [c.model_dump() for c in cfs],
        }
    finally:
        conn.close()


@app.get("/api/forensics/costs")
def get_costs():
    """Feature C: cost breakdown."""
    conn = connect(_get_db_path())
    try:
        bds, agg = analyze_costs(conn)
        return {
            "aggregate": agg.model_dump(),
            "breakdowns": [b.model_dump() for b in bds],
        }
    finally:
        conn.close()


@app.get("/api/forensics/blocked")
def get_blocked():
    """Feature D: blocked orders."""
    conn = connect(_get_db_path())
    try:
        blocked, agg = analyze_blocked(conn)
        return {
            "aggregate": agg.model_dump(),
            "blocked": [b.model_dump() for b in blocked],
        }
    finally:
        conn.close()


@app.get("/api/forensics/roundtrips")
def get_roundtrips():
    """Feature E: round-trips."""
    conn = connect(_get_db_path())
    try:
        trips = analyze_roundtrips(conn)
        return {"roundtrips": [t.model_dump() for t in trips]}
    finally:
        conn.close()


@app.get("/api/forensics/context")
def get_context():
    """Feature F: decision contexts."""
    conn = connect(_get_db_path())
    try:
        contexts = analyze_context(conn)
        return {"contexts": [c.model_dump() for c in contexts]}
    finally:
        conn.close()


@app.get("/api/sse")
async def sse_stream():
    """SSE stream — polls DB every 2s, emits new forensics data on change."""

    async def event_generator():
        last_mtime = 0.0
        db_path = Path(_get_db_path())

        while True:
            try:
                current_mtime = db_path.stat().st_mtime if db_path.exists() else 0.0

                if current_mtime > last_mtime:
                    last_mtime = current_mtime
                    conn = connect(_get_db_path())
                    try:
                        report = build_report(conn, str(db_path))
                        data = json.dumps(report.model_dump(), default=str)
                        yield f"data: {data}\n\n"
                    finally:
                        conn.close()
            except Exception:
                _logger.exception("SSE stream error")
                yield f"data: {json.dumps({'error': 'internal error'})}\n\n"

            await asyncio.sleep(SSE_POLL_INTERVAL_SECONDS)

    return StreamingResponse(
        event_generator(),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )
