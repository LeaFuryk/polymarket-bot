# analysis — Replay & Validation Tools

Post-trade analysis package for replaying candle orderbook data, validating
decision quality, and generating performance reports.

## Modules

| File | Responsibility |
|------|---------------|
| `constants.py` | All magic numbers: thresholds, TTL values, color breakpoints |
| `engine.py` | Pure replay analysis functions (stateless, no I/O) |
| `replay.py` | DB loading, replay orchestration, Rich rendering, CLI |
| `validate.py` | Decision validation and accuracy analysis |
| `report.py` | Performance reporting with Sharpe ratio, PnL |
| `archive.py` | Database archiving utilities |
| `compare.py` | Cross-run comparison tools |

## Architecture

```
CLI (main)
  └─ replay.py          I/O layer: DB reads, Rich output
       └─ engine.py     Pure functions: stats, fillability, insights
            └─ constants.py
```

### engine.py — Pure Analysis Functions

Six stateless functions extracted from `replay.py`:

- **`compute_ob_stats`** — Orderbook summary statistics (min/max/mean/stdev)
- **`fillability_scan`** — Simulate limit orders across time, measure fill rate
- **`build_decision_timeline`** — Overlay AI decisions against book state
- **`post_cancel_recovery`** — Check if price recovers after missed/cancelled orders
- **`live_order_telemetry`** — Extract and overlay live order data from decisions
- **`generate_insights`** — Auto-generate textual insights from analysis results

All functions take pre-loaded data (dicts/lists) and return analysis results.
No database, filesystem, or console access.

### replay.py — Orchestration & Rendering

- **DB helpers**: `_connect`, `_find_candles`, `_load_snapshots`, `_load_decisions`
- **`replay_candle`**: Orchestrates the 6 engine functions for a single candle
- **`replay_all_candles`**: Aggregates across all candles in a database
- **Rendering**: Rich panels/tables for each analysis section
- **CLI**: `polybot-replay` entry point with argparse

## Key Constants

| Constant | Value | Used In |
|----------|-------|---------|
| `RECOVERY_WINDOW_SECONDS` | 30 | Post-cancel recovery analysis |
| `TTL_COUNTERFACTUAL_VALUES` | [5, 8, 10] | Missed order TTL simulation |
| `DEFAULT_TTL_SECONDS` | 3 | Default fillability scan TTL |
| `FILL_RATE_GREEN/YELLOW` | 0.7 / 0.4 | Single-candle fill rate color |
| `AGG_FILL_RATE_GREEN/YELLOW` | 0.5 / 0.3 | Aggregate fill rate color |
| `ANNUALIZATION_FACTOR` | 1440 | Sharpe ratio (cycles/day) |
