"""Port: model prediction interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Predictor(Protocol):
    """Predicts probability of UP outcome from an indicator row."""

    def predict(self, row: dict) -> float:
        """Return P(UP) in [0, 1]."""
        ...
