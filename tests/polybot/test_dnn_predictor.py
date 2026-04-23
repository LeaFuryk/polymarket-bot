"""Tests for DnnPredictor."""

from __future__ import annotations

import tempfile
from pathlib import Path

import joblib
import numpy as np

torch = __import__("pytest").importorskip("torch")

from polybot.adapters.dnn_predictor import DnnPredictor  # noqa: E402
from polybot.ports.predictor import Predictor  # noqa: E402

# Number of features used throughout the tests.
_N_FEATURES = 11
_FEATURE_COLS = [f"feat_{i}" for i in range(_N_FEATURES)]


def _make_row(candle_id: str = "c1", **overrides: float) -> dict:
    """Build a sample row with all feature columns set to 1.0."""
    row: dict = {col: 1.0 for col in _FEATURE_COLS}
    row["candle_id"] = candle_id
    # Allow extra/override keys.
    row.update(overrides)
    return row


class _SimpleLinear(torch.nn.Module):
    """Deterministic single-layer model for testing single-snapshot mode."""

    def __init__(self, n_features: int) -> None:
        super().__init__()
        self.linear = torch.nn.Linear(n_features, 1)
        # Fix weights so output is deterministic.
        with torch.no_grad():
            self.linear.weight.fill_(0.1)
            self.linear.bias.fill_(0.0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.linear(x)


class _SimpleTemporalModel(torch.nn.Module):
    """Deterministic model that accepts 3-D input (batch, seq_len, features).

    Averages across the sequence dimension then applies a linear layer.
    """

    def __init__(self, n_features: int) -> None:
        super().__init__()
        self.linear = torch.nn.Linear(n_features, 1)
        with torch.no_grad():
            self.linear.weight.fill_(0.1)
            self.linear.bias.fill_(0.0)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x shape: (batch, seq_len, n_features)
        pooled = x.mean(dim=1)  # (batch, n_features)
        return self.linear(pooled)


def _save_model_files(
    tmpdir: str,
    model: torch.nn.Module,
    *,
    with_scaler: bool = False,
) -> tuple[str, str, str | None]:
    """Persist model + feature_cols (and optional scaler) to *tmpdir*.

    Returns (model_path, cols_path, scaler_path | None).
    """
    model_path = str(Path(tmpdir) / "model.pt")
    cols_path = str(Path(tmpdir) / "feature_cols.joblib")
    torch.save(model, model_path)
    joblib.dump(_FEATURE_COLS, cols_path)

    scaler_path: str | None = None
    if with_scaler:
        from sklearn.preprocessing import StandardScaler

        scaler = StandardScaler()
        scaler.fit(np.ones((_N_FEATURES, _N_FEATURES)))  # fit on dummy data
        scaler_path = str(Path(tmpdir) / "scaler.joblib")
        joblib.dump(scaler, scaler_path)

    return model_path, cols_path, scaler_path


# ---------------------------------------------------------------
# Tests
# ---------------------------------------------------------------


class TestDnnPredictorProtocol:
    """DnnPredictor must satisfy the Predictor protocol."""

    def test_isinstance_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _SimpleLinear(_N_FEATURES)
            mp, cp, _ = _save_model_files(tmpdir, model)
            pred = DnnPredictor(model_path=mp, feature_cols_path=cp)
            assert isinstance(pred, Predictor)


class TestSingleSnapshotMode:
    """Tests for ``temporal=False`` (default)."""

    def test_predict_returns_float_in_01(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _SimpleLinear(_N_FEATURES)
            mp, cp, _ = _save_model_files(tmpdir, model)
            pred = DnnPredictor(model_path=mp, feature_cols_path=cp)
            prob = pred.predict(_make_row())
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0

    def test_picks_only_feature_columns(self) -> None:
        """Extra keys in the row must be ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _SimpleLinear(_N_FEATURES)
            mp, cp, _ = _save_model_files(tmpdir, model)
            pred = DnnPredictor(model_path=mp, feature_cols_path=cp)

            row_minimal = _make_row()
            row_extra = _make_row(extra_a=999.0, extra_b=-42.0)
            assert pred.predict(row_minimal) == pred.predict(row_extra)

    def test_deterministic_output(self) -> None:
        """Same input should give the same output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _SimpleLinear(_N_FEATURES)
            mp, cp, _ = _save_model_files(tmpdir, model)
            pred = DnnPredictor(model_path=mp, feature_cols_path=cp)
            row = _make_row()
            assert pred.predict(row) == pred.predict(row)

    def test_expected_logit_value(self) -> None:
        """With weight=0.1 and bias=0, features all 1.0 → logit = 1.1 → sigmoid ≈ 0.75."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _SimpleLinear(_N_FEATURES)
            mp, cp, _ = _save_model_files(tmpdir, model)
            pred = DnnPredictor(model_path=mp, feature_cols_path=cp)
            prob = pred.predict(_make_row())
            expected = float(torch.sigmoid(torch.tensor(0.1 * _N_FEATURES)))
            assert abs(prob - expected) < 1e-6

    def test_with_scaler(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _SimpleLinear(_N_FEATURES)
            mp, cp, sp = _save_model_files(tmpdir, model, with_scaler=True)
            pred = DnnPredictor(model_path=mp, feature_cols_path=cp, scaler_path=sp)
            prob = pred.predict(_make_row())
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0

    def test_scaler_changes_output(self) -> None:
        """When a scaler is applied the output should differ from unscaled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _SimpleLinear(_N_FEATURES)
            mp, cp, sp = _save_model_files(tmpdir, model, with_scaler=True)
            pred_no_scaler = DnnPredictor(model_path=mp, feature_cols_path=cp)
            pred_with_scaler = DnnPredictor(model_path=mp, feature_cols_path=cp, scaler_path=sp)

            row = _make_row()
            p_no = pred_no_scaler.predict(row)
            p_yes = pred_with_scaler.predict(row)
            # The scaler was fit on all-ones → std≈0, so it's not identity.
            # We just verify the outputs differ (scaler had an effect).
            assert p_no != p_yes


class TestMissingAndNoneColumns:
    """Missing or None feature values should default to 0.0."""

    def test_missing_column_defaults_to_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _SimpleLinear(_N_FEATURES)
            mp, cp, _ = _save_model_files(tmpdir, model)
            pred = DnnPredictor(model_path=mp, feature_cols_path=cp)

            # Row with only one feature present.
            row = {"feat_0": 5.0, "candle_id": "c1"}
            prob = pred.predict(row)
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0

    def test_none_value_treated_as_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _SimpleLinear(_N_FEATURES)
            mp, cp, _ = _save_model_files(tmpdir, model)
            pred = DnnPredictor(model_path=mp, feature_cols_path=cp)

            row_with_none = {col: None for col in _FEATURE_COLS}
            row_with_none["candle_id"] = "c1"
            row_with_zero = {col: 0.0 for col in _FEATURE_COLS}
            row_with_zero["candle_id"] = "c1"

            assert pred.predict(row_with_none) == pred.predict(row_with_zero)


class TestTemporalMode:
    """Tests for ``temporal=True``."""

    def _make_temporal_predictor(self, tmpdir: str, seq_len: int = 5) -> DnnPredictor:
        model = _SimpleTemporalModel(_N_FEATURES)
        mp, cp, _ = _save_model_files(tmpdir, model)
        return DnnPredictor(
            model_path=mp,
            feature_cols_path=cp,
            temporal=True,
            seq_len=seq_len,
        )

    def test_predict_returns_float_in_01(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pred = self._make_temporal_predictor(tmpdir)
            prob = pred.predict(_make_row())
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0

    def test_buffer_accumulates_within_candle(self) -> None:
        """Multiple predict() calls with same candle_id grow the buffer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pred = self._make_temporal_predictor(tmpdir, seq_len=5)

            # Feed 3 ticks in the same candle.
            for _ in range(3):
                pred.predict(_make_row(candle_id="c1"))

            assert len(pred._buffer) == 3

    def test_buffer_resets_on_candle_change(self) -> None:
        """When candle_id changes the buffer must be cleared."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pred = self._make_temporal_predictor(tmpdir, seq_len=5)

            for _ in range(4):
                pred.predict(_make_row(candle_id="c1"))
            assert len(pred._buffer) == 4

            # Switch candle.
            pred.predict(_make_row(candle_id="c2"))
            assert len(pred._buffer) == 1
            assert pred._current_candle_id == "c2"

    def test_pads_short_sequences(self) -> None:
        """When buffer length < seq_len the first row is repeated to pad."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pred = self._make_temporal_predictor(tmpdir, seq_len=5)

            # One tick → buffer has 1 row, should still produce valid output.
            prob = pred.predict(_make_row(candle_id="c1"))
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0
            # Buffer should still only have the 1 real row.
            assert len(pred._buffer) == 1

    def test_truncates_long_sequences(self) -> None:
        """When buffer length > seq_len only the last seq_len rows are used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            seq_len = 3
            pred = self._make_temporal_predictor(tmpdir, seq_len=seq_len)

            # Feed 6 ticks.
            for i in range(6):
                pred.predict(_make_row(candle_id="c1", feat_0=float(i)))

            # Buffer grows unbounded in memory, but model only sees last 3.
            assert len(pred._buffer) == 6
            # Output should be deterministic with the last 3 rows.
            prob = pred.predict(_make_row(candle_id="c1", feat_0=6.0))
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0

    def test_padded_output_differs_from_full(self) -> None:
        """A single-tick padded sequence should differ from a full buffer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            seq_len = 3
            pred = self._make_temporal_predictor(tmpdir, seq_len=seq_len)

            # First tick: padded (all copies of first row).
            prob_padded = pred.predict(_make_row(candle_id="c1", feat_0=1.0))

            # Feed different values for remaining ticks.
            pred.predict(_make_row(candle_id="c1", feat_0=2.0))
            prob_full = pred.predict(_make_row(candle_id="c1", feat_0=3.0))

            # With different feature values, padding vs full should differ.
            assert prob_padded != prob_full

    def test_temporal_with_scaler(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            model = _SimpleTemporalModel(_N_FEATURES)
            mp, cp, sp = _save_model_files(tmpdir, model, with_scaler=True)
            pred = DnnPredictor(
                model_path=mp,
                feature_cols_path=cp,
                scaler_path=sp,
                temporal=True,
                seq_len=3,
            )
            prob = pred.predict(_make_row())
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0

    def test_none_candle_id_does_not_crash(self) -> None:
        """If candle_id is missing from the row, temporal mode should still work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pred = self._make_temporal_predictor(tmpdir, seq_len=3)

            row = {col: 1.0 for col in _FEATURE_COLS}
            # No candle_id key at all.
            prob = pred.predict(row)
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0
