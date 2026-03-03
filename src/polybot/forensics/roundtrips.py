"""Feature E: Entry-to-exit round-trip pairing with PnL and excursion analysis."""

from __future__ import annotations

import sqlite3
from collections import deque

from .db import load_candles, load_orders, load_snapshots_for_candle
from .types import RoundTrip


def analyze_roundtrips(conn: sqlite3.Connection) -> list[RoundTrip]:
    """FIFO pair BUY entries with SELL exits to form round-trips."""
    rows = load_orders(conn)

    # Build candle_id → candle map
    candles = load_candles(conn)
    candle_map: dict[int, dict] = {c["candle_id"]: c for c in candles}

    # Separate filled BUYs and SELLs by token_side
    buys: dict[str, deque[dict]] = {}  # token_side → deque of BUY decisions
    sells: list[dict] = []

    for d in rows:
        action = d.get("action", "")
        fill_price = d.get("fill_price")
        fill_size = d.get("fill_size")
        token_side = d.get("token_side", "")

        if not fill_price or not fill_size or fill_size <= 0:
            continue

        if action == "BUY" and token_side:
            if token_side not in buys:
                buys[token_side] = deque()
            buys[token_side].append(d)
        elif action == "SELL" and token_side:
            sells.append(d)

    trips: list[RoundTrip] = []

    for sell in sells:
        token_side = sell.get("token_side", "")
        if token_side not in buys or not buys[token_side]:
            continue

        buy = buys[token_side].popleft()  # FIFO

        entry_price = buy.get("fill_price", 0.0)
        exit_price = sell.get("fill_price", 0.0)
        size = min(buy.get("fill_size", 0.0), sell.get("fill_size", 0.0))
        entry_ts = buy.get("timestamp", 0.0)
        exit_ts = sell.get("timestamp", 0.0)
        hold_duration_s = exit_ts - entry_ts

        # PnL: for tokens, profit = (exit - entry) * size
        realized_pnl = (exit_price - entry_price) * size

        entry_candle_id = buy.get("candle_id", 0)
        exit_candle_id = sell.get("candle_id", 0)

        # Load snapshots between entry and exit for MFE/MAE
        # Collect all snapshots from candles in the hold window
        candle_ids = set()
        for cid, candle in candle_map.items():
            if candle.get("start_time", 0) <= exit_ts and candle.get("end_time", float("inf")) >= entry_ts:
                candle_ids.add(cid)
        if entry_candle_id:
            candle_ids.add(entry_candle_id)
        if exit_candle_id:
            candle_ids.add(exit_candle_id)

        all_snaps = []
        for cid in sorted(candle_ids):
            all_snaps.extend(load_snapshots_for_candle(conn, cid))

        # Filter to hold window
        hold_snaps = [s for s in all_snaps if entry_ts <= s["timestamp"] <= exit_ts]

        # Compute mid prices during hold
        mids = []
        mid_times = []
        for snap in hold_snaps:
            if token_side == "UP":
                mid = snap.get("up_mid")
            elif token_side == "DOWN":
                mid = snap.get("down_mid")
            else:
                mid = None
            if mid is not None:
                mids.append(mid)
                mid_times.append(snap["timestamp"])

        if mids:
            mfe = max(mids)  # Best price during hold
            mae = min(mids)  # Worst price during hold
            mfe_idx = mids.index(mfe)
            entry_to_mfe_s = mid_times[mfe_idx] - entry_ts if mid_times else 0.0
        else:
            mfe = entry_price
            mae = entry_price
            entry_to_mfe_s = 0.0

        # Exit efficiency: how much of the max potential did we capture?
        mfe_potential = (mfe - entry_price) * size
        if mfe_potential > 0:
            exit_efficiency = realized_pnl / mfe_potential
        else:
            exit_efficiency = 0.0 if realized_pnl <= 0 else 1.0

        trips.append(RoundTrip(
            entry_candle_id=entry_candle_id,
            exit_candle_id=exit_candle_id,
            side=token_side,
            entry_price=entry_price,
            exit_price=exit_price,
            size=size,
            hold_duration_s=hold_duration_s,
            realized_pnl=realized_pnl,
            mfe=mfe,
            mae=mae,
            entry_to_mfe_s=entry_to_mfe_s,
            exit_efficiency=exit_efficiency,
        ))

    return trips
