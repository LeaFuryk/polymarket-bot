"""Hybrid ML scorer — logistic regression on computed features.

Provides a fast, cheap baseline prediction for BTC 5-min candle direction
using a simple logistic regression model trained on historical outcomes.
The ML score is passed to Claude as additional context, not as a replacement.
"""

from polybot.ml_scorer.constants import FEATURE_NAMES, NUM_FEATURES
from polybot.ml_scorer.feature_extractor import FeatureExtractor
from polybot.ml_scorer.models import MLPrediction, ModelState
from polybot.ml_scorer.scorer import MLScorer

__all__ = [
    # Core
    "MLScorer",
    "FeatureExtractor",
    # Models
    "MLPrediction",
    "ModelState",
    # Constants
    "FEATURE_NAMES",
    "NUM_FEATURES",
]
