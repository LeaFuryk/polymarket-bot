"""Online logistic regression scorer.

Trains incrementally after each candle resolution.  No external ML
libraries needed — pure Python implementation for minimal dependencies.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from polybot.ml_scorer.constants import (
    FEATURE_NAMES,
    LEAN_DOWN_THRESHOLD,
    LEAN_UP_THRESHOLD,
    MIN_TRAINING_SAMPLES,
    NUM_FEATURES,
    STRONG_DOWN_THRESHOLD,
    STRONG_UP_THRESHOLD,
)
from polybot.ml_scorer.feature_extractor import FeatureExtractor
from polybot.ml_scorer.models import MLPrediction, ModelState, sigmoid

DEFAULT_LEARNING_RATE = 0.01


class MLScorer:
    """Online logistic regression for BTC 5-min candle direction prediction.

    Trains incrementally after each resolution.  No external ML libraries
    needed.

    Args:
        data_dir: Directory for model persistence (``ml_model.json``).
        learning_rate: SGD learning rate.
        logger: Optional logger; defaults to module-level logger.
    """

    def __init__(
        self,
        data_dir: str | Path,
        learning_rate: float = DEFAULT_LEARNING_RATE,
        logger: logging.Logger | None = None,
    ) -> None:
        self._log = logger or logging.getLogger(__name__)
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._model_path = self._data_dir / "ml_model.json"
        self._learning_rate = learning_rate

        # Model weights (initialized to zero)
        self._weights: list[float] = [0.0] * NUM_FEATURES
        self._bias: float = 0.0
        self._training_samples: int = 0
        self._min_samples = MIN_TRAINING_SAMPLES

        self._feature_extractor = FeatureExtractor()

        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict(self, features: dict[str, float]) -> MLPrediction:
        """Predict UP probability from features.

        Args:
            features: dict mapping feature names to values.

        Returns:
            MLPrediction with UP probability and confidence level.
        """
        x_norm = FeatureExtractor.normalize(FeatureExtractor.to_vector(features))

        score = self._compute_score(x_norm)
        prob = sigmoid(score)

        contributions = {name: round(self._weights[i] * x_norm[i], 4) for i, name in enumerate(FEATURE_NAMES)}

        confidence = self._classify_confidence(prob)
        trained = self._training_samples >= self._min_samples

        return MLPrediction(
            up_probability=round(prob, 4),
            confidence=confidence,
            feature_contributions=contributions,
            model_trained=trained,
        )

    def train(self, features: dict[str, float], up_won: bool) -> None:
        """Update model weights based on one resolution outcome.

        Uses online gradient descent on binary cross-entropy loss.
        """
        x_norm = FeatureExtractor.normalize(FeatureExtractor.to_vector(features))

        y = 1.0 if up_won else 0.0
        score = self._compute_score(x_norm)
        pred = sigmoid(score)

        error = pred - y

        for i in range(NUM_FEATURES):
            self._weights[i] -= self._learning_rate * error * x_norm[i]
        self._bias -= self._learning_rate * error

        self._training_samples += 1
        self._save()

        self._log.debug(
            "ML model updated: sample=%d, pred=%.3f, actual=%s, error=%.3f",
            self._training_samples,
            pred,
            "UP" if up_won else "DOWN",
            error,
        )

    def extract_features(
        self,
        candles,
        btc_price: float | None,
        candle_open: float | None,
        up_mid: float | None,
        down_mid: float | None,
        up_bid_depth: float = 0,
        up_ask_depth: float = 0,
        reversal_rate: float = 0.0,
    ) -> dict[str, float]:
        """Extract ML features from market data.

        Convenience method that delegates to :class:`FeatureExtractor`.
        """
        return self._feature_extractor.extract(
            candles=candles,
            btc_price=btc_price,
            candle_open=candle_open,
            up_mid=up_mid,
            down_mid=down_mid,
            up_bid_depth=up_bid_depth,
            up_ask_depth=up_ask_depth,
            reversal_rate=reversal_rate,
        )

    def get_summary(self) -> str:
        """Generate a summary for the AI prompt."""
        if self._training_samples < self._min_samples:
            return f"ML Model: training ({self._training_samples}/{self._min_samples} samples)"

        indexed = [(abs(w), FEATURE_NAMES[i], w) for i, w in enumerate(self._weights)]
        indexed.sort(reverse=True)
        top = indexed[:5]
        weight_str = ", ".join(f"{name}={w:+.3f}" for _, name, w in top)
        return f"ML Model ({self._training_samples} samples): bias={self._bias:+.3f}, top weights: {weight_str}"

    def get_model_state(self) -> ModelState:
        """Return a snapshot of model internals for dashboards / diagnostics."""
        return ModelState(
            training_samples=self._training_samples,
            model_trained=self._training_samples >= self._min_samples,
            weights={name: round(w, 4) for name, w in zip(FEATURE_NAMES, self._weights, strict=True)},
            bias=round(self._bias, 4),
            feature_names=list(FEATURE_NAMES),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_score(self, features: list[float]) -> float:
        """Compute raw logistic regression score (before sigmoid)."""
        score = self._bias
        for w, x in zip(self._weights, features, strict=True):
            score += w * x
        return score

    @staticmethod
    def _classify_confidence(prob: float) -> str:
        if prob > STRONG_UP_THRESHOLD:
            return "strong_up"
        if prob > LEAN_UP_THRESHOLD:
            return "lean_up"
        if prob < STRONG_DOWN_THRESHOLD:
            return "strong_down"
        if prob < LEAN_DOWN_THRESHOLD:
            return "lean_down"
        return "neutral"

    def _load(self) -> None:
        """Load model weights from disk."""
        if not self._model_path.exists():
            return
        try:
            data = json.loads(self._model_path.read_text())
            self._weights = data.get("weights", [0.0] * NUM_FEATURES)
            self._bias = data.get("bias", 0.0)
            self._training_samples = data.get("training_samples", 0)
            if len(self._weights) != NUM_FEATURES:
                self._log.warning("Feature count mismatch, resetting ML model")
                self._weights = [0.0] * NUM_FEATURES
                self._bias = 0.0
                self._training_samples = 0
            elif self._training_samples > 0:
                self._log.info(
                    "Loaded ML model: %d training samples, bias=%.4f",
                    self._training_samples,
                    self._bias,
                )
        except Exception:
            self._log.warning("Could not load ML model", exc_info=True)

    def _save(self) -> None:
        """Save model weights to disk."""
        try:
            self._model_path.write_text(
                json.dumps(
                    {
                        "weights": [round(w, 6) for w in self._weights],
                        "bias": round(self._bias, 6),
                        "training_samples": self._training_samples,
                        "feature_names": FEATURE_NAMES,
                    },
                    indent=2,
                )
                + "\n"
            )
        except Exception:
            self._log.warning("Could not save ML model", exc_info=True)
