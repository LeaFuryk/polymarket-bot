# exit_tracker — Quantitative Exit Strategy Analysis

Logs every SELL (exit) and measures what-if outcomes to answer: "Is early profit-taking actually optimal, or are we leaving money on the table?"

## Architecture

```
exit_tracker/
├── __init__.py      # Re-exports for backward compatibility
├── constants.py     # File names, rounding precision, outcome values
├── tracker.py       # ExitRecord dataclass + ExitTracker class
└── README.md
```

## How It Works

1. **Register exit** — When the bot sells a position, `register_exit()` records the entry/exit prices and size
2. **Record outcome** — When the candle resolves, `record_outcome()` computes what-if PnL:
   - `held_value`: $1.00 if the token side won, $0.00 if it lost
   - `actual_pnl`: realized PnL from the exit
   - `missed_pnl`: difference between hold-to-expiry PnL and actual PnL
3. **Classify** — If `missed_pnl <= 0`, the exit was a GOOD EXIT (saved money vs holding). If positive, we MISSED UPSIDE.

## Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `EXIT_ANALYSIS_FILENAME` | `exit_analysis.jsonl` | Persistence file |
| `PRICE_PRECISION` | 4 | Decimal places for price rounding |
| `SIZE_PRECISION` | 2 | Decimal places for size rounding |
| `WON_VALUE` / `LOST_VALUE` | 1.0 / 0.0 | Binary outcome values |

## Persistence

Data is stored as newline-delimited JSON (JSONL) in the configured log directory. Records accumulate across sessions for long-term strategy analysis.
