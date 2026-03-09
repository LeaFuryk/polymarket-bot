# agent/ — Trading Agent Package

Orchestrates concurrent tasks for market monitoring, AI decisions, position management, and dashboard broadcasting.

## Module Structure

| Module | Responsibility | Key Classes/Functions |
|---|---|---|
| `core.py` | Thin orchestrator — wires components, launches async tasks | `TradingAgent` |
| `context.py` | Typed dataclass holding references to all sub-components | `AgentContext` |
| `factory.py` | Constructs all sub-components and assembles AgentContext | `ContextFactory` |
| `dashboard.py` | Dashboard data assembly and JSON writing (module-level functions) | `assemble_dashboard_data()`, `write_dashboard_json()`, `sync_from_ai_decision()` |
| `rotation.py` | Market discovery, candle transitions, microstructure capture | `RotationManager` |
| `helpers.py` | Startup data loading, state persistence, PnL computation, logging setup, iteration summaries | `StartupData`, `load_startup_data()`, `save_agent_state()`, `resolve_pending_bets()`, `enrich_iteration_summary()`, `setup_logging()`, `compute_pnl_from_trades()` |

## Architecture

All extracted modules receive an `AgentContext` dataclass instead of importing `TradingAgent`. This breaks circular dependencies and keeps coupling explicit.

```
TradingAgent (core.py)
  ├── calls load_startup_data() before context creation
  ├── passes StartupData to ContextFactory.build()
  ├── delegates to RotationManager (called by MarketMonitor)
  ├── wires on_cycle_complete callback → dashboard sync + WS broadcast
  ├── MarketMonitor broadcasts MSG_MARKET + MSG_STATUS per tick
  ├── PositionMonitor broadcasts MSG_POSITION per tick
  └── owns run() lifecycle + shutdown
```

## Consumers

- `polybot/__main__.py` → `from polybot.agent import TradingAgent`
- `polybot/ws/broadcaster.py` → accesses `TradingAgent` (TYPE_CHECKING only)
- `polybot/analysis/archive.py` → `from polybot.agent import enrich_iteration_summary`
