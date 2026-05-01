"""Adapter: consensus voting across multiple model predictions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from polybot.ports.ensemble import EnsemblePredictor

if TYPE_CHECKING:
    from polybot_data.services.indicator_engine import IndicatorSnapshot


class ConsensusPredictor(EnsemblePredictor):
    """Bets when DNN has edge and majority of other models agree on direction."""

    def __init__(
        self,
        dnn_name: str = "DNN",
        edge_threshold: float = 0.07,
        min_agreement: int = 2,
        logger: logging.Logger | None = None,
    ) -> None:
        self._dnn_name = dnn_name
        self._edge_threshold = edge_threshold
        self._min_agreement = min_agreement
        self._log = logger or logging.getLogger(__name__)

    def predict_ensemble(
        self,
        predictions: dict[str, float],
        row: dict,
        snapshot: IndicatorSnapshot,
    ) -> float | None:
        dnn_prob = predictions.get(self._dnn_name)
        if dnn_prob is None:
            return None

        dnn_conf = max(dnn_prob, 1.0 - dnn_prob)
        dnn_dir = 1 if dnn_prob >= 0.5 else 0

        # Get ask price for DNN's direction
        if dnn_dir == 1:
            if not snapshot.up_asks:
                return None
            ask = snapshot.up_asks[0][0]
        else:
            if not snapshot.down_asks:
                return None
            ask = snapshot.down_asks[0][0]

        # DNN edge check
        edge = dnn_conf - ask
        if edge < self._edge_threshold:
            return None

        # Count agreement from other models
        others = {k: v for k, v in predictions.items() if k != self._dnn_name}
        agrees = sum(1 for v in others.values() if (v >= 0.5) == (dnn_dir == 1))
        if agrees < self._min_agreement:
            return None

        return dnn_prob
