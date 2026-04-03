"""Evaluator for binary outcome prediction models (UP/DOWN).

Adapted from the LLM Engineering course's Tester/evaluate pattern,
but specialized for Polymarket candle outcome prediction.

Usage:
    from evaluator import Evaluator
    ev = Evaluator(y_true, y_pred, y_prob, title="My Model")
    ev.report()           # prints metrics
    ev.chart()            # actual vs predicted scatter
    ev.error_chart()      # error distribution histogram
    ev.confusion_chart()  # confusion matrix heatmap
"""

from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)


class Evaluator:
    """Evaluate a binary classifier with both regression and classification metrics.

    The model predicts a continuous score (probability of UP), which is
    thresholded at 0.5 to produce the binary prediction.

    Args:
        y_true:   array of true labels (1=UP, 0=DOWN)
        y_pred:   array of binary predictions (1=UP, 0=DOWN)
        y_prob:   array of predicted probabilities (continuous, 0-1 range)
        title:    display name for charts and reports
    """

    def __init__(
        self,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        y_prob: np.ndarray,
        title: str = "Model",
    ) -> None:
        self.y_true = np.asarray(y_true)
        self.y_pred = np.asarray(y_pred)
        self.y_prob = np.asarray(y_prob)
        self.title = title

        # Regression metrics (on probability vs binary truth)
        self.mse = mean_squared_error(self.y_true, self.y_prob)
        self.r2 = r2_score(self.y_true, self.y_prob)
        self.mae = float(np.mean(np.abs(self.y_true - self.y_prob)))

        # Classification metrics
        self.accuracy = accuracy_score(self.y_true, self.y_pred)
        self.precision = precision_score(self.y_true, self.y_pred, zero_division=0)
        self.recall = recall_score(self.y_true, self.y_pred, zero_division=0)
        self.f1 = f1_score(self.y_true, self.y_pred, zero_division=0)

    def report(self) -> None:
        """Print a formatted metrics report."""
        print(f"=== {self.title} ===")
        print(f"  Regression:      MSE={self.mse:.4f}  R²={self.r2 * 100:.1f}%  MAE={self.mae:.4f}")
        print(
            f"  Classification:  Accuracy={self.accuracy * 100:.1f}%  "
            f"Precision={self.precision * 100:.1f}%  Recall={self.recall * 100:.1f}%  "
            f"F1={self.f1 * 100:.1f}%"
        )
        print(
            f"  Samples:         {len(self.y_true)} (UP={int(self.y_true.sum())}, DOWN={int((1 - self.y_true).sum())})"
        )

    def chart(self, ax=None) -> None:
        """Scatter plot: predicted probability vs true label."""
        import matplotlib.pyplot as plt

        if ax is None:
            _, ax = plt.subplots(figsize=(10, 5))
        colors = ["#2ecc71" if p == t else "#e74c3c" for p, t in zip(self.y_pred, self.y_true, strict=True)]
        ax.scatter(range(len(self.y_prob)), self.y_prob, c=colors, alpha=0.3, s=4)
        ax.axhline(0.5, color="gray", linestyle="--", linewidth=1, label="threshold=0.5")
        ax.set_xlabel("Sample Index")
        ax.set_ylabel("Predicted Probability (UP)")
        ax.set_title(f"{self.title}\nAccuracy={self.accuracy * 100:.1f}%  MSE={self.mse:.4f}  R²={self.r2 * 100:.1f}%")
        ax.legend(["threshold", "correct", "incorrect"])
        ax.set_ylim(-0.1, 1.1)

    def error_chart(self, ax=None) -> None:
        """Histogram of prediction errors (prob - truth)."""
        import matplotlib.pyplot as plt

        if ax is None:
            _, ax = plt.subplots(figsize=(10, 4))
        errors = self.y_prob - self.y_true
        ax.hist(errors, bins=50, color="steelblue", edgecolor="white", alpha=0.8)
        ax.axvline(0, color="red", linestyle="--", linewidth=1)
        ax.axvline(np.mean(errors), color="orange", linestyle="--", label=f"mean={np.mean(errors):.4f}")
        ax.set_xlabel("Error (predicted - actual)")
        ax.set_ylabel("Count")
        ax.set_title(f"{self.title} — Error Distribution (MAE={self.mae:.4f})")
        ax.legend()

    def confusion_chart(self, ax=None) -> None:
        """Confusion matrix heatmap."""
        import matplotlib.pyplot as plt

        if ax is None:
            _, ax = plt.subplots(figsize=(5, 4))
        cm = confusion_matrix(self.y_true, self.y_pred)
        im = ax.imshow(cm, cmap="Blues")
        ax.set_xticks([0, 1])
        ax.set_yticks([0, 1])
        ax.set_xticklabels(["DOWN", "UP"])
        ax.set_yticklabels(["DOWN", "UP"])
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual")
        ax.set_title(f"{self.title} — Confusion Matrix")
        for i in range(2):
            for j in range(2):
                ax.text(
                    j,
                    i,
                    str(cm[i, j]),
                    ha="center",
                    va="center",
                    color="white" if cm[i, j] > cm.max() / 2 else "black",
                    fontsize=14,
                )
        plt.colorbar(im, ax=ax)

    def full_report(self) -> None:
        """Print metrics + show all three charts."""
        import matplotlib.pyplot as plt

        self.report()
        fig, axes = plt.subplots(1, 3, figsize=(18, 5))
        self.chart(axes[0])
        self.error_chart(axes[1])
        self.confusion_chart(axes[2])
        plt.tight_layout()
        plt.show()
