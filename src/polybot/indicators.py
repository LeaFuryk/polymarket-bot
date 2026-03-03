"""Dynamic feature selection — registry of computed indicators with config-driven activation."""

from __future__ import annotations

import json
import logging
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    candle_open_btc: float | None = None  # BTC price at current candle open


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
        return {"indicators": [{"name": e.name, "enabled": e.enabled, "params": e.params} for e in self._entries]}


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
# EMA helper
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


# ---------------------------------------------------------------------------
# Market trend indicator (EMA-based regime detection)
# ---------------------------------------------------------------------------


@register("market_trend")
def _market_trend(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
) -> IndicatorResult | None:
    """EMA20/EMA50 regime detection on 5-min BTC candle closes."""
    candles = snap.btc_candles
    if len(candles) < 50:
        return None

    closes = [c.close for c in candles]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    price = closes[-1]

    # Score components (each -1 to +1)
    ema_diff = ema20 - ema50
    ema_signal = max(-1, min(1, ema_diff / 100))  # $100 = full signal

    price_diff = price - ema50
    price_signal = max(-1, min(1, price_diff / 150))

    last_12 = candles[-12:]
    up_ratio = sum(1 for c in last_12 if c.direction == "up") / len(last_12)
    candle_signal = (up_ratio - 0.5) * 2  # 0..1 → -1..+1

    score = 0.4 * ema_signal + 0.35 * price_signal + 0.25 * candle_signal
    score = max(-1, min(1, score))

    if score >= 0.5:
        label_text = "STRONG BULLISH"
    elif score >= 0.2:
        label_text = "BULLISH"
    elif score > -0.2:
        label_text = "NEUTRAL"
    elif score > -0.5:
        label_text = "BEARISH"
    else:
        label_text = "STRONG BEARISH"

    return IndicatorResult(
        name="Market Trend",
        value=score,
        label=f"{score:+.2f} ({label_text}) | EMA20=${ema20:,.0f} EMA50=${ema50:,.0f}",
    )


# ---------------------------------------------------------------------------
# Token midpoint indicators (use snapshot.price_history)
# ---------------------------------------------------------------------------


@register("token_momentum")
def _token_momentum(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
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
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
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
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
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
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
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
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
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
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
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


@register("down_orderbook_imbalance")
def _down_orderbook_imbalance(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
) -> IndicatorResult | None:
    """Bid/ask depth ratio for the DOWN token orderbook."""
    bid_d = snap.down_orderbook.bid_depth
    ask_d = snap.down_orderbook.ask_depth
    if ask_d < 1e-9:
        return None
    ratio = bid_d / ask_d
    if ratio > 1.5:
        signal = "strong buy pressure on DOWN"
    elif ratio > 1.1:
        signal = "slight buy pressure on DOWN"
    elif ratio < 0.67:
        signal = "strong sell pressure on DOWN"
    elif ratio < 0.9:
        signal = "slight sell pressure on DOWN"
    else:
        signal = "balanced"
    return IndicatorResult(
        name="Down Book Imbalance",
        value=ratio,
        label=f"{ratio:.2f} ({signal})",
    )


@register("cross_book_flow")
def _cross_book_flow(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
) -> IndicatorResult | None:
    """Compare UP vs DOWN orderbook depth to detect informed flow.

    If one side has significantly more depth, it may indicate informed
    traders are positioning. Depth asymmetry between UP and DOWN
    can signal directional conviction.
    """
    up_depth = snap.orderbook.bid_depth + snap.orderbook.ask_depth
    down_depth = snap.down_orderbook.bid_depth + snap.down_orderbook.ask_depth
    total = up_depth + down_depth
    if total < 1e-9:
        return None
    up_share = up_depth / total
    down_share = down_depth / total

    if up_share > 0.65:
        signal = "heavy UP liquidity — possible informed bullish flow"
    elif down_share > 0.65:
        signal = "heavy DOWN liquidity — possible informed bearish flow"
    elif abs(up_share - 0.5) < 0.05:
        signal = "balanced liquidity"
    else:
        signal = f"UP={up_share:.0%} DOWN={down_share:.0%}"

    return IndicatorResult(
        name="Cross-Book Flow",
        value=up_share - down_share,
        label=f"UP={up_share:.0%} DOWN={down_share:.0%} ({signal})",
    )


@register("best_entry_analysis")
def _best_entry_analysis(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
) -> IndicatorResult | None:
    """Analyze which token offers the better entry price.

    For binary options, lower entry = better risk/reward. Compare UP ask
    vs DOWN ask to identify the cheaper bet.
    """
    up_ask = snap.orderbook.best_ask
    down_ask = snap.down_orderbook.best_ask
    if up_ask is None or down_ask is None:
        return None

    # Risk/reward: entry at P → max profit = 1-P, max loss = P
    up_rr = (1 - up_ask) / up_ask if up_ask > 0 else 0
    down_rr = (1 - down_ask) / down_ask if down_ask > 0 else 0

    cheaper = "UP" if up_ask < down_ask else "DOWN"
    diff = abs(up_ask - down_ask)

    parts = [
        f"UP ask={up_ask:.3f} (R/R={up_rr:.1f}x)",
        f"DOWN ask={down_ask:.3f} (R/R={down_rr:.1f}x)",
    ]
    if diff > 0.05:
        parts.append(f"{cheaper} significantly cheaper")
    elif diff > 0.02:
        parts.append(f"{cheaper} slightly cheaper")
    else:
        parts.append("similar pricing")

    return IndicatorResult(
        name="Best Entry Analysis",
        value=min(up_ask, down_ask),
        label=" | ".join(parts),
    )


@register("token_price_divergence")
def _token_price_divergence(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
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
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
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
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
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
# BTC candle indicators (use snapshot.btc_candles)
# ---------------------------------------------------------------------------


@register("btc_candle_momentum")
def _btc_candle_momentum(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
) -> IndicatorResult | None:
    """Up/down ratio of last N 5-min BTC candles."""
    window = params.get("window", 6)
    candles = snap.btc_candles
    if len(candles) < window:
        return None
    recent = candles[-window:]
    up_count = sum(1 for c in recent if c.direction == "up")
    ratio = up_count / window
    if ratio >= 0.67:
        signal = "bullish momentum"
    elif ratio <= 0.33:
        signal = "bearish momentum"
    else:
        signal = "mixed"
    return IndicatorResult(
        name=f"BTC Candle Momentum ({window})",
        value=ratio,
        label=f"{up_count}/{window} up ({signal})",
    )


@register("btc_candle_ma_cross")
def _btc_candle_ma_cross(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
) -> IndicatorResult | None:
    """MA5 vs MA12 crossover on 5-min BTC candle closes."""
    candles = snap.btc_candles
    if len(candles) < 12:
        return None
    closes = [c.close for c in candles]
    ma5 = statistics.mean(closes[-5:])
    ma12 = statistics.mean(closes[-12:])
    diff = ma5 - ma12
    signal = "bullish cross" if diff > 0 else "bearish cross"
    return IndicatorResult(
        name="BTC Candle MA Cross (5/12)",
        value=diff,
        label=f"${diff:+.0f} ({signal})",
    )


# ---------------------------------------------------------------------------
# Session indicators
# ---------------------------------------------------------------------------


@register("session_streak")
def _session_streak(
    snap: MarketSnapshot,
    params: dict,
    session: SessionContext | None,
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
    snap: MarketSnapshot,
    params: dict,
    session: SessionContext | None,
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


# ---------------------------------------------------------------------------
# BTC candle streak & magnitude indicators
# ---------------------------------------------------------------------------


@register("consecutive_streak")
def _consecutive_streak(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
) -> IndicatorResult | None:
    """Count of consecutive same-direction 5-min BTC candles (from most recent)."""
    candles = snap.btc_candles
    if not candles:
        return None
    streak = 1
    direction = candles[-1].direction
    for c in reversed(candles[:-1]):
        if c.direction == direction:
            streak += 1
        else:
            break
    if streak >= 4:
        signal = f"strong {direction} streak — mean reversion likely"
    elif streak >= 3:
        signal = f"moderate {direction} streak — watch for reversal"
    elif streak >= 2:
        signal = f"mild {direction} continuation"
    else:
        signal = "no streak"
    return IndicatorResult(
        name="Consecutive Streak",
        value=float(streak),
        label=f"{streak} {direction.upper()} candles ({signal})",
    )


@register("streak_magnitude")
def _streak_magnitude(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
) -> IndicatorResult | None:
    """Total BTC $ move during the current consecutive candle streak."""
    candles = snap.btc_candles
    if len(candles) < 2:
        return None
    # Count streak
    direction = candles[-1].direction
    streak_start = len(candles) - 1
    for i in range(len(candles) - 2, -1, -1):
        if candles[i].direction == direction:
            streak_start = i
        else:
            break
    magnitude = candles[-1].close - candles[streak_start].open
    abs_mag = abs(magnitude)
    if abs_mag > 200:
        signal = "exhaustion zone — reversal risk high"
    elif abs_mag > 100:
        signal = "strong move — consider fade"
    elif abs_mag > 50:
        signal = "moderate move"
    else:
        signal = "small move"
    return IndicatorResult(
        name="Streak Magnitude",
        value=magnitude,
        label=f"${magnitude:+,.0f} ({signal})",
    )


@register("btc_vs_candle_open")
def _btc_vs_candle_open(
    snap: MarketSnapshot,
    params: dict,
    session: SessionContext | None,
) -> IndicatorResult | None:
    """Where is BTC NOW relative to the current 5-min candle open?

    This is the key metric for binary candle markets: if BTC is already
    above the candle open, UP is currently winning (and vice versa).
    Uses the actual recorded candle open price when available (from the
    resolution tracker), falls back to last completed candle close.
    """
    if not snap.btc_price:
        return None

    # Prefer actual recorded candle open, fallback to last candle close
    candle_open = None
    if session and session.candle_open_btc is not None:
        candle_open = session.candle_open_btc
    elif snap.btc_candles:
        candle_open = snap.btc_candles[-1].close

    if candle_open is None:
        return None

    current_price = snap.btc_price.price_usd
    diff = current_price - candle_open
    pct = diff / candle_open * 100 if candle_open else 0

    source = "recorded" if (session and session.candle_open_btc) else "estimated"
    if diff > 0:
        signal = "UP currently winning"
    elif diff < 0:
        signal = "DOWN currently winning"
    else:
        signal = "flat — UP wins ties"

    return IndicatorResult(
        name="BTC vs Candle Open",
        value=diff,
        label=f"${diff:+,.0f} ({pct:+.3f}%) — {signal} (open ${candle_open:,.0f} [{source}])",
    )


@register("volatility_30m")
def _volatility_30m(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
) -> IndicatorResult | None:
    """Standard deviation of 5-min candle ranges over last 30 minutes."""
    candles = snap.btc_candles
    if len(candles) < 6:
        return None
    recent = candles[-6:]
    ranges = [c.high - c.low for c in recent]
    vol = statistics.stdev(ranges) if len(ranges) >= 2 else 0
    avg_range = statistics.mean(ranges)

    if avg_range > 150:
        regime = "high volatility — trending market"
    elif avg_range > 80:
        regime = "moderate volatility"
    elif avg_range > 30:
        regime = "low volatility — range-bound"
    else:
        regime = "very low volatility — choppy"

    return IndicatorResult(
        name="30min Volatility",
        value=avg_range,
        label=f"avg_range=${avg_range:.0f} stdev=${vol:.0f} ({regime})",
    )


@register("chainlink_divergence")
def _chainlink_divergence(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
) -> IndicatorResult | None:
    """Binance vs Chainlink price divergence.

    Since Polymarket resolves using Chainlink BTC/USD Data Streams,
    any divergence between Binance (our primary feed) and Chainlink
    (the resolution source) could lead to unexpected outcomes.

    Large divergence = higher resolution risk.
    """
    if not snap.btc_price or snap.btc_price.chainlink_price is None:
        return None

    divergence = snap.btc_price.price_divergence or 0.0
    abs_div = abs(divergence)
    chainlink = snap.btc_price.chainlink_price
    pct = divergence / chainlink * 100 if chainlink else 0

    # Binance vs Chainlink divergence = resolution risk
    if abs_div > 50:
        signal = "HIGH divergence — resolution risk"
    elif abs_div > 20:
        signal = "moderate divergence — monitor"
    elif abs_div > 5:
        signal = "minor divergence"
    else:
        signal = "aligned"

    # If Chainlink is higher, it means the resolution source sees a higher price
    # This matters for "close >= open" comparisons
    if divergence > 5:
        note = "Chainlink LOWER → resolution may differ from Binance"
    elif divergence < -5:
        note = "Chainlink HIGHER → resolution may differ from Binance"
    else:
        note = ""

    label = f"${divergence:+,.0f} ({pct:+.3f}%) — {signal}"
    if note:
        label += f" | {note}"

    return IndicatorResult(
        name="Chainlink Divergence",
        value=divergence,
        label=label,
    )


@register("flat_market_edge")
def _flat_market_edge(
    snap: MarketSnapshot,
    params: dict,
    session: SessionContext | None,
) -> IndicatorResult | None:
    """Detect flat/near-flat BTC conditions where UP wins by default.

    Polymarket rule: BTC close >= open → UP wins. Equal price = UP wins.
    When BTC is barely moving (<$5 range), UP has a structural edge that
    may be underpriced in the market.
    """
    candles = snap.btc_candles
    if len(candles) < 3:
        return None

    # Check recent candles for flat patterns
    flat_threshold = params.get("flat_threshold", 5.0)  # $ threshold for "flat"
    recent = candles[-6:] if len(candles) >= 6 else candles
    flat_count = sum(1 for c in recent if abs(c.close - c.open) < flat_threshold)
    flat_ratio = flat_count / len(recent)

    # Check if UP token is underpriced in flat conditions
    up_mid = snap.orderbook.midpoint

    signal_parts = [f"{flat_count}/{len(recent)} flat candles"]

    if flat_ratio >= 0.5 and up_mid is not None and up_mid < 0.50:
        signal_parts.append(f"UP underpriced at {up_mid:.3f} — structural edge")
        signal = " | ".join(signal_parts)
        return IndicatorResult(
            name="Flat Market Edge",
            value=flat_ratio,
            label=f"{signal}",
        )
    elif flat_ratio >= 0.5:
        signal_parts.append("flat market — UP wins ties")
        signal = " | ".join(signal_parts)
        return IndicatorResult(
            name="Flat Market Edge",
            value=flat_ratio,
            label=f"{signal}",
        )

    # Not flat enough to signal
    return IndicatorResult(
        name="Flat Market Edge",
        value=flat_ratio,
        label=f"{flat_count}/{len(recent)} flat candles (no edge)",
    )


@register("volume_trend")
def _volume_trend(
    snap: MarketSnapshot,
    params: dict,
    _session: SessionContext | None,
) -> IndicatorResult | None:
    """Compare recent volume to earlier volume — increasing/decreasing/flat."""
    candles = snap.btc_candles
    if len(candles) < 6:
        return None
    recent_3 = candles[-3:]
    prior_3 = candles[-6:-3]
    recent_vol = statistics.mean([c.volume for c in recent_3])
    prior_vol = statistics.mean([c.volume for c in prior_3])
    if prior_vol < 1e-9:
        return None
    ratio = recent_vol / prior_vol
    if ratio > 1.3:
        signal = "increasing — confirms direction"
    elif ratio > 1.1:
        signal = "slightly increasing"
    elif ratio < 0.7:
        signal = "decreasing — weakening momentum"
    elif ratio < 0.9:
        signal = "slightly decreasing"
    else:
        signal = "flat"

    return IndicatorResult(
        name="Volume Trend",
        value=ratio,
        label=f"{ratio:.2f}x ({signal})",
    )
