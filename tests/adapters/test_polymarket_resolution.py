"""Tests for PolymarketAdapter.get_resolution()."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from polybot_data.adapters.polymarket import PolymarketAdapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(json_data):
    """Build a mock httpx.Response with .json() and .raise_for_status()."""
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _make_adapter(gamma_data=None, error=None) -> PolymarketAdapter:
    """Create adapter with a mocked Gamma HTTP client."""
    adapter = PolymarketAdapter()
    if error:
        adapter._gamma_client.get = AsyncMock(side_effect=error)
    elif gamma_data is not None:
        adapter._gamma_client.get = AsyncMock(return_value=_mock_response(gamma_data))
    return adapter


def _gamma_event(
    *,
    price_to_beat="67800.0",
    final_price="67850.0",
    outcome_prices=None,
    meta_as_string=False,
    meta=None,
):
    """Build a Gamma API event payload for resolution tests."""
    if meta is None:
        meta = {}
        if price_to_beat is not None:
            meta["priceToBeat"] = price_to_beat
        if final_price is not None:
            meta["finalPrice"] = final_price

    event_metadata = meta
    if meta_as_string:
        import json

        event_metadata = json.dumps(meta)

    if outcome_prices is None:
        outcome_prices = ["1", "0"]

    return {
        "title": "BTC 5m candle",
        "eventMetadata": event_metadata,
        "markets": [
            {
                "conditionId": "0xabc",
                "outcomePrices": outcome_prices,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGetResolutionUpWins:
    async def test_returns_correct_dict_when_up_wins(self):
        """outcomePrices=["1","0"] means UP token won."""
        event = _gamma_event(
            price_to_beat="67800.0",
            final_price="67850.0",
            outcome_prices=["1", "0"],
        )
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")

        assert result is not None
        assert result["open"] == pytest.approx(67800.0)
        assert result["close"] == pytest.approx(67850.0)
        assert result["outcome"] == "UP"


class TestGetResolutionDownWins:
    async def test_returns_correct_dict_when_down_wins(self):
        """outcomePrices=["0","1"] means DOWN token won."""
        event = _gamma_event(
            price_to_beat="67800.0",
            final_price="67750.0",
            outcome_prices=["0", "1"],
        )
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")

        assert result is not None
        assert result["open"] == pytest.approx(67800.0)
        assert result["close"] == pytest.approx(67750.0)
        assert result["outcome"] == "DOWN"


class TestGetResolutionReturnsNone:
    async def test_empty_response(self):
        """No events returned by Gamma API."""
        adapter = _make_adapter(gamma_data=[])

        result = await adapter.get_resolution("btc-updown-5m-900")
        assert result is None

    async def test_missing_price_to_beat(self):
        """eventMetadata has no priceToBeat."""
        event = _gamma_event(price_to_beat=None, final_price="67850.0")
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")
        assert result is None

    async def test_missing_final_price(self):
        """eventMetadata has no finalPrice."""
        event = _gamma_event(price_to_beat="67800.0", final_price=None)
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")
        assert result is None

    async def test_outcome_prices_fewer_than_two(self):
        """outcomePrices has only one element."""
        event = _gamma_event(outcome_prices=["1"])
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")
        assert result is None

    async def test_outcome_prices_empty_list(self):
        """outcomePrices is an empty list."""
        event = _gamma_event(outcome_prices=[])
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")
        assert result is None

    async def test_http_error(self):
        """Network error returns None, does not raise."""
        adapter = _make_adapter(
            error=httpx.HTTPStatusError(
                "500 Server Error",
                request=MagicMock(),
                response=MagicMock(status_code=500),
            )
        )

        result = await adapter.get_resolution("btc-updown-5m-900")
        assert result is None

    async def test_generic_exception(self):
        """Arbitrary exception returns None."""
        adapter = _make_adapter(error=Exception("connection reset"))

        result = await adapter.get_resolution("btc-updown-5m-900")
        assert result is None


class TestGetResolutionJsonStringHandling:
    async def test_event_metadata_as_json_string(self):
        """eventMetadata can be a JSON string rather than a dict."""
        event = _gamma_event(
            price_to_beat="67800.0",
            final_price="67850.0",
            outcome_prices=["1", "0"],
            meta_as_string=True,
        )
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")

        assert result is not None
        assert result["open"] == pytest.approx(67800.0)
        assert result["close"] == pytest.approx(67850.0)
        assert result["outcome"] == "UP"

    async def test_outcome_prices_as_json_string(self):
        """outcomePrices can be a JSON string rather than a list."""
        import json

        event = _gamma_event(
            price_to_beat="67800.0",
            final_price="67850.0",
        )
        # Replace the list with a JSON string
        event["markets"][0]["outcomePrices"] = json.dumps(["1", "0"])
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")

        assert result is not None
        assert result["outcome"] == "UP"

    async def test_outcome_prices_json_string_down_wins(self):
        """outcomePrices as JSON string where DOWN wins."""
        import json

        event = _gamma_event(
            price_to_beat="67800.0",
            final_price="67750.0",
        )
        event["markets"][0]["outcomePrices"] = json.dumps(["0", "1"])
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")

        assert result is not None
        assert result["outcome"] == "DOWN"


class TestGetResolutionEdgeCases:
    async def test_up_price_exactly_half(self):
        """up_price == 0.5 => not > 0.5 => outcome is DOWN."""
        event = _gamma_event(
            price_to_beat="67800.0",
            final_price="67800.0",
            outcome_prices=["0.5", "0.5"],
        )
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")

        assert result is not None
        assert result["outcome"] == "DOWN"

    async def test_up_price_just_above_half(self):
        """up_price == 0.51 => > 0.5 => outcome is UP."""
        event = _gamma_event(
            price_to_beat="67800.0",
            final_price="67810.0",
            outcome_prices=["0.51", "0.49"],
        )
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")

        assert result is not None
        assert result["outcome"] == "UP"

    async def test_missing_event_metadata_key(self):
        """Event has no eventMetadata key at all — falls back to empty dict."""
        event = {
            "title": "BTC 5m candle",
            "markets": [
                {
                    "conditionId": "0xabc",
                    "outcomePrices": ["1", "0"],
                }
            ],
        }
        adapter = _make_adapter(gamma_data=[event])

        result = await adapter.get_resolution("btc-updown-5m-900")
        # priceToBeat and finalPrice will be None from empty dict
        assert result is None
