# Feature Selection Pipeline — Proper ML Practices

## Context

The current feature selection approach has fundamental flaws:
- **Single train/val split** with no cross-validation — results overfit to one specific split
- **Impurity-based importance** (Gini/gain) for RF/XGB — biased toward correlated and high-cardinality features (sklearn docs explicitly warn about this)
- **No decorrelation** — 6 price-proxy features (`up_risk_reward`, `down_risk_reward`, `rr_spread`, `up_implied_probability`, `down_implied_probability`, `btc_move_from_open`) all encode "which side is the market favorite." Importance ranking fills top-N with redundant copies and the model learns to follow the market rather than predict.
- **XGB hyperparameter tuning leaks** — early stopping uses the same validation set used to evaluate performance
- **LR uses O(N²) forward selection** — slow and single-split dependent

## Design: 3-Stage Pipeline

All notebooks (`lr/01_feature_selection`, `rf/01_feature_selection`, `xgb/01_feature_selection`) will be rewritten with the same 3-stage pipeline, adapted per model type. Every stage is documented with markdown cells explaining the rationale.

### Stage 1: Decorrelation (shared across all models)

**Goal:** Collapse redundant features so the model is forced to use diverse signal types.

**Method:**
1. Compute Spearman correlation matrix on training data
2. Hierarchical clustering of features with |ρ| > 0.7
3. For each cluster, keep the feature with highest mutual information (sklearn `mutual_info_classif`) with the target
4. Visualize: correlation heatmap before/after, cluster dendrogram

**Expected outcome:** ~60 features collapse to ~30-40 decorrelated features. The 6 price-proxy features become 1-2 representatives.

**Notebook documentation:** Explain why correlated features are problematic (inflated importance, redundant signal, crowding out complementary features). Show the correlation matrix and clusters.

### Stage 2: Feature Selection (model-specific)

#### LR: L1 Regularization Path

**Why not forward selection:** O(N²) model fits, single-split dependent, doesn't handle correlation.

**Method:**
1. Train `LogisticRegression(penalty='l1', solver='saga')` across a range of C values (e.g., `np.logspace(-3, 1, 20)`)
2. For each C, record which features have non-zero coefficients
3. Use `GroupKFold(n_splits=5)` grouped by `candle_id` for each C value
4. Plot: number of active features vs mean CV accuracy
5. Select features that survive L1 shrinkage at the optimal C (best CV accuracy)

**Notebook documentation:** Explain L1 regularization (Lasso), how it performs automatic feature selection by driving coefficients to zero, and why it handles correlation naturally (picks one from a correlated group).

#### RF: RFECV with Permutation Importance

**Why not impurity importance + top-N:** Impurity importance is biased by correlation and cardinality. Top-N doesn't account for redundancy.

**Method:**
1. Use `sklearn.feature_selection.RFECV` with `RandomForestClassifier`
2. Importance via `sklearn.inspection.permutation_importance` (unbiased)
3. Cross-validation: `GroupKFold(n_splits=5)` grouped by `candle_id`
4. Scoring: `accuracy` (primary), also report F1 and Brier
5. Step size: 1 (remove one feature per iteration for precision)

**Notebook documentation:** Explain RFECV (iteratively removes least important feature, cross-validates at each step). Explain why permutation importance is preferred over impurity importance (sklearn docs reference). Show the RFECV curve (number of features vs CV score).

#### XGB: RFECV with Permutation Importance + Nested CV for Hyperparameters

**Why nested CV:** The current approach tunes hyperparameters on the validation set and evaluates on the same set — information leakage.

**Method:**
1. Outer loop: `GroupKFold(n_splits=5)` for feature selection evaluation
2. Inner loop: `GroupKFold(n_splits=3)` for hyperparameter tuning (grid search)
3. RFECV with permutation importance on the outer folds
4. Early stopping uses inner validation fold (not outer)
5. Probability calibration: `CalibratedClassifierCV` with `cv=3` on training fold only

**Notebook documentation:** Explain nested cross-validation (inner for tuning, outer for evaluation), why early stopping on the evaluation set is leakage, and how this design prevents it.

### Stage 3: Cross-Validated Evaluation and Stability (shared)

**Goal:** Report reliable performance estimates and feature stability.

**Method:**
1. For each fold, record: selected features, accuracy, F1, Brier score, AUC
2. Report: mean ± std across folds for each metric
3. Feature stability: how often each feature is selected across folds (%)
4. Only features selected in ≥60% of folds are "stable" and included in the final set
5. Visualize: stability bar chart, metric distributions across folds

**Notebook documentation:** Explain why stability matters (a feature selected in 1/5 folds is noise, one selected in 5/5 is genuine signal).

### Output: JSON Config

Same output format as before (`data/optimal_features_*.json`) but with additional metadata:

```json
{
  "model": "xgboost",
  "features": ["feat1", "feat2", "..."],
  "n_features": 15,
  "accuracy_cv_mean": 0.72,
  "accuracy_cv_std": 0.02,
  "f1_cv_mean": 0.71,
  "brier_cv_mean": 0.19,
  "selection_method": "rfecv_permutation_importance",
  "cv_folds": 5,
  "stability_threshold": 0.6,
  "feature_stability": {"feat1": 1.0, "feat2": 0.8, "...": "..."},
  "decorrelation_threshold": 0.7,
  "features_before_decorrelation": 60,
  "features_after_decorrelation": 35,
  "hyperparameters": {"...": "..."},
  "source": "data/latest_features.jsonl",
  "created_at": "..."
}
```

### Notebook Structure (same for all 3)

Each notebook follows this structure:

1. **Introduction** — goal, method summary, why this approach
2. **Load data** — same as before
3. **Stage 1: Decorrelation**
   - Markdown: explain why, how, what to expect
   - Code: correlation matrix, clustering, visualization
   - Markdown: interpret results, which clusters formed
4. **Stage 2: Feature Selection**
   - Markdown: explain the method (L1 / RFECV), why it's better than the old approach
   - Code: run selection with GroupKFold
   - Markdown: interpret results, show selection curve
5. **Stage 3: Evaluation and Stability**
   - Markdown: explain stability, cross-validation metrics
   - Code: compute metrics, stability chart
   - Markdown: final feature set, comparison to old approach
6. **Save config** — JSON output
7. **Conclusion** — summary, next steps

### Dependencies

New sklearn imports needed:
- `sklearn.feature_selection.RFECV`
- `sklearn.inspection.permutation_importance`
- `sklearn.feature_selection.mutual_info_classif`
- `sklearn.model_selection.GroupKFold`
- `scipy.cluster.hierarchy` for dendrogram
- `scipy.spatial.distance` for correlation distance

All available in the current environment (sklearn 1.8.0, scipy).

## Out of Scope

- Changing the 60 features computed by `indicator_engine.py`
- Modifying the export or strategy notebooks (they consume the JSON config as before)
- Hyperparameter tuning for LR and RF (only XGB does nested CV tuning)
- Adding new features

## Impact

- `02_export` and `03_strategy` notebooks are unchanged — they read `optimal_features_*.json`
- The `ModelRunner` in the bot is unchanged — it loads exported models
- Only the `01_feature_selection` notebooks are rewritten
