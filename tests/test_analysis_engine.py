"""Tests for polybot.analysis.engine — pure replay analysis functions."""

from __future__ import annotations

import pytest

from polybot.analysis.engine import (
    build_decision_timeline,
    compute_ob_stats,
    fillability_scan,
    generate_insights,
    live_order_telemetry,
    post_cancel_recovery,
)

# ---------------------------------------------------------------------------
# Fixtures — reusable test data
# ---------------------------------------------------------------------------


def _snap(ts: float, up_ask: float | None = 0.55, up_bid: float | None = 0.50, btc: float = 60000.0) -> dict:
    """Build a minimal snapshot dict for the 'up' side."""
    return {
        "timestamp": ts,
        "up_best_ask": up_ask,
        "up_best_bid": up_bid,
        "up_mid": (up_ask + up_bid) / 2 if up_ask is not None and up_bid is not None else None,
        "up_spread_pct": ((up_ask - up_bid) / up_bid * 100) if up_ask is not None and up_bid is not None else None,
        "btc_price": btc,
    }


def _decision(ts: float, action: str = "BUY", **kwargs) -> dict:
    d = {"timestamp": ts, "action": action, "_live_order": None}
    d.update(kwargs)
    return d


# ---------------------------------------------------------------------------
# compute_ob_stats
# ---------------------------------------------------------------------------


class TestComputeObStats:
    def test_basic_stats(self):
        snaps = [_snap(0, 0.55, 0.50), _snap(1, 0.56, 0.51), _snap(2, 0.54, 0.49)]
        result = compute_ob_stats(snaps, "up")

        assert result["total_snapshots"] == 3
        assert result["duration_s"] == 2
        assert result["best_ask"]["min"] == 0.54
        assert result["best_ask"]["max"] == 0.56
        assert result["best_bid"]["min"] == 0.49
        assert result["btc_price"]["mean"] == 60000.0

    def test_single_snapshot(self):
        snaps = [_snap(100, 0.55, 0.50)]
        result = compute_ob_stats(snaps, "up")

        assert result["total_snapshots"] == 1
        assert result["duration_s"] == 0
        assert result["best_ask"]["stdev"] == 0.0

    def test_none_values_filtered(self):
        snaps = [_snap(0, None, None), _snap(1, 0.55, 0.50)]
        result = compute_ob_stats(snaps, "up")

        assert result["total_snapshots"] == 2
        assert result["best_ask"]["min"] == 0.55
        assert result["best_bid"]["min"] == 0.50

    def test_all_none_values(self):
        snaps = [_snap(0, None, None, btc=0), _snap(1, None, None, btc=0)]
        result = compute_ob_stats(snaps, "up")

        assert result["best_ask"]["min"] is None
        assert result["best_bid"]["mean"] is None

    def test_down_side(self):
        snaps = [
            {
                "timestamp": 0,
                "down_best_ask": 0.45,
                "down_best_bid": 0.40,
                "down_mid": 0.425,
                "down_spread_pct": 12.5,
                "btc_price": 60000,
            },
            {
                "timestamp": 1,
                "down_best_ask": 0.46,
                "down_best_bid": 0.41,
                "down_mid": 0.435,
                "down_spread_pct": 12.2,
                "btc_price": 60100,
            },
        ]
        result = compute_ob_stats(snaps, "down")

        assert result["best_ask"]["min"] == 0.45
        assert result["best_bid"]["max"] == 0.41


# ---------------------------------------------------------------------------
# fillability_scan
# ---------------------------------------------------------------------------


class TestFillabilityScan:
    def test_all_fillable_with_fixed_price(self):
        snaps = [_snap(i, up_ask=0.50) for i in range(5)]
        result = fillability_scan(snaps, "up", ttl=3, limit_price=0.55)

        assert result["fillable_seconds"] == 5
        assert result["total_seconds"] == 5
        assert result["fill_rate"] == 1.0
        assert result["reference_price"] == 0.55

    def test_none_fillable(self):
        snaps = [_snap(i, up_ask=0.60) for i in range(5)]
        result = fillability_scan(snaps, "up", ttl=3, limit_price=0.50)

        assert result["fillable_seconds"] == 0
        assert result["fill_rate"] == 0

    def test_partial_fill_within_ttl(self):
        snaps = [
            _snap(0, up_ask=0.60),
            _snap(1, up_ask=0.58),
            _snap(2, up_ask=0.55),  # drops below limit at T+2
            _snap(3, up_ask=0.60),
        ]
        result = fillability_scan(snaps, "up", ttl=3, limit_price=0.56)

        # T=0: looks ahead 3s, finds ask=0.55 at T=2 → fill
        # T=1: looks ahead 3s, finds ask=0.55 at T=2 → fill
        # T=2: ask=0.55 <= 0.56 → fill (instant)
        # T=3: ask=0.60 > 0.56 → no fill
        assert result["fillable_seconds"] == 3
        assert result["total_seconds"] == 4

    def test_zero_limit_price_uses_per_second_ask(self):
        snaps = [_snap(i, up_ask=0.55) for i in range(3)]
        result = fillability_scan(snaps, "up", ttl=3, limit_price=0.0)

        # Every second fills itself
        assert result["fill_rate"] == 1.0
        assert result["reference_price"] is None

    def test_best_worst_entry(self):
        snaps = [_snap(0, up_ask=0.52), _snap(1, up_ask=0.50), _snap(2, up_ask=0.54)]
        result = fillability_scan(snaps, "up", ttl=3, limit_price=0.55)

        assert result["best_entry"] == 0.50
        assert result["worst_entry"] == 0.54
        assert result["book_best_ask"] == 0.50
        assert result["book_worst_ask"] == 0.54

    def test_empty_snapshots(self):
        result = fillability_scan([], "up", ttl=3, limit_price=0.55)

        assert result["fillable_seconds"] == 0
        assert result["total_seconds"] == 0
        assert result["fill_rate"] == 0

    def test_none_asks_skipped(self):
        # With limit_price=0 (per-second mode), None asks are skipped
        snaps = [_snap(0, up_ask=None), _snap(1, up_ask=0.50)]
        result = fillability_scan(snaps, "up", ttl=3, limit_price=0.0)

        assert result["total_seconds"] == 1
        assert result["fillable_seconds"] == 1


# ---------------------------------------------------------------------------
# build_decision_timeline
# ---------------------------------------------------------------------------


class TestBuildDecisionTimeline:
    def test_basic_timeline(self):
        snaps = [_snap(100), _snap(101), _snap(102)]
        decisions = [_decision(100.5, "BUY", confidence=0.8, token_side="up")]

        result = build_decision_timeline(snaps, decisions, "up")

        assert len(result) == 1
        assert result[0]["action"] == "BUY"
        assert result[0]["token_side"] == "up"
        assert result[0]["confidence"] == 0.8
        assert result[0]["offset_s"] == pytest.approx(0.5)
        assert result[0]["book_ask"] == 0.55

    def test_empty_snapshots(self):
        result = build_decision_timeline([], [_decision(100)], "up")
        assert result == []

    def test_empty_decisions(self):
        snaps = [_snap(100)]
        result = build_decision_timeline(snaps, [], "up")
        assert result == []

    def test_multiple_decisions(self):
        snaps = [_snap(0), _snap(1), _snap(2)]
        decisions = [_decision(0.5, "HOLD"), _decision(1.5, "BUY")]

        result = build_decision_timeline(snaps, decisions, "up")
        assert len(result) == 2
        assert result[0]["action"] == "HOLD"
        assert result[1]["action"] == "BUY"

    def test_closest_snapshot_matched(self):
        snaps = [_snap(0, up_ask=0.50), _snap(10, up_ask=0.60)]
        decisions = [_decision(8)]  # closer to T=10

        result = build_decision_timeline(snaps, decisions, "up")
        assert result[0]["book_ask"] == 0.60


# ---------------------------------------------------------------------------
# post_cancel_recovery
# ---------------------------------------------------------------------------


class TestPostCancelRecovery:
    def test_recovery_found(self):
        snaps = [_snap(i, up_ask=0.55) for i in range(40)]
        # Drop the ask after missed decision
        snaps[15] = _snap(15, up_ask=0.53)
        decisions = [_decision(10, "BUY", fill_price=None)]

        result = post_cancel_recovery(snaps, decisions, "up")

        assert result is not None
        assert result["recovered"] is True
        assert result["min_ask_after"] == 0.53
        assert result["window_seconds"] == 30

    def test_no_recovery(self):
        # Decision at T=10.5 — closest snap is T=10 (ask=0.55).
        # Recovery window starts at T>10.5, all snaps have ask=0.58 → NOT recovered.
        snaps = [_snap(i, up_ask=0.55) for i in range(40)]
        for i in range(11, 40):
            snaps[i] = _snap(i, up_ask=0.58)
        decisions = [_decision(10.5, "BUY", fill_price=None)]

        result = post_cancel_recovery(snaps, decisions, "up")

        assert result is not None
        assert result["recovered"] is False

    def test_no_missed_buys(self):
        snaps = [_snap(i) for i in range(10)]
        decisions = [_decision(5, "BUY", fill_price=0.55)]  # filled

        result = post_cancel_recovery(snaps, decisions, "up")
        assert result is None

    def test_risk_blocked_counts_as_missed(self):
        snaps = [_snap(i, up_ask=0.55) for i in range(40)]
        snaps[15] = _snap(15, up_ask=0.50)
        decisions = [_decision(10, "BUY", fill_price=0.55, risk_blocked=True)]

        result = post_cancel_recovery(snaps, decisions, "up")
        assert result is not None
        assert result["recovered"] is True

    def test_no_snapshots_in_window(self):
        snaps = [_snap(0, up_ask=0.55)]  # only one snapshot at T=0
        decisions = [_decision(100, "BUY", fill_price=None)]  # way after

        result = post_cancel_recovery(snaps, decisions, "up")
        # No snapshots in the 30s window after T=100
        assert result is None


# ---------------------------------------------------------------------------
# live_order_telemetry
# ---------------------------------------------------------------------------


class TestLiveOrderTelemetry:
    def test_no_live_orders(self):
        decisions = [_decision(10, "BUY")]
        snaps = [_snap(10)]

        result = live_order_telemetry(decisions, snaps, "up")
        assert result is None

    def test_with_live_order(self):
        lo = {
            "order_id": "abc123",
            "limit_price": 0.55,
            "submit_ts": 10.0,
            "fill_ts": 12.0,
            "cancel_ts": None,
            "fill_source": "size_matched",
            "ttl_used": 3,
            "polls": [{"status": "LIVE", "size_matched": 0}],
            "ob_at_submit": {"best_ask": 0.55},
            "ob_at_end": {"best_ask": 0.56},
            "ob_post_cancel": None,
            "decision_ob_ask": 0.54,
            "decision_ob_bid": 0.49,
        }
        decisions = [_decision(10, "BUY", _live_order=lo)]
        snaps = [_snap(10), _snap(11), _snap(12)]

        result = live_order_telemetry(decisions, snaps, "up")

        assert result is not None
        assert len(result["orders"]) == 1
        order = result["orders"][0]
        assert order["order_id"] == "abc123"
        assert order["filled"] is True
        assert order["book_at_submit"]["ask"] == 0.55
        assert order["book_at_fill"]["ask"] == 0.55

    def test_unfilled_live_order(self):
        lo = {
            "order_id": "xyz",
            "limit_price": 0.55,
            "submit_ts": 10.0,
            "fill_ts": None,
            "cancel_ts": 13.0,
            "fill_source": "",
            "ttl_used": 3,
            "polls": [],
            "ob_at_submit": {},
            "ob_at_end": {},
            "ob_post_cancel": None,
            "decision_ob_ask": None,
            "decision_ob_bid": None,
        }
        decisions = [_decision(10, "BUY", _live_order=lo)]
        snaps = [_snap(10), _snap(13)]

        result = live_order_telemetry(decisions, snaps, "up")

        assert result is not None
        order = result["orders"][0]
        assert order["filled"] is False
        assert order["book_at_fill"] is None
        assert order["book_at_cancel"] is not None

    def test_empty_snapshots(self):
        lo = {"order_id": "a", "submit_ts": 10, "fill_ts": None, "cancel_ts": None}
        decisions = [_decision(10, "BUY", _live_order=lo)]

        result = live_order_telemetry(decisions, [], "up")

        assert result is not None
        order = result["orders"][0]
        assert order["book_at_submit"] == {}


# ---------------------------------------------------------------------------
# generate_insights
# ---------------------------------------------------------------------------


class TestGenerateInsights:
    def test_no_snapshots(self):
        result = generate_insights(
            candle={},
            snapshots=[],
            decisions=[],
            ob_stats={},
            fill_scan={},
            post_cancel=None,
            side="up",
            ttl=3,
        )
        assert result == ["No snapshot data available for analysis."]

    def test_best_entry_insight(self):
        snaps = [_snap(0, up_ask=0.55), _snap(1, up_ask=0.50), _snap(2, up_ask=0.54)]
        fill_scan = {"book_best_ask": 0.50}

        result = generate_insights(
            candle={},
            snapshots=snaps,
            decisions=[],
            ob_stats={},
            fill_scan=fill_scan,
            post_cancel=None,
            side="up",
            ttl=3,
        )
        assert any("Best entry was at T+1s" in i for i in result)

    def test_fill_vs_best_entry(self):
        snaps = [_snap(0, up_ask=0.50), _snap(1, up_ask=0.55)]
        decisions = [_decision(1, "BUY", fill_price=0.55)]
        fill_scan = {"book_best_ask": 0.50, "fill_rate": 1.0, "total_seconds": 2, "fillable_seconds": 2}

        result = generate_insights(
            candle={},
            snapshots=snaps,
            decisions=decisions,
            ob_stats={},
            fill_scan=fill_scan,
            post_cancel=None,
            side="up",
            ttl=3,
        )
        assert any("could have saved" in i for i in result)

    def test_fill_matches_best(self):
        snaps = [_snap(0, up_ask=0.50)]
        decisions = [_decision(0, "BUY", fill_price=0.50)]
        fill_scan = {"book_best_ask": 0.50, "fill_rate": 1.0, "total_seconds": 1, "fillable_seconds": 1}

        result = generate_insights(
            candle={},
            snapshots=snaps,
            decisions=decisions,
            ob_stats={},
            fill_scan=fill_scan,
            post_cancel=None,
            side="up",
            ttl=3,
        )
        assert any("matched or beat" in i for i in result)

    def test_fill_rate_insight(self):
        snaps = [_snap(0)]
        fill_scan = {"fill_rate": 0.75, "total_seconds": 4, "fillable_seconds": 3}

        result = generate_insights(
            candle={},
            snapshots=snaps,
            decisions=[],
            ob_stats={},
            fill_scan=fill_scan,
            post_cancel=None,
            side="up",
            ttl=3,
        )
        assert any("Fillability: 3/4" in i for i in result)

    def test_post_cancel_recovered(self):
        snaps = [_snap(0)]
        post_cancel = {"recovered": True, "recovery_depth": 0.02, "snapshots_in_window": 10}

        result = generate_insights(
            candle={},
            snapshots=snaps,
            decisions=[],
            ob_stats={},
            fill_scan={},
            post_cancel=post_cancel,
            side="up",
            ttl=3,
        )
        assert any("recovered to fillable" in i for i in result)

    def test_post_cancel_not_recovered(self):
        snaps = [_snap(0)]
        post_cancel = {"recovered": False, "min_ask_after": 0.58, "decision_ask": 0.55}

        result = generate_insights(
            candle={},
            snapshots=snaps,
            decisions=[],
            ob_stats={},
            fill_scan={},
            post_cancel=post_cancel,
            side="up",
            ttl=3,
        )
        assert any("NOT recover" in i for i in result)

    def test_winner_correct(self):
        snaps = [_snap(0)]
        result = generate_insights(
            candle={"winner": "up"},
            snapshots=snaps,
            decisions=[],
            ob_stats={},
            fill_scan={},
            post_cancel=None,
            side="up",
            ttl=3,
        )
        assert any("CORRECT" in i for i in result)

    def test_winner_wrong(self):
        snaps = [_snap(0)]
        result = generate_insights(
            candle={"winner": "down"},
            snapshots=snaps,
            decisions=[],
            ob_stats={},
            fill_scan={},
            post_cancel=None,
            side="up",
            ttl=3,
        )
        assert any("WRONG" in i for i in result)

    def test_no_insights_fallback(self):
        snaps = [_snap(0)]
        result = generate_insights(
            candle={},
            snapshots=snaps,
            decisions=[],
            ob_stats={},
            fill_scan={},
            post_cancel=None,
            side="up",
            ttl=3,
        )
        assert any("No notable insights" in i for i in result)

    def test_ttl_counterfactual(self):
        # Missed buy at T=10, ask drops at T=14 (within TTL=5)
        snaps = [_snap(i, up_ask=0.55) for i in range(20)]
        snaps[14] = _snap(14, up_ask=0.53)
        decisions = [_decision(10, "BUY", fill_price=None)]

        result = generate_insights(
            candle={},
            snapshots=snaps,
            decisions=decisions,
            ob_stats={},
            fill_scan={},
            post_cancel=None,
            side="up",
            ttl=3,
        )
        assert any("Missed order would have filled with TTL=5s" in i for i in result)


# ---------------------------------------------------------------------------
# Constants import check
# ---------------------------------------------------------------------------


class TestConstants:
    def test_all_constants_importable(self):
        from polybot.analysis.constants import (
            AGG_FILL_RATE_GREEN,
            AGG_FILL_RATE_YELLOW,
            ANNUALIZATION_FACTOR,
            DEFAULT_TTL_SECONDS,
            ENTRY_GAP_GREEN,
            ENTRY_GAP_YELLOW,
            FILL_RATE_GREEN,
            FILL_RATE_YELLOW,
            PERCENTILE_BUCKETS,
            RECOVERY_RATE_GREEN,
            RECOVERY_WINDOW_SECONDS,
            SIDE_ACCURACY_GREEN,
            SIDE_ACCURACY_YELLOW,
            TTL_COUNTERFACTUAL_VALUES,
            VALIDATE_CONFIDENCE_LOW,
            VALIDATE_CONFIDENCE_MODERATE,
        )

        assert RECOVERY_WINDOW_SECONDS == 30
        assert DEFAULT_TTL_SECONDS == 3
        assert TTL_COUNTERFACTUAL_VALUES == [5, 8, 10]
        assert FILL_RATE_GREEN == 0.7
        assert FILL_RATE_YELLOW == 0.4
        assert AGG_FILL_RATE_GREEN == 0.5
        assert AGG_FILL_RATE_YELLOW == 0.3
        assert ENTRY_GAP_GREEN == 0.05
        assert ENTRY_GAP_YELLOW == 0.15
        assert RECOVERY_RATE_GREEN == 0.5
        assert SIDE_ACCURACY_GREEN == 0.6
        assert SIDE_ACCURACY_YELLOW == 0.45
        assert VALIDATE_CONFIDENCE_LOW == 50
        assert VALIDATE_CONFIDENCE_MODERATE == 100
        assert PERCENTILE_BUCKETS == [10, 25, 50, 75, 90, 95]
        assert ANNUALIZATION_FACTOR == 1440
