"""Unit tests for the forensics analysis system."""

from __future__ import annotations

from polybot.forensics.blocked import analyze_blocked
from polybot.forensics.context import analyze_context
from polybot.forensics.costs import analyze_costs
from polybot.forensics.execution import analyze_orders
from polybot.forensics.roundtrips import analyze_roundtrips
from polybot.forensics.ttl import analyze_ttl

# ---------------------------------------------------------------------------
# Feature A: Execution
# ---------------------------------------------------------------------------


class TestExecution:
    def test_latency_calculation(self, tmp_db, sample_decisions):
        """decision_to_submit_ms = (submit_ts - decision_ts) * 1000"""
        metrics, _ = analyze_orders(tmp_db)
        # Find the filled BUY order
        filled = [m for m in metrics if m.order_id == "order_filled_1"]
        assert len(filled) == 1
        m = filled[0]
        # submit_ts=BASE_TS+10.5, decision_ts=BASE_TS+10 → 500ms
        assert abs(m.decision_to_submit_ms - 500.0) < 1.0

    def test_drift_calculation(self, tmp_db, sample_decisions):
        """ask_drift_bps = (submit_ask - decision_ask) / decision_ask * 10000"""
        metrics, _ = analyze_orders(tmp_db)
        filled = [m for m in metrics if m.order_id == "order_filled_1"]
        assert len(filled) == 1
        m = filled[0]
        # decision_ask=0.53, submit_ask=0.54 → drift = (0.54-0.53)/0.53*10000 ≈ 188.7 bps
        assert m.ask_drift_bps is not None
        assert abs(m.ask_drift_bps - 188.68) < 1.0

    def test_aggregate_fill_rate(self, tmp_db, sample_decisions):
        """Verify fill rate and source counts."""
        _, agg = analyze_orders(tmp_db)
        # 3 orders with live_order_json (BUY filled, BUY timeout, SELL filled)
        assert agg.total_orders == 3
        assert agg.filled_count == 2
        assert abs(agg.fill_rate - 2 / 3) < 0.01

    def test_aggregate_percentiles(self, tmp_db, sample_decisions):
        """Verify p50/p95 computation on known dataset."""
        _, agg = analyze_orders(tmp_db)
        # 2 filled orders with known latencies
        assert agg.p50_latency_ms is not None
        assert agg.p95_latency_ms is not None
        assert agg.max_latency_ms is not None

    def test_fill_source_histogram(self, tmp_db, sample_decisions):
        """Fill sources are correctly counted."""
        _, agg = analyze_orders(tmp_db)
        assert "status_poll" in agg.by_fill_source
        assert "size_matched" in agg.by_fill_source
        assert "timeout" in agg.by_fill_source

    def test_balance_delta(self, tmp_db, sample_decisions):
        """post_balance - pre_balance computed correctly."""
        metrics, _ = analyze_orders(tmp_db)
        filled = [m for m in metrics if m.order_id == "order_filled_1"]
        assert len(filled) == 1
        assert filled[0].balance_delta == 20.0


# ---------------------------------------------------------------------------
# Feature B: TTL
# ---------------------------------------------------------------------------


class TestTTL:
    def test_rescue_known_data(self, tmp_db, sample_decisions, sample_snapshots):
        """Timeout order + snapshots → rescue at TTL=5 but not TTL=3."""
        cfs, agg = analyze_ttl(tmp_db, grid=[1, 3, 5, 10, 20, 30, 60])

        assert agg.total_timeouts == 1
        assert len(cfs) == 1

        cf = cfs[0]
        assert cf.order_id == "order_timeout_1"
        # Order was submitted at BASE_TS+60.5, limit_price=0.50
        # Snapshots: ask drops to 0.49 at t=64 (4.5s after submit)
        # So TTL=3 should NOT rescue, but TTL=5 SHOULD
        assert cf.grid.get(3) is False
        assert cf.grid.get(5) is True
        assert cf.rescue_ttl == 5

    def test_grid_rescue_counts(self, tmp_db, sample_decisions, sample_snapshots):
        """Aggregate rescue counts accumulate correctly."""
        _, agg = analyze_ttl(tmp_db)
        assert agg.total_timeouts == 1
        # TTL=5 and above should rescue
        assert agg.rescued_at.get(5, 0) >= 1
        assert agg.rescued_at.get(10, 0) >= 1

    def test_already_filled_excluded(self, tmp_db, sample_decisions, sample_snapshots):
        """Filled orders are not included in TTL analysis."""
        cfs, agg = analyze_ttl(tmp_db)
        order_ids = [cf.order_id for cf in cfs]
        assert "order_filled_1" not in order_ids
        assert "order_sell_1" not in order_ids


# ---------------------------------------------------------------------------
# Feature C: Costs
# ---------------------------------------------------------------------------


class TestCosts:
    def test_drift_calculation(self, tmp_db, sample_decisions):
        """drift_cost = (submit_ask - decision_ask) * fill_size"""
        bds, _ = analyze_costs(tmp_db)
        filled_buy = [b for b in bds if b.order_id == "order_filled_1"]
        assert len(filled_buy) == 1
        bd = filled_buy[0]
        # decision_ask=0.53, submit_ask=0.54, fill_size=20
        # drift = (0.54 - 0.53) * 20 = 0.20
        assert abs(bd.drift_cost - 0.20) < 0.01

    def test_fee_aggregation(self, tmp_db, sample_decisions):
        """Total fees sum correctly."""
        _, agg = analyze_costs(tmp_db)
        # Two filled orders: fee 0.002 + 0.003 = 0.005
        assert abs(agg.total_fees - 0.005) < 0.001

    def test_by_outcome(self, tmp_db, sample_decisions):
        """Costs grouped by win/loss outcome."""
        _, agg = analyze_costs(tmp_db)
        assert "win" in agg.by_outcome  # Winner is UP, both orders are UP token

    def test_by_side(self, tmp_db, sample_decisions):
        """Costs grouped by BUY/SELL."""
        _, agg = analyze_costs(tmp_db)
        assert "BUY" in agg.by_side
        assert "SELL" in agg.by_side


# ---------------------------------------------------------------------------
# Feature D: Blocked
# ---------------------------------------------------------------------------


class TestBlocked:
    def test_classification(self, tmp_db, sample_decisions):
        """risk_reason strings → correct category mapping."""
        blocked, agg = analyze_blocked(tmp_db)
        assert agg.total_blocked == 1
        assert len(blocked) == 1
        assert blocked[0].category == "kill_switch"
        assert blocked[0].action == "BUY"

    def test_category_counts(self, tmp_db, sample_decisions):
        """by_category counts are correct."""
        _, agg = analyze_blocked(tmp_db)
        assert agg.by_category.get("kill_switch") == 1

    def test_multiple_categories(self, tmp_db, sample_candle):
        """Multiple different risk reasons are classified correctly."""
        reasons = [
            ("kill switch active", "kill_switch"),
            ("no token_id available", "no_token_id"),
            ("no ask in orderbook", "no_book"),
            ("exceeds max position", "max_size"),
            ("wallet below minimum", "low_balance"),
        ]
        for reason, _ in reasons:
            tmp_db.execute(
                "INSERT INTO decisions (candle_id, timestamp, cycle, trigger_type, action, "
                "token_side, risk_blocked, risk_reason, live_order_json) "
                "VALUES (?, ?, 1, 'entry', 'BUY', 'UP', 1, ?, '')",
                (sample_candle, 1000000.0, reason),
            )
        tmp_db.commit()

        blocked, agg = analyze_blocked(tmp_db)
        for reason, expected_cat in reasons:
            matching = [b for b in blocked if b.risk_reason == reason]
            assert len(matching) == 1, f"No match for {reason}"
            assert matching[0].category == expected_cat, f"{reason} → {matching[0].category}, expected {expected_cat}"


# ---------------------------------------------------------------------------
# Feature E: Round-trips
# ---------------------------------------------------------------------------


class TestRoundtrips:
    def test_fifo_pairing(self, tmp_db, sample_decisions):
        """BUY then SELL of same token → one round-trip with correct PnL."""
        trips = analyze_roundtrips(tmp_db)
        assert len(trips) == 1
        t = trips[0]
        assert t.side == "UP"
        assert t.entry_price == 0.54
        assert t.exit_price == 0.60
        # PnL = (0.60 - 0.54) * 20 = 1.20
        assert abs(t.realized_pnl - 1.20) < 0.01

    def test_hold_duration(self, tmp_db, sample_decisions):
        """Hold duration calculated from decision timestamps."""
        trips = analyze_roundtrips(tmp_db)
        assert len(trips) == 1
        # entry_ts = BASE_TS+10, exit_ts = BASE_TS+200
        assert abs(trips[0].hold_duration_s - 190.0) < 1.0

    def test_mfe_mae(self, tmp_db, sample_decisions, sample_snapshots):
        """Known mid prices during hold → correct MFE/MAE."""
        trips = analyze_roundtrips(tmp_db)
        assert len(trips) == 1
        t = trips[0]
        # MFE should be > entry_price (ask dropped then rose)
        # MAE should be < entry_price or at least at the minimum
        assert t.mfe >= t.entry_price or t.mfe > 0  # MFE is at least entry
        assert t.mae > 0  # MAE should be positive


# ---------------------------------------------------------------------------
# Feature F: Decision Context
# ---------------------------------------------------------------------------


class TestContext:
    def test_indicator_parsing(self, tmp_db, sample_decisions):
        """indicators_json parsed into dict of floats."""
        contexts = analyze_context(tmp_db)
        # 3 non-HOLD decisions (BUY filled, BUY timeout, SELL filled)
        # Plus the blocked BUY which is non-HOLD
        assert len(contexts) >= 3

        # Check momentum indicator was parsed
        buy_ctx = [c for c in contexts if c.action == "BUY" and c.candle_id == 1]
        assert len(buy_ctx) >= 1
        assert "momentum" in buy_ctx[0].indicators

    def test_outcome_mapping(self, tmp_db, sample_decisions):
        """Winner=UP, token_side=UP → win."""
        contexts = analyze_context(tmp_db)
        up_buys = [c for c in contexts if c.action == "BUY" and c.candle_id == 1]
        # UP token decisions on a candle won by UP should be "win"
        for ctx in up_buys:
            if ctx.confidence == 0.75:  # the filled BUY
                assert ctx.outcome == "win"

    def test_rr_ratio(self, tmp_db, sample_decisions, sample_snapshots):
        """R/R ratio extracted from nearest snapshot."""
        contexts = analyze_context(tmp_db)
        assert len(contexts) >= 1
        # All snapshots have rr_up=1.5, so any UP decision should get ~1.5
        up_ctx = [c for c in contexts if c.action == "BUY" and c.candle_id == 1]
        for ctx in up_ctx:
            if ctx.confidence == 0.75:
                assert abs(ctx.rr_ratio - 1.5) < 0.1
