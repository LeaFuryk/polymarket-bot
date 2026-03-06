# `tasks` — Event-Driven Trading Tasks

## Overview

The `tasks` package contains the event-driven AI decision pipeline and its
supporting helper modules. The core `AIDecision` class coordinates entry/exit
triggers, AI calls, risk guards, trade execution, and logging. Pure helper
functions are split into focused modules for independent testability.

## Architecture

```
tasks/
├── ai_decision.py       # Thin coordinator — trigger handling, execution, state
├── prompt_context.py     # BTC trajectory, retracement, microstructure, timing stats
├── decision_guards.py    # Confidence gate, entry cap, anti-flip, sizing, etc.
├── context_builder.py    # ML line, chainlink/trend/stop-loss warnings
├── trade_logger.py       # TradeRecord and DecisionRow assembly
├── market_monitor.py     # Market data monitoring task (separate concern)
├── position_monitor.py   # Position monitoring task (separate concern)
└── __init__.py           # Re-exports all public names
```

## Decision Pipeline

```
Trigger (entry/exit)
  │
  ▼
Feature Vector + Indicators
  │
  ▼
ML Prediction ──► format_ml_line()
  │
  ▼
Context Building ──► append_section(), build_*_warning()
  │
  ▼
Two-Pass Screening (optional, entry only)
  │
  ▼
Full AI Decision (DecisionEngine.decide())
  │
  ▼
Guard Chain:
  ├── clamp_sell_size()
  ├── force_exit_side()
  ├── apply_confidence_gate()
  ├── calibration check
  ├── anti-hedge / auto-close-for-flip
  ├── apply_anti_flip()
  ├── apply_single_entry()
  ├── apply_entry_price_cap()
  └── apply_position_sizing()
  │
  ▼
Execution (live or paper)
  │
  ▼
Logging ──► build_trade_record(), build_decision_row()
```

## Module Responsibilities

### `ai_decision.py` (coordinator)
- `AIDecision` class: manages trigger loop, state, execution
- `_handle_entry_trigger()`: pre-trade risk checks, delegates to `_run_ai_decision()`
- `_handle_exit_trigger()`: stop-loss/take-profit with cooldown, winner-near-expiry guard
- `_try_contrarian_flip()`: post-exit opposite-side entry evaluation
- `_auto_close_for_flip()`: position auto-close during reversal flips
- `_run_ai_decision()`: the core pipeline (indicators → AI → guards → execute → log)

### `prompt_context.py` (pure functions)
- `compute_btc_trajectory()`: 60-second BTC price path analysis
- `compute_retracement_context()`: reversal retracement analytics
- `format_microstructure()`: tick-level microstructure summary
- `compute_entry_timing_stats()`: session entry timing analysis

### `decision_guards.py` (pure functions)
- `override_to_hold()`: standard HOLD override preserving metadata
- `clamp_sell_size()`: clamp sell to actual held shares
- `force_exit_side()`: force token_side on exit triggers
- `apply_confidence_gate()`: block low-confidence BUYs
- `apply_entry_price_cap()`: block entries above price cap (R/R too low)
- `apply_anti_flip()`: block opposite-side buy after same-candle sell
- `apply_single_entry()`: block double-entry on same side per candle
- `compute_position_scale()`: R/R, move magnitude, counter-trend scaling
- `apply_position_sizing()`: apply scale and enforce minimum size

### `context_builder.py` (pure functions)
- `append_section()`: clean section concatenation with blank-line separation
- `format_ml_line()`: ML prediction one-liner for indicators block
- `build_chainlink_warning()`: chainlink divergence warning (|div| > $100)
- `build_counter_trend_advisory()`: counter-trend advisory (|trend| >= 0.3)
- `build_stop_loss_warning()`: post-stop-loss cooldown warning

### `trade_logger.py` (pure functions)
- `build_trade_record()`: assembles `TradeRecord` from cycle outputs
- `build_decision_row()`: assembles `DecisionRow` for SQLite analytics

## Design Decisions

1. **Pure function extraction**: All extracted modules contain pure functions
   with no class state. They receive all inputs as arguments, making them
   independently unit-testable without mocking the full `AIDecision` class.

2. **Guard chain pattern**: Decision guards follow a uniform signature:
   `(decision, context_args, *, log=None) -> TradingDecision`. Each guard
   returns the input unchanged when not applicable, or a new immutable
   `TradingDecision` when overriding.

3. **Injectable logger**: Guard functions accept `log: logging.Logger | None`
   so tests can inject a test logger or suppress output.

4. **Coordinator stays stateful**: `AIDecision` retains state (portfolio refs,
   candle-level tracking sets, session counters) and async execution logic.
   Extracted modules are stateless and synchronous.
