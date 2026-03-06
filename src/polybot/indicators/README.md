# indicators — Dynamic Feature Selection

Config-driven indicator registry that computes market signals each decision cycle.

## Architecture

```
indicators/
├── __init__.py      # Re-exports for backward compatibility
├── constants.py     # Thresholds and magic numbers
├── core.py          # Registry, config, compute/format, 24 indicator functions
└── README.md
```

## How It Works

1. **FeatureConfig** reads `data/feature_config.json` each cycle to get the list of enabled indicators and their params
2. **compute_indicators()** iterates enabled indicators, calls each registered function, collects non-None results
3. **format_indicators()** formats results into a markdown block for the AI prompt

## Indicator Categories

| Category | Indicators | Data Source |
|----------|-----------|-------------|
| Market trend | `market_trend` | `btc_candles` (EMA20/50) |
| Token midpoint | `token_momentum`, `token_volatility`, `token_ma_crossover`, `token_mean_reversion` | `price_history` |
| Orderbook | `orderbook_imbalance`, `spread_trend`, `down_orderbook_imbalance`, `cross_book_flow`, `best_entry_analysis`, `token_price_divergence` | `orderbook`, `down_orderbook` |
| BTC price | `btc_momentum`, `btc_volatility` | `btc_price_history` |
| BTC candles | `btc_candle_momentum`, `btc_candle_ma_cross`, `consecutive_streak`, `streak_magnitude`, `btc_vs_candle_open`, `volatility_30m`, `volume_trend` | `btc_candles` |
| Session | `session_streak`, `confidence_calibration` | `SessionContext` |
| Resolution risk | `chainlink_divergence`, `flat_market_edge` | `btc_price`, `btc_candles` |

## Registry Pattern

Indicators self-register via the `@register("name")` decorator. The registry is a module-level dict populated at import time, so all indicators are available as soon as `polybot.indicators` is imported.

## Adding a New Indicator

```python
@register("my_indicator")
def _my_indicator(snap, params, session):
    # Return IndicatorResult or None (to skip)
    return IndicatorResult(name="My Indicator", value=0.5, label="description")
```

Then add it to `data/feature_config.json` with `"enabled": true`.
