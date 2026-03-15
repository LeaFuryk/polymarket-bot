"""Confidence calibration indicator — avg win vs loss confidence."""

from __future__ import annotations

from polybot.indicators.constants import CALIBRATION_TOLERANCE
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class ConfidenceCalibrationIndicator:
    name = "confidence_calibration"
    display_name = "Confidence Calibration"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        if ctx.session is None:
            return None
        total = ctx.session.wins + ctx.session.losses
        if total == 0:
            return None
        diff = ctx.session.avg_win_confidence - ctx.session.avg_loss_confidence
        if abs(diff) < CALIBRATION_TOLERANCE:
            assessment = "well calibrated"
        elif diff > 0:
            assessment = "higher confidence on wins"
        else:
            assessment = "higher confidence on losses — miscalibrated"
        return IndicatorResult(
            name="Confidence Calibration",
            value=diff,
            label=(
                f"win_avg={ctx.session.avg_win_confidence:.2f} "
                f"loss_avg={ctx.session.avg_loss_confidence:.2f} ({assessment})"
            ),
        )
