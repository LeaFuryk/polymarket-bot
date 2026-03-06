# models/

Pydantic data models — single source of truth for data contracts across the bot.

## Architecture

```
core.py         All model definitions (enums, market data, decisions, portfolio, risk, logging)
constants.py    Default values (confidence, TTL, position threshold, observation expiry)
```

## Model Domains

| Domain | Models | Description |
|--------|--------|-------------|
| Enums | `Side`, `Action`, `OrderType`, `TokenSide` | Trading action/direction enums |
| Market Data | `BtcPrice`, `BtcCandle`, `OrderbookLevel`, `OrderbookSnapshot`, `MarketSnapshot`, `CandleMarket` | Market state and orderbook data |
| Decisions | `TradingDecision`, `FeatureVector` | AI input and output |
| Execution | `SimulatedFill`, `LiveOrderResult`, `PendingLimitOrder` | Order execution and fill tracking |
| Portfolio | `PositionState` | Position shares and P&L |
| Risk | `RiskCheckResult`, `RiskState` | Risk check results and daily state |
| Logging | `TradeRecord`, `ResolutionRecord` | Audit trail and resolution records |
| Reflection | `ObservationCategory`, `Observation`, `Scorecard`, `ScorecardDelta` | AI self-reflection data |

## Key Computed Properties

- **`OrderbookSnapshot`**: `best_bid`, `best_ask`, `midpoint`, `spread`, `spread_pct`, `bid_depth`, `ask_depth`
- **`BtcCandle`**: `direction` (up/down), `body_pct` (% move)
- **`PendingLimitOrder`**: `expires_at`, `is_expired()`
- **`PositionState`**: `market_value`, `is_flat()`
- **`CandleMarket`**: `time_remaining()`

## Backward Compatibility

All models are re-exported from `__init__.py`. Existing imports
(`from polybot.models import X`) continue to work unchanged.
