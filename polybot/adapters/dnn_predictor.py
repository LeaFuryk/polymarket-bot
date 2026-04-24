"""Adapter: load a PyTorch DNN model and predict P(UP) from raw market data."""

from __future__ import annotations

import logging
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import joblib
import numpy as np
import torch
import torch.nn as nn

from polybot.adapters.dnn_models import ResidualBlock, ResidualMLP  # noqa: F401 — needed for torch.load unpickling
from polybot.ports.predictor import Predictor

# Default number of snapshots per candle (~50 ticks in 5 min).
_DEFAULT_SEQ_LEN = 50


class DnnPredictor(Predictor):
    """Loads a pre-trained PyTorch model and predicts P(UP) from raw columns.

    Supports two inference modes controlled by ``temporal``:

    * **Single-snapshot** (``temporal=False``): each ``predict(row)`` call
      extracts features from the current row and runs a single forward pass.
    * **Temporal** (``temporal=True``): an internal buffer accumulates
      snapshots within the current candle.  On each ``predict(row)`` call the
      buffer is padded/truncated to ``seq_len`` and fed as a 3-D tensor.
      The buffer resets automatically when ``row["candle_id"]`` changes.
    """

    def __init__(
        self,
        model_path: str,
        feature_cols_path: str,
        scaler_path: str | None = None,
        calibrator_path: str | None = None,
        temporal: bool = False,
        seq_len: int = _DEFAULT_SEQ_LEN,
        logger: logging.Logger | None = None,
    ) -> None:
        self._log = logger or logging.getLogger(__name__)
        self._feature_cols: list[str] = joblib.load(feature_cols_path)
        self._scaler = joblib.load(scaler_path) if scaler_path else None
        self._calibrator = joblib.load(calibrator_path) if calibrator_path else None
        self._temporal = temporal
        self._seq_len = seq_len

        self._model: nn.Module = torch.load(model_path, weights_only=False)
        self._model.eval()

        # Temporal state
        self._buffer: list[list[float]] = []
        self._current_candle_id: str | None = None

        self._log.info(
            "Loaded DNN from %s (%d features, temporal=%s)",
            model_path,
            len(self._feature_cols),
            self._temporal,
        )

    # ------------------------------------------------------------------
    # Predictor protocol
    # ------------------------------------------------------------------

    def predict(self, row: dict) -> float:
        """Return P(UP) in [0, 1]."""
        features = [float(row.get(col) or 0.0) for col in self._feature_cols]

        if self._scaler is not None:
            features = self._scaler.transform(np.array(features).reshape(1, -1))[0].tolist()

        if self._temporal:
            return self._predict_temporal(features, row.get("candle_id"))
        return self._predict_single(features)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _calibrate(self, raw_prob: float) -> float:
        if self._calibrator is None:
            return raw_prob
        return float(self._calibrator.predict([raw_prob])[0])

    def _predict_single(self, features: list[float]) -> float:
        tensor = torch.tensor([features], dtype=torch.float32)
        with torch.no_grad():
            logit = self._model(tensor)
        raw = float(torch.sigmoid(logit).item())
        return self._calibrate(raw)

    def _predict_temporal(self, features: list[float], candle_id: str | None) -> float:
        # Reset buffer on candle boundary.
        if candle_id != self._current_candle_id:
            self._buffer = []
            self._current_candle_id = candle_id

        self._buffer.append(features)

        # Pad (repeat first row) or truncate to fixed length.
        buf = self._buffer[-self._seq_len :]
        while len(buf) < self._seq_len:
            buf = [buf[0]] + buf

        tensor = torch.tensor([buf], dtype=torch.float32)  # (1, seq_len, n_features)
        with torch.no_grad():
            logit = self._model(tensor)
        raw = float(torch.sigmoid(logit).item())
        return self._calibrate(raw)
