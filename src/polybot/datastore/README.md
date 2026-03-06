# datastore — SQLite Analytics Layer

Non-blocking, batched persistence for per-second market replay and decision analysis.

## Architecture

```
datastore/
├── __init__.py          # Re-exports for backward compatibility
├── constants.py         # Flush thresholds, SQLite pragma settings
├── rows.py              # Row dataclasses (SnapshotRow, DecisionRow, MarketSnapshotRow)
├── store.py             # DataStore — analytics DB (candles, snapshots, decisions)
├── market_history.py    # MarketHistoryStore — persistent market data across iterations
└── README.md
```

## Two Stores

| Store | Purpose | Tables | Lifetime |
|-------|---------|--------|----------|
| **DataStore** | Full analytics (market + decisions + portfolio) | `candles`, `snapshots`, `decisions` | Per-session (archived) |
| **MarketHistoryStore** | Market observables only | `market_candles`, `market_snapshots` | Permanent (never deleted) |

## Write Pipeline

Both stores use the same non-blocking async pattern:

```
Hot loop → queue_snapshot/queue_decision (non-blocking put_nowait)
         ↓
Background writer_loop → drain queue → batch insert every 5s or 50 rows
         ↓
SQLite WAL mode (readers don't block writers)
```

## Row Types

- **SnapshotRow** — Full per-second state: orderbook (UP + DOWN), BTC price, streak, prefilter result, indicators JSON
- **MarketSnapshotRow** — Same as SnapshotRow but without prefilter/indicator fields (market-only data)
- **DecisionRow** — AI decision: action, confidence, reasoning, fill, risk, portfolio state, API cost

## Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `FLUSH_INTERVAL_SECONDS` | 5.0 | Max time between batch inserts |
| `FLUSH_BATCH_SIZE` | 50 | Max rows before forcing a flush |
| `JOURNAL_MODE` | WAL | Write-ahead logging for concurrent reads |
| `SYNCHRONOUS_MODE` | NORMAL | Balanced durability vs performance |
