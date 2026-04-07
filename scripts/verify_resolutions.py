"""Verify all candles against Polymarket's Gamma API resolution.

Updates open, close, outcome, final_ret in the DB if they differ from Polymarket.

Usage:
    uv run python scripts/verify_resolutions.py
    uv run python scripts/verify_resolutions.py --dry-run   # show diffs without updating
"""

from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import sys

import httpx

DB_PATH = "data/collection.db"
GAMMA_HOST = "https://gamma-api.polymarket.com"
BATCH_SIZE = 10  # concurrent requests per batch
BATCH_DELAY = 0.5  # seconds between batches


async def get_resolution(client: httpx.AsyncClient, slug: str) -> dict | None:
    try:
        resp = await client.get("/events", params={"slug": slug})
        resp.raise_for_status()
        events = resp.json()
        if not events:
            return None

        event = events[0]
        meta = event.get("eventMetadata", {})
        if isinstance(meta, str):
            meta = json.loads(meta)

        price_to_beat = meta.get("priceToBeat")
        final_price = meta.get("finalPrice")
        if price_to_beat is None or final_price is None:
            return None

        mkt = event.get("markets", [{}])[0]
        outcome_prices = mkt.get("outcomePrices", "[]")
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)

        if len(outcome_prices) < 2:
            return None

        up_price = float(outcome_prices[0])
        outcome = "UP" if up_price > 0.5 else "DOWN"

        return {
            "open": float(price_to_beat),
            "close": float(final_price),
            "outcome": outcome,
        }
    except Exception as e:
        print(f"  ERROR fetching {slug}: {e}")
        return None


async def main() -> None:
    dry_run = "--dry-run" in sys.argv

    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT candle_id, open, close, outcome, final_ret FROM candles ORDER BY start_time").fetchall()
    print(f"Checking {len(rows)} candles against Polymarket...")
    if dry_run:
        print("(DRY RUN — no updates)")

    mismatches = 0
    no_resolution = 0
    checked = 0

    async with httpx.AsyncClient(base_url=GAMMA_HOST, timeout=10.0) as client:
        for batch_start in range(0, len(rows), BATCH_SIZE):
            batch = rows[batch_start : batch_start + BATCH_SIZE]

            tasks = []
            for candle_id, db_open, db_close, db_outcome, db_ret in batch:
                tasks.append((candle_id, db_open, db_close, db_outcome, db_ret, get_resolution(client, candle_id)))

            results = await asyncio.gather(*[t[5] for t in tasks])

            for (candle_id, db_open, db_close, db_outcome, _db_ret, _), resolution in zip(tasks, results, strict=False):
                checked += 1

                if resolution is None:
                    no_resolution += 1
                    continue

                pm_open = resolution["open"]
                pm_close = resolution["close"]
                pm_outcome = resolution["outcome"]

                outcome_diff = pm_outcome != db_outcome
                open_diff = abs(pm_open - db_open) > 0.01
                close_diff = abs(pm_close - db_close) > 0.01

                if not outcome_diff and not open_diff and not close_diff:
                    continue

                mismatches += 1
                final_ret = math.log(pm_close / pm_open) if pm_open > 0 else 0.0

                changes = []
                if outcome_diff:
                    changes.append(f"outcome: {db_outcome}→{pm_outcome}")
                if open_diff:
                    changes.append(f"open: ${db_open:.2f}→${pm_open:.2f}")
                if close_diff:
                    changes.append(f"close: ${db_close:.2f}→${pm_close:.2f}")

                print(f"  {candle_id}: {', '.join(changes)}")

                if not dry_run:
                    conn.execute(
                        "UPDATE candles SET open = ?, close = ?, outcome = ?, final_ret = ? WHERE candle_id = ?",
                        (pm_open, pm_close, pm_outcome, final_ret, candle_id),
                    )

            if not dry_run and mismatches > 0:
                conn.commit()

            if batch_start + BATCH_SIZE < len(rows):
                await asyncio.sleep(BATCH_DELAY)

            # Progress
            pct = checked / len(rows) * 100
            if checked % 100 == 0 or checked == len(rows):
                print(f"  [{checked}/{len(rows)} ({pct:.0f}%)] mismatches={mismatches} no_resolution={no_resolution}")

    if not dry_run:
        conn.commit()
    conn.close()

    print(f"\nDone. Checked: {checked}, Mismatches fixed: {mismatches}, No resolution: {no_resolution}")


if __name__ == "__main__":
    asyncio.run(main())
