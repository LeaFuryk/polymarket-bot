"""Target market identification and CLOB endpoint."""

from __future__ import annotations

from pydantic import BaseModel

from polybot.config.constants import (
    DEFAULT_CLOB_API_URL,
    DEFAULT_CONDITION_ID,
    DEFAULT_SERIES_SLUG,
)


class MarketConfig(BaseModel):
    """Target market identification and CLOB endpoint."""

    condition_id: str = DEFAULT_CONDITION_ID
    clob_api_url: str = DEFAULT_CLOB_API_URL
    token_id: str = ""
    series_slug: str = DEFAULT_SERIES_SLUG
