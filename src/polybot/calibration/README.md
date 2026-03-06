# calibration/

Confidence calibration — maps the bot's stated confidence to actual win rates.

## Architecture

```
tracker.py      ConfidenceCalibrator — bins, persistence, checking
constants.py    Bin width, min samples, break-even threshold, file name
```

## How It Works

1. **Register**: When the AI makes a trade decision, the stated confidence
   (0.0–1.0) is registered with `register_trade()`.
2. **Resolve**: When the candle resolves, `record_outcome()` scores the
   prediction as win/loss and persists to JSONL.
3. **Bin**: Confidence values are bucketed into 10% bins (0.0–0.1, 0.1–0.2, …).
   Each bin tracks wins and losses independently.
4. **Check**: `check()` looks up the bin for a given confidence and returns
   the historical win rate. If the calibrated win rate falls below break-even,
   the trade should be rejected.
5. **Shadow**: HOLD cycles can register shadow predictions (no capital at risk)
   via `register_shadow()` to track directional accuracy without trading.

## Calibration Summary

`get_calibration_summary()` produces a human-readable table injected into the
AI's system prompt, showing actual vs stated confidence. Overconfident bins
(actual win rate < stated lower bound) are flagged.

## Persistence

Data is stored as JSONL in `calibration_data.jsonl` under the configured
data directory. Each line contains: confidence, won, token_side, entry_price,
slug. Data survives across sessions so calibration improves over time.
