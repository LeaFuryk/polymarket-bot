"""Tests for BinanceVolumeAdapter."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from polybot.adapters.binance_volume import BinanceVolumeAdapter
from polybot.ports.volume_feed import VolumeFeed

# Sample Binance kline: [open_time, open, high, low, close, volume, close_time, ...]
SAMPLE_KLINE = [
    1700000000000,
    "67800.00",
    "67850.00",
    "67750.00",
    "67820.00",
    "18.42",  # index 5 = base asset volume (BTC)
    1700000299999,
    "1249000.00",
    150,
    "1248000.00",
    "1250000.00",
    "0",
]


def _mock_client(json_data=None, error=None):
    """Create a mock httpx.AsyncClient context manager."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = json_data or []
    mock_resp.raise_for_status = MagicMock()

    client = AsyncMock()
    if error:
        client.get = AsyncMock(side_effect=error)
    else:
        client.get = AsyncMock(return_value=mock_resp)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestBinanceVolumeAdapter:
    def test_satisfies_protocol(self):
        adapter = BinanceVolumeAdapter()
        assert isinstance(adapter, VolumeFeed)

    async def test_get_volume(self):
        adapter = BinanceVolumeAdapter()

        with patch("polybot.adapters.binance_volume.httpx.AsyncClient", return_value=_mock_client([SAMPLE_KLINE])):
            volume = await adapter.get_volume(1700000000.0, 1700000300.0)

        assert volume == pytest.approx(18.42)

    async def test_get_candle_volumes(self):
        adapter = BinanceVolumeAdapter()
        klines = [
            [*SAMPLE_KLINE[:5], "10.5", *SAMPLE_KLINE[6:]],
            [*SAMPLE_KLINE[:5], "12.3", *SAMPLE_KLINE[6:]],
            [*SAMPLE_KLINE[:5], "18.42", *SAMPLE_KLINE[6:]],
        ]

        with patch("polybot.adapters.binance_volume.httpx.AsyncClient", return_value=_mock_client(klines)):
            volumes = await adapter.get_candle_volumes(3)

        assert volumes == [pytest.approx(10.5), pytest.approx(12.3), pytest.approx(18.42)]

    async def test_api_error_returns_zero(self):
        adapter = BinanceVolumeAdapter()

        with patch(
            "polybot.adapters.binance_volume.httpx.AsyncClient",
            return_value=_mock_client(error=Exception("connection error")),
        ):
            volume = await adapter.get_volume(1700000000.0, 1700000300.0)

        assert volume == 0.0

    async def test_api_error_returns_empty_list(self):
        adapter = BinanceVolumeAdapter()

        with patch(
            "polybot.adapters.binance_volume.httpx.AsyncClient",
            return_value=_mock_client(error=Exception("connection error")),
        ):
            volumes = await adapter.get_candle_volumes(3)

        assert volumes == []
