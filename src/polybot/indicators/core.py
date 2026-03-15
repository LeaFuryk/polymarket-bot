"""Dynamic feature selection — registry of computed indicators with config-driven activation.

Retains backward-compatible types and functions. Indicator logic has been moved
to individual classes under ``polybot.indicators.catalog``.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from polybot.models import MarketSnapshot

_default_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class IndicatorResult:
    """Single indicator output — one line of text for the prompt."""

    name: str
    value: float
    label: str  # human-readable summary, e.g. "+0.0032 (bullish)"


@dataclass
class SessionContext:
    """Lightweight session stats passed into session-based indicators."""

    wins: int = 0
    losses: int = 0
    avg_win_confidence: float = 0.0
    avg_loss_confidence: float = 0.0
    candle_open_btc: float | None = None  # BTC price at current candle open


# ---------------------------------------------------------------------------
# Indicator registry (populated by catalog on import)
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Callable[..., IndicatorResult | None]] = {}


def register(name: str):
    """Decorator to register an indicator function by name."""

    def decorator(fn: Callable[..., IndicatorResult | None]):
        _REGISTRY[name] = fn
        return fn

    return decorator


def get_registry() -> dict[str, Callable[..., IndicatorResult | None]]:
    # Ensure catalog is loaded so _REGISTRY is populated
    import polybot.indicators.catalog  # noqa: F401

    return _REGISTRY


# ---------------------------------------------------------------------------
# Feature config (read from disk each cycle)
# ---------------------------------------------------------------------------


@dataclass
class FeatureConfigEntry:
    name: str
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)


class FeatureConfig:
    """Reads data/feature_config.json each cycle; returns enabled indicators."""

    def __init__(
        self,
        path: str | Path,
        logger: logging.Logger | None = None,
    ) -> None:
        self._path = Path(path)
        self._entries: list[FeatureConfigEntry] = []
        self._logger = logger or _default_logger

    def load(self) -> None:
        """Re-read config from disk. Safe if file is missing or malformed."""
        if not self._path.exists():
            self._entries = []
            return
        try:
            data = json.loads(self._path.read_text())
            self._entries = [
                FeatureConfigEntry(
                    name=item["name"],
                    enabled=item.get("enabled", False),
                    params=item.get("params", {}),
                )
                for item in data.get("indicators", [])
            ]
        except (json.JSONDecodeError, KeyError, TypeError):
            self._logger.warning("Could not parse feature config at %s", self._path)
            self._entries = []

    def enabled_indicators(self) -> list[tuple[str, dict[str, Any]]]:
        """Return list of (name, params) for enabled indicators."""
        return [(e.name, e.params) for e in self._entries if e.enabled]

    def to_dict(self) -> dict:
        """Serialize current config back to a JSON-serializable dict."""
        return {"indicators": [{"name": e.name, "enabled": e.enabled, "params": e.params} for e in self._entries]}


# ---------------------------------------------------------------------------
# Compute + format helpers (backward-compatible thin wrappers)
# ---------------------------------------------------------------------------


def compute_indicators(
    snapshot: MarketSnapshot,
    config: FeatureConfig,
    session: SessionContext | None = None,
    logger: logging.Logger | None = None,
) -> list[IndicatorResult]:
    """Run all enabled indicators and return results.

    Backward-compatible wrapper that delegates to IndicatorsProcessor.
    """
    from polybot.indicators.catalog import all_indicators
    from polybot.indicators.processor import IndicatorsProcessor

    processor = IndicatorsProcessor(all_indicators(), config, logger=logger)
    indicator_results = processor.compute(
        snapshot,
        session,
        candle_open_btc=session.candle_open_btc if session else None,
    )
    return indicator_results.results


def format_indicators(results: list[IndicatorResult]) -> str:
    """Format indicator results into a markdown block for the prompt."""
    if not results:
        return ""
    lines = ["## Computed Indicators"]
    for r in results:
        lines.append(f"- {r.name}: {r.label}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# EMA helper (kept for backward compatibility)
# ---------------------------------------------------------------------------


def _ema(values: list[float], period: int) -> float:
    """Exponential moving average of the last `period` values."""
    if len(values) < period:
        return statistics.mean(values)
    k = 2 / (period + 1)
    ema = values[-period]  # seed with first value in window
    for v in values[-period + 1 :]:
        ema = v * k + ema * (1 - k)
    return ema
