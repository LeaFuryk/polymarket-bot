"""Adapter: load sklearn model from joblib files and predict."""

from __future__ import annotations

import logging

import joblib
import numpy as np

from polybot.ports.predictor import Predictor


class JoblibPredictor(Predictor):
    """Loads a pre-trained sklearn model + scaler + feature columns from disk."""

    def __init__(
        self,
        model_path: str,
        scaler_path: str,
        feature_cols_path: str,
        logger: logging.Logger | None = None,
    ) -> None:
        self._log = logger or logging.getLogger(__name__)
        self._model = joblib.load(model_path)
        self._scaler = joblib.load(scaler_path)
        self._feature_cols: list[str] = joblib.load(feature_cols_path)
        self._log.info(
            "Loaded model from %s (%d features)",
            model_path,
            len(self._feature_cols),
        )

    def predict(self, row: dict) -> float:
        """Return P(UP) from the indicator row."""
        features = np.array([float(row.get(col) or 0.0) for col in self._feature_cols]).reshape(1, -1)
        scaled = self._scaler.transform(features)
        return float(self._model.predict_proba(scaled)[0, 1])
