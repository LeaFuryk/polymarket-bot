"""Models module constants — default values used across model definitions."""

# Position flat threshold (shares below this are considered zero)
FLAT_POSITION_THRESHOLD: float = 1e-9

# Default confidence for trading decisions
DEFAULT_CONFIDENCE: float = 0.5

# Default TTL for limit orders (seconds)
DEFAULT_TTL_SECONDS: int = 300

# Default observation expiry (number of resolutions)
DEFAULT_OBSERVATION_EXPIRY: int = 30
