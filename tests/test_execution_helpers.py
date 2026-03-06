"""Tests for polybot.execution.helpers — pure parsing & fill-construction logic."""

from __future__ import annotations

import pytest

from polybot.execution.constants import BPS_DIVISOR, TAKER_FEE_BPS
from polybot.execution.helpers import (
    extract_order_fill_info,
    make_fill_from_balance,
    parse_order_response,
    snapshot_ob,
)
from polybot.models import OrderbookLevel, OrderbookSnapshot, Side

# ---------------------------------------------------------------------------
# snapshot_ob
# ---------------------------------------------------------------------------


class TestSnapshotOb:
    def test_none_returns_empty_dict(self):
        assert snapshot_ob(None) == {}

    def test_full_snapshot(self):
        ob = OrderbookSnapshot(
            bids=[OrderbookLevel(price=0.55, size=100)],
            asks=[OrderbookLevel(price=0.60, size=200)],
        )
        snap = snapshot_ob(ob)
        assert snap["best_bid"] == 0.55
        assert snap["best_ask"] == 0.60
        assert snap["bid_depth"] == round(0.55 * 100, 2)
        assert snap["ask_depth"] == round(0.60 * 200, 2)
        assert snap["spread_pct"] is not None

    def test_empty_orderbook(self):
        ob = OrderbookSnapshot(bids=[], asks=[])
        snap = snapshot_ob(ob)
        assert snap["best_bid"] is None
        assert snap["best_ask"] is None
        assert snap["bid_depth"] == 0.0
        assert snap["ask_depth"] == 0.0
        assert snap["spread_pct"] is None

    def test_single_side(self):
        ob = OrderbookSnapshot(
            bids=[OrderbookLevel(price=0.50, size=10)],
            asks=[],
        )
        snap = snapshot_ob(ob)
        assert snap["best_bid"] == 0.50
        assert snap["best_ask"] is None
        assert snap["spread_pct"] is None


# ---------------------------------------------------------------------------
# extract_order_fill_info
# ---------------------------------------------------------------------------


class TestExtractOrderFillInfo:
    def test_matched_dict(self):
        status, sm = extract_order_fill_info({"status": "MATCHED", "size_matched": "10.5"})
        assert status == "MATCHED"
        assert sm == 10.5

    def test_live_dict(self):
        status, sm = extract_order_fill_info({"status": "live", "size_matched": "0"})
        assert status == "LIVE"
        assert sm == 0.0

    def test_camel_case_size_matched(self):
        status, sm = extract_order_fill_info({"status": "FILLED", "sizeMatched": "5.0"})
        assert status == "FILLED"
        assert sm == 5.0

    def test_missing_fields(self):
        status, sm = extract_order_fill_info({})
        assert status == ""
        assert sm == 0.0

    def test_invalid_size_matched(self):
        status, sm = extract_order_fill_info({"status": "LIVE", "size_matched": "not_a_number"})
        assert status == "LIVE"
        assert sm == 0.0

    def test_object_response(self):
        class FakeOrder:
            status = "matched"
            size_matched = "7.5"

        status, sm = extract_order_fill_info(FakeOrder())
        assert status == "MATCHED"
        assert sm == 7.5

    def test_none_size_matched(self):
        status, sm = extract_order_fill_info({"status": "LIVE", "size_matched": None})
        assert status == "LIVE"
        assert sm == 0.0

    def test_empty_string_size_matched(self):
        status, sm = extract_order_fill_info({"status": "LIVE", "size_matched": ""})
        assert status == "LIVE"
        assert sm == 0.0


# ---------------------------------------------------------------------------
# make_fill_from_balance
# ---------------------------------------------------------------------------


class TestMakeFillFromBalance:
    def test_buy_fill(self):
        fill = make_fill_from_balance(Side.BUY, fill_size=10.0, limit_price=0.50)
        assert fill.side == Side.BUY
        assert fill.size == 10.0
        assert fill.fill_price == 0.50
        assert fill.slippage_bps == 0.0
        notional = 0.50 * 10.0
        expected_fee = notional * (TAKER_FEE_BPS / BPS_DIVISOR)
        assert fill.fee_amount == pytest.approx(expected_fee)
        assert fill.total_cost == pytest.approx(notional + expected_fee)

    def test_sell_fill(self):
        fill = make_fill_from_balance(Side.SELL, fill_size=5.0, limit_price=0.60)
        notional = 0.60 * 5.0
        expected_fee = notional * (TAKER_FEE_BPS / BPS_DIVISOR)
        assert fill.side == Side.SELL
        assert fill.total_cost == pytest.approx(-(notional - expected_fee))

    def test_zero_size(self):
        fill = make_fill_from_balance(Side.BUY, fill_size=0.0, limit_price=0.50)
        assert fill.size == 0.0
        assert fill.total_cost == 0.0
        assert fill.fee_amount == 0.0

    def test_zero_price(self):
        fill = make_fill_from_balance(Side.BUY, fill_size=10.0, limit_price=0.0)
        assert fill.total_cost == 0.0


# ---------------------------------------------------------------------------
# parse_order_response
# ---------------------------------------------------------------------------


class TestParseOrderResponse:
    def test_none_response(self):
        assert parse_order_response(None, Side.BUY, 10.0, 0.50) is None

    def test_not_filled(self):
        resp = {"success": False, "status": "LIVE"}
        assert parse_order_response(resp, Side.BUY, 10.0, 0.50) is None

    def test_matched_status_without_success(self):
        resp = {"success": False, "status": "MATCHED"}
        fill = parse_order_response(resp, Side.BUY, 10.0, 0.50)
        assert fill is not None
        assert fill.size == 10.0
        assert fill.fill_price == 0.50

    def test_success_flag(self):
        resp = {"success": True, "status": ""}
        fill = parse_order_response(resp, Side.BUY, 10.0, 0.50)
        assert fill is not None

    def test_fill_with_average_price(self):
        resp = {"success": True, "averagePrice": "0.48", "filledAmount": "9.5"}
        fill = parse_order_response(resp, Side.BUY, 10.0, 0.50)
        assert fill is not None
        assert fill.fill_price == 0.48
        assert fill.size == 9.5
        assert fill.slippage_bps == pytest.approx(abs(0.48 - 0.50) / 0.50 * BPS_DIVISOR)

    def test_sell_fill_cost_negative(self):
        resp = {"success": True, "status": "MATCHED"}
        fill = parse_order_response(resp, Side.SELL, 10.0, 0.60)
        assert fill is not None
        assert fill.total_cost < 0  # SELL = cash inflow

    def test_object_response_with_attributes(self):
        class FakeResp:
            success = True
            status = "FILLED"
            averagePrice = 0.55
            filledAmount = 8.0

        fill = parse_order_response(FakeResp(), Side.BUY, 10.0, 0.50)
        assert fill is not None
        assert fill.fill_price == 0.55
        assert fill.size == 8.0

    def test_zero_requested_price(self):
        resp = {"success": True}
        fill = parse_order_response(resp, Side.BUY, 10.0, 0.0)
        assert fill is not None
        assert fill.slippage_bps == 0

    def test_error_response(self):
        resp = {"success": False, "error": "insufficient_balance"}
        assert parse_order_response(resp, Side.BUY, 10.0, 0.50) is None


# ---------------------------------------------------------------------------
# Constants sanity checks
# ---------------------------------------------------------------------------


class TestConstants:
    def test_constants_importable(self):
        from polybot.execution.constants import (
            BPS_DIVISOR,
            FEE_RATE_BPS,
            ORDER_EXPIRATION,
            POLL_INTERVAL_SECONDS,
            POST_CANCEL_WAIT_SECONDS,
            SIGNATURE_TYPE,
            STEALTH_FILL_TOLERANCE,
            TAKER_FEE_BPS,
            USDC_DECIMALS,
        )

        assert SIGNATURE_TYPE == 2
        assert FEE_RATE_BPS == 0
        assert ORDER_EXPIRATION == 0
        assert TAKER_FEE_BPS == 20
        assert BPS_DIVISOR == 10_000
        assert USDC_DECIMALS == 1e6
        assert POLL_INTERVAL_SECONDS == 1.0
        assert POST_CANCEL_WAIT_SECONDS == 1.0
        assert 0.0 < STEALTH_FILL_TOLERANCE <= 1.0
