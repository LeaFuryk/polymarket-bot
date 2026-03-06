"""Confidence calibration — maps stated AI confidence to actual win rates."""

from polybot.calibration.constants import (
    BIN_WIDTH,
    CONFIDENCE_PRECISION,
    DATA_FILE_NAME,
    DEFAULT_BREAK_EVEN,
    DEFAULT_CONFIDENCE,
    MIN_SAMPLES,
)
from polybot.calibration.tracker import CalibrationBin, CalibrationResult, ConfidenceCalibrator

__all__ = [
    "BIN_WIDTH",
    "CONFIDENCE_PRECISION",
    "CalibrationBin",
    "CalibrationResult",
    "ConfidenceCalibrator",
    "DATA_FILE_NAME",
    "DEFAULT_BREAK_EVEN",
    "DEFAULT_CONFIDENCE",
    "MIN_SAMPLES",
]
