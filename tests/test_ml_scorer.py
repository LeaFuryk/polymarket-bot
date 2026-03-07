"""Tests for the ml_scorer package."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from polybot.ml_scorer.constants import (
    DEFAULT_LEARNING_RATE,
    FEATURE_NAMES,
    FLAT_CANDLE_THRESHOLD,
    LEAN_DOWN_THRESHOLD,
    LEAN_UP_THRESHOLD,
    MIN_TRAINING_SAMPLES,
    NORMALIZATION_SCALES,
    NUM_FEATURES,
    STRONG_DOWN_THRESHOLD,
    STRONG_UP_THRESHOLD,
    VOLATILITY_WINDOW,
    VOLUME_WINDOW,
)
from polybot.ml_scorer.feature_extractor import FeatureExtractor
from polybot.ml_scorer.models import MLPrediction, ModelState, sigmoid
from polybot.ml_scorer.scorer import MLScorer

# ── Helpers ───────────────────────────────────────────────────────────


@dataclass
class FakeCandle:
    """Minimal candle object for testing feature extraction."""

    direction: str
    open: float
    close: float
    high: float
    low: float
    volume: float


def _make_candles(n: int, direction: str = "up", base: float = 100_000.0) -> list[FakeCandle]:
    """Create a sequence of candles going in one direction."""
    candles = []
    for i in range(n):
        o = base + i * 10
        c = o + (5 if direction == "up" else -5)
        candles.append(
            FakeCandle(
                direction=direction,
                open=o,
                close=c,
                high=max(o, c) + 2,
                low=min(o, c) - 2,
                volume=100.0 + i,
            )
        )
    return candles


def _zero_features() -> dict[str, float]:
    return {name: 0.0 for name in FEATURE_NAMES}


# ── Constants ─────────────────────────────────────────────────────────


class TestConstants:
    def test_feature_count(self):
        assert NUM_FEATURES == 10

    def test_feature_names_length_matches(self):
        assert len(FEATURE_NAMES) == NUM_FEATURES

    def test_normalization_scales_length(self):
        assert len(NORMALIZATION_SCALES) == NUM_FEATURES

    def test_thresholds_ordered(self):
        assert STRONG_DOWN_THRESHOLD < LEAN_DOWN_THRESHOLD
        assert LEAN_DOWN_THRESHOLD < LEAN_UP_THRESHOLD
        assert LEAN_UP_THRESHOLD < STRONG_UP_THRESHOLD

    def test_default_learning_rate(self):
        assert DEFAULT_LEARNING_RATE == 0.01

    def test_min_training_samples(self):
        assert MIN_TRAINING_SAMPLES == 10

    def test_flat_candle_threshold(self):
        assert FLAT_CANDLE_THRESHOLD == 5.0

    def test_volatility_window(self):
        assert VOLATILITY_WINDOW == 6

    def test_volume_window(self):
        assert VOLUME_WINDOW == 6


# ── Models ────────────────────────────────────────────────────────────


class TestSigmoid:
    def test_sigmoid_zero(self):
        assert sigmoid(0.0) == pytest.approx(0.5)

    def test_sigmoid_large_positive(self):
        assert sigmoid(100.0) == pytest.approx(1.0, abs=1e-6)

    def test_sigmoid_large_negative(self):
        assert sigmoid(-100.0) == pytest.approx(0.0, abs=1e-6)

    def test_sigmoid_symmetry(self):
        assert sigmoid(2.0) + sigmoid(-2.0) == pytest.approx(1.0)


class TestMLPrediction:
    def test_dataclass_fields(self):
        p = MLPrediction(
            up_probability=0.6,
            confidence="lean_up",
            feature_contributions={"streak_signed": 0.1},
            model_trained=True,
        )
        assert p.up_probability == 0.6
        assert p.confidence == "lean_up"
        assert p.model_trained is True


class TestModelState:
    def test_dataclass_fields(self):
        s = ModelState(
            training_samples=42,
            model_trained=True,
            weights={"streak_signed": 0.1},
            bias=0.05,
            feature_names=["streak_signed"],
        )
        assert s.training_samples == 42
        assert s.model_trained is True
        assert s.bias == 0.05


# ── FeatureExtractor ──────────────────────────────────────────────────


class TestFeatureExtractor:
    def setup_method(self):
        self.extractor = FeatureExtractor()

    def test_extract_no_candles(self):
        features = self.extractor.extract(
            candles=None,
            btc_price=None,
            candle_open=None,
            up_mid=None,
            down_mid=None,
        )
        assert features["streak_signed"] == 0.0
        assert features["volume_ratio"] == 1.0
        assert features["up_midpoint"] == 0.5
        assert features["down_midpoint"] == 0.5
        assert features["book_imbalance"] == 1.0
        assert features["reversal_rate"] == 0.0

    def test_extract_with_candles_streak(self):
        candles = _make_candles(3, direction="up")
        features = self.extractor.extract(
            candles=candles,
            btc_price=None,
            candle_open=None,
            up_mid=0.6,
            down_mid=0.4,
        )
        assert features["streak_signed"] == 3.0
        assert features["up_midpoint"] == 0.6
        assert features["down_midpoint"] == 0.4

    def test_extract_down_streak(self):
        candles = _make_candles(4, direction="down")
        features = self.extractor.extract(
            candles=candles,
            btc_price=None,
            candle_open=None,
            up_mid=None,
            down_mid=None,
        )
        assert features["streak_signed"] == -4.0

    def test_extract_btc_vs_open(self):
        features = self.extractor.extract(
            candles=None,
            btc_price=100_050.0,
            candle_open=100_000.0,
            up_mid=None,
            down_mid=None,
        )
        assert features["btc_vs_open"] == 50.0

    def test_extract_book_imbalance(self):
        features = self.extractor.extract(
            candles=None,
            btc_price=None,
            candle_open=None,
            up_mid=None,
            down_mid=None,
            up_bid_depth=300.0,
            up_ask_depth=100.0,
        )
        assert features["book_imbalance"] == 3.0

    def test_extract_book_imbalance_zero_ask(self):
        features = self.extractor.extract(
            candles=None,
            btc_price=None,
            candle_open=None,
            up_mid=None,
            down_mid=None,
            up_bid_depth=300.0,
            up_ask_depth=0.0,
        )
        assert features["book_imbalance"] == 1.0

    def test_extract_reversal_rate_passthrough(self):
        features = self.extractor.extract(
            candles=None,
            btc_price=None,
            candle_open=None,
            up_mid=None,
            down_mid=None,
            reversal_rate=0.42,
        )
        assert features["reversal_rate"] == 0.42

    def test_extract_volatility(self):
        candles = _make_candles(8, direction="up")
        features = self.extractor.extract(
            candles=candles,
            btc_price=None,
            candle_open=None,
            up_mid=None,
            down_mid=None,
        )
        # Each candle has high-low = (open+7) - (open-7) = 14 for up candles
        # Actually: high = max(o, c) + 2, low = min(o, c) - 2
        # For up: c = o+5, so high = o+5+2 = o+7, low = o-2, range = 9
        assert features["volatility_30m"] == pytest.approx(9.0)

    def test_extract_volume_ratio(self):
        candles = _make_candles(6, direction="up")
        features = self.extractor.extract(
            candles=candles,
            btc_price=None,
            candle_open=None,
            up_mid=None,
            down_mid=None,
        )
        # volumes: [100, 101, 102, 103, 104, 105]
        # recent_3: [103, 104, 105] mean=104
        # prior_3: [100, 101, 102] mean=101
        assert features["volume_ratio"] == pytest.approx(104.0 / 101.0, rel=1e-4)

    def test_extract_flat_ratio(self):
        candles = [
            FakeCandle("up", 100.0, 102.0, 103.0, 99.0, 50.0),  # |close-open| = 2 < 5 → flat
            FakeCandle("up", 100.0, 110.0, 111.0, 99.0, 50.0),  # |close-open| = 10 > 5 → not flat
            FakeCandle("up", 100.0, 101.0, 103.0, 99.0, 50.0),  # flat
        ]
        features = self.extractor.extract(
            candles=candles,
            btc_price=None,
            candle_open=None,
            up_mid=None,
            down_mid=None,
        )
        assert features["flat_ratio"] == pytest.approx(2.0 / 3.0)

    def test_normalize_identity_for_already_scaled(self):
        raw = [0.0] * NUM_FEATURES
        raw[5] = 0.7  # up_midpoint, scale=1.0
        normed = FeatureExtractor.normalize(raw)
        assert normed[5] == 0.7

    def test_normalize_divides_by_scale(self):
        raw = [0.0] * NUM_FEATURES
        raw[0] = 5.0  # streak_signed, scale=5.0
        normed = FeatureExtractor.normalize(raw)
        assert normed[0] == pytest.approx(1.0)

    def test_to_vector_preserves_order(self):
        features = {name: float(i) for i, name in enumerate(FEATURE_NAMES)}
        vec = FeatureExtractor.to_vector(features)
        assert vec == [float(i) for i in range(NUM_FEATURES)]

    def test_to_vector_missing_keys_default_zero(self):
        features = {"streak_signed": 3.0}
        vec = FeatureExtractor.to_vector(features)
        assert vec[0] == 3.0
        assert all(v == 0.0 for v in vec[1:])

    def test_all_features_present(self):
        candles = _make_candles(8, direction="up")
        features = self.extractor.extract(
            candles=candles,
            btc_price=100_050.0,
            candle_open=100_000.0,
            up_mid=0.6,
            down_mid=0.4,
            up_bid_depth=200.0,
            up_ask_depth=100.0,
            reversal_rate=0.3,
        )
        for name in FEATURE_NAMES:
            assert name in features, f"Missing feature: {name}"


# ── MLScorer ──────────────────────────────────────────────────────────


class TestMLScorer:
    def setup_method(self, tmp_path_factory=None):
        pass

    @pytest.fixture
    def scorer(self, tmp_path: Path) -> MLScorer:
        return MLScorer(data_dir=tmp_path)

    def test_predict_untrained_returns_neutral(self, scorer: MLScorer):
        pred = scorer.predict(_zero_features())
        assert pred.up_probability == pytest.approx(0.5)
        assert pred.confidence == "neutral"
        assert pred.model_trained is False

    def test_predict_returns_all_contributions(self, scorer: MLScorer):
        pred = scorer.predict(_zero_features())
        assert set(pred.feature_contributions.keys()) == set(FEATURE_NAMES)

    def test_train_increases_sample_count(self, scorer: MLScorer):
        scorer.train(_zero_features(), up_won=True)
        state = scorer.get_model_state()
        assert state.training_samples == 1

    def test_train_saves_to_disk(self, tmp_path: Path):
        scorer = MLScorer(data_dir=tmp_path)
        scorer.train(_zero_features(), up_won=True)
        model_file = tmp_path / "ml_model.json"
        assert model_file.exists()
        data = json.loads(model_file.read_text())
        assert data["training_samples"] == 1

    def test_persistence_round_trip(self, tmp_path: Path):
        scorer1 = MLScorer(data_dir=tmp_path)
        features = {"streak_signed": 3.0, "up_midpoint": 0.7}
        for _ in range(5):
            scorer1.train(features, up_won=True)

        scorer2 = MLScorer(data_dir=tmp_path)
        state = scorer2.get_model_state()
        assert state.training_samples == 5
        assert state.bias != 0.0

    def test_train_shifts_probability_toward_outcome(self, tmp_path: Path):
        scorer = MLScorer(data_dir=tmp_path)
        features = {"streak_signed": 3.0, "up_midpoint": 0.7}

        for _ in range(20):
            scorer.train(features, up_won=True)

        pred = scorer.predict(features)
        assert pred.up_probability > 0.5

    def test_train_down_shifts_probability_down(self, tmp_path: Path):
        scorer = MLScorer(data_dir=tmp_path)
        features = {"streak_signed": -3.0, "down_midpoint": 0.7}

        for _ in range(20):
            scorer.train(features, up_won=False)

        pred = scorer.predict(features)
        assert pred.up_probability < 0.5

    def test_confidence_classification(self, scorer: MLScorer):
        assert scorer._classify_confidence(0.70) == "strong_up"
        assert scorer._classify_confidence(0.60) == "lean_up"
        assert scorer._classify_confidence(0.50) == "neutral"
        assert scorer._classify_confidence(0.40) == "lean_down"
        assert scorer._classify_confidence(0.30) == "strong_down"

    def test_get_model_state(self, scorer: MLScorer):
        state = scorer.get_model_state()
        assert state.training_samples == 0
        assert state.model_trained is False
        assert len(state.weights) == NUM_FEATURES
        assert state.feature_names == FEATURE_NAMES

    def test_get_summary_untrained(self, scorer: MLScorer):
        summary = scorer.get_summary()
        assert "training" in summary
        assert "0/10" in summary

    def test_get_summary_trained(self, tmp_path: Path):
        scorer = MLScorer(data_dir=tmp_path)
        features = {"streak_signed": 3.0, "up_midpoint": 0.7}
        for _ in range(15):
            scorer.train(features, up_won=True)
        summary = scorer.get_summary()
        assert "15 samples" in summary
        assert "bias=" in summary

    def test_extract_features_delegates(self, scorer: MLScorer):
        candles = _make_candles(3, direction="up")
        features = scorer.extract_features(
            candles=candles,
            btc_price=100_050.0,
            candle_open=100_000.0,
            up_mid=0.6,
            down_mid=0.4,
        )
        assert features["streak_signed"] == 3.0
        assert features["btc_vs_open"] == 50.0

    def test_feature_count_mismatch_resets(self, tmp_path: Path):
        model_file = tmp_path / "ml_model.json"
        model_file.write_text(
            json.dumps(
                {
                    "weights": [0.1, 0.2],  # wrong length
                    "bias": 0.5,
                    "training_samples": 100,
                }
            )
        )
        scorer = MLScorer(data_dir=tmp_path)
        state = scorer.get_model_state()
        assert state.training_samples == 0
        assert state.bias == 0.0

    def test_model_trained_after_min_samples(self, tmp_path: Path):
        scorer = MLScorer(data_dir=tmp_path)
        for i in range(MIN_TRAINING_SAMPLES):
            scorer.train(_zero_features(), up_won=i % 2 == 0)
        assert scorer.get_model_state().model_trained is True

    def test_injectable_logger(self, tmp_path: Path):
        import logging

        custom_logger = logging.getLogger("test.ml_scorer")
        scorer = MLScorer(data_dir=tmp_path, logger=custom_logger)
        assert scorer._log is custom_logger


# ── Backward compatibility ────────────────────────────────────────────


class TestBackwardCompatibility:
    """Verify that the package __init__.py re-exports all public names."""

    def test_import_mlscorer(self):
        from polybot.ml_scorer import MLScorer  # noqa: F811

        assert MLScorer is not None

    def test_import_mlprediction(self):
        from polybot.ml_scorer import MLPrediction  # noqa: F811

        assert MLPrediction is not None

    def test_import_feature_names(self):
        from polybot.ml_scorer import FEATURE_NAMES  # noqa: F811

        assert len(FEATURE_NAMES) == 10

    def test_import_num_features(self):
        from polybot.ml_scorer import NUM_FEATURES  # noqa: F811

        assert NUM_FEATURES == 10

    def test_import_feature_extractor(self):
        from polybot.ml_scorer import FeatureExtractor  # noqa: F811

        assert FeatureExtractor is not None

    def test_import_model_state(self):
        from polybot.ml_scorer import ModelState  # noqa: F811

        assert ModelState is not None
