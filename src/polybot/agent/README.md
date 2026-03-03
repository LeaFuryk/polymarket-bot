# agent/ — Trading Agent Package

Orchestrates concurrent tasks for market monitoring, AI decisions, position management, and dashboard broadcasting.

## Module Structure

| Module | Responsibility | Key Classes/Functions |
|---|---|---|
| `core.py` | Thin orchestrator — wires components, launches async tasks | `TradingAgent` |
| `context.py` | Typed dataclass holding references to all sub-components | `AgentContext` |
| `dashboard.py` | Dashboard data assembly, JSON writing, WS broadcasting | `DashboardAssembler`, `enrich_iteration_summary()` |
| `rotation.py` | Market discovery, candle transitions, microstructure capture | `RotationManager` |
| `state.py` | Agent state persistence, history loading, pending bet resolution | `StatePersistence` |
| `helpers.py` | Logging setup, PnL computation | `setup_logging()`, `compute_pnl_from_trades()` |

## Architecture

All extracted modules receive an `AgentContext` dataclass instead of importing `TradingAgent`. This breaks circular dependencies and keeps coupling explicit.

```
TradingAgent (core.py)
  ├── creates AgentContext
  ├── delegates to RotationManager.rotation_loop(ctx)
  ├── delegates to DashboardAssembler.dashboard_loop(ctx)
  ├── delegates to StatePersistence.load/save(ctx)
  └── owns run() lifecycle + shutdown
```

## Consumers

- `polybot/__main__.py` → `from polybot.agent import TradingAgent`
- `polybot/ws/broadcaster.py` → accesses `TradingAgent` (TYPE_CHECKING only)
- `polybot/analysis/archive.py` → `from polybot.agent import enrich_iteration_summary`
