"""Indicator catalog — all indicator class instances and legacy registry wiring."""

from __future__ import annotations

from polybot.indicators.catalog.best_entry import BestEntryIndicator
from polybot.indicators.catalog.best_entry_analysis import BestEntryAnalysisIndicator
from polybot.indicators.catalog.btc_candle_ma_cross import BtcCandleMaCrossIndicator
from polybot.indicators.catalog.btc_candle_momentum import BtcCandleMomentumIndicator
from polybot.indicators.catalog.btc_momentum import BtcMomentumIndicator
from polybot.indicators.catalog.btc_move_from_open import BtcMoveFromOpenIndicator
from polybot.indicators.catalog.btc_range_30m import BtcRange30mIndicator
from polybot.indicators.catalog.btc_retracement import BtcRetracementIndicator
from polybot.indicators.catalog.btc_trajectory import BtcTrajectoryIndicator
from polybot.indicators.catalog.btc_velocity_conflict import BtcVelocityConflictIndicator
from polybot.indicators.catalog.btc_volatility import BtcVolatilityIndicator
from polybot.indicators.catalog.btc_vs_candle_open import BtcVsCandleOpenIndicator
from polybot.indicators.catalog.chainlink_divergence import ChainlinkDivergenceIndicator
from polybot.indicators.catalog.confidence_calibration import ConfidenceCalibrationIndicator
from polybot.indicators.catalog.consecutive_streak import ConsecutiveStreakIndicator
from polybot.indicators.catalog.cross_book_flow import CrossBookFlowIndicator
from polybot.indicators.catalog.down_orderbook_imbalance import DownOrderbookImbalanceIndicator
from polybot.indicators.catalog.entry_timing import EntryTimingIndicator
from polybot.indicators.catalog.flat_market_edge import FlatMarketEdgeIndicator
from polybot.indicators.catalog.market_trend import MarketTrendIndicator
from polybot.indicators.catalog.microstructure import MicrostructureIndicator
from polybot.indicators.catalog.orderbook_imbalance import OrderbookImbalanceIndicator
from polybot.indicators.catalog.reversal_regime import ReversalRegimeIndicator
from polybot.indicators.catalog.rr_ratio import RiskRewardIndicator
from polybot.indicators.catalog.session_streak import SessionStreakIndicator
from polybot.indicators.catalog.spread_trend import SpreadTrendIndicator
from polybot.indicators.catalog.streak_magnitude import StreakMagnitudeIndicator
from polybot.indicators.catalog.token_ma_crossover import TokenMaCrossoverIndicator
from polybot.indicators.catalog.token_mean_reversion import TokenMeanReversionIndicator
from polybot.indicators.catalog.token_momentum import TokenMomentumIndicator
from polybot.indicators.catalog.token_price_divergence import TokenPriceDivergenceIndicator
from polybot.indicators.catalog.token_volatility import TokenVolatilityIndicator
from polybot.indicators.catalog.volatility_30m import Volatility30mIndicator
from polybot.indicators.catalog.volume_trend import VolumeTrendIndicator
from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import _REGISTRY

_ALL_INDICATORS = [
    # Token indicators
    MarketTrendIndicator(),
    TokenMomentumIndicator(),
    TokenVolatilityIndicator(),
    TokenMaCrossoverIndicator(),
    TokenMeanReversionIndicator(),
    # Orderbook indicators
    OrderbookImbalanceIndicator(),
    SpreadTrendIndicator(),
    DownOrderbookImbalanceIndicator(),
    CrossBookFlowIndicator(),
    BestEntryAnalysisIndicator(),
    TokenPriceDivergenceIndicator(),
    # BTC indicators
    BtcMomentumIndicator(),
    BtcVolatilityIndicator(),
    BtcCandleMomentumIndicator(),
    BtcCandleMaCrossIndicator(),
    # Session indicators
    SessionStreakIndicator(),
    ConfidenceCalibrationIndicator(),
    # Streak indicators
    ConsecutiveStreakIndicator(),
    StreakMagnitudeIndicator(),
    # Other indicators
    BtcVsCandleOpenIndicator(),
    Volatility30mIndicator(),
    ChainlinkDivergenceIndicator(),
    FlatMarketEdgeIndicator(),
    VolumeTrendIndicator(),
    # New consolidated indicators
    RiskRewardIndicator(),
    BtcMoveFromOpenIndicator(),
    BtcRange30mIndicator(),
    BestEntryIndicator(),
    # Prompt-context indicators (formerly ad-hoc computations)
    BtcVelocityConflictIndicator(),
    BtcTrajectoryIndicator(),
    BtcRetracementIndicator(),
    ReversalRegimeIndicator(),
    EntryTimingIndicator(),
    MicrostructureIndicator(),
]


def _wrap(indicator):
    """Create a backward-compatible wrapper for the legacy registry."""

    def fn(snap, params, session):
        btc_candles = tuple(getattr(snap, "btc_candles", ()) or ())
        ctx = IndicatorContext(snapshot=snap, params=params, session=session, btc_candles=btc_candles)
        return indicator.compute(ctx)

    return fn


# Auto-register all catalog indicators in the legacy _REGISTRY
for _ind in _ALL_INDICATORS:
    _REGISTRY[_ind.name] = _wrap(_ind)


def all_indicators():
    """Return all indicator instances (shared singletons)."""
    return list(_ALL_INDICATORS)


__all__ = [
    "all_indicators",
    "BestEntryAnalysisIndicator",
    "BestEntryIndicator",
    "BtcCandleMaCrossIndicator",
    "BtcCandleMomentumIndicator",
    "BtcMomentumIndicator",
    "BtcMoveFromOpenIndicator",
    "BtcRange30mIndicator",
    "BtcRetracementIndicator",
    "BtcTrajectoryIndicator",
    "BtcVelocityConflictIndicator",
    "BtcVolatilityIndicator",
    "BtcVsCandleOpenIndicator",
    "ChainlinkDivergenceIndicator",
    "ConfidenceCalibrationIndicator",
    "ConsecutiveStreakIndicator",
    "CrossBookFlowIndicator",
    "DownOrderbookImbalanceIndicator",
    "EntryTimingIndicator",
    "FlatMarketEdgeIndicator",
    "MarketTrendIndicator",
    "MicrostructureIndicator",
    "OrderbookImbalanceIndicator",
    "ReversalRegimeIndicator",
    "RiskRewardIndicator",
    "SessionStreakIndicator",
    "SpreadTrendIndicator",
    "StreakMagnitudeIndicator",
    "TokenMaCrossoverIndicator",
    "TokenMeanReversionIndicator",
    "TokenMomentumIndicator",
    "TokenPriceDivergenceIndicator",
    "TokenVolatilityIndicator",
    "Volatility30mIndicator",
    "VolumeTrendIndicator",
]
