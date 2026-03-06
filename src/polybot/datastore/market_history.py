"""MarketHistoryStore — persistent market data across iterations."""

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
from polybot.datastore.rows import MarketSnapshotRow

_default_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_MARKET_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_candles (
    candle_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id  TEXT    NOT NULL,
    slug          TEXT    NOT NULL,
    iteration     TEXT    NOT NULL DEFAULT '',
    start_time    REAL    NOT NULL,
    end_time      REAL    NOT NULL,
    btc_open      REAL,
    btc_close     REAL,
    winner        TEXT,
    UNIQUE(condition_id)
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    snapshot_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    candle_id         INTEGER NOT NULL REFERENCES market_candles(candle_id),
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
    streak_direction  TEXT
);

CREATE INDEX IF NOT EXISTS idx_msnap_candle ON market_snapshots(candle_id);
CREATE INDEX IF NOT EXISTS idx_mcandle_slug ON market_candles(slug);
"""


class MarketHistoryStore:
    """Persistent market data store — never deleted by archive/cleanup.

    Stores only market observables (candles + snapshots). No session-specific
    data (decisions, portfolio). Accumulates across all iterations so we can
    statistically validate assumptions with hundreds of candles.
    """

    def __init__(
        self,
        db_path: str | Path,
        iteration: str = "",
        logger: logging.Logger | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._iteration = iteration
        self._conn: sqlite3.Connection | None = None
        self._queue: asyncio.Queue[MarketSnapshotRow] = asyncio.Queue()
        self._current_candle_id: int | None = None
        self._pending_items: list[MarketSnapshotRow] = []
        self._logger = logger or _default_logger

    @property
    def current_candle_id(self) -> int | None:
        return self._current_candle_id

    # --- Lifecycle ---

    def open(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute(f"PRAGMA journal_mode={JOURNAL_MODE}")
        self._conn.execute(f"PRAGMA synchronous={SYNCHRONOUS_MODE}")
        self._conn.executescript(_MARKET_HISTORY_SCHEMA)
        self._conn.commit()
        self._logger.info("MarketHistoryStore opened: %s (iteration=%s)", self._db_path, self._iteration)

    async def close(self) -> None:
        if self._conn is None:
            return
        await self._flush()
        self._conn.close()
        self._conn = None
        self._logger.info("MarketHistoryStore closed")

    # --- Candle lifecycle ---

    def begin_candle(
        self,
        condition_id: str,
        slug: str,
        start_time: float,
        end_time: float,
        btc_open: float | None,
    ) -> int | None:
        if self._conn is None:
            return None
        try:
            cur = self._conn.execute(
                """INSERT OR IGNORE INTO market_candles
                   (condition_id, slug, iteration, start_time, end_time, btc_open)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (condition_id, slug, self._iteration, start_time, end_time, btc_open),
            )
            self._conn.commit()

            if cur.lastrowid and cur.lastrowid > 0:
                self._current_candle_id = cur.lastrowid
            else:
                row = self._conn.execute(
                    "SELECT candle_id FROM market_candles WHERE condition_id = ?",
                    (condition_id,),
                ).fetchone()
                self._current_candle_id = row[0] if row else None

            self._logger.info(
                "MarketHistoryStore: begin_candle id=%s slug=%s",
                self._current_candle_id,
                slug,
            )
            return self._current_candle_id
        except Exception:
            self._logger.exception("MarketHistoryStore: begin_candle failed")
            return None

    def resolve_candle(
        self,
        candle_id: int,
        btc_close: float,
        winner: str,
    ) -> None:
        if self._conn is None:
            return
        try:
            self._conn.execute(
                """UPDATE market_candles
                   SET btc_close = ?, winner = ?
                   WHERE candle_id = ?""",
                (btc_close, winner, candle_id),
            )
            self._conn.commit()
            self._logger.info(
                "MarketHistoryStore: resolve_candle id=%d winner=%s",
                candle_id,
                winner,
            )
        except Exception:
            self._logger.exception("MarketHistoryStore: resolve_candle failed")

    # --- Non-blocking queue API ---

    def queue_snapshot(self, row: MarketSnapshotRow) -> None:
        try:
            self._queue.put_nowait(row)
        except asyncio.QueueFull:
            self._logger.warning("MarketHistoryStore: snapshot queue full, dropping row")

    # --- Background writer task ---

    async def writer_loop(self) -> None:
        self._logger.info("MarketHistoryStore writer_loop started")
        last_flush = time.monotonic()

        while True:
            try:
                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=FLUSH_INTERVAL_SECONDS)
                    self._pending_items.append(item)
                except TimeoutError:
                    pass
                except asyncio.CancelledError:
                    raise

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
                await self._flush()
                self._logger.info("MarketHistoryStore writer_loop stopped")
                return
            except Exception:
                self._logger.exception("MarketHistoryStore writer_loop error")
                await asyncio.sleep(1.0)

    async def _flush(self) -> None:
        while not self._queue.empty():
            try:
                self._pending_items.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not self._pending_items or self._conn is None:
            return

        snapshots = list(self._pending_items)
        self._pending_items.clear()

        try:
            self._conn.executemany(
                """INSERT INTO market_snapshots (
                    candle_id, timestamp, time_remaining,
                    up_best_bid, up_best_ask, up_mid, up_spread_pct,
                    up_bid_depth, up_ask_depth,
                    down_best_bid, down_best_ask, down_mid, down_spread_pct,
                    down_bid_depth, down_ask_depth,
                    rr_up, rr_down,
                    btc_price, btc_move_from_open,
                    streak, streak_direction
                ) VALUES (
                    ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?,
                    ?, ?,
                    ?, ?
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
                    )
                    for s in snapshots
                ],
            )
            self._conn.commit()
            if snapshots:
                self._logger.debug("MarketHistoryStore flushed %d snapshots", len(snapshots))
        except Exception:
            self._logger.exception("MarketHistoryStore flush error")
