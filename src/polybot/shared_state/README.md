# shared_state — Typed State Container

## Overview

The `shared_state` package provides a typed `SharedState` container that
coordinates data flow between the bot's concurrent async tasks. It is
**not** a module-level global — it is created once in `Agent.__init__()` and
injected into each task.

All tasks run as `asyncio.Task` instances in a single event loop, so
attribute access is safe without locks.

## Architecture

```
shared_state/
├── __init__.py              — Public API re-exports
├── constants.py             — Default values as named constants
├── entry_context.py         — EntryContext (market conditions at fill time)
├── candle_microstructure.py — CandleMicrostructure (end-of-candle summary)
├── prefilter_snapshot.py    — PreFilterSnapshot (per-second market state)
├── stop_loss_record.py      — StopLossRecord (typed stop-loss exit record)
└── state.py                 — SharedState (central hub)
```

## State Sections

| Section | Fields | Written by | Read by |
|---|---|---|---|
| **Market data** | `latest_snapshot`, `snapshot_timestamp` | MarketMonitor | AIDecision, PositionMonitor |
| **Candle** | `current_market`, `candle_open_btc` | Agent | All tasks |
| **Pre-filter** | `prefilter_history` | MarketMonitor | AIDecision |
| **AI trigger** | `ai_trigger_reason`, `ai_last_call_time` | AIDecision | Dashboard/WS |
| **P&L** | `position_pnl_pct` | PositionMonitor | Dashboard/WS |
| **Session stats** | `session_wins`, `session_losses` | Agent | Indicators |
| **Microstructure** | `microstructure_history` | Agent | AIDecision |
| **Stop-loss** | `last_stop_loss` | AIDecision | AIDecision |
| **Dynamic SL/TP** | `entry_context`, `reversal_rate`, `signal_type`, `regime`, `dynamic_sl`, `dynamic_tp` | AIDecision, PositionMonitor | Dashboard/WS |
| **Monitor** | `monitor_status` | MarketMonitor | Dashboard/WS |
| **Tech metrics** | `api_latencies`, `ws_client_count`, `sqlite_queue_depth` | Various | Dashboard/WS |
| **Lifecycle** | `shutdown`, `rotation_in_progress` | Agent | All tasks |

## Usage

```python
from polybot.shared_state import SharedState

# Created once and injected
state = SharedState()
task = AIDecisionTask(shared=state, ...)
```

## Candle Rotation

The `Agent` is responsible for resetting per-candle transient state during
candle transitions. `SharedState` is a pure data container and does not own
lifecycle logic.
