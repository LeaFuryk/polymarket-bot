# ml_scorer

Online logistic regression scorer for BTC 5-minute candle direction prediction.

## Architecture

```
ml_scorer/
├── __init__.py           # Re-exports public API
├── constants.py          # Feature names, normalization scales, thresholds
├── models.py             # MLPrediction, ModelState dataclasses, sigmoid
├── feature_extractor.py  # Stateless feature engineering from market data
├── scorer.py             # MLScorer — training, prediction, persistence
└── README.md
```

### Separation of concerns

| Class | Responsibility |
|---|---|
| `FeatureExtractor` | Converts raw market data (candles, prices, order book) into a fixed-length feature dict. Pure and stateless. |
| `MLScorer` | Online logistic regression — predict, train, persist weights to JSON. Delegates feature vectorization to `FeatureExtractor`. |
| `MLPrediction` | Immutable result of a prediction (probability, confidence label, per-feature contributions). |
| `ModelState` | Snapshot of model internals for dashboards/diagnostics (replaces direct private-attribute access). |

## Features used

| # | Name | Description | Scale |
|---|---|---|---|
| 0 | `streak_signed` | Consecutive candle streak (+ = up) | ÷5 |
| 1 | `streak_magnitude` | $ move during streak | ÷200 |
| 2 | `btc_vs_open` | Current BTC − candle open ($) | ÷100 |
| 3 | `volatility_30m` | Avg candle range (6 candles) | ÷100 |
| 4 | `volume_ratio` | Recent 3 / prior 3 candle volume | ÷1 |
| 5 | `up_midpoint` | UP token midpoint (0-1) | ÷1 |
| 6 | `down_midpoint` | DOWN token midpoint (0-1) | ÷1 |
| 7 | `book_imbalance` | UP bid depth / ask depth | ÷2 |
| 8 | `flat_ratio` | Fraction of flat candles | ÷1 |
| 9 | `reversal_rate` | Rolling reversal rate (0-1) | ÷1 |

## How scoring works

1. `FeatureExtractor.extract()` produces a raw feature dict from market data.
2. `FeatureExtractor.to_vector()` converts the dict to a list in canonical order.
3. `FeatureExtractor.normalize()` applies fixed divisors to prevent extreme gradients.
4. `MLScorer._compute_score()` computes `w · x + b` (dot product + bias).
5. `sigmoid()` maps to a probability in (0, 1).
6. Confidence is classified as: strong_up (>0.65), lean_up (>0.55), neutral, lean_down (<0.45), strong_down (<0.35).

## Training

After each candle resolution, `MLScorer.train(features, up_won)` updates weights via online gradient descent on binary cross-entropy loss. The model persists to `ml_model.json` after each update.

## Adding a new model

To swap the logistic regression for a different model, create a new class that implements the same `predict()` / `train()` interface as `MLScorer`. The `FeatureExtractor` is independent and can be reused.
