# Feature Selection Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite all 3 feature selection notebooks (`lr/`, `rf/`, `xgb/`) with a proper ML pipeline: decorrelation → model-appropriate selection → cross-validated evaluation with stability analysis.

**Architecture:** A shared `notebooks/feature_utils.py` helper provides the decorrelation and stability logic. Each notebook imports it and adds model-specific selection (L1 path for LR, RFECV with permutation importance for RF/XGB). All use `GroupKFold(n_splits=5)` grouped by `candle_id`. Every decision is documented in markdown cells.

**Tech Stack:** Python 3.11+, scikit-learn 1.8 (RFECV, permutation_importance, mutual_info_classif, GroupKFold), scipy (hierarchy clustering), matplotlib, xgboost

**Spec:** `docs/superpowers/specs/2026-04-16-feature-selection-pipeline-design.md`

---

### File Structure

```
notebooks/
├── feature_utils.py              # NEW: shared decorrelation + stability helpers
├── lr/01_feature_selection.ipynb  # REWRITE: L1 path + GroupKFold
├── rf/01_feature_selection.ipynb  # REWRITE: RFECV + permutation importance
└── xgb/01_feature_selection.ipynb # REWRITE: RFECV + nested CV
```

No other files are changed. The `02_export` and `03_strategy` notebooks consume `data/optimal_features_*.json` as before — the output format is backward compatible with added metadata fields.

---

### Task 1: Create `feature_utils.py` — shared decorrelation and stability helpers

**Files:**
- Create: `notebooks/feature_utils.py`

- [ ] **Step 1: Create the helper module**

```python
"""Shared utilities for feature selection notebooks.

Provides decorrelation (Spearman clustering) and feature stability analysis
used by all three model-specific feature selection notebooks.
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import linkage, fcluster
from scipy.spatial.distance import squareform
from sklearn.feature_selection import mutual_info_classif


def decorrelate_features(
    df: pd.DataFrame,
    feature_cols: list[str],
    target: np.ndarray,
    threshold: float = 0.7,
) -> tuple[list[str], dict]:
    """Collapse correlated features into cluster representatives.

    For each cluster of features with |Spearman ρ| > threshold,
    keeps the feature with highest mutual information with the target.

    Args:
        df: DataFrame with feature columns.
        feature_cols: List of feature column names.
        target: Binary target array (0/1).
        threshold: Correlation threshold for clustering.

    Returns:
        Tuple of (selected feature names, metadata dict with cluster info).
    """
    # Spearman correlation matrix
    corr = df[feature_cols].corr(method="spearman").abs()

    # Convert to distance matrix and cluster
    dist = 1 - corr.values
    np.fill_diagonal(dist, 0)
    dist = np.clip(dist, 0, None)  # numerical safety
    condensed = squareform(dist)
    Z = linkage(condensed, method="average")
    labels = fcluster(Z, t=1 - threshold, criterion="distance")

    # For each cluster, pick the feature with highest mutual info
    mi = mutual_info_classif(df[feature_cols].fillna(0), target, random_state=42)
    mi_map = dict(zip(feature_cols, mi))

    clusters: dict[int, list[str]] = {}
    for feat, label in zip(feature_cols, labels):
        clusters.setdefault(label, []).append(feat)

    selected = []
    cluster_info = {}
    for cluster_id, members in sorted(clusters.items()):
        best = max(members, key=lambda f: mi_map[f])
        selected.append(best)
        cluster_info[best] = {
            "cluster_id": int(cluster_id),
            "cluster_size": len(members),
            "dropped": [m for m in members if m != best],
            "mutual_info": round(mi_map[best], 6),
        }

    return sorted(selected), cluster_info


def plot_correlation_matrix(df: pd.DataFrame, features: list[str], title: str = "Correlation Matrix") -> None:
    """Plot Spearman correlation heatmap."""
    corr = df[features].corr(method="spearman")
    fig, ax = plt.subplots(figsize=(max(8, len(features) * 0.3), max(6, len(features) * 0.25)))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    ax.set_xticks(range(len(features)))
    ax.set_yticks(range(len(features)))
    ax.set_xticklabels(features, rotation=90, fontsize=7)
    ax.set_yticklabels(features, fontsize=7)
    ax.set_title(title)
    plt.colorbar(im, ax=ax, shrink=0.8)
    plt.tight_layout()
    plt.show()


def feature_stability_report(
    fold_features: list[list[str]],
    all_features: list[str],
    threshold: float = 0.6,
) -> tuple[list[str], dict[str, float]]:
    """Compute feature selection stability across CV folds.

    Args:
        fold_features: List of selected feature lists, one per fold.
        all_features: All candidate features.
        threshold: Minimum selection frequency to be "stable".

    Returns:
        Tuple of (stable feature names, stability scores dict).
    """
    n_folds = len(fold_features)
    counts: dict[str, int] = {f: 0 for f in all_features}
    for features in fold_features:
        for f in features:
            counts[f] = counts.get(f, 0) + 1

    stability = {f: counts[f] / n_folds for f in all_features}
    stable = sorted([f for f, s in stability.items() if s >= threshold])

    return stable, stability


def plot_stability(stability: dict[str, float], threshold: float = 0.6, title: str = "Feature Stability") -> None:
    """Bar chart of feature selection frequency across folds."""
    sorted_items = sorted(stability.items(), key=lambda x: -x[1])
    names = [x[0] for x in sorted_items]
    scores = [x[1] for x in sorted_items]

    fig, ax = plt.subplots(figsize=(10, max(4, len(names) * 0.3)))
    colors = ["#2ecc71" if s >= threshold else "#95a5a6" for s in scores]
    ax.barh(range(len(names)), scores, color=colors, edgecolor="white")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.axvline(threshold, color="red", linestyle="--", alpha=0.5, label=f"threshold={threshold}")
    ax.set_xlabel("Selection Frequency Across Folds")
    ax.set_title(title)
    ax.set_xlim(0, 1.05)
    ax.legend()
    ax.invert_yaxis()
    plt.tight_layout()
    plt.show()
```

- [ ] **Step 2: Verify imports work**

Run: `cd notebooks && uv run python -c "from feature_utils import decorrelate_features, feature_stability_report; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add notebooks/feature_utils.py
git commit -m "feat: add shared feature selection utilities (decorrelation, stability)"
```

---

### Task 2: Rewrite `lr/01_feature_selection.ipynb` — L1 Regularization Path

**Files:**
- Rewrite: `notebooks/lr/01_feature_selection.ipynb`

This is a complete notebook rewrite. The notebook is built programmatically as a Python script that generates the `.ipynb` JSON.

- [ ] **Step 1: Write the notebook generator script**

Create a Python script that builds the notebook with these cells (in order):

**Cell 0 (markdown):**
```markdown
# LogisticRegression — Feature Selection

**Method:** L1 Regularization Path (Lasso)

**Why L1 instead of forward selection?**
- Forward selection is O(N²) — trains N×N models. With 60 features, that's 1,830 model fits on a single split.
- L1 regularization naturally performs feature selection by driving coefficients to exactly zero.
- It handles correlated features gracefully — from a group of correlated features, L1 picks one and zeros the others.
- Combined with cross-validation, it gives reliable feature importance that doesn't overfit to one split.

**Pipeline:**
1. Decorrelation: collapse redundant features (Spearman clustering, threshold=0.7)
2. L1 path: scan regularization strength C, find features that survive shrinkage
3. GroupKFold(5) cross-validation grouped by candle_id
4. Stability analysis: only keep features selected in ≥60% of folds
```

**Cell 1 (code): Imports**
```python
import sys
sys.path.insert(0, str(__import__("pathlib").Path.cwd().parent))

import json as _json
import random
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, brier_score_loss
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

from feature_utils import (
    decorrelate_features,
    feature_stability_report,
    plot_correlation_matrix,
    plot_stability,
)

random.seed(42)
np.random.seed(42)

FEATURES_PATH = Path("../../data/latest_features.jsonl")
```

**Cell 2 (markdown):** `## 1. Load data`

**Cell 3 (code): Load data**
```python
rows = []
with open(FEATURES_PATH) as f:
    for line in f:
        rows.append(_json.loads(line))

df = pd.DataFrame(rows)
df["target"] = (df["outcome"] == "UP").astype(int)

NON_FEAT = {
    "candle_id", "session", "timestamp", "elapsed_pct", "btc_price",
    "up_best_bid", "up_best_ask", "up_bid_depth", "up_ask_depth",
    "down_best_bid", "down_best_ask", "down_bid_depth", "down_ask_depth",
    "market_volume", "outcome", "target",
}
all_feat_cols = sorted([c for c in df.columns if c not in NON_FEAT])
df[all_feat_cols] = df[all_feat_cols].fillna(0.0)

print(f"Features: {len(all_feat_cols)}")
print(f"Candles: {df['candle_id'].nunique()}")
print(f"Rows: {len(df):,}")
```

**Cell 4 (markdown):**
```markdown
## 2. Stage 1: Decorrelation

Many features are highly correlated — especially the price-proxy features (`up_risk_reward`, `down_risk_reward`, `rr_spread`, `up_implied_probability`, etc.) which all encode "which side is the market favorite."

Correlated features cause problems:
- **Inflated importance**: models split credit between redundant features
- **Unstable selection**: which correlated feature gets picked varies by random split
- **Crowding out**: redundant price features fill the top-N, preventing technical indicators from being selected

We fix this by clustering features with Spearman |ρ| > 0.7 and keeping only the cluster representative with highest mutual information with the target.
```

**Cell 5 (code): Decorrelation**
```python
# Show correlation before decorrelation
plot_correlation_matrix(df, all_feat_cols, "Before Decorrelation (all 60 features)")

# Decorrelate
decorr_features, cluster_info = decorrelate_features(
    df, all_feat_cols, df["target"].values, threshold=0.7,
)

print(f"\nBefore: {len(all_feat_cols)} features")
print(f"After:  {len(decorr_features)} features ({len(all_feat_cols) - len(decorr_features)} dropped)")
print(f"\nClusters with >1 member (collapsed):")
for feat, info in sorted(cluster_info.items(), key=lambda x: -x[1]["cluster_size"]):
    if info["cluster_size"] > 1:
        print(f"  {feat} (MI={info['mutual_info']:.4f}) ← kept from {info['cluster_size']} features")
        print(f"    dropped: {info['dropped']}")

# Show correlation after
plot_correlation_matrix(df, decorr_features, f"After Decorrelation ({len(decorr_features)} features)")
```

**Cell 6 (markdown):**
```markdown
## 3. Stage 2: L1 Regularization Path

L1 (Lasso) regularization adds a penalty proportional to the absolute value of coefficients.
As we increase regularization (lower C), more coefficients are driven to exactly zero.

We scan a range of C values using GroupKFold(5) cross-validation:
- At each C, train LR with L1 penalty on 4 folds, evaluate on the 5th
- Record which features have non-zero coefficients and the CV accuracy
- The optimal C is the one with highest mean CV accuracy

This replaces the old O(N²) forward selection with an O(N_C × K) approach where N_C is the number of C values tested and K is the number of folds.
```

**Cell 7 (code): L1 path with GroupKFold**
```python
C_values = np.logspace(-3, 1, 25)
gkf = GroupKFold(n_splits=5)
groups = df["candle_id"].values

results = []
fold_selected_features = {c_val: [] for c_val in C_values}

for c_val in C_values:
    fold_accs = []
    fold_f1s = []
    fold_briers = []
    fold_feats = []

    for train_idx, val_idx in gkf.split(df, df["target"], groups=groups):
        X_train = df.iloc[train_idx][decorr_features].values
        X_val = df.iloc[val_idx][decorr_features].values
        y_train = df.iloc[train_idx]["target"].values
        y_val = df.iloc[val_idx]["target"].values

        scaler = StandardScaler()
        X_train = scaler.fit_transform(X_train)
        X_val = scaler.transform(X_val)

        model = LogisticRegression(C=c_val, penalty="l1", solver="saga", max_iter=2000, random_state=42)
        model.fit(X_train, y_train)

        probs = model.predict_proba(X_val)[:, 1]
        preds = (probs >= 0.5).astype(int)

        fold_accs.append(accuracy_score(y_val, preds))
        fold_f1s.append(f1_score(y_val, preds))
        fold_briers.append(brier_score_loss(y_val, probs))

        # Which features survived L1?
        nonzero = [decorr_features[i] for i in range(len(decorr_features)) if abs(model.coef_[0][i]) > 1e-6]
        fold_feats.append(nonzero)

    results.append({
        "C": c_val,
        "acc_mean": np.mean(fold_accs),
        "acc_std": np.std(fold_accs),
        "f1_mean": np.mean(fold_f1s),
        "brier_mean": np.mean(fold_briers),
        "n_features_mean": np.mean([len(ff) for ff in fold_feats]),
    })
    fold_selected_features[c_val] = fold_feats

results_df = pd.DataFrame(results)

# Find best C
best_idx = results_df["acc_mean"].idxmax()
best_C = results_df.loc[best_idx, "C"]
best_acc = results_df.loc[best_idx, "acc_mean"]
best_n = results_df.loc[best_idx, "n_features_mean"]

print(f"Best C={best_C:.4f}: accuracy={best_acc*100:.1f}% ± {results_df.loc[best_idx, 'acc_std']*100:.1f}%, ~{best_n:.0f} features")
```

**Cell 8 (code): Plot L1 path**
```python
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

axes[0].semilogx(results_df["C"], results_df["acc_mean"] * 100, "o-", color="steelblue")
axes[0].fill_between(
    results_df["C"],
    (results_df["acc_mean"] - results_df["acc_std"]) * 100,
    (results_df["acc_mean"] + results_df["acc_std"]) * 100,
    alpha=0.2,
)
axes[0].axvline(best_C, color="green", linestyle="--", alpha=0.5, label=f"best C={best_C:.4f}")
axes[0].set_xlabel("C (regularization strength)")
axes[0].set_ylabel("CV Accuracy (%)")
axes[0].set_title("L1 Path: Accuracy vs Regularization")
axes[0].legend()
axes[0].grid(alpha=0.3)

axes[1].semilogx(results_df["C"], results_df["n_features_mean"], "o-", color="darkorange")
axes[1].axvline(best_C, color="green", linestyle="--", alpha=0.5)
axes[1].set_xlabel("C (regularization strength)")
axes[1].set_ylabel("Number of Features (mean across folds)")
axes[1].set_title("L1 Path: Feature Count vs Regularization")
axes[1].grid(alpha=0.3)

plt.suptitle("LogisticRegression L1 Feature Selection", fontsize=13)
plt.tight_layout()
plt.show()
```

**Cell 9 (markdown):**
```markdown
## 4. Stage 3: Stability Analysis

A feature selected in only 1 out of 5 folds is noise — it happened to help on that particular split but doesn't generalize. A feature selected in 5/5 folds is genuine signal.

We take the features selected at the optimal C across all 5 folds, and keep only those selected in ≥60% of folds.
```

**Cell 10 (code): Stability analysis**
```python
best_fold_feats = fold_selected_features[best_C]

stable_features, stability_scores = feature_stability_report(
    best_fold_feats, decorr_features, threshold=0.6,
)

plot_stability(stability_scores, threshold=0.6, title="LR Feature Stability (L1 at optimal C)")

print(f"\nStable features (selected in ≥60% of folds): {len(stable_features)}")
for f in stable_features:
    print(f"  {f}: {stability_scores[f]*100:.0f}%")
```

**Cell 11 (code): Final evaluation**
```python
# Evaluate the stable feature set with GroupKFold
accs, f1s, briers = [], [], []

for train_idx, val_idx in gkf.split(df, df["target"], groups=groups):
    X_train = df.iloc[train_idx][stable_features].values
    X_val = df.iloc[val_idx][stable_features].values
    y_train = df.iloc[train_idx]["target"].values
    y_val = df.iloc[val_idx]["target"].values

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_val = scaler.transform(X_val)

    model = LogisticRegression(C=best_C, penalty="l1", solver="saga", max_iter=2000, random_state=42)
    model.fit(X_train, y_train)
    probs = model.predict_proba(X_val)[:, 1]
    preds = (probs >= 0.5).astype(int)

    accs.append(accuracy_score(y_val, preds))
    f1s.append(f1_score(y_val, preds))
    briers.append(brier_score_loss(y_val, probs))

print(f"Final CV results with {len(stable_features)} stable features:")
print(f"  Accuracy: {np.mean(accs)*100:.1f}% ± {np.std(accs)*100:.1f}%")
print(f"  F1:       {np.mean(f1s)*100:.1f}% ± {np.std(f1s)*100:.1f}%")
print(f"  Brier:    {np.mean(briers):.4f} ± {np.std(briers):.4f}")
```

**Cell 12 (markdown):** `## 5. Save config`

**Cell 13 (code): Save JSON**
```python
config = {
    "model": "logistic_regression",
    "features": stable_features,
    "n_features": len(stable_features),
    "accuracy_cv_mean": round(float(np.mean(accs)), 4),
    "accuracy_cv_std": round(float(np.std(accs)), 4),
    "f1_cv_mean": round(float(np.mean(f1s)), 4),
    "brier_cv_mean": round(float(np.mean(briers)), 4),
    "selection_method": "l1_regularization_path",
    "cv_folds": 5,
    "stability_threshold": 0.6,
    "feature_stability": {f: round(stability_scores[f], 2) for f in stable_features},
    "decorrelation_threshold": 0.7,
    "features_before_decorrelation": len(all_feat_cols),
    "features_after_decorrelation": len(decorr_features),
    "hyperparameters": {"C": round(float(best_C), 6), "penalty": "l1", "solver": "saga", "max_iter": 2000},
    "source": "data/latest_features.jsonl",
    "created_at": datetime.now(timezone.utc).isoformat(),
}

out_path = Path("../../data/optimal_features_lr.json")
with open(out_path, "w") as f:
    _json.dump(config, f, indent=2)

print(f"Saved {config['n_features']} LR features to {out_path}")
```

**Cell 14 (markdown):**
```markdown
## Conclusion

Feature selection pipeline:
1. **Decorrelation**: collapsed correlated features using Spearman clustering (threshold=0.7)
2. **L1 path**: scanned 25 regularization strengths with GroupKFold(5)
3. **Stability**: kept features selected in ≥60% of folds

This replaces the old O(N²) forward selection on a single split with a cross-validated, stability-checked approach that handles correlated features naturally.
```

- [ ] **Step 2: Generate the notebook**

Run a Python script that builds the notebook JSON from the cells above and writes to `notebooks/lr/01_feature_selection.ipynb`.

- [ ] **Step 3: Commit**

```bash
git add notebooks/lr/01_feature_selection.ipynb
git commit -m "feat: rewrite LR feature selection — L1 path + GroupKFold + stability"
```

---

### Task 3: Rewrite `rf/01_feature_selection.ipynb` — RFECV with Permutation Importance

**Files:**
- Rewrite: `notebooks/rf/01_feature_selection.ipynb`

Same structure as Task 2 but with RF-specific selection. Key differences:

**Cell 0 (markdown):** Title explains RFECV with permutation importance, why not impurity importance (sklearn docs warn it's biased by correlation and cardinality).

**Stage 2 cells use RFECV:**
```python
from sklearn.feature_selection import RFECV
from sklearn.inspection import permutation_importance
from sklearn.ensemble import RandomForestClassifier

gkf = GroupKFold(n_splits=5)
groups = df["candle_id"].values

RF_PARAMS = {
    "n_estimators": 200,
    "max_depth": 15,
    "min_samples_leaf": 20,
    "random_state": 42,
    "n_jobs": -1,
}

# RFECV: iteratively removes least important feature, cross-validates at each step
scaler = StandardScaler()
X_scaled = scaler.fit_transform(df[decorr_features].values)
y = df["target"].values

rfecv = RFECV(
    estimator=RandomForestClassifier(**RF_PARAMS),
    step=1,
    cv=gkf,
    scoring="accuracy",
    min_features_to_select=5,
    n_jobs=-1,
)
rfecv.fit(X_scaled, y, groups=groups)

rfecv_features = [decorr_features[i] for i in range(len(decorr_features)) if rfecv.support_[i]]
print(f"RFECV selected {len(rfecv_features)} features")
print(f"CV accuracy: {rfecv.cv_results_['mean_test_score'].max()*100:.1f}%")
```

**Stability analysis:** Run RFECV on each fold independently, collect selected features, apply stability threshold.

```python
fold_features = []
fold_accs = []
fold_f1s = []
fold_briers = []

for train_idx, val_idx in gkf.split(df, y, groups=groups):
    X_train = scaler.fit_transform(df.iloc[train_idx][decorr_features].values)
    X_val = scaler.transform(df.iloc[val_idx][decorr_features].values)
    y_train = df.iloc[train_idx]["target"].values
    y_val = df.iloc[val_idx]["target"].values

    rf = RandomForestClassifier(**RF_PARAMS)
    rf.fit(X_train, y_train)

    # Permutation importance (not impurity)
    perm_imp = permutation_importance(rf, X_val, y_val, n_repeats=10, random_state=42, n_jobs=-1)
    imp_mean = perm_imp.importances_mean

    # Select features with positive permutation importance
    selected = [decorr_features[i] for i in range(len(decorr_features)) if imp_mean[i] > 0]
    fold_features.append(selected)

    # Evaluate
    probs = rf.predict_proba(X_val)[:, 1]
    preds = (probs >= 0.5).astype(int)
    fold_accs.append(accuracy_score(y_val, preds))
    fold_f1s.append(f1_score(y_val, preds))
    fold_briers.append(brier_score_loss(y_val, probs))

stable_features, stability_scores = feature_stability_report(
    fold_features, decorr_features, threshold=0.6,
)
```

**JSON output** includes `"selection_method": "rfecv_permutation_importance"`.

- [ ] **Step 1: Generate the notebook** (same script pattern as Task 2)

- [ ] **Step 2: Commit**

```bash
git add notebooks/rf/01_feature_selection.ipynb
git commit -m "feat: rewrite RF feature selection — RFECV + permutation importance + stability"
```

---

### Task 4: Rewrite `xgb/01_feature_selection.ipynb` — RFECV with Nested CV

**Files:**
- Rewrite: `notebooks/xgb/01_feature_selection.ipynb`

Same structure but with nested cross-validation for hyperparameter tuning.

**Key difference from RF:** XGB needs hyperparameter tuning. The old approach tuned on the validation set and evaluated on the same set (information leakage). Nested CV fixes this:

**Cell 7 (markdown):**
```markdown
## 3. Stage 2: Feature Selection with Nested CV

**Why nested CV?** XGBoost has many hyperparameters (learning_rate, max_depth, etc.) that need tuning. If we tune on the same data we evaluate on, we get inflated accuracy estimates.

Nested CV uses two loops:
- **Outer loop** (GroupKFold, 5 folds): evaluates feature selection + model performance
- **Inner loop** (GroupKFold, 3 folds): tunes hyperparameters within each outer training fold

This ensures the performance estimate is never contaminated by tuning decisions.
```

**Stage 2 code:**
```python
import xgboost as xgb
from sklearn.model_selection import GridSearchCV

gkf_outer = GroupKFold(n_splits=5)
gkf_inner = GroupKFold(n_splits=3)
groups = df["candle_id"].values
y = df["target"].values

param_grid = {
    "learning_rate": [0.01, 0.05],
    "max_depth": [3, 6],
    "min_child_weight": [10, 20],
    "subsample": [0.7, 0.8],
    "colsample_bytree": [0.7, 0.8],
}

fold_features = []
fold_accs = []
fold_f1s = []
fold_briers = []
fold_params = []

for fold_i, (train_idx, val_idx) in enumerate(gkf_outer.split(df, y, groups=groups)):
    print(f"\n--- Outer fold {fold_i + 1}/5 ---")
    X_train_raw = df.iloc[train_idx][decorr_features].values
    X_val_raw = df.iloc[val_idx][decorr_features].values
    y_train = df.iloc[train_idx]["target"].values
    y_val = df.iloc[val_idx]["target"].values
    groups_train = df.iloc[train_idx]["candle_id"].values

    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train_raw)
    X_val = scaler.transform(X_val_raw)

    # Inner CV: tune hyperparameters
    inner_search = GridSearchCV(
        xgb.XGBClassifier(n_estimators=200, eval_metric="logloss", random_state=42, n_jobs=-1),
        param_grid,
        cv=gkf_inner,
        scoring="accuracy",
        n_jobs=-1,
    )
    inner_search.fit(X_train, y_train, groups=groups_train)
    best_params = inner_search.best_params_
    fold_params.append(best_params)
    print(f"  Best params: {best_params}")

    # Train with best params, get permutation importance
    best_model = xgb.XGBClassifier(
        n_estimators=200, eval_metric="logloss", random_state=42, n_jobs=-1, **best_params,
    )
    best_model.fit(X_train, y_train)

    perm_imp = permutation_importance(best_model, X_val, y_val, n_repeats=10, random_state=42, n_jobs=-1)
    selected = [decorr_features[i] for i in range(len(decorr_features)) if perm_imp.importances_mean[i] > 0]
    fold_features.append(selected)

    # Evaluate
    probs = best_model.predict_proba(X_val)[:, 1]
    preds = (probs >= 0.5).astype(int)
    fold_accs.append(accuracy_score(y_val, preds))
    fold_f1s.append(f1_score(y_val, preds))
    fold_briers.append(brier_score_loss(y_val, probs))
    print(f"  Features: {len(selected)}, Acc: {fold_accs[-1]*100:.1f}%")
```

**JSON output** includes `"selection_method": "nested_cv_permutation_importance"` and the most common hyperparameters across folds.

- [ ] **Step 1: Generate the notebook**

- [ ] **Step 2: Commit**

```bash
git add notebooks/xgb/01_feature_selection.ipynb
git commit -m "feat: rewrite XGB feature selection — nested CV + permutation importance + stability"
```

---

### Task 5: Verify all 3 notebooks run without errors

- [ ] **Step 1: Run LR notebook**

```bash
cd notebooks/lr && uv run jupyter nbconvert --to notebook --execute 01_feature_selection.ipynb --output /tmp/lr_test.ipynb
```

Check: no errors, JSON config written to `data/optimal_features_lr.json`.

- [ ] **Step 2: Run RF notebook**

```bash
cd notebooks/rf && uv run jupyter nbconvert --to notebook --execute 01_feature_selection.ipynb --output /tmp/rf_test.ipynb
```

- [ ] **Step 3: Run XGB notebook**

```bash
cd notebooks/xgb && uv run jupyter nbconvert --to notebook --execute 01_feature_selection.ipynb --output /tmp/xgb_test.ipynb
```

- [ ] **Step 4: Verify JSON outputs**

```bash
for f in data/optimal_features_*.json; do echo "=== $f ===" && python3 -c "import json; d=json.load(open('$f')); print(f'  features: {d[\"n_features\"]}'); print(f'  method: {d[\"selection_method\"]}'); print(f'  cv_folds: {d.get(\"cv_folds\", \"N/A\")}'); print(f'  accuracy: {d.get(\"accuracy_cv_mean\", \"N/A\")}')"; done
```

- [ ] **Step 5: Commit any fixes**

```bash
git add -A notebooks/ data/optimal_features_*.json
git commit -m "feat: verify all feature selection notebooks run cleanly"
```
