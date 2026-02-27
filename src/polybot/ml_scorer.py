"""Hybrid ML scorer — logistic regression on computed features.

Provides a fast, cheap baseline prediction for BTC 5-min candle direction
using a simple logistic regression model trained on historical outcomes.
The ML score is passed to Claude as additional context, not as a replacement.

The model trains online: after each resolution, it updates weights using
gradient descent on the binary outcome. No external ML library needed —
pure Python implementation for minimal dependencies.

Features used:
- Consecutive candle streak (signed: positive=up, negative=down)
- Streak magnitude ($)
- BTC vs candle open ($)
- 30min volatility (avg range)
- Volume trend ratio
- UP token midpoint
- DOWN token midpoint
- Orderbook imbalance ratio (UP)
- Flat candle ratio
- Rolling reversal rate (from adaptive entry tracker)
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Feature names in fixed order
FEATURE_NAMES = [
    "streak_signed",      # positive=up streak, negative=down streak
    "streak_magnitude",   # $ move during streak
    "btc_vs_open",        # current BTC - candle open
    "volatility_30m",     # avg candle range
    "volume_ratio",       # recent/prior volume
    "up_midpoint",        # UP token midpoint (market-implied prob)
    "down_midpoint",      # DOWN token midpoint
    "book_imbalance",     # UP bid_depth / ask_depth
    "flat_ratio",         # fraction of flat candles
    "reversal_rate",      # rolling reversal rate from adaptive entry (0-1)
]

NUM_FEATURES = len(FEATURE_NAMES)


def _sigmoid(x: float) -> float:
    """Numerically stable sigmoid."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)


@dataclass
class MLPrediction:
    """Result from the ML scorer."""

    up_probability: float  # 0-1 probability that UP wins
    confidence: str  # "strong_up", "lean_up", "neutral", "lean_down", "strong_down"
    feature_contributions: dict[str, float]  # feature_name -> contribution to score
    model_trained: bool  # whether the model has been trained on enough data


class MLScorer:
    """Online logistic regression for BTC 5-min candle direction prediction.

    Trains incrementally after each resolution. No external ML libraries needed.
    """

    def __init__(self, data_dir: str | Path, learning_rate: float = 0.01) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._model_path = self._data_dir / "ml_model.json"
        self._learning_rate = learning_rate

        # Model weights (initialized to zero)
        self._weights: list[float] = [0.0] * NUM_FEATURES
        self._bias: float = 0.0
        self._training_samples: int = 0
        self._min_samples = 10  # minimum before trusting predictions

        self._load()

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
                # Feature set changed — reset
                logger.warning("Feature count mismatch, resetting ML model")
                self._weights = [0.0] * NUM_FEATURES
                self._bias = 0.0
                self._training_samples = 0
            elif self._training_samples > 0:
                logger.info(
                    "Loaded ML model: %d training samples, bias=%.4f",
                    self._training_samples, self._bias,
                )
        except Exception:
            logger.warning("Could not load ML model", exc_info=True)

    def _save(self) -> None:
        """Save model weights to disk."""
        try:
            self._model_path.write_text(json.dumps({
                "weights": [round(w, 6) for w in self._weights],
                "bias": round(self._bias, 6),
                "training_samples": self._training_samples,
                "feature_names": FEATURE_NAMES,
            }, indent=2) + "\n")
        except Exception:
            logger.warning("Could not save ML model", exc_info=True)

    def _compute_score(self, features: list[float]) -> float:
        """Compute raw logistic regression score (before sigmoid)."""
        score = self._bias
        for w, x in zip(self._weights, features):
            score += w * x
        return score

    def predict(self, features: dict[str, float]) -> MLPrediction:
        """Predict UP probability from features.

        Args:
            features: dict mapping feature names to values.

        Returns:
            MLPrediction with UP probability and confidence level.
        """
        # Build feature vector in fixed order
        x = [features.get(name, 0.0) for name in FEATURE_NAMES]

        # Normalize features to prevent extreme values
        x_norm = self._normalize(x)

        score = self._compute_score(x_norm)
        prob = _sigmoid(score)

        # Compute per-feature contributions
        contributions = {}
        for i, name in enumerate(FEATURE_NAMES):
            contributions[name] = round(self._weights[i] * x_norm[i], 4)

        # Classify confidence
        if prob > 0.65:
            confidence = "strong_up"
        elif prob > 0.55:
            confidence = "lean_up"
        elif prob < 0.35:
            confidence = "strong_down"
        elif prob < 0.45:
            confidence = "lean_down"
        else:
            confidence = "neutral"

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
        x = [features.get(name, 0.0) for name in FEATURE_NAMES]
        x_norm = self._normalize(x)

        y = 1.0 if up_won else 0.0
        score = self._compute_score(x_norm)
        pred = _sigmoid(score)

        # Gradient of binary cross-entropy
        error = pred - y

        # Update weights
        for i in range(NUM_FEATURES):
            self._weights[i] -= self._learning_rate * error * x_norm[i]
        self._bias -= self._learning_rate * error

        self._training_samples += 1
        self._save()

        logger.debug(
            "ML model updated: sample=%d, pred=%.3f, actual=%s, error=%.3f",
            self._training_samples, pred, "UP" if up_won else "DOWN", error,
        )

    @staticmethod
    def _normalize(x: list[float]) -> list[float]:
        """Simple feature normalization to prevent extreme gradients.

        Uses fixed scaling based on expected ranges rather than learned
        statistics (avoids cold-start issues).
        """
        scales = [
            5.0,     # streak_signed: typically -6 to +6
            200.0,   # streak_magnitude: typically -$500 to +$500
            100.0,   # btc_vs_open: typically -$200 to +$200
            100.0,   # volatility_30m: typically $10 to $300
            1.0,     # volume_ratio: typically 0.3 to 3.0 (already scaled)
            1.0,     # up_midpoint: 0 to 1
            1.0,     # down_midpoint: 0 to 1
            2.0,     # book_imbalance: typically 0.3 to 3.0
            1.0,     # flat_ratio: 0 to 1
            1.0,     # reversal_rate: 0 to 1 (already scaled)
        ]
        return [xi / s if s != 0 else xi for xi, s in zip(x, scales)]

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

        Convenience method that pulls features from raw market data
        so callers don't need to know the feature schema.
        """
        features: dict[str, float] = {}

        # Streak
        if candles:
            streak = 1
            direction = candles[-1].direction
            for c in reversed(candles[:-1]):
                if c.direction == direction:
                    streak += 1
                else:
                    break
            features["streak_signed"] = float(streak if direction == "up" else -streak)

            # Magnitude
            streak_start = len(candles) - streak
            if streak_start < len(candles):
                features["streak_magnitude"] = candles[-1].close - candles[streak_start].open
            else:
                features["streak_magnitude"] = 0.0

            # Volatility
            recent = candles[-6:] if len(candles) >= 6 else candles
            import statistics
            ranges = [c.high - c.low for c in recent]
            features["volatility_30m"] = statistics.mean(ranges) if ranges else 0.0

            # Volume trend
            if len(candles) >= 6:
                recent_3 = candles[-3:]
                prior_3 = candles[-6:-3]
                recent_vol = statistics.mean([c.volume for c in recent_3])
                prior_vol = statistics.mean([c.volume for c in prior_3])
                features["volume_ratio"] = recent_vol / prior_vol if prior_vol > 0 else 1.0
            else:
                features["volume_ratio"] = 1.0

            # Flat ratio
            flat_count = sum(1 for c in recent if abs(c.close - c.open) < 5.0)
            features["flat_ratio"] = flat_count / len(recent) if recent else 0.0
        else:
            features.update({
                "streak_signed": 0.0,
                "streak_magnitude": 0.0,
                "volatility_30m": 0.0,
                "volume_ratio": 1.0,
                "flat_ratio": 0.0,
            })

        # BTC vs candle open
        if btc_price and candle_open:
            features["btc_vs_open"] = btc_price - candle_open
        else:
            features["btc_vs_open"] = 0.0

        # Token midpoints
        features["up_midpoint"] = up_mid or 0.5
        features["down_midpoint"] = down_mid or 0.5

        # Book imbalance
        if up_ask_depth > 0:
            features["book_imbalance"] = up_bid_depth / up_ask_depth
        else:
            features["book_imbalance"] = 1.0

        # Reversal rate from adaptive entry
        features["reversal_rate"] = reversal_rate

        return features

    def get_summary(self) -> str:
        """Generate a summary for the AI prompt."""
        if self._training_samples < self._min_samples:
            return f"ML Model: training ({self._training_samples}/{self._min_samples} samples)"

        # Show top feature weights
        indexed = [(abs(w), FEATURE_NAMES[i], w) for i, w in enumerate(self._weights)]
        indexed.sort(reverse=True)
        top = indexed[:5]
        weight_str = ", ".join(
            f"{name}={w:+.3f}" for _, name, w in top
        )
        return (
            f"ML Model ({self._training_samples} samples): "
            f"bias={self._bias:+.3f}, top weights: {weight_str}"
        )
