"""Feature F: Decision context — indicators, R/R ratio, ML score, and outcomes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .constants import ML_MODEL_PATH
from .db import load_candles, load_orders, load_snapshots_for_candle
from .types import DecisionContext


def analyze_context(conn: sqlite3.Connection) -> list[DecisionContext]:
    """Extract R/R, indicators, and ML score at each decision point."""
    rows = load_orders(conn)

    # Build candle_id → winner map
    candles = load_candles(conn)
    candle_winner: dict[int, str | None] = {c["candle_id"]: c.get("winner") for c in candles}

    # Try to load ML model for scoring
    ml_weights = _load_ml_weights()

    contexts: list[DecisionContext] = []

    for d in rows:
        action = d.get("action", "")
        if action == "HOLD":
            continue

        candle_id = d.get("candle_id", 0)
        confidence = d.get("confidence") or 0.0
        token_side = d.get("token_side", "")

        # Parse indicators
        indicators: dict[str, float] = {}
        ind_raw = d.get("indicators_json") or ""
        if ind_raw.strip():
            try:
                ind_data = json.loads(ind_raw)
                for name, info in ind_data.items():
                    if isinstance(info, dict) and "value" in info:
                        try:
                            indicators[name] = float(info["value"])
                        except (ValueError, TypeError):
                            pass
                    elif isinstance(info, int | float):
                        indicators[name] = float(info)
            except (json.JSONDecodeError, TypeError):
                pass

        # Get R/R ratio from nearest snapshot
        rr_ratio = 0.0
        decision_ts = d.get("timestamp", 0.0)
        snaps = load_snapshots_for_candle(conn, candle_id)
        if snaps:
            # Find nearest snapshot to decision time
            nearest = min(snaps, key=lambda s: abs(s["timestamp"] - decision_ts))
            if token_side == "UP":
                rr_ratio = nearest.get("rr_up") or 0.0
            elif token_side == "DOWN":
                rr_ratio = nearest.get("rr_down") or 0.0

        # ML score from weights
        ml_score = None
        if ml_weights and indicators:
            ml_score = _compute_ml_score(indicators, ml_weights)

        # Outcome from candle resolution
        winner = candle_winner.get(candle_id)
        outcome = None
        if winner and token_side:
            outcome = "win" if winner.upper() == token_side.upper() else "loss"

        contexts.append(
            DecisionContext(
                candle_id=candle_id,
                action=action,
                confidence=confidence,
                rr_ratio=rr_ratio,
                indicators=indicators,
                ml_score=ml_score,
                outcome=outcome,
            )
        )

    return contexts


def _load_ml_weights() -> dict | None:
    """Try to load ML model weights from logs/ml_model.json."""
    path = Path(ML_MODEL_PATH)
    if not path.exists():
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("weights") or data.get("coefficients")
    except (json.JSONDecodeError, OSError):
        return None


def _compute_ml_score(indicators: dict[str, float], weights: dict) -> float:
    """Compute a simple weighted sum ML score."""
    score = weights.get("intercept", 0.0) if isinstance(weights, dict) else 0.0
    if isinstance(weights, dict):
        for name, value in indicators.items():
            w = weights.get(name, 0.0)
            if isinstance(w, int | float):
                score += w * value
    return score
