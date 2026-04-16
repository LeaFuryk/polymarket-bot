"""Shared utilities for feature selection notebooks.

Provides decorrelation (Spearman clustering) and feature stability analysis
used by all three model-specific feature selection notebooks.
"""

from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
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
    mi_map = dict(zip(feature_cols, mi, strict=False))

    clusters: dict[int, list[str]] = {}
    for feat, label in zip(feature_cols, labels, strict=False):
        clusters.setdefault(int(label), []).append(feat)

    selected = []
    cluster_info = {}
    for cluster_id, members in sorted(clusters.items()):
        best = max(members, key=lambda f: mi_map[f])
        selected.append(best)
        cluster_info[best] = {
            "cluster_id": cluster_id,
            "cluster_size": len(members),
            "dropped": [m for m in members if m != best],
            "mutual_info": round(mi_map[best], 6),
        }

    return sorted(selected), cluster_info


def plot_correlation_matrix(
    df: pd.DataFrame,
    features: list[str],
    title: str = "Correlation Matrix",
) -> None:
    """Plot Spearman correlation heatmap."""
    corr = df[features].corr(method="spearman")
    size = max(8, len(features) * 0.3)
    fig, ax = plt.subplots(figsize=(size, size * 0.8))
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


def plot_stability(
    stability: dict[str, float],
    threshold: float = 0.6,
    title: str = "Feature Stability",
) -> None:
    """Bar chart of feature selection frequency across folds."""
    sorted_items = sorted(stability.items(), key=lambda x: -x[1])
    # Only show features selected at least once
    sorted_items = [(n, s) for n, s in sorted_items if s > 0]
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
