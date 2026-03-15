"""Tests for polybot.shared_state — typed state container and data classes."""

from __future__ import annotations

from polybot.shared_state import (
    CandleMicrostructure,
    EntryContext,
    SharedState,
    StopLossRecord,
)
from polybot.shared_state.constants import (
    DEFAULT_AVG_IMBALANCE,
    DEFAULT_ML_CONFIDENCE,
    DEFAULT_ML_UP_PROBABILITY,
    DEFAULT_REGIME,
    DEFAULT_SIGNAL_TYPE,
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
