# adaptive_entry

Learns optimal BTC move thresholds and max entry prices from rolling candle outcomes.

## Architecture

```
adaptive_entry/
├── __init__.py              # Re-exports public API
├── constants.py             # All thresholds, boundaries, and magic numbers
├── models.py                # CandleOutcome dataclass
├── reversal_detector.py     # Retracement-based reversal detection
├── threshold_calculator.py  # Fakeout-based threshold computation
├── ai_context.py            # AI prompt context generation
├── tracker.py               # AdaptiveEntryTracker orchestrator
└── README.md
```

### Separation of concerns

| Module | Responsibility |
|---|---|
| `reversal_detector` | Given a candle's prefilter snapshots, determines initial direction, peak moves, and whether an 80%+ retracement reversal occurred. Pure function, no state. |
| `threshold_calculator` | Given rolling candle history, computes fakeout-based BTC threshold, max entry price, and signal type. Pure function, no state. |
| `ai_context` | Builds the reversal rate context section for Claude prompts. Pure function, no state. |
| `tracker` | Orchestrates the above — persistence (JSONL), Binance bootstrap, and rolling window management. Only stateful component. |

## How it works

### Fakeout-based threshold

For each resolved candle, measures the **peak move in the wrong direction** (fakeout) before the winner was decided:
- **threshold** = P50 of last 5 fakeout magnitudes, clamped to [$20, adaptive_cap]
- **adaptive_cap** = max($50, min($100, P75 × 1.2))

Small fakeouts → low threshold → enter early on clear signals.
Large fakeouts → high threshold → wait for sustained confirmation.

### Reversal detection

Uses retracement-based detection with two mechanisms:
1. **Threshold crossing**: BTC move exceeds the adaptive threshold → momentum confirmed
2. **80% retracement**: Peak move retraces 80%+ with accelerating retreat → reversal detected

### Signal types

| Reversal rate | Signal type | Interpretation |
|---|---|---|
| < 40% | MOMENTUM | Initial BTC move usually continues |
| 40-60% | UNCERTAIN | Direction unreliable |
| > 60% | CONTRARIAN | Initial move usually reverses |

### Market regimes

| Reversal rate | Regime |
|---|---|
| < 20% | CALM |
| 20-40% | MODERATE |
| > 40% | CHOPPY |

## Max entry price

Calibrated from rolling winner ask prices: `avg(winner_ask_at_threshold) + $0.10`, capped at $0.65.
