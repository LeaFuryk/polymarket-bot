"""Adapter: Binance klines API for BTC volume and OHLCV candles."""

from __future__ import annotations

import logging

import httpx

from polybot.domain.models import Candle

BINANCE_BASE_URL = "https://api.binance.com"
KLINES_ENDPOINT = "/api/v3/klines"

# Binance interval strings
_INTERVAL_MAP = {
    60: "1m",
    180: "3m",
    300: "5m",
    900: "15m",
    3600: "1h",
}


class BinanceVolumeAdapter:
    """VolumeFeed implementation using Binance public klines API.

    No authentication required. Fetches OHLCV klines and extracts
    the volume field (index 5) which is base asset volume (BTC).
    """

    def __init__(
        self,
        symbol: str = "BTCUSDT",
        base_url: str = BINANCE_BASE_URL,
        logger: logging.Logger | None = None,
    ) -> None:
        self._symbol = symbol
        self._log = logger or logging.getLogger(__name__)
        self._client = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def get_volume(self, start_time: float, end_time: float) -> float:
        """Get BTC volume between start_time and end_time (epoch seconds)."""
        interval_sec = int(end_time - start_time)
        interval = _INTERVAL_MAP.get(interval_sec, "5m")

        params = {
            "symbol": self._symbol,
            "interval": interval,
            "startTime": int(start_time * 1000),
            "endTime": int(end_time * 1000),
            "limit": 1,
        }

        kline = await self._fetch_klines(params)
        if not kline:
            return 0.0

        return float(kline[0][5])

    async def get_candle_volumes(self, count: int, interval_sec: int = 300) -> list[float]:
        """Get volume for the last N candles."""
        interval = _INTERVAL_MAP.get(interval_sec, "5m")

        params = {
            "symbol": self._symbol,
            "interval": interval,
            "limit": count,
        }

        klines = await self._fetch_klines(params)
        if not klines:
            return []

        return [float(k[5]) for k in klines]

    async def get_candles(self, count: int, interval_sec: int = 300) -> list[Candle]:
        """Get last N OHLCV candles as Candle objects."""
        interval = _INTERVAL_MAP.get(interval_sec, "5m")

        params = {
            "symbol": self._symbol,
            "interval": interval,
            "limit": count,
        }

        klines = await self._fetch_klines(params)
        if not klines:
            return []

        return [
            Candle(
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                start_time=k[0] / 1000.0,
                end_time=k[6] / 1000.0,
            )
            for k in klines
        ]

    async def _fetch_klines(self, params: dict) -> list:
        """Call Binance klines endpoint."""
        try:
            resp = await self._client.get(KLINES_ENDPOINT, params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            self._log.exception("Binance klines request failed")
            return []
