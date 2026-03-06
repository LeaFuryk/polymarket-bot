"""Exit tracker constants — file names and rounding precision."""

# Persistence
EXIT_ANALYSIS_FILENAME = "exit_analysis.jsonl"

# Rounding precision for JSONL serialization
PRICE_PRECISION = 4
SIZE_PRECISION = 2
TIME_PRECISION = 1

# Binary outcome values (prediction market: winning token → $1, losing → $0)
WON_VALUE = 1.0
LOST_VALUE = 0.0
