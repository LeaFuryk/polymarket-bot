# Learning Curves Notebook

**Date:** 2026-04-21
**File:** `notebooks/eval/03_learning_curves.ipynb`

## Problem

We don't know how much training data each model needs to reach peak performance, or whether collecting more data will improve predictions. Without a learning curve, we're guessing.

## Solution

A single diagnostic notebook that trains LR, RF, XGB, and DNN on increasing data subsets, measures accuracy and Brier score via GroupKFold CV at each size, and plots the results.

## Notebook Structure

### Section 1: Setup
- Load `data/latest_features.jsonl`
- Load `optimal_features_{lr,rf,xgb}.json` for per-model feature lists and hyperparameters
- Define training sizes: `[100, 200, 400, 600, 800, 1000, 1500, 2000, 2500, 3000, 3500, 4000]`
- Cap at actual candle count if fewer than 4000 available

### Section 2: Learning Curve Engine
- For each model, for each training size N:
  - Take the **first N candles** (time-ordered, no shuffling)
  - All snapshots for those candles (preserves temporal structure)
  - Run 5-fold GroupKFold CV (group by `candle_id`)
  - On each fold's validation set, compute accuracy and Brier score
  - Record mean±std of both metrics across folds
- Models:
  - **LR**: LogisticRegression with features/hyperparams from `optimal_features_lr.json`
  - **RF**: RandomForestClassifier with features/hyperparams from `optimal_features_rf.json`
  - **XGB**: XGBClassifier with features/hyperparams from `optimal_features_xgb.json`
  - **DNN-features**: DeepNeuralNetworkRunner from `notebooks/deep_neural_network.py` (subprocess, 60 engineered features, 20 epochs, patience=5)
  - **DNN-raw**: Same architecture but trained on raw inputs only (btc_price, elapsed_pct, up/down bid/ask/depth, market_volume) — lets the DNN learn its own features from raw data
- All models use StandardScaler fit on training fold
- tqdm progress bars for outer loop (sizes) and inner loop (models)

### Section 3: Accuracy Learning Curves
- Line plot: x=training candles, y=accuracy (mean with ±1std shaded band)
- All 4 models overlaid, distinct colors
- Horizontal dashed line at 0.5 (random baseline)
- Title: "Learning Curves — Accuracy vs Training Set Size"

### Section 4: Brier Score Learning Curves
- Same layout as accuracy but y=Brier score (lower is better)
- Horizontal dashed line at 0.25 (random baseline Brier)

### Section 5: Summary Table
- For each model at each size: accuracy mean±std, Brier mean±std
- Highlight the "knee point" — smallest size where accuracy is within 0.5% of the model's best accuracy

### Section 6: Conclusions
- Markdown cell summarizing which models have plateaued, which benefit from more data, and whether DNN is viable at current data sizes

## Model Configurations

Each model loads its config from the corresponding JSON file:
- LR: `data/optimal_features_lr.json` → features + `{C, l1_ratio, solver, max_iter}`
- RF: `data/optimal_features_rf.json` → features + `{n_estimators, max_depth, min_samples_leaf}`
- XGB: `data/optimal_features_xgb.json` → features + `{learning_rate, max_depth, min_child_weight, subsample, colsample_bytree}`
- DNN-features: All 60 feature columns (same as `eval/02_advanced_models.ipynb`), 4x ResBlock(128), 20 epochs, patience=5
- DNN-raw: Raw columns only: `btc_price, elapsed_pct, up_best_bid, up_best_ask, up_bid_depth, up_ask_depth, down_best_bid, down_best_ask, down_bid_depth, down_ask_depth, market_volume`. Same architecture.

## What This Does NOT Do

- No model export
- No strategy evaluation
- No forward-testing
- No changes to production code
