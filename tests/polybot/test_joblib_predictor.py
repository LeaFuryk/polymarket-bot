"""Tests for JoblibPredictor."""

import tempfile
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from polybot.adapters.joblib_predictor import JoblibPredictor
from polybot.ports.predictor import Predictor


class TestJoblibPredictor:
    def _create_model_files(self, tmpdir: str) -> tuple[str, str, str]:
        feat_cols = ["feat_a", "feat_b", "feat_c"]
        X = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0], [10.0, 11.0, 12.0]])
        y = np.array([0, 1, 0, 1])
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        model = LogisticRegression(random_state=42)
        model.fit(X_scaled, y)
        model_path = str(Path(tmpdir) / "model.joblib")
        scaler_path = str(Path(tmpdir) / "scaler.joblib")
        cols_path = str(Path(tmpdir) / "cols.joblib")
        joblib.dump(model, model_path)
        joblib.dump(scaler, scaler_path)
        joblib.dump(feat_cols, cols_path)
        return model_path, scaler_path, cols_path

    def test_implements_protocol(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mp, sp, cp = self._create_model_files(tmpdir)
            pred = JoblibPredictor(model_path=mp, scaler_path=sp, feature_cols_path=cp)
            assert isinstance(pred, Predictor)

    def test_predict_returns_float_between_0_and_1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mp, sp, cp = self._create_model_files(tmpdir)
            pred = JoblibPredictor(model_path=mp, scaler_path=sp, feature_cols_path=cp)
            row = {"feat_a": 5.0, "feat_b": 6.0, "feat_c": 7.0, "extra_field": 999}
            prob = pred.predict(row)
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0

    def test_predict_missing_feature_defaults_to_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mp, sp, cp = self._create_model_files(tmpdir)
            pred = JoblibPredictor(model_path=mp, scaler_path=sp, feature_cols_path=cp)
            row = {"feat_a": 5.0}
            prob = pred.predict(row)
            assert isinstance(prob, float)
            assert 0.0 <= prob <= 1.0

    def test_predict_none_values_treated_as_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mp, sp, cp = self._create_model_files(tmpdir)
            pred = JoblibPredictor(model_path=mp, scaler_path=sp, feature_cols_path=cp)
            row = {"feat_a": 5.0, "feat_b": None, "feat_c": 7.0}
            prob = pred.predict(row)
            assert isinstance(prob, float)
