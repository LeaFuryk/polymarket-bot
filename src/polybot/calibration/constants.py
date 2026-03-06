"""Calibration module constants."""

# Confidence is bucketed into bins of this width
BIN_WIDTH: float = 0.10

# Minimum samples in a bin before we trust the calibration
MIN_SAMPLES: int = 10

# Default break-even threshold (price + fees)
DEFAULT_BREAK_EVEN: float = 0.55

# JSONL file name for calibration data persistence
DATA_FILE_NAME: str = "calibration_data.jsonl"

# Default confidence when missing from a loaded record
DEFAULT_CONFIDENCE: float = 0.5

# Decimal precision for rounding confidence values
CONFIDENCE_PRECISION: int = 4
