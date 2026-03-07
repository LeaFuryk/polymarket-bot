"""Data models for the ml_scorer package."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class MLPrediction:
    """Result from the ML scorer."""

    up_probability: float  # 0-1 probability that UP wins
    confidence: str  # "strong_up", "lean_up", "neutral", "lean_down", "strong_down"
    feature_contributions: dict[str, float]  # feature_name -> contribution to score
    model_trained: bool  # whether the model has been trained on enough data


@dataclass
class ModelState:
    """Snapshot of model internals for dashboard / diagnostics."""

    training_samples: int
    model_trained: bool
    weights: dict[str, float]
    bias: float
    feature_names: list[str]


def sigmoid(x: float) -> float:
    """Numerically stable sigmoid function."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)
