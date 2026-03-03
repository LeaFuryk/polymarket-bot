# prefilter — Rules-based market screening

Runs cheap, stateless checks **before** calling the AI to decide on a trade.
Filters out cycles where HOLD is the only sensible decision, saving 60-70%
of AI API costs.

## Architecture

```
protocol.py      MarketFilter protocol (structural typing)
filters.py       One class per filter criterion (all implement MarketFilter)
signals.py       Pure-function signal computations (streak, BTC range, best entry)
composite.py     PreFilter orchestrator — chains filters, tracks stats
result.py        PreFilterResult dataclass
constants.py     Default thresholds
__init__.py      Re-exports for backward-compatible imports
```

## Filter pipeline

Filters run in order — first skip wins:

| # | Filter | What it checks |
|---|--------|---------------|
| 1 | `OpenPositionFilter` | Position already open → PositionMonitor handles exits |
| 2 | `TimeRemainingFilter` | Less than 45s before candle close |
| 3 | `WideSpreadFilter` | Both UP and DOWN spreads exceed 8% |
| 4 | `ThinBookFilter` | Both orderbooks have less than $50 total depth |
| 5 | `ChoppyMarketFilter` | BTC range < $50 AND best entry > 0.28 |
| 6 | `NoStreakFilter` | No directional streak (< 2 candles) AND best entry > 0.50 |

## Adding a new filter

1. Create a class in `filters.py` matching the `MarketFilter` protocol
2. Add it to `default_filters()` in `composite.py`
3. Re-export from `__init__.py`
4. Write tests

No existing code needs to change — the protocol is structural (duck typing).

## Customisation

Pass custom thresholds to `PreFilter()` or inject your own filter list:

```python
from polybot.prefilter import PreFilter, TimeRemainingFilter, WideSpreadFilter

pf = PreFilter(filters=[
    TimeRemainingFilter(min_time=30.0),
    WideSpreadFilter(max_spread_pct=0.10),
])
```
