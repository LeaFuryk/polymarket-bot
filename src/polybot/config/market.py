"""Target market identification and CLOB endpoint."""

from __future__ import annotations

from pydantic import BaseModel

from polybot.config.constants import (
    DEFAULT_CONDITION_ID,
    DEFAULT_SERIES_SLUG,
)


class MarketConfig(BaseModel):
    """Target market identification and CLOB endpoint."""

    condition_id: str = DEFAULT_CONDITION_ID
    token_id: str = ""
    series_slug: str = DEFAULT_SERIES_SLUG
