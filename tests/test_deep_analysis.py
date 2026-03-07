"""Tests for polybot.analysis.deep — post-run analysis functions."""

from __future__ import annotations

from polybot.analysis.deep import (
    analyze_entry_quality,
    analyze_flips,
    analyze_losses,
    analyze_missed_opportunities,
    analyze_side_accuracy,
    analyze_timing,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _trade(
    action: str = "BUY",
    fill_price: float | None = 0.50,
    confidence: float | None = 0.7,
    token_side: str = "UP",
    candle_slug: str = "slug_1",
    risk_blocked: bool = False,
    reasoning: str = "test",
    fee: float = 0.01,
    time_remaining_at_trade: float | None = None,
) -> dict:
    d: dict = {
        "action": action,
        "fill_price": fill_price,
        "confidence": confidence,
        "token_side": token_side,
        "candle_slug": candle_slug,
        "risk_blocked": risk_blocked,
        "reasoning": reasoning,
        "fee": fee,
    }
    if time_remaining_at_trade is not None:
        d["time_remaining_at_trade"] = time_remaining_at_trade
    return d


def _resolution(
    slug: str = "slug_1",
    winner: str = "UP",
    btc_move: float = 100.0,
    pnl: float = 0.10,
) -> dict:
    return {"slug": slug, "winner": winner, "btc_move": btc_move, "pnl": pnl}


# ---------------------------------------------------------------------------
# analyze_entry_quality
# ---------------------------------------------------------------------------


class TestAnalyzeEntryQuality:
    def test_empty_trades(self):
        result = analyze_entry_quality([])
        assert result["total_buys"] == 0
        assert result["total_fills"] == 0
        assert result["avg_fill_price"] == 0.0

    def test_basic_distribution(self):
        trades = [
            _trade(fill_price=0.35),  # cheap
            _trade(fill_price=0.38),  # cheap
            _trade(fill_price=0.45),  # ok
            _trade(fill_price=0.58),  # expensive
            _trade(fill_price=0.72),  # very_expensive
        ]
        result = analyze_entry_quality(trades)
        assert result["total_buys"] == 5
        assert result["total_fills"] == 5
        assert result["cheap"] == 2
        assert result["ok"] == 1
        assert result["expensive"] == 1
        assert result["very_expensive"] == 1

    def test_risk_blocked_excluded(self):
        trades = [
            _trade(fill_price=0.50),
            _trade(fill_price=0.55, risk_blocked=True),
        ]
        result = analyze_entry_quality(trades)
        assert result["total_buys"] == 1
        assert result["total_fills"] == 1

    def test_holds_excluded(self):
        trades = [
            _trade(action="HOLD", fill_price=None),
            _trade(fill_price=0.45),
        ]
        result = analyze_entry_quality(trades)
        assert result["total_buys"] == 1

    def test_sells_excluded(self):
        trades = [
            _trade(action="SELL", fill_price=0.60),
            _trade(fill_price=0.45),
        ]
        result = analyze_entry_quality(trades)
        assert result["total_buys"] == 1

    def test_none_fill_price(self):
        trades = [_trade(fill_price=None)]
        result = analyze_entry_quality(trades)
        assert result["total_buys"] == 1
        assert result["total_fills"] == 0
        assert result["avg_fill_price"] == 0.0

    def test_avg_confidence(self):
        trades = [
            _trade(confidence=0.8),
            _trade(confidence=0.6),
        ]
        result = analyze_entry_quality(trades)
        assert result["avg_confidence"] == 0.7

    def test_avg_entry_gap(self):
        trades = [_trade(fill_price=0.60)]  # gap = |0.60 - 0.50| = 0.10
        result = analyze_entry_quality(trades)
        assert result["avg_entry_gap"] == 0.1


# ---------------------------------------------------------------------------
# analyze_side_accuracy
# ---------------------------------------------------------------------------


class TestAnalyzeSideAccuracy:
    def test_empty(self):
        result = analyze_side_accuracy([], [])
        assert result == {}

    def test_basic_up_down(self):
        trades = [
            _trade(token_side="UP", candle_slug="s1"),
            _trade(token_side="DOWN", candle_slug="s2"),
        ]
        resolutions = [
            _resolution(slug="s1", pnl=0.10),
            _resolution(slug="s2", pnl=-0.05),
        ]
        result = analyze_side_accuracy(trades, resolutions)
        assert result["UP"]["trades"] == 1
        assert result["UP"]["wins"] == 1
        assert result["UP"]["win_rate"] == 1.0
        assert result["DOWN"]["trades"] == 1
        assert result["DOWN"]["losses"] == 1
        assert result["DOWN"]["win_rate"] == 0.0

    def test_risk_blocked_excluded(self):
        trades = [
            _trade(token_side="UP", candle_slug="s1", risk_blocked=True),
        ]
        resolutions = [_resolution(slug="s1", pnl=0.10)]
        result = analyze_side_accuracy(trades, resolutions)
        assert result == {}

    def test_holds_excluded(self):
        trades = [_trade(action="HOLD", token_side="UP", candle_slug="s1")]
        resolutions = [_resolution(slug="s1", pnl=0.10)]
        result = analyze_side_accuracy(trades, resolutions)
        assert result == {}

    def test_no_matching_resolution(self):
        trades = [_trade(token_side="UP", candle_slug="s1")]
        resolutions = [_resolution(slug="s2", pnl=0.10)]
        result = analyze_side_accuracy(trades, resolutions)
        assert result["UP"]["trades"] == 1
        assert result["UP"]["wins"] == 0
        assert result["UP"]["losses"] == 0
        assert result["UP"]["win_rate"] == 0.0

    def test_total_pnl(self):
        trades = [
            _trade(token_side="UP", candle_slug="s1"),
            _trade(token_side="UP", candle_slug="s2"),
        ]
        resolutions = [
            _resolution(slug="s1", pnl=0.20),
            _resolution(slug="s2", pnl=-0.05),
        ]
        result = analyze_side_accuracy(trades, resolutions)
        assert result["UP"]["total_pnl"] == 0.15

    def test_sell_included(self):
        trades = [_trade(action="SELL", token_side="UP", candle_slug="s1")]
        resolutions = [_resolution(slug="s1", pnl=0.10)]
        result = analyze_side_accuracy(trades, resolutions)
        assert result["UP"]["trades"] == 1


# ---------------------------------------------------------------------------
# analyze_missed_opportunities
# ---------------------------------------------------------------------------


class TestAnalyzeMissedOpportunities:
    def test_empty(self):
        result = analyze_missed_opportunities([], [])
        assert result["total_candles"] == 0
        assert result["missed_candles"] == 0

    def test_all_traded(self):
        trades = [_trade(candle_slug="s1"), _trade(candle_slug="s2")]
        resolutions = [
            _resolution(slug="s1", btc_move=100),
            _resolution(slug="s2", btc_move=50),
        ]
        result = analyze_missed_opportunities(trades, resolutions)
        assert result["traded_candles"] == 2
        assert result["missed_candles"] == 0

    def test_high_move_missed(self):
        trades = [_trade(action="HOLD", candle_slug="s1")]
        resolutions = [_resolution(slug="s1", btc_move=107.7)]
        result = analyze_missed_opportunities(trades, resolutions)
        assert result["missed_candles"] == 1
        assert result["high_move_missed"] == 1
        assert result["low_move_skipped"] == 0
        assert result["biggest_missed_move"] == 107.7

    def test_low_move_skipped(self):
        trades = [_trade(action="HOLD", candle_slug="s1")]
        resolutions = [_resolution(slug="s1", btc_move=20.0)]
        result = analyze_missed_opportunities(trades, resolutions)
        assert result["missed_candles"] == 1
        assert result["high_move_missed"] == 0
        assert result["low_move_skipped"] == 1

    def test_mixed_scenario(self):
        trades = [
            _trade(candle_slug="s1"),  # traded
            _trade(action="HOLD", candle_slug="s2"),  # hold, high move
            _trade(action="HOLD", candle_slug="s3"),  # hold, low move
        ]
        resolutions = [
            _resolution(slug="s1", btc_move=80.0),
            _resolution(slug="s2", btc_move=100.0),
            _resolution(slug="s3", btc_move=10.0),
        ]
        result = analyze_missed_opportunities(trades, resolutions)
        assert result["total_candles"] == 3
        assert result["traded_candles"] == 1
        assert result["missed_candles"] == 2
        assert result["high_move_missed"] == 1
        assert result["low_move_skipped"] == 1
        assert result["biggest_missed_move"] == 100.0

    def test_risk_blocked_not_traded(self):
        trades = [_trade(candle_slug="s1", risk_blocked=True)]
        resolutions = [_resolution(slug="s1", btc_move=80.0)]
        result = analyze_missed_opportunities(trades, resolutions)
        assert result["missed_candles"] == 1
        assert result["high_move_missed"] == 1

    def test_negative_btc_move(self):
        trades = []
        resolutions = [_resolution(slug="s1", btc_move=-75.0)]
        result = analyze_missed_opportunities(trades, resolutions)
        assert result["missed_candles"] == 1
        assert result["high_move_missed"] == 1
        assert result["biggest_missed_move"] == 75.0

    def test_no_resolutions(self):
        trades = [_trade(candle_slug="s1")]
        result = analyze_missed_opportunities(trades, [])
        assert result["total_candles"] == 0
        assert result["missed_candles"] == 0
        assert result["biggest_missed_move"] == 0.0

    def test_missed_details_structure(self):
        trades = [_trade(action="HOLD", candle_slug="s1")]
        resolutions = [_resolution(slug="s1", btc_move=60.0, winner="UP")]
        result = analyze_missed_opportunities(trades, resolutions)
        detail = result["missed_details"][0]
        assert detail["slug"] == "s1"
        assert detail["btc_move"] == 60.0
        assert detail["winner"] == "UP"
        assert detail["category"] == "high_move_missed"


# ---------------------------------------------------------------------------
# analyze_losses
# ---------------------------------------------------------------------------


class TestAnalyzeLosses:
    def test_empty(self):
        assert analyze_losses([], []) == []

    def test_identifies_loss(self):
        trades = [_trade(token_side="UP", candle_slug="s1", fill_price=0.55, reasoning="bullish momentum")]
        resolutions = [_resolution(slug="s1", winner="DOWN", pnl=-0.10, btc_move=-80.0)]
        result = analyze_losses(trades, resolutions)
        assert len(result) == 1
        assert result[0]["slug"] == "s1"
        assert result[0]["side"] == "UP"
        assert result[0]["pnl"] == -0.1
        assert result[0]["predictable"] is True  # large opposite move

    def test_win_excluded(self):
        trades = [_trade(candle_slug="s1")]
        resolutions = [_resolution(slug="s1", pnl=0.10)]
        assert analyze_losses(trades, resolutions) == []

    def test_risk_blocked_excluded(self):
        trades = [_trade(candle_slug="s1", risk_blocked=True)]
        resolutions = [_resolution(slug="s1", pnl=-0.10)]
        assert analyze_losses(trades, resolutions) == []

    def test_holds_excluded(self):
        trades = [_trade(action="HOLD", candle_slug="s1")]
        resolutions = [_resolution(slug="s1", pnl=-0.10)]
        assert analyze_losses(trades, resolutions) == []

    def test_not_predictable_small_move(self):
        trades = [_trade(token_side="UP", candle_slug="s1")]
        resolutions = [_resolution(slug="s1", winner="DOWN", pnl=-0.05, btc_move=-20.0)]
        result = analyze_losses(trades, resolutions)
        assert len(result) == 1
        assert result[0]["predictable"] is False

    def test_not_predictable_same_side_loss(self):
        # Lost despite correct side — unpredictable
        trades = [_trade(token_side="UP", candle_slug="s1")]
        resolutions = [_resolution(slug="s1", winner="UP", pnl=-0.02, btc_move=10.0)]
        result = analyze_losses(trades, resolutions)
        assert len(result) == 1
        assert result[0]["predictable"] is False

    def test_reasoning_excerpt_truncated(self):
        long_reasoning = "A" * 300
        trades = [_trade(candle_slug="s1", reasoning=long_reasoning)]
        resolutions = [_resolution(slug="s1", pnl=-0.10, winner="DOWN")]
        result = analyze_losses(trades, resolutions)
        assert len(result[0]["reasoning_excerpt"]) == 200

    def test_no_matching_resolution(self):
        trades = [_trade(candle_slug="s1")]
        resolutions = [_resolution(slug="s2", pnl=-0.10)]
        assert analyze_losses(trades, resolutions) == []


# ---------------------------------------------------------------------------
# analyze_flips
# ---------------------------------------------------------------------------


class TestAnalyzeFlips:
    def test_empty(self):
        assert analyze_flips([]) == []

    def test_no_flip_single_trade(self):
        trades = [_trade(candle_slug="s1")]
        assert analyze_flips(trades) == []

    def test_no_flip_same_direction(self):
        trades = [
            _trade(action="BUY", candle_slug="s1"),
            _trade(action="BUY", candle_slug="s1"),
        ]
        assert analyze_flips(trades) == []

    def test_basic_flip(self):
        trades = [
            _trade(action="BUY", candle_slug="s1", fee=0.01),
            _trade(action="SELL", candle_slug="s1", fee=0.02),
        ]
        result = analyze_flips(trades)
        assert len(result) == 1
        assert result[0]["slug"] == "s1"
        assert result[0]["flip_count"] == 1
        assert result[0]["trade_count"] == 2
        assert result[0]["total_fees"] == 0.03

    def test_double_flip(self):
        trades = [
            _trade(action="BUY", candle_slug="s1"),
            _trade(action="SELL", candle_slug="s1"),
            _trade(action="BUY", candle_slug="s1"),
        ]
        result = analyze_flips(trades)
        assert len(result) == 1
        assert result[0]["flip_count"] == 2
        assert result[0]["actions"] == ["BUY", "SELL", "BUY"]

    def test_risk_blocked_excluded(self):
        trades = [
            _trade(action="BUY", candle_slug="s1"),
            _trade(action="SELL", candle_slug="s1", risk_blocked=True),
        ]
        assert analyze_flips(trades) == []

    def test_different_candles_no_flip(self):
        trades = [
            _trade(action="BUY", candle_slug="s1"),
            _trade(action="SELL", candle_slug="s2"),
        ]
        assert analyze_flips(trades) == []


# ---------------------------------------------------------------------------
# analyze_timing
# ---------------------------------------------------------------------------


class TestAnalyzeTiming:
    def test_empty(self):
        result = analyze_timing([], [])
        assert result["0-60s"]["trades"] == 0
        assert result["240-300s"]["trades"] == 0

    def test_early_entry(self):
        # time_remaining=270 → elapsed=30 → bucket 0-60s
        trades = [_trade(candle_slug="s1", time_remaining_at_trade=270)]
        resolutions = [_resolution(slug="s1", pnl=0.10)]
        result = analyze_timing(trades, resolutions)
        assert result["0-60s"]["trades"] == 1
        assert result["0-60s"]["wins"] == 1
        assert result["0-60s"]["win_rate"] == 1.0

    def test_late_entry(self):
        # time_remaining=50 → elapsed=250 → bucket 240-300s
        trades = [_trade(candle_slug="s1", time_remaining_at_trade=50)]
        resolutions = [_resolution(slug="s1", pnl=-0.05)]
        result = analyze_timing(trades, resolutions)
        assert result["240-300s"]["trades"] == 1
        assert result["240-300s"]["losses"] == 1
        assert result["240-300s"]["win_rate"] == 0.0

    def test_mid_entry(self):
        # time_remaining=180 → elapsed=120 → bucket 120-180s
        trades = [_trade(candle_slug="s1", time_remaining_at_trade=180)]
        resolutions = [_resolution(slug="s1", pnl=0.10)]
        result = analyze_timing(trades, resolutions)
        assert result["120-180s"]["trades"] == 1
        assert result["120-180s"]["wins"] == 1

    def test_no_time_remaining_skipped(self):
        trades = [_trade(candle_slug="s1")]  # no time_remaining_at_trade
        resolutions = [_resolution(slug="s1", pnl=0.10)]
        result = analyze_timing(trades, resolutions)
        assert all(b["trades"] == 0 for b in result.values())

    def test_risk_blocked_excluded(self):
        trades = [_trade(candle_slug="s1", time_remaining_at_trade=270, risk_blocked=True)]
        resolutions = [_resolution(slug="s1", pnl=0.10)]
        result = analyze_timing(trades, resolutions)
        assert all(b["trades"] == 0 for b in result.values())

    def test_holds_excluded(self):
        trades = [_trade(action="HOLD", candle_slug="s1", time_remaining_at_trade=270)]
        resolutions = [_resolution(slug="s1", pnl=0.10)]
        result = analyze_timing(trades, resolutions)
        assert all(b["trades"] == 0 for b in result.values())

    def test_no_matching_resolution(self):
        trades = [_trade(candle_slug="s1", time_remaining_at_trade=270)]
        resolutions = [_resolution(slug="s2", pnl=0.10)]
        result = analyze_timing(trades, resolutions)
        assert result["0-60s"]["trades"] == 1
        assert result["0-60s"]["wins"] == 0
        assert result["0-60s"]["losses"] == 0
        assert result["0-60s"]["win_rate"] == 0.0

    def test_all_buckets(self):
        result = analyze_timing([], [])
        assert len(result) == 5
        expected = ["0-60s", "60-120s", "120-180s", "180-240s", "240-300s"]
        assert list(result.keys()) == expected
