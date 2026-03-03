"""Shared database helpers for forensics modules."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a read-only connection to the polybot.db SQLite database."""
    p = Path(db_path)
    if not p.exists():
        print(f"Error: {p} not found. Run the bot first to accumulate data.")
        sys.exit(1)
    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    return conn


def has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table via PRAGMA table_info."""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def load_orders(conn: sqlite3.Connection) -> list[dict]:
    """Load all decisions with parsed live_order_json as _live_order.

    Returns dicts with all decision columns plus a '_live_order' key containing
    the parsed JSON (or None if absent/empty).
    """
    if not has_column(conn, "decisions", "live_order_json"):
        return []

    rows = conn.execute(
        "SELECT * FROM decisions ORDER BY timestamp"
    ).fetchall()

    results = []
    for r in rows:
        d = dict(r)
        raw = d.get("live_order_json") or ""
        if raw.strip():
            try:
                d["_live_order"] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d["_live_order"] = None
        else:
            d["_live_order"] = None
        results.append(d)
    return results


def load_snapshots_for_candle(conn: sqlite3.Connection, candle_id: int) -> list[dict]:
    """Load all per-second snapshots for a candle, ordered by timestamp."""
    rows = conn.execute(
        "SELECT * FROM snapshots WHERE candle_id = ? ORDER BY timestamp",
        (candle_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def load_snapshots_in_window(
    conn: sqlite3.Connection, candle_id: int, start_ts: float, end_ts: float
) -> list[dict]:
    """Load snapshots within a time window for a specific candle."""
    rows = conn.execute(
        "SELECT * FROM snapshots WHERE candle_id = ? AND timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
        (candle_id, start_ts, end_ts),
    ).fetchall()
    return [dict(r) for r in rows]


def load_candles(conn: sqlite3.Connection) -> list[dict]:
    """Load all candles ordered by candle_id."""
    rows = conn.execute("SELECT * FROM candles ORDER BY candle_id").fetchall()
    return [dict(r) for r in rows]
