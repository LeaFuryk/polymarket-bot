# knowledge — Feedback Learning System

Structured observations, scorecard computation, and periodic AI reflection on trading outcomes.

## Architecture

```
knowledge/
├── __init__.py      # Re-exports for backward compatibility
├── constants.py     # Thresholds, file names, API settings
├── manager.py       # KnowledgeManager class (observations, cache, reflection)
├── scorecard.py     # Pure scorecard computation and formatting
└── README.md
```

## How It Works

1. **Scorecard** (`scorecard.py`) — Pure functions that compute win rate, avg PnL, hold rate, etc. from a batch of resolutions and trades. Also formats scorecard deltas for human/AI consumption.

2. **KnowledgeManager** (`manager.py`) — Orchestrates the feedback loop:
   - **Base knowledge**: Reads `.md` files (trading_patterns, self_assessment) with TTL-based caching
   - **Observations**: JSONL-based store of AI-generated insights with resolution-based expiry
   - **Session history**: Rolling markdown table of session summaries (last 20 entries)
   - **Feedback context**: Assembles all knowledge into a prompt block for the decision engine
   - **Reflection**: Calls Claude to analyze outcomes and produce new observations

## Observation Lifecycle

```
reflect() called with batch of resolutions/trades
  → compact expired observations
  → compute scorecard + delta
  → build prompt with tables + active observations
  → Claude produces new observations + expire IDs
  → append new observations to JSONL
  → remove expired observations
  → update session history
```

Observations expire after a configurable number of resolutions (default 30). The `freshness` metric (0-100%) indicates how close an observation is to expiry; observations below 50% freshness are tagged `[AGING]`.

## Key Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `PNL_THRESHOLD` | 0.001 | Min PnL to count as win/loss |
| `CACHE_TTL_SECONDS` | 60 | Base knowledge cache duration |
| `DRAWDOWN_ALERT_THRESHOLD` | -5.0 | Rolling PnL trigger for drawdown warning |
| `EXPENSIVE_SIDE_THRESHOLD` | 0.55 | Entry price above which side is "expensive" |
| `CHEAP_SIDE_THRESHOLD` | 0.40 | Entry price below which opposite is "cheap" |
| `DEFAULT_OBSERVATION_EXPIRY` | 30 | Resolutions until observation expires |
