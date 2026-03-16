"""IndicatorsProcessor — computes all indicators once per tick."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from polybot.indicators.context import IndicatorContext
from polybot.indicators.results import IndicatorResults

if TYPE_CHECKING:
    from polybot.indicators.core import FeatureConfig, SessionContext
    from polybot.indicators.protocol import Indicator
    from polybot.models import MarketSnapshot

_default_logger = logging.getLogger(__name__)


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
        position_side: str = "",
        btc_candles: Sequence | None = None,
        microstructure_history: Sequence | None = None,
        session_trades: Sequence | None = None,
        session_resolutions: Sequence | None = None,
    ) -> IndicatorResults:
        """Run all indicators and return results."""
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
                position_side=position_side,
                btc_candles=tuple(btc_candles) if btc_candles else (),
                microstructure_history=tuple(microstructure_history) if microstructure_history else (),
                session_trades=tuple(session_trades) if session_trades else (),
                session_resolutions=tuple(session_resolutions) if session_resolutions else (),
            )
            try:
                result = indicator.compute(ctx)
                if result is not None:
                    # Include in results if no config provided, or indicator is enabled
                    if self._feature_config is None or indicator.name in enabled_names:
                        results.results.append(result)
            except Exception:
                self._logger.debug("Indicator %r raised, skipping", indicator.name, exc_info=True)

        return results
