"""Re-export from canonical indicator engine. Notebooks import from here."""

import sys
from pathlib import Path

# Add project root to path so notebooks can import polybot_data
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from polybot_data.domain.collection import CandleRecord  # noqa: E402, F401
from polybot_data.services.indicator_engine import (  # noqa: E402, F401
    IndicatorSnapshot,
    compute_all,
)
