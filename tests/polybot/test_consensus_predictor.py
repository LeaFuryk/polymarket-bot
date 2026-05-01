"""Tests for ConsensusPredictor."""

import time

from polybot.adapters.consensus_predictor import ConsensusPredictor
from polybot.ports.ensemble import EnsemblePredictor
from polybot_data.services.indicator_engine import IndicatorSnapshot


def _make_snapshot(up_ask=0.60, down_ask=0.40):
    return IndicatorSnapshot(
        candle_id="c1",
        timestamp=time.time(),
        elapsed_pct=0.1,
        btc_price=70000.0,
        btc_bid=69999.0,
        btc_ask=70001.0,
        up_bids=[(0.58, 100)],
        up_asks=[(up_ask, 100)],
        down_bids=[(0.38, 100)],
        down_asks=[(down_ask, 100)],
        market_volume=50.0,
    )


class TestConsensusPredictor:
    def test_satisfies_protocol(self):
        p = ConsensusPredictor(dnn_name="DNN", edge_threshold=0.07, min_agreement=2)
        assert isinstance(p, EnsemblePredictor)

    def test_bet_when_dnn_has_edge_and_majority_agrees(self):
        p = ConsensusPredictor(dnn_name="DNN", edge_threshold=0.07, min_agreement=2)
        preds = {"LR": 0.62, "RF": 0.71, "XGB": 0.45, "DNN": 0.74}
        result = p.predict_ensemble(preds, {}, _make_snapshot(up_ask=0.60))
        assert result == 0.74

    def test_skip_when_majority_disagrees(self):
        p = ConsensusPredictor(dnn_name="DNN", edge_threshold=0.07, min_agreement=2)
        preds = {"LR": 0.40, "RF": 0.60, "XGB": 0.35, "DNN": 0.74}
        result = p.predict_ensemble(preds, {}, _make_snapshot(up_ask=0.60))
        assert result is None

    def test_skip_when_dnn_edge_too_low(self):
        p = ConsensusPredictor(dnn_name="DNN", edge_threshold=0.07, min_agreement=2)
        preds = {"LR": 0.62, "RF": 0.71, "XGB": 0.60, "DNN": 0.55}
        result = p.predict_ensemble(preds, {}, _make_snapshot(up_ask=0.50))
        assert result is None

    def test_down_direction(self):
        p = ConsensusPredictor(dnn_name="DNN", edge_threshold=0.07, min_agreement=2)
        preds = {"LR": 0.35, "RF": 0.30, "XGB": 0.40, "DNN": 0.30}
        result = p.predict_ensemble(preds, {}, _make_snapshot(down_ask=0.40))
        assert result == 0.30

    def test_missing_ask_data_skips(self):
        p = ConsensusPredictor(dnn_name="DNN", edge_threshold=0.07, min_agreement=2)
        preds = {"LR": 0.62, "RF": 0.71, "XGB": 0.60, "DNN": 0.74}
        snap = IndicatorSnapshot(
            candle_id="c1",
            timestamp=time.time(),
            elapsed_pct=0.1,
            btc_price=70000.0,
            btc_bid=69999.0,
            btc_ask=70001.0,
            up_bids=[],
            up_asks=[],
            down_bids=[],
            down_asks=[],
            market_volume=50.0,
        )
        result = p.predict_ensemble(preds, {}, snap)
        assert result is None

    def test_skip_when_dnn_prediction_missing(self):
        p = ConsensusPredictor(dnn_name="DNN", edge_threshold=0.07, min_agreement=2)
        preds = {"LR": 0.62, "RF": 0.71, "XGB": 0.60}
        result = p.predict_ensemble(preds, {}, _make_snapshot())
        assert result is None
