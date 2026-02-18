"""Dynamic feature selection — registry of computed indicators with config-driven activation."""

from __future__ import annotations

import json
import logging
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from polybot.models import MarketSnapshot

logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Indicator registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, Callable[..., IndicatorResult | None]] = {}


def register(name: str):
    """Decorator to register an indicator function by name."""
    def decorator(fn: Callable[..., IndicatorResult | None]):
        _REGISTRY[name] = fn
        return fn
    return decorator


def get_registry() -> dict[str, Callable[..., IndicatorResult | None]]:
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

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._entries: list[FeatureConfigEntry] = []

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
            logger.warning("Could not parse feature config at %s", self._path)
            self._entries = []

    def enabled_indicators(self) -> list[tuple[str, dict[str, Any]]]:
        """Return list of (name, params) for enabled indicators."""
        return [(e.name, e.params) for e in self._entries if e.enabled]

    def to_dict(self) -> dict:
        """Serialize current config back to a JSON-serializable dict."""
        return {
            "indicators": [
                {"name": e.name, "enabled": e.enabled, "params": e.params}
                for e in self._entries
            ]
        }


# ---------------------------------------------------------------------------
# Compute + format helpers
# ---------------------------------------------------------------------------

def compute_indicators(
    snapshot: MarketSnapshot,
    config: FeatureConfig,
    session: SessionContext | None = None,
) -> list[IndicatorResult]:
    """Run all enabled indicators and return results."""
    results: list[IndicatorResult] = []
    for name, params in config.enabled_indicators():
        fn = _REGISTRY.get(name)
        if fn is None:
            logger.debug("Indicator %r not found in registry, skipping", name)
            continue
        try:
            result = fn(snapshot, params, session)
            if result is not None:
                results.append(result)
        except Exception:
            logger.debug("Indicator %r raised, skipping", name, exc_info=True)
    return results


def format_indicators(results: list[IndicatorResult]) -> str:
    """Format indicator results into a markdown block for the prompt."""
    if not results:
        return ""
    lines = ["## Computed Indicators"]
    for r in results:
        lines.append(f"- {r.name}: {r.label}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Token midpoint indicators (use snapshot.price_history)
# ---------------------------------------------------------------------------

@register("token_momentum")
def _token_momentum(
    snap: MarketSnapshot, params: dict, _session: SessionContext | None,
) -> IndicatorResult | None:
    window = params.get("window", 10)
    history = snap.price_history
    if len(history) < window:
        return None
    segment = history[-window:]
    roc = segment[-1] - segment[0]
    direction = "bullish" if roc > 0 else "bearish" if roc < 0 else "flat"
    return IndicatorResult(
        name=f"Token Momentum ({window}pt)",
        value=roc,
        label=f"{roc:+.4f} ({direction})",
    )


@register("token_volatility")
def _token_volatility(
    snap: MarketSnapshot, params: dict, _session: SessionContext | None,
) -> IndicatorResult | None:
    window = params.get("window", 20)
    history = snap.price_history
    if len(history) < max(window, 2):
        return None
    segment = history[-window:]
    vol = statistics.stdev(segment)
    level = "high" if vol > 0.02 else "moderate" if vol > 0.005 else "low"
    return IndicatorResult(
        name=f"Token Volatility ({window}pt)",
        value=vol,
        label=f"{vol:.4f} ({level})",
    )


@register("token_ma_crossover")
def _token_ma_crossover(
    snap: MarketSnapshot, params: dict, _session: SessionContext | None,
) -> IndicatorResult | None:
    short_w = params.get("short_window", 5)
    long_w = params.get("long_window", 20)
    history = snap.price_history
    if len(history) < long_w:
        return None
    short_ma = statistics.mean(history[-short_w:])
    long_ma = statistics.mean(history[-long_w:])
    diff = short_ma - long_ma
    signal = "bullish cross" if diff > 0 else "bearish cross"
    return IndicatorResult(
        name=f"Token MA Crossover ({short_w}/{long_w})",
        value=diff,
        label=f"{diff:+.4f} ({signal})",
    )


@register("token_mean_reversion")
def _token_mean_reversion(
    snap: MarketSnapshot, params: dict, _session: SessionContext | None,
) -> IndicatorResult | None:
    window = params.get("window", 20)
    history = snap.price_history
    if len(history) < max(window, 2):
        return None
    segment = history[-window:]
    mean = statistics.mean(segment)
    std = statistics.stdev(segment)
    if std < 1e-9:
        return None
    z = (history[-1] - mean) / std
    if abs(z) > 2:
        flag = "overextended"
    elif abs(z) > 1:
        flag = "stretched"
    else:
        flag = "normal"
    return IndicatorResult(
        name=f"Token Mean Reversion ({window}pt)",
        value=z,
        label=f"z={z:+.2f} ({flag})",
    )


# ---------------------------------------------------------------------------
# Orderbook indicators (use current snapshot)
# ---------------------------------------------------------------------------

@register("orderbook_imbalance")
def _orderbook_imbalance(
    snap: MarketSnapshot, params: dict, _session: SessionContext | None,
) -> IndicatorResult | None:
    bid_d = snap.orderbook.bid_depth
    ask_d = snap.orderbook.ask_depth
    if ask_d < 1e-9:
        return None
    ratio = bid_d / ask_d
    if ratio > 1.5:
        signal = "strong buy pressure"
    elif ratio > 1.1:
        signal = "slight buy pressure"
    elif ratio < 0.67:
        signal = "strong sell pressure"
    elif ratio < 0.9:
        signal = "slight sell pressure"
    else:
        signal = "balanced"
    return IndicatorResult(
        name="Orderbook Imbalance",
        value=ratio,
        label=f"{ratio:.2f} ({signal})",
    )


@register("spread_trend")
def _spread_trend(
    snap: MarketSnapshot, params: dict, _session: SessionContext | None,
) -> IndicatorResult | None:
    sp = snap.orderbook.spread_pct
    if sp is None:
        return None
    if sp > 0.05:
        level = "very wide"
    elif sp > 0.02:
        level = "wide"
    elif sp > 0.005:
        level = "normal"
    else:
        level = "tight"
    return IndicatorResult(
        name="Spread Level",
        value=sp,
        label=f"{sp:.2%} ({level})",
    )


@register("token_price_divergence")
def _token_price_divergence(
    snap: MarketSnapshot, params: dict, _session: SessionContext | None,
) -> IndicatorResult | None:
    up_mid = snap.orderbook.midpoint
    down_mid = snap.down_orderbook.midpoint
    if up_mid is None or down_mid is None:
        return None
    total = up_mid + down_mid
    deviation = total - 1.0
    if abs(deviation) > 0.03:
        flag = "significant divergence"
    elif abs(deviation) > 0.01:
        flag = "minor divergence"
    else:
        flag = "well-priced"
    return IndicatorResult(
        name="Token Price Divergence",
        value=deviation,
        label=f"{deviation:+.4f} ({flag})",
    )


# ---------------------------------------------------------------------------
# BTC indicators (use snapshot.btc_price_history)
# ---------------------------------------------------------------------------

@register("btc_momentum")
def _btc_momentum(
    snap: MarketSnapshot, params: dict, _session: SessionContext | None,
) -> IndicatorResult | None:
    window = params.get("window", 10)
    history = snap.btc_price_history
    if len(history) < window:
        return None
    segment = history[-window:]
    roc = segment[-1] - segment[0]
    direction = "bullish" if roc > 0 else "bearish" if roc < 0 else "flat"
    return IndicatorResult(
        name=f"BTC Momentum ({window}pt)",
        value=roc,
        label=f"${roc:+.0f} ({direction})",
    )


@register("btc_volatility")
def _btc_volatility(
    snap: MarketSnapshot, params: dict, _session: SessionContext | None,
) -> IndicatorResult | None:
    window = params.get("window", 20)
    history = snap.btc_price_history
    if len(history) < max(window, 2):
        return None
    segment = history[-window:]
    vol = statistics.stdev(segment)
    level = "high" if vol > 200 else "moderate" if vol > 50 else "low"
    return IndicatorResult(
        name=f"BTC Volatility ({window}pt)",
        value=vol,
        label=f"${vol:.0f} ({level})",
    )


# ---------------------------------------------------------------------------
# Session indicators
# ---------------------------------------------------------------------------

@register("session_streak")
def _session_streak(
    snap: MarketSnapshot, params: dict, session: SessionContext | None,
) -> IndicatorResult | None:
    if session is None:
        return None
    total = session.wins + session.losses
    if total == 0:
        return None
    wr = session.wins / total * 100
    return IndicatorResult(
        name="Session Streak",
        value=wr,
        label=f"{session.wins}W/{session.losses}L ({wr:.0f}% win rate)",
    )


@register("confidence_calibration")
def _confidence_calibration(
    snap: MarketSnapshot, params: dict, session: SessionContext | None,
) -> IndicatorResult | None:
    if session is None:
        return None
    total = session.wins + session.losses
    if total == 0:
        return None
    diff = session.avg_win_confidence - session.avg_loss_confidence
    if abs(diff) < 0.01:
        assessment = "well calibrated"
    elif diff > 0:
        assessment = "higher confidence on wins"
    else:
        assessment = "higher confidence on losses — miscalibrated"
    return IndicatorResult(
        name="Confidence Calibration",
        value=diff,
        label=f"win_avg={session.avg_win_confidence:.2f} loss_avg={session.avg_loss_confidence:.2f} ({assessment})",
    )
