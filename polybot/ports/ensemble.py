"""Port: ensemble prediction interface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from polybot_data.services.indicator_engine import IndicatorSnapshot


@runtime_checkable
class EnsemblePredictor(Protocol):
    """Predicts P(UP) using multiple models' predictions."""

    def predict_ensemble(
        self,
        predictions: dict[str, float],
        row: dict,
        snapshot: IndicatorSnapshot,
    ) -> float | None:
        """Return P(UP) in [0, 1], or None to skip."""
        ...
