"""Tests for polybot.shared_state — typed state container and data classes."""

from __future__ import annotations

from polybot.shared_state import (
    CandleMicrostructure,
    EntryContext,
    PreFilterSnapshot,
    SharedState,
    StopLossRecord,
)
from polybot.shared_state.constants import (
    DEFAULT_AVG_IMBALANCE,
    DEFAULT_BEST_ENTRY,
    DEFAULT_ML_CONFIDENCE,
    DEFAULT_ML_UP_PROBABILITY,
    DEFAULT_REGIME,
    DEFAULT_SIGNAL_TYPE,
    PREFILTER_HISTORY_MAXLEN,
)

# -- Constants -----------------------------------------------------------------


class TestConstants:
    """Constants are used by dataclasses and SharedState."""

    def test_entry_context_defaults(self):
        ctx = EntryContext()
        assert ctx.ml_up_probability == DEFAULT_ML_UP_PROBABILITY
        assert ctx.ml_confidence == DEFAULT_ML_CONFIDENCE

    def test_microstructure_defaults(self):
        ms = CandleMicrostructure()
        assert ms.avg_imbalance == DEFAULT_AVG_IMBALANCE

    def test_prefilter_defaults(self):
        snap = PreFilterSnapshot(timestamp=1.0, time_remaining=299.0)
        assert snap.best_entry_up == DEFAULT_BEST_ENTRY
        assert snap.best_entry_down == DEFAULT_BEST_ENTRY


# -- Dataclass construction ---------------------------------------------------


class TestEntryContext:
    def test_defaults(self):
        ctx = EntryContext()
        assert ctx.entry_price == 0.0
        assert ctx.ml_confidence == DEFAULT_ML_CONFIDENCE

    def test_custom_values(self):
        ctx = EntryContext(entry_price=0.55, confidence_at_entry=0.8)
        assert ctx.entry_price == 0.55
        assert ctx.confidence_at_entry == 0.8


class TestStopLossRecord:
    def test_construction(self):
        rec = StopLossRecord(token_side="up", pnl_pct=-0.25, timestamp=1000.0)
        assert rec.token_side == "up"
        assert rec.pnl_pct == -0.25
        assert rec.timestamp == 1000.0


class TestPreFilterSnapshot:
    def test_required_fields(self):
        snap = PreFilterSnapshot(timestamp=100.0, time_remaining=200.0)
        assert snap.timestamp == 100.0
        assert snap.checks == {}
        assert snap.reasons == []

    def test_optional_fields(self):
        snap = PreFilterSnapshot(
            timestamp=100.0,
            time_remaining=200.0,
            rr_up=1.5,
            btc_price=65000.0,
        )
        assert snap.rr_up == 1.5
        assert snap.btc_price == 65000.0


class TestCandleMicrostructure:
    def test_defaults(self):
        ms = CandleMicrostructure()
        assert ms.avg_imbalance == DEFAULT_AVG_IMBALANCE
        assert ms.btc_range == 0.0


# -- SharedState initialization -----------------------------------------------


class TestSharedStateInit:
    def test_initial_state(self):
        state = SharedState()
        assert state.latest_snapshot is None
        assert state.snapshot_timestamp == 0.0
        assert state.current_market is None
        assert state.shutdown is False
        assert state.session_wins == 0
        assert state.session_losses == 0

    def test_prefilter_history_maxlen(self):
        state = SharedState()
        assert state.prefilter_history.maxlen == PREFILTER_HISTORY_MAXLEN

    def test_last_stop_loss_initially_none(self):
        state = SharedState()
        assert state.last_stop_loss is None

    def test_dynamic_sl_tp_empty(self):
        state = SharedState()
        assert state.dynamic_sl == {}
        assert state.dynamic_tp == {}

    def test_signal_type_and_regime_defaults(self):
        state = SharedState()
        assert state.signal_type == DEFAULT_SIGNAL_TYPE
        assert state.regime == DEFAULT_REGIME
