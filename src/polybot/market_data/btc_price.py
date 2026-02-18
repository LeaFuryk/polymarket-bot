"""BTC spot price feed from CoinGecko free API."""

from __future__ import annotations

import logging
import time

import httpx

from polybot.config import ApiConfig
from polybot.models import BtcCandle, BtcPrice

logger = logging.getLogger(__name__)

CACHE_TTL = 30  # seconds


class BtcPriceFeed:
    """Fetches BTC/USD price with caching to respect rate limits."""

    def __init__(self, api_config: ApiConfig) -> None:
        self._base_url = api_config.coingecko_url
        self._client = httpx.AsyncClient(timeout=10.0)
        self._cache: BtcPrice | None = None
        self._cache_time: float = 0.0
        self._candles: list[BtcCandle] = []

    @property
    def candles(self) -> list[BtcCandle]:
        return self._candles

    async def load_candle_history(self, limit: int = 200) -> None:
        """Fetch historical 5-min OHLCV candles from Binance."""
        try:
            resp = await self._client.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "5m",
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._candles = [
                BtcCandle(
                    open_time=float(k[0]) / 1000,
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    close_time=float(k[6]) / 1000,
                )
                for k in data
            ]
            logger.info("Loaded %d 5-min BTC candles", len(self._candles))
        except Exception:
            logger.exception("Failed to load BTC candle history")

    async def append_latest_candle(self) -> None:
        """Fetch the latest 2 candles and append the completed one if new."""
        try:
            resp = await self._client.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "5m",
                    "limit": 2,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return
            # The first candle is the most recently completed one
            completed = data[0]
            candle = BtcCandle(
                open_time=float(completed[0]) / 1000,
                open=float(completed[1]),
                high=float(completed[2]),
                low=float(completed[3]),
                close=float(completed[4]),
                volume=float(completed[5]),
                close_time=float(completed[6]) / 1000,
            )
            # Only append if newer than last stored
            if not self._candles or candle.open_time > self._candles[-1].open_time:
                self._candles.append(candle)
                # Cap at 200
                if len(self._candles) > 200:
                    self._candles = self._candles[-200:]
        except Exception:
            logger.exception("Failed to append latest BTC candle")

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
