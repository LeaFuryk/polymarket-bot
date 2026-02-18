"""BTC spot price feed from CoinGecko free API."""

from __future__ import annotations

import logging
import time

import httpx

from polybot.config import ApiConfig
from polybot.models import BtcPrice

logger = logging.getLogger(__name__)

CACHE_TTL = 30  # seconds


class BtcPriceFeed:
    """Fetches BTC/USD price with caching to respect rate limits."""

    def __init__(self, api_config: ApiConfig) -> None:
        self._base_url = api_config.coingecko_url
        self._client = httpx.AsyncClient(timeout=10.0)
        self._cache: BtcPrice | None = None
        self._cache_time: float = 0.0

    async def get_price(self) -> BtcPrice | None:
        now = time.time()
        if self._cache and (now - self._cache_time) < CACHE_TTL:
            return self._cache

        try:
            resp = await self._client.get(
                f"{self._base_url}/simple/price",
                params={
                    "ids": "bitcoin",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                },
            )
            resp.raise_for_status()
            data = resp.json().get("bitcoin", {})

            price = BtcPrice(
                price_usd=data.get("usd", 0.0),
                change_24h_pct=data.get("usd_24h_change", 0.0),
            )
            self._cache = price
            self._cache_time = now
            return price

        except Exception:
            logger.exception("Failed to fetch BTC price")
            return self._cache  # return stale cache on error

    async def get_price_at(self, timestamp: float) -> float | None:
        """Get BTC price at a specific timestamp via Binance klines API.

        Returns the close price of the 1-minute candle containing the timestamp,
        or None on failure.
        """
        ts_ms = int(timestamp * 1000)
        try:
            resp = await self._client.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "startTime": ts_ms,
                    "limit": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data and len(data) > 0:
                # Kline format: [open_time, open, high, low, close, ...]
                close_price = float(data[0][4])
                return close_price
        except Exception:
            logger.exception("Failed to fetch historical BTC price at %.0f", timestamp)
        return None

    async def close(self) -> None:
        await self._client.aclose()
