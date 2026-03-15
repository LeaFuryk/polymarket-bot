"""Reversal regime indicator — cross-candle reversal pattern detection."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class ReversalRegimeIndicator:
    name = "reversal_regime"
    display_name = "Reversal Regime"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        history = ctx.microstructure_history
        if len(history) < 2:
            return None

        # Cross-candle score from completed candles
        intensities = [h.reversal_intensity for h in history]
        crossings = [h.zero_crossings for h in history]
        avg_intensity = sum(intensities) / len(intensities)
        avg_crossings = sum(crossings) / len(crossings)
        crossing_score = min(avg_crossings / 4.0, 1.0)
        cross_candle_score = 0.5 * avg_intensity + 0.5 * crossing_score

        # Live candle metrics from btc_price_history
        live_score: float | None = None
        candle_open = ctx.candle_open_btc
        btc_history = ctx.snapshot.btc_price_history
        if candle_open is not None and len(btc_history) >= 10:
            moves = [p - candle_open for p in btc_history]
            # Live zero crossings
            live_crossings = 0
            for i in range(1, len(moves)):
                if moves[i - 1] * moves[i] < 0 and abs(moves[i]) >= 1.0 and abs(moves[i - 1]) >= 1.0:
                    live_crossings += 1
            # Live reversal intensity
            btc_range = max(moves) - min(moves)
            btc_final = moves[-1]
            live_intensity = (1.0 - abs(btc_final) / btc_range) if btc_range > 1.0 else 0.0
            live_score = 0.5 * live_intensity + 0.5 * min(live_crossings / 4.0, 1.0)

        # Combined score
        if live_score is not None:
            score = 0.6 * cross_candle_score + 0.4 * live_score
        else:
            score = cross_candle_score

        score = max(0.0, min(score, 1.0))

        if score >= 0.6:
            regime_label = "HIGH_REVERSAL"
            advice = " — size auto-reduced 50%"
        elif score >= 0.35:
            regime_label = "MODERATE_REVERSAL"
            advice = " — size auto-reduced 75%"
        else:
            regime_label = "DIRECTIONAL"
            advice = ""

        label = (
            f"{regime_label} (score={score:.2f}, avg_cross={avg_crossings:.1f}, avg_int={avg_intensity:.2f}){advice}"
        )

        return IndicatorResult(name=self.display_name, value=score, label=label)
