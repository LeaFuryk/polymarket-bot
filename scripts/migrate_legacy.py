"""Migrate legacy market_history.db to a single JSONL file.

Each line is a CandleRecord with its Snapshots nested inside:
  { "candle_id": ..., "open": ..., ..., "snapshots": [ {...}, ... ] }

Reads from legacy/data/market_history.db, writes to data/legacy_candles.jsonl.

Usage:
    uv run python scripts/migrate_legacy.py [--db PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path

LEGACY_DB = Path("legacy/data/market_history.db")
OUT_PATH = Path("data/legacy_candles.jsonl")


def build_snapshots(
    cur: sqlite3.Cursor,
    candles: dict[int, dict],
) -> dict[int, list[dict]]:
    """Read legacy snapshots, group by legacy candle_id."""
    cur.execute(
        "SELECT candle_id, timestamp, time_remaining, "
        "up_best_bid, up_best_ask, up_bid_depth, up_ask_depth, "
        "down_best_bid, down_best_ask, down_bid_depth, down_ask_depth, "
        "btc_price "
        "FROM market_snapshots ORDER BY candle_id, timestamp"
    )
    grouped: dict[int, list[dict]] = defaultdict(list)
    for row in cur.fetchall():
        (
            legacy_cid,
            ts,
            time_remaining,
            ub_bid,
            ub_ask,
            ub_depth,
            ua_depth,
            db_bid,
            db_ask,
            db_depth,
            da_depth,
            btc,
        ) = row

        candle = candles.get(legacy_cid)
        if candle is None:
            continue

        duration = candle["end_time"] - candle["start_time"]
        elapsed_pct = max(0.0, min(1.0 - time_remaining / duration, 1.0)) if duration > 0 else 0.0

        up_bids = [[ub_bid, ub_depth]] if ub_bid is not None else []
        up_asks = [[ub_ask, ua_depth]] if ub_ask is not None else []
        down_bids = [[db_bid, db_depth]] if db_bid is not None else []
        down_asks = [[db_ask, da_depth]] if db_ask is not None else []

        market_volume = sum(v for v in (ub_depth, ua_depth, db_depth, da_depth) if v is not None)

        grouped[legacy_cid].append(
            {
                "timestamp": ts,
                "tick_timestamp": ts,
                "elapsed_pct": round(elapsed_pct, 6),
                "btc_price": btc,
                "btc_bid": btc,
                "btc_ask": btc,
                "up_bids": up_bids,
                "up_asks": up_asks,
                "down_bids": down_bids,
                "down_asks": down_asks,
                "up_last_trade": None,
                "down_last_trade": None,
                "market_volume": market_volume,
            }
        )
    return grouped


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate legacy market_history.db to JSONL")
    parser.add_argument("--db", type=Path, default=LEGACY_DB, help="Path to legacy SQLite DB")
    parser.add_argument("--out", type=Path, default=OUT_PATH, help="Output JSONL path")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")

    conn = sqlite3.connect(str(args.db))
    cur = conn.cursor()

    # Load candles, skip incomplete ones
    cur.execute(
        "SELECT candle_id, slug, start_time, end_time, btc_open, btc_close, winner "
        "FROM market_candles "
        "WHERE winner IS NOT NULL AND btc_open IS NOT NULL AND btc_close IS NOT NULL"
    )
    candles: dict[int, dict] = {}
    for row in cur.fetchall():
        legacy_id, slug, start, end, op, cl, winner = row
        candles[legacy_id] = {
            "candle_id": slug,
            "start_time": start,
            "end_time": end,
            "open": op,
            "high": max(op, cl),
            "low": min(op, cl),
            "close": cl,
            "volume": 0.0,
            "outcome": winner.upper(),
            "final_ret": math.log(cl / op) if op > 0 else 0.0,
        }

    # Load and group snapshots
    grouped = build_snapshots(cur, candles)
    conn.close()

    # Write single JSONL: one candle per line with nested snapshots
    args.out.parent.mkdir(parents=True, exist_ok=True)
    total_snaps = 0
    with open(args.out, "w") as f:
        for legacy_id, candle in candles.items():
            snaps = grouped.get(legacy_id, [])
            total_snaps += len(snaps)
            record = {**candle, "snapshots": snaps}
            f.write(json.dumps(record) + "\n")

    print(f"Wrote {len(candles)} candles ({total_snaps} snapshots) to {args.out}")


if __name__ == "__main__":
    main()
