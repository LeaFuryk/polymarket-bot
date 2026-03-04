# Forensics

Offline execution analysis system for auditing trade quality across six dimensions.

## Pipeline

```
db.connect(path) → load_orders/snapshots/candles
        ↓
   ┌────┴────────────────────────────────┐
   │  6 independent investigations       │
   │  (each: conn → typed results)       │
   │                                     │
   │  A. execution  → OrderMetrics       │
   │  B. ttl        → TTLCounterfactual  │
   │  C. costs      → CostBreakdown      │
   │  D. blocked    → BlockedOrder       │
   │  E. roundtrips → RoundTrip          │
   │  F. context    → DecisionContext    │
   └────┬────────────────────────────────┘
        ↓
   aggregate.build_report() → ForensicsReport
        ↓
   render / CLI / JSON
```

## Investigations

| ID | Module | What it measures |
|----|--------|-----------------|
| A | `execution.py` | Latency, price drift, fill rates, balance deltas |
| B | `ttl.py` | Counterfactual: which TTL values would have rescued timeouts |
| C | `costs.py` | Fee, slippage, and decision-drift cost per filled order |
| D | `blocked.py` | Risk-blocked order classification and recoverability |
| E | `roundtrips.py` | FIFO entry/exit pairing with PnL, MFE, MAE, exit efficiency |
| F | `context.py` | Decision-time indicators, R/R ratio, ML score, win/loss outcome |

## Key design decisions

- **Stateless functions** — each `analyze_*` takes `conn` and returns Pydantic models; no shared mutable state.
- **Investigator protocol** — `protocols.py` defines a pluggable interface. New investigations implement `name` + `analyze(conn)`.
- **Injectable logger** — all functions accept `logger: logging.Logger | None = None`.
- **Constants in one place** — `constants.py` holds thresholds, grids, category maps. No magic numbers in analysis code.

## Adding a new investigation

1. Create `src/polybot/forensics/new_feature.py`
2. Define result model(s) in `types.py`
3. Implement `analyze_new_feature(conn, *, logger=None) → results`
4. Wire it into `aggregate.py` → `build_report()`
5. Add render function in `render.py`
6. Add tests in `tests/test_forensics.py`
7. Re-export from `__init__.py`
