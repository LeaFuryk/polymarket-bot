"""Dynamic BTC 5-min candle market discovery via the Gamma API."""

from __future__ import annotations

import json
import logging
import time

import httpx

from polybot.config import AppConfig
from polybot.models import CandleMarket

logger = logging.getLogger(__name__)

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CANDLE_INTERVAL = 300  # 5 minutes in seconds


def _boundary_ts(offset: int = 0) -> int:
    """Return the Unix timestamp of the current (or next) 5-min boundary.

    offset=0 → current candle start, offset=1 → next candle start.
    """
    now = int(time.time())
    boundary = now - (now % CANDLE_INTERVAL)
    return boundary + offset * CANDLE_INTERVAL


class MarketDiscovery:
    """Discovers active BTC 5-min candle markets from the Gamma API."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._series_slug = config.market.series_slug
        self._client = httpx.AsyncClient(timeout=10.0)

    async def get_current_market(self) -> CandleMarket | None:
        """Fetch the candle market for the current 5-min window."""
        return await self._fetch_market(offset=0)

    async def get_next_market(self) -> CandleMarket | None:
        """Fetch the candle market for the next 5-min window."""
        return await self._fetch_market(offset=1)

    async def _fetch_market(self, offset: int) -> CandleMarket | None:
        """Query Gamma API for a candle market at the given boundary offset."""
        boundary = _boundary_ts(offset)
        slug = f"{self._series_slug}-{boundary}"

        try:
            resp = await self._client.get(
                f"{GAMMA_API_BASE}/events",
                params={"slug": slug},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.exception("Failed to fetch market for slug=%s", slug)
            return None

        if not data:
            logger.warning("No market found for slug=%s", slug)
            return None

        # The API returns a list; take the first event
        event = data[0] if isinstance(data, list) else data

        # Extract market from the event's markets array
        markets = event.get("markets", [])
        if not markets:
            logger.warning("Event has no markets: slug=%s", slug)
            return None

        market = markets[0]
        condition_id = market.get("conditionId", "")

        clob_token_ids = market.get("clobTokenIds")
        # Gamma API returns clobTokenIds as a JSON-encoded string, not a list
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except (ValueError, TypeError):
                logger.warning("Could not parse clobTokenIds string for slug=%s", slug)
                return None
        if not clob_token_ids or len(clob_token_ids) < 2:
            logger.warning("Missing clobTokenIds for slug=%s", slug)
            return None

        up_token_id = clob_token_ids[0]
        down_token_id = clob_token_ids[1]

        end_date = market.get("endDate", "")
        title = event.get("title", slug)

        # Parse end_date ISO 8601 to Unix timestamp
        end_time = self._parse_iso_timestamp(end_date) if end_date else float(boundary + CANDLE_INTERVAL)
        start_time = float(boundary)

        return CandleMarket(
            condition_id=condition_id,
            up_token_id=up_token_id,
            down_token_id=down_token_id,
            slug=slug,
            title=title,
            start_time=start_time,
            end_time=end_time,
        )

    @staticmethod
    def _parse_iso_timestamp(iso_str: str) -> float:
        """Parse an ISO 8601 timestamp string to Unix epoch float."""
        from datetime import datetime, timezone

        # Handle common formats: with or without Z, with or without microseconds
        iso_str = iso_str.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            logger.warning("Could not parse ISO timestamp: %s", iso_str)
            return 0.0

    async def close(self) -> None:
        await self._client.aclose()
