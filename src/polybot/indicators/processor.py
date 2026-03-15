"""IndicatorsProcessor — computes all indicators once per tick."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from polybot.indicators.catalog.best_entry import BestEntryIndicator
from polybot.indicators.catalog.btc_move_from_open import BtcMoveFromOpenIndicator
from polybot.indicators.catalog.btc_range_30m import BtcRange30mIndicator
from polybot.indicators.catalog.consecutive_streak import ConsecutiveStreakIndicator
from polybot.indicators.catalog.rr_ratio import RiskRewardIndicator
from polybot.indicators.context import IndicatorContext
from polybot.indicators.results import IndicatorResults

if TYPE_CHECKING:
    from polybot.indicators.core import FeatureConfig, SessionContext
    from polybot.indicators.protocol import Indicator
    from polybot.models import MarketSnapshot

_default_logger = logging.getLogger(__name__)

# Indicator names that always run to populate derived fields on IndicatorResults.
_INFRASTRUCTURE_NAMES: frozenset[str] = frozenset(
    {
        "rr_ratio",
        "btc_move_from_open",
        "btc_range_30m",
        "best_entry",
        "consecutive_streak",
    }
)


class IndicatorsProcessor:
    """Computes all indicators once per tick and returns an IndicatorResults container."""

    def __init__(
        self,
        indicators: Sequence[Indicator],
        feature_config: FeatureConfig | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._indicators = indicators
        self._feature_config = feature_config
        self._logger = logger or _default_logger

    def compute(
        self,
        snapshot: MarketSnapshot,
        session: SessionContext | None = None,
        *,
        candle_open_btc: float | None = None,
        has_open_position: bool = False,
        time_remaining: float = 0.0,
    ) -> IndicatorResults:
        """Run all indicators and return results with derived fields populated."""
        if self._feature_config is not None:
            self._feature_config.load()

        # Build params map from feature config
        params_map: dict[str, dict] = {}
        enabled_names: set[str] = set()
        if self._feature_config is not None:
            for name, params in self._feature_config.enabled_indicators():
                params_map[name] = params
                enabled_names.add(name)

        results = IndicatorResults()

        for indicator in self._indicators:
            params = params_map.get(indicator.name, {})
            ctx = IndicatorContext(
                snapshot=snapshot,
                params=params,
                session=session,
                candle_open_btc=candle_open_btc,
                has_open_position=has_open_position,
                time_remaining=time_remaining,
            )
            try:
                result = indicator.compute(ctx)
                if result is not None:
                    # Include in prompt results if no config, or indicator is enabled
                    if self._feature_config is None or indicator.name in enabled_names:
                        results.results.append(result)
                    # Always extract derived fields from infrastructure indicators
                    if indicator.name in _INFRASTRUCTURE_NAMES:
                        self._extract_derived(results, indicator, result)
            except Exception:
                self._logger.debug("Indicator %r raised, skipping", indicator.name, exc_info=True)

        return results

    @staticmethod
    def _extract_derived(
        results: IndicatorResults,
        indicator: Indicator,
        result,
    ) -> None:
        """Populate derived fields by reading from the indicator that just ran."""
        if isinstance(indicator, RiskRewardIndicator):
            results.rr_up = indicator.last_rr_up
            results.rr_down = indicator.last_rr_down
        elif isinstance(indicator, BtcMoveFromOpenIndicator):
            results.btc_move_from_open = result.value
        elif isinstance(indicator, ConsecutiveStreakIndicator):
            results.consecutive_streak = indicator.last_streak
            results.streak_direction = indicator.last_direction
        elif isinstance(indicator, BtcRange30mIndicator):
            results.btc_range_30m = result.value
        elif isinstance(indicator, BestEntryIndicator):
            results.best_entry_price = result.value
