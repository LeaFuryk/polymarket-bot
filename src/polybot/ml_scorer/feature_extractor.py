"""Feature extraction from raw market data.

Converts market observations (candle history, BTC price, order book state)
into a fixed-length feature dict used by the scorer.  Pure and stateless —
all state lives in the inputs.
"""

from __future__ import annotations

import statistics
from typing import Any

from polybot.ml_scorer.constants import (
    FEATURE_NAMES,
    FLAT_CANDLE_THRESHOLD,
    NORMALIZATION_SCALES,
    VOLATILITY_WINDOW,
    VOLUME_WINDOW,
)


class FeatureExtractor:
    """Extracts ML features from market data.

    Stateless — instantiate once and reuse.  All configuration lives in
    ``constants.py``.
    """

    def extract(
        self,
        candles: Any,
        btc_price: float | None,
        candle_open: float | None,
        up_mid: float | None,
        down_mid: float | None,
        up_bid_depth: float = 0,
        up_ask_depth: float = 0,
        reversal_rate: float = 0.0,
        btc_velocity: float = 0.0,
        velocity_conflict_severity: float = 0.0,
    ) -> dict[str, float]:
        """Extract feature dict from raw market data.

        Args:
            candles: Sequence of candle objects with .direction, .open, .close,
                     .high, .low, .volume attributes.
            btc_price: Current BTC price.
            candle_open: BTC price at candle open.
            up_mid: UP token midpoint (0-1).
            down_mid: DOWN token midpoint (0-1).
            up_bid_depth: UP bid depth from order book.
            up_ask_depth: UP ask depth from order book.
            reversal_rate: Rolling reversal rate from adaptive entry (0-1).
            btc_velocity: Current BTC velocity in $/s.
            velocity_conflict_severity: Velocity-magnitude conflict severity (0-1).

        Returns:
            Dict mapping each feature name to its raw (un-normalized) value.
        """
        features: dict[str, float] = {}

        if candles:
            self._extract_streak_features(candles, features)
            self._extract_volatility_features(candles, features)
            self._extract_volume_features(candles, features)
            self._extract_flat_ratio(candles, features)
        else:
            features.update(
                {
                    "streak_signed": 0.0,
                    "streak_magnitude": 0.0,
                    "volatility_30m": 0.0,
                    "volume_ratio": 1.0,
                    "flat_ratio": 0.0,
                }
            )

        features["btc_vs_open"] = (btc_price - candle_open) if btc_price and candle_open else 0.0
        features["up_midpoint"] = up_mid or 0.5
        features["down_midpoint"] = down_mid or 0.5
        features["book_imbalance"] = up_bid_depth / up_ask_depth if up_ask_depth > 0 else 1.0
        features["reversal_rate"] = reversal_rate
        features["btc_velocity"] = btc_velocity
        features["velocity_conflict"] = velocity_conflict_severity

        return features

    @staticmethod
    def normalize(raw: list[float]) -> list[float]:
        """Apply fixed-scale normalization to a feature vector.

        Uses pre-defined scales rather than learned statistics to avoid
        cold-start issues.
        """
        return [xi / s if s != 0 else xi for xi, s in zip(raw, NORMALIZATION_SCALES, strict=True)]

    @staticmethod
    def to_vector(features: dict[str, float]) -> list[float]:
        """Convert feature dict to a list in canonical feature order."""
        return [features.get(name, 0.0) for name in FEATURE_NAMES]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_streak_features(candles: Any, out: dict[str, float]) -> None:
        streak = 1
        direction = candles[-1].direction
        for c in reversed(candles[:-1]):
            if c.direction == direction:
                streak += 1
            else:
                break
        out["streak_signed"] = float(streak if direction == "up" else -streak)

        streak_start = len(candles) - streak
        if streak_start < len(candles):
            out["streak_magnitude"] = candles[-1].close - candles[streak_start].open
        else:
            out["streak_magnitude"] = 0.0

    @staticmethod
    def _extract_volatility_features(candles: Any, out: dict[str, float]) -> None:
        recent = candles[-VOLATILITY_WINDOW:] if len(candles) >= VOLATILITY_WINDOW else candles
        ranges = [c.high - c.low for c in recent]
        out["volatility_30m"] = statistics.mean(ranges) if ranges else 0.0

    @staticmethod
    def _extract_volume_features(candles: Any, out: dict[str, float]) -> None:
        half = VOLUME_WINDOW // 2
        if len(candles) >= VOLUME_WINDOW:
            recent_half = candles[-half:]
            prior_half = candles[-VOLUME_WINDOW:-half]
            recent_vol = statistics.mean([c.volume for c in recent_half])
            prior_vol = statistics.mean([c.volume for c in prior_half])
            out["volume_ratio"] = recent_vol / prior_vol if prior_vol > 0 else 1.0
        else:
            out["volume_ratio"] = 1.0

    @staticmethod
    def _extract_flat_ratio(candles: Any, out: dict[str, float]) -> None:
        recent = candles[-VOLATILITY_WINDOW:] if len(candles) >= VOLATILITY_WINDOW else candles
        flat_count = sum(1 for c in recent if abs(c.close - c.open) < FLAT_CANDLE_THRESHOLD)
        out["flat_ratio"] = flat_count / len(recent) if recent else 0.0
