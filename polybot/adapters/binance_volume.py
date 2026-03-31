"""Adapter: Binance klines API for BTC volume."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

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
        *,
        base_url: str = BINANCE_BASE_URL,
    ) -> None:
        self._symbol = symbol
        self._base_url = base_url

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

        # Index 5 = base asset volume (BTC)
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

    async def _fetch_klines(self, params: dict) -> list:
        """Call Binance klines endpoint."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self._base_url}{KLINES_ENDPOINT}",
                    params=params,
                    timeout=10.0,
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            logger.exception("Binance klines request failed")
            return []
