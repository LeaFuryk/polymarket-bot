"""Shared fixtures for forensics tests."""

from __future__ import annotations

import json
import sqlite3
import time

import pytest

# Schema copied from datastore.py
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

BASE_TS = 1709300000.0  # Fixed base timestamp for reproducibility


@pytest.fixture
def tmp_db():
    """In-memory SQLite with the polybot schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    yield conn
    conn.close()


@pytest.fixture
def sample_candle(tmp_db):
    """Insert a test candle and return candle_id."""
    tmp_db.execute(
        "INSERT INTO candles (condition_id, slug, title, start_time, end_time, btc_open, btc_close, winner) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("cond_1", "btc-5m", "BTC 5m", BASE_TS, BASE_TS + 300, 65000.0, 65050.0, "UP"),
    )
    tmp_db.commit()
    return 1  # candle_id


@pytest.fixture
def sample_decisions(tmp_db, sample_candle):
    """Insert test decisions with live_order_json."""
    # Filled BUY order
    live_order_filled = {
        "order_id": "order_filled_1",
        "limit_price": 0.55,
        "submit_ts": BASE_TS + 10.5,
        "fill_ts": BASE_TS + 12.0,
        "cancel_ts": None,
        "fill_source": "status_poll",
        "ttl_used": 3,
        "polls": [
            {"ts": BASE_TS + 11.0, "status": "LIVE", "size_matched": 0},
            {"ts": BASE_TS + 12.0, "status": "MATCHED", "size_matched": 20},
        ],
        "ob_at_submit": {"best_ask": 0.54, "best_bid": 0.52},
        "ob_at_end": {"best_ask": 0.55, "best_bid": 0.53},
        "pre_balance": 0.0,
        "post_balance": 20.0,
        "decision_ob_ask": 0.53,
        "decision_ob_bid": 0.51,
    }

    # Timed-out BUY order
    live_order_timeout = {
        "order_id": "order_timeout_1",
        "limit_price": 0.50,
        "submit_ts": BASE_TS + 60.5,
        "fill_ts": None,
        "cancel_ts": BASE_TS + 63.5,
        "fill_source": "",
        "ttl_used": 3,
        "polls": [
            {"ts": BASE_TS + 61.5, "status": "LIVE", "size_matched": 0},
            {"ts": BASE_TS + 62.5, "status": "LIVE", "size_matched": 0},
        ],
        "ob_at_submit": {"best_ask": 0.52, "best_bid": 0.50},
        "ob_at_end": {"best_ask": 0.53, "best_bid": 0.51},
        "ob_post_cancel": {"best_ask": 0.51, "best_bid": 0.49},
        "pre_balance": 0.0,
        "post_balance": 0.0,
        "decision_ob_ask": 0.51,
        "decision_ob_bid": 0.49,
    }

    # Filled SELL order (for round-trip)
    live_order_sell = {
        "order_id": "order_sell_1",
        "limit_price": 0.60,
        "submit_ts": BASE_TS + 200.5,
        "fill_ts": BASE_TS + 201.5,
        "cancel_ts": None,
        "fill_source": "size_matched",
        "ttl_used": 3,
        "polls": [{"ts": BASE_TS + 201.0, "status": "MATCHED", "size_matched": 20}],
        "ob_at_submit": {"best_ask": 0.62, "best_bid": 0.60},
        "ob_at_end": {"best_ask": 0.62, "best_bid": 0.60},
        "pre_balance": 20.0,
        "post_balance": 0.0,
        "decision_ob_ask": 0.61,
        "decision_ob_bid": 0.59,
    }

    decisions = [
        # Filled BUY
        (sample_candle, BASE_TS + 10, 1, "entry", "BUY", "UP", 0.75, "bullish", "up trend",
         20.0, 0.54, 20.0, 5.0, 0.002, 0, None, 100.0, 100.0, 0.0, 0.0,
         0.01, 500.0, '{"momentum": {"value": 0.7, "label": "bullish"}}',
         json.dumps(live_order_filled)),
        # Timed-out BUY
        (sample_candle, BASE_TS + 60, 2, "entry", "BUY", "UP", 0.65, "maybe up", "uncertain",
         20.0, None, None, None, None, 0, None, 80.0, 80.0, 20.0, 0.0,
         0.01, 450.0, '{"momentum": {"value": 0.5, "label": "neutral"}}',
         json.dumps(live_order_timeout)),
        # Filled SELL
        (sample_candle, BASE_TS + 200, 3, "exit", "SELL", "UP", 0.80, "taking profit", "profit",
         20.0, 0.60, 20.0, 3.0, 0.003, 0, None, 88.0, 108.0, 20.0, 0.0,
         0.01, 400.0, '{"momentum": {"value": -0.3, "label": "bearish"}}',
         json.dumps(live_order_sell)),
    ]

    # Also a blocked decision
    decisions.append(
        (sample_candle, BASE_TS + 120, 4, "entry", "BUY", "DOWN", 0.60, "blocked", "risk",
         20.0, None, None, None, None, 1, "kill switch active", 80.0, 80.0, 20.0, 0.0,
         0.0, 0.0, '{}', ''),
    )

    for d in decisions:
        tmp_db.execute(
            "INSERT INTO decisions (candle_id, timestamp, cycle, trigger_type, action, token_side, "
            "confidence, reasoning, market_view, decision_size, fill_price, fill_size, slippage_bps, "
            "fee_amount, risk_blocked, risk_reason, cash, portfolio_value, up_shares, down_shares, "
            "ai_cost, ai_latency_ms, indicators_json, live_order_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            d,
        )
    tmp_db.commit()
    return decisions


@pytest.fixture
def sample_snapshots(tmp_db, sample_candle):
    """Insert per-second snapshots for the test candle."""
    snapshots = []
    for i in range(300):
        ts = BASE_TS + i
        # Ask starts at 0.53, stays above 0.50 until t=64, drops to 0.49 at t=65
        # Order submitted at t=60.5 with limit_price=0.50:
        #   TTL=3 window [60.5, 63.5] → ask=0.53 (no fill)
        #   TTL=5 window [60.5, 65.5] → ask drops to 0.49 at t=65 (fills!)
        if i < 64:
            up_ask = 0.53
        elif i < 66:
            up_ask = 0.53 - (i - 63) * 0.02  # drops: 0.51, 0.49, 0.47
        elif i < 70:
            up_ask = 0.49 + (i - 66) * 0.005  # rises back
        else:
            up_ask = 0.52 + (i - 70) * 0.0005

        up_bid = up_ask - 0.02
        up_mid = (up_ask + up_bid) / 2

        snapshots.append((
            sample_candle, ts, 300 - i,
            up_bid, up_ask, up_mid, 0.04, 100.0, 100.0,
            1 - up_bid, 1 - up_ask, 1 - up_mid, 0.04, 100.0, 100.0,
            1.5, 1.5,
            65000.0 + i * 0.5, i * 0.5 / 65000 * 100,
            0, None, 1, None, None,
        ))

    for s in snapshots:
        tmp_db.execute(
            "INSERT INTO snapshots (candle_id, timestamp, time_remaining, "
            "up_best_bid, up_best_ask, up_mid, up_spread_pct, up_bid_depth, up_ask_depth, "
            "down_best_bid, down_best_ask, down_mid, down_spread_pct, down_bid_depth, down_ask_depth, "
            "rr_up, rr_down, btc_price, btc_move_from_open, "
            "streak, streak_direction, prefilter_passed, prefilter_reasons, indicators_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            s,
        )
    tmp_db.commit()
    return snapshots
