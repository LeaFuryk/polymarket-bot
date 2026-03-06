"""DataStore — SQLite analytics store with non-blocking async queue and batched writes."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from pathlib import Path

from polybot.datastore.constants import (
    FLUSH_BATCH_SIZE,
    FLUSH_INTERVAL_SECONDS,
    JOURNAL_MODE,
    SYNCHRONOUS_MODE,
)
from polybot.datastore.rows import DecisionRow, SnapshotRow

_default_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    candle_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id  TEXT    NOT NULL,
    slug          TEXT    NOT NULL,
    title         TEXT    NOT NULL DEFAULT '',
    start_time    REAL    NOT NULL,
    end_time      REAL    NOT NULL,
    btc_open      REAL,
    btc_close     REAL,
    winner        TEXT,
    resolution_pnl REAL,
    UNIQUE(condition_id)
);

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    candle_id         INTEGER NOT NULL REFERENCES candles(candle_id),
    timestamp         REAL    NOT NULL,
    time_remaining    REAL    NOT NULL,

    up_best_bid       REAL,
    up_best_ask       REAL,
    up_mid            REAL,
    up_spread_pct     REAL,
    up_bid_depth      REAL,
    up_ask_depth      REAL,

    down_best_bid     REAL,
    down_best_ask     REAL,
    down_mid          REAL,
    down_spread_pct   REAL,
    down_bid_depth    REAL,
    down_ask_depth    REAL,

    rr_up             REAL,
    rr_down           REAL,

    btc_price         REAL,
    btc_move_from_open REAL,

    streak            INTEGER,
    streak_direction  TEXT,

    prefilter_passed  INTEGER,
    prefilter_reasons TEXT,

    indicators_json   TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    candle_id      INTEGER NOT NULL REFERENCES candles(candle_id),
    timestamp      REAL    NOT NULL,
    cycle          INTEGER NOT NULL,
    trigger_type   TEXT    NOT NULL DEFAULT 'entry',

    action         TEXT    NOT NULL,
    token_side     TEXT,
    confidence     REAL,
    reasoning      TEXT,
    market_view    TEXT,
    decision_size  REAL,

    fill_price     REAL,
    fill_size      REAL,
    slippage_bps   REAL,
    fee_amount     REAL,

    risk_blocked   INTEGER,
    risk_reason    TEXT,

    cash           REAL,
    portfolio_value REAL,
    up_shares      REAL,
    down_shares    REAL,

    ai_cost        REAL,
    ai_latency_ms  REAL,

    indicators_json TEXT,
    live_order_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_candle ON snapshots(candle_id);
CREATE INDEX IF NOT EXISTS idx_decisions_candle ON decisions(candle_id);
CREATE INDEX IF NOT EXISTS idx_candles_slug ON candles(slug);
"""


class DataStore:
    """SQLite analytics store with non-blocking async queue and batched writes."""

    def __init__(
        self,
        db_path: str | Path,
        logger: logging.Logger | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._queue: asyncio.Queue[SnapshotRow | DecisionRow] = asyncio.Queue()
        self._current_candle_id: int | None = None
        self._pending_items: list[SnapshotRow | DecisionRow] = []
        self._logger = logger or _default_logger

    # --- Lifecycle ---

    def open(self) -> None:
        """Connect to SQLite, create tables, enable WAL mode."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute(f"PRAGMA journal_mode={JOURNAL_MODE}")
        self._conn.execute(f"PRAGMA synchronous={SYNCHRONOUS_MODE}")
        self._conn.executescript(_SCHEMA)
        # Migrate: add live_order_json column if missing (v0.14.5+)
        try:
            self._conn.execute("ALTER TABLE decisions ADD COLUMN live_order_json TEXT")
            self._conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists
        self._conn.commit()
        self._logger.info("DataStore opened: %s (WAL mode)", self._db_path)

    async def close(self) -> None:
        """Flush remaining queue items and close connection."""
        if self._conn is None:
            return
        # Final flush
        await self._flush()
        self._conn.close()
        self._conn = None
        self._logger.info("DataStore closed")

    # --- Candle lifecycle (called from RotationLoop, infrequent) ---

    def begin_candle(
        self,
        condition_id: str,
        slug: str,
        title: str,
        start_time: float,
        end_time: float,
        btc_open: float | None,
    ) -> int | None:
        """Insert or find a candle row. Returns candle_id."""
        if self._conn is None:
            return None
        try:
            cur = self._conn.execute(
                """INSERT OR IGNORE INTO candles
                   (condition_id, slug, title, start_time, end_time, btc_open)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (condition_id, slug, title, start_time, end_time, btc_open),
            )
            self._conn.commit()

            if cur.lastrowid and cur.lastrowid > 0:
                self._current_candle_id = cur.lastrowid
            else:
                # Already existed — look it up
                row = self._conn.execute(
                    "SELECT candle_id FROM candles WHERE condition_id = ?",
                    (condition_id,),
                ).fetchone()
                self._current_candle_id = row[0] if row else None

            self._logger.info(
                "DataStore: begin_candle id=%s slug=%s",
                self._current_candle_id,
                slug,
            )
            return self._current_candle_id
        except Exception:
            self._logger.exception("DataStore: begin_candle failed")
            return None

    def resolve_candle(
        self,
        candle_id: int,
        btc_close: float,
        winner: str,
        resolution_pnl: float,
    ) -> None:
        """Update candle with resolution data."""
        if self._conn is None:
            return
        try:
            self._conn.execute(
                """UPDATE candles
                   SET btc_close = ?, winner = ?, resolution_pnl = ?
                   WHERE candle_id = ?""",
                (btc_close, winner, resolution_pnl, candle_id),
            )
            self._conn.commit()
            self._logger.info(
                "DataStore: resolve_candle id=%d winner=%s pnl=%.4f",
                candle_id,
                winner,
                resolution_pnl,
            )
        except Exception:
            self._logger.exception("DataStore: resolve_candle failed")

    @property
    def current_candle_id(self) -> int | None:
        return self._current_candle_id

    # --- Non-blocking queue API (called from hot loops) ---

    def queue_snapshot(self, row: SnapshotRow) -> None:
        """Enqueue a snapshot row for batched insert. Non-blocking."""
        try:
            self._queue.put_nowait(row)
        except asyncio.QueueFull:
            self._logger.warning("DataStore: snapshot queue full, dropping row")

    def queue_decision(self, row: DecisionRow) -> None:
        """Enqueue a decision row for batched insert. Non-blocking."""
        try:
            self._queue.put_nowait(row)
        except asyncio.QueueFull:
            self._logger.warning("DataStore: decision queue full, dropping row")

    # --- Background writer task ---

    async def writer_loop(self) -> None:
        """Async task: drain queue and batch-insert every N seconds or N rows."""
        self._logger.info("DataStore writer_loop started")
        last_flush = time.monotonic()

        while True:
            try:
                # Wait for at least one item or timeout
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=FLUSH_INTERVAL_SECONDS)
                    self._pending_items.append(item)
                except TimeoutError:
                    pass
                except asyncio.CancelledError:
                    raise

                # Drain any additional items that are ready
                while not self._queue.empty():
                    try:
                        item = self._queue.get_nowait()
                        self._pending_items.append(item)
                    except asyncio.QueueEmpty:
                        break

                now = time.monotonic()
                elapsed = now - last_flush
                if len(self._pending_items) >= FLUSH_BATCH_SIZE or elapsed >= FLUSH_INTERVAL_SECONDS:
                    await self._flush()
                    last_flush = time.monotonic()

            except asyncio.CancelledError:
                # Final flush on cancellation
                await self._flush()
                self._logger.info("DataStore writer_loop stopped")
                return
            except Exception:
                self._logger.exception("DataStore writer_loop error")
                await asyncio.sleep(1.0)

    async def _flush(self) -> None:
        """Drain queue and batch-insert all pending rows."""
        # Drain anything still in the queue
        while not self._queue.empty():
            try:
                self._pending_items.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not self._pending_items or self._conn is None:
            return

        snapshots = [r for r in self._pending_items if isinstance(r, SnapshotRow)]
        decisions = [r for r in self._pending_items if isinstance(r, DecisionRow)]
        self._pending_items.clear()

        try:
            if snapshots:
                self._conn.executemany(
                    """INSERT INTO snapshots (
                        candle_id, timestamp, time_remaining,
                        up_best_bid, up_best_ask, up_mid, up_spread_pct,
                        up_bid_depth, up_ask_depth,
                        down_best_bid, down_best_ask, down_mid, down_spread_pct,
                        down_bid_depth, down_ask_depth,
                        rr_up, rr_down,
                        btc_price, btc_move_from_open,
                        streak, streak_direction,
                        prefilter_passed, prefilter_reasons,
                        indicators_json
                    ) VALUES (
                        ?, ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?,
                        ?, ?,
                        ?, ?,
                        ?, ?,
                        ?, ?,
                        ?
                    )""",
                    [
                        (
                            s.candle_id,
                            s.timestamp,
                            s.time_remaining,
                            s.up_best_bid,
                            s.up_best_ask,
                            s.up_mid,
                            s.up_spread_pct,
                            s.up_bid_depth,
                            s.up_ask_depth,
                            s.down_best_bid,
                            s.down_best_ask,
                            s.down_mid,
                            s.down_spread_pct,
                            s.down_bid_depth,
                            s.down_ask_depth,
                            s.rr_up,
                            s.rr_down,
                            s.btc_price,
                            s.btc_move_from_open,
                            s.streak,
                            s.streak_direction,
                            int(s.prefilter_passed),
                            s.prefilter_reasons,
                            s.indicators_json,
                        )
                        for s in snapshots
                    ],
                )

            if decisions:
                self._conn.executemany(
                    """INSERT INTO decisions (
                        candle_id, timestamp, cycle, trigger_type,
                        action, token_side, confidence, reasoning, market_view,
                        decision_size,
                        fill_price, fill_size, slippage_bps, fee_amount,
                        risk_blocked, risk_reason,
                        cash, portfolio_value, up_shares, down_shares,
                        ai_cost, ai_latency_ms,
                        indicators_json, live_order_json
                    ) VALUES (
                        ?, ?, ?, ?,
                        ?, ?, ?, ?, ?,
                        ?,
                        ?, ?, ?, ?,
                        ?, ?,
                        ?, ?, ?, ?,
                        ?, ?,
                        ?, ?
                    )""",
                    [
                        (
                            d.candle_id,
                            d.timestamp,
                            d.cycle,
                            d.trigger_type,
                            d.action,
                            d.token_side,
                            d.confidence,
                            d.reasoning,
                            d.market_view,
                            d.decision_size,
                            d.fill_price,
                            d.fill_size,
                            d.slippage_bps,
                            d.fee_amount,
                            int(d.risk_blocked),
                            d.risk_reason,
                            d.cash,
                            d.portfolio_value,
                            d.up_shares,
                            d.down_shares,
                            d.ai_cost,
                            d.ai_latency_ms,
                            d.indicators_json,
                            d.live_order_json,
                        )
                        for d in decisions
                    ],
                )

            self._conn.commit()
            total = len(snapshots) + len(decisions)
            if total > 0:
                self._logger.debug(
                    "DataStore flushed %d snapshots + %d decisions",
                    len(snapshots),
                    len(decisions),
                )
        except Exception:
            self._logger.exception("DataStore flush error")
