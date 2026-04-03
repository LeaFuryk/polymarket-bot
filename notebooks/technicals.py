"""Technical indicators for bet outcome inference.

All functions are pure: they take data, return a float or None.
No side effects, no state.

Usage:
    indicators = compute_all(prior_candles, candle_open, snapshots_so_far)
    # -> {"prior_return": 0.0003, "streak": 2, ...}

Arguments:
    prior_candles:      list of completed candle dicts (chronological)
    candle_open:        float, BTC open price of current candle
    snapshots_so_far:   list of snapshot dicts seen so far in this candle
                        (including the current one, last element = current)
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_log(a: float, b: float) -> float:
    if a > 0 and b > 0:
        return math.log(a / b)
    return 0.0


def _linreg_slope(x: list[float], y: list[float]) -> float | None:
    """Simple OLS slope. Returns None if fewer than 3 points."""
    n = len(x)
    if n < 3:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    num = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y, strict=False))
    den = sum((xi - mx) ** 2 for xi in x)
    if den == 0:
        return None
    return num / den


def _std(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _snap_up_mid(s: dict) -> float | None:
    if s["up_bids"] and s["up_asks"]:
        return (s["up_bids"][0][0] + s["up_asks"][0][0]) / 2
    return None


def _snap_down_mid(s: dict) -> float | None:
    if s["down_bids"] and s["down_asks"]:
        return (s["down_bids"][0][0] + s["down_asks"][0][0]) / 2
    return None


def _ema(vals: list[float], period: int) -> list[float]:
    """Exponential moving average. Returns list same length as vals."""
    if not vals:
        return []
    alpha = 2 / (period + 1)
    result = [vals[0]]
    for v in vals[1:]:
        result.append(alpha * v + (1 - alpha) * result[-1])
    return result


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation coefficient."""
    if len(xs) < 3:
        return None
    mx, my = _mean(xs), _mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


# ===================================================================
# CATEGORY 1: BTC Cross-Candle
# ===================================================================


def prior_return(prior_candles: list[dict]) -> float | None:
    """Log return of the most recent completed candle."""
    if not prior_candles:
        return None
    return prior_candles[-1]["final_ret"]


def consecutive_streak(prior_candles: list[dict]) -> int | None:
    """Signed streak length. Positive = UP streak, negative = DOWN."""
    if not prior_candles:
        return None
    direction = prior_candles[-1]["outcome"]
    streak = 1
    for i in range(len(prior_candles) - 2, -1, -1):
        if prior_candles[i]["outcome"] == direction:
            streak += 1
        else:
            break
    return streak if direction == "UP" else -streak


def streak_magnitude(prior_candles: list[dict]) -> float | None:
    """Total BTC $ move during the current streak. Signed by direction."""
    if not prior_candles:
        return None
    direction = prior_candles[-1]["outcome"]
    total = 0.0
    for i in range(len(prior_candles) - 1, -1, -1):
        if prior_candles[i]["outcome"] == direction:
            total += abs(prior_candles[i]["close"] - prior_candles[i]["open"])
        else:
            break
    return total if direction == "UP" else -total


def rolling_volatility(prior_candles: list[dict], window: int = 6) -> float | None:
    """Average |close - open| over last `window` candles."""
    if len(prior_candles) < window:
        return None
    recent = prior_candles[-window:]
    return _mean([abs(c["close"] - c["open"]) for c in recent])


def candle_momentum(prior_candles: list[dict], window: int = 6) -> float | None:
    """Fraction of UP candles in last `window`. Range [0, 1]."""
    if len(prior_candles) < window:
        return None
    recent = prior_candles[-window:]
    return sum(1 for c in recent if c["outcome"] == "UP") / window


def ma_crossover(prior_candles: list[dict]) -> float | None:
    """MA5 - MA12 on closes ($). Positive = bullish."""
    if len(prior_candles) < 12:
        return None
    closes = [c["close"] for c in prior_candles[-12:]]
    ma5 = _mean(closes[-5:])
    ma12 = _mean(closes)
    return ma5 - ma12


def trend_consistency(prior_candles: list[dict], window: int = 10) -> float | None:
    """Mean sign of log returns over last `window` candles. Range [-1, 1]."""
    if len(prior_candles) < window + 1:
        return None
    closes = [c["close"] for c in prior_candles[-(window + 1) :]]
    signs = []
    for i in range(1, len(closes)):
        r = _safe_log(closes[i], closes[i - 1])
        signs.append(1 if r > 0 else -1 if r < 0 else 0)
    return _mean(signs)


def reversal_regime(prior_candles: list[dict], window: int = 4) -> float | None:
    """Direction flip ratio in last `window` candles. Range [0, 1]."""
    if len(prior_candles) < window:
        return None
    recent = prior_candles[-window:]
    flips = sum(1 for i in range(1, len(recent)) if recent[i]["outcome"] != recent[i - 1]["outcome"])
    return flips / (window - 1)


def rsi(prior_candles: list[dict], period: int = 14) -> float | None:
    """Relative Strength Index on BTC closes. Range [0, 100]."""
    if len(prior_candles) < period + 1:
        return None
    closes = [c["close"] for c in prior_candles[-(period + 1) :]]
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = _mean(gains)
    avg_loss = _mean(losses)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def bollinger_pct_b(prior_candles: list[dict], period: int = 20, num_std: float = 2.0) -> float | None:
    """Position within Bollinger Bands. 0=lower, 0.5=mid, 1=upper."""
    if len(prior_candles) < period:
        return None
    closes = [c["close"] for c in prior_candles[-period:]]
    ma = _mean(closes)
    sd = _std(closes)
    if sd == 0:
        return 0.5
    upper = ma + num_std * sd
    lower = ma - num_std * sd
    band_width = upper - lower
    if band_width == 0:
        return 0.5
    return (closes[-1] - lower) / band_width


def stochastic_k(prior_candles: list[dict], period: int = 14) -> float | None:
    """Stochastic %K: where close sits within N-candle high-low range. [0, 100]."""
    if len(prior_candles) < period:
        return None
    recent = prior_candles[-period:]
    highest = max(c["high"] for c in recent)
    lowest = min(c["low"] for c in recent)
    rng = highest - lowest
    if rng == 0:
        return 50.0
    return (recent[-1]["close"] - lowest) / rng * 100.0


def adx(prior_candles: list[dict], period: int = 14) -> float | None:
    """Average Directional Index. Measures trend strength [0, 100], direction-agnostic."""
    if len(prior_candles) < period + 1:
        return None
    recent = prior_candles[-(period + 1) :]
    plus_dm_list = []
    minus_dm_list = []
    tr_list = []
    for i in range(1, len(recent)):
        high_diff = recent[i]["high"] - recent[i - 1]["high"]
        low_diff = recent[i - 1]["low"] - recent[i]["low"]
        plus_dm_list.append(max(high_diff, 0.0) if high_diff > low_diff else 0.0)
        minus_dm_list.append(max(low_diff, 0.0) if low_diff > high_diff else 0.0)
        tr = max(
            recent[i]["high"] - recent[i]["low"],
            abs(recent[i]["high"] - recent[i - 1]["close"]),
            abs(recent[i]["low"] - recent[i - 1]["close"]),
        )
        tr_list.append(tr)
    atr = _mean(tr_list)
    if atr == 0:
        return 0.0
    plus_di = _mean(plus_dm_list) / atr * 100
    minus_di = _mean(minus_dm_list) / atr * 100
    di_sum = plus_di + minus_di
    if di_sum == 0:
        return 0.0
    dx = abs(plus_di - minus_di) / di_sum * 100
    return dx


def return_autocorrelation(prior_candles: list[dict], lag: int = 1, window: int = 20) -> float | None:
    """Autocorrelation of candle returns at given lag. Positive = momentum, negative = reversal."""
    if len(prior_candles) < window + lag:
        return None
    rets = [c["final_ret"] for c in prior_candles[-(window + lag) :]]
    x = rets[: len(rets) - lag]
    y = rets[lag:]
    return _pearson(x, y)


def multi_candle_return_3(prior_candles: list[dict]) -> float | None:
    """Cumulative log return over last 3 candles."""
    if len(prior_candles) < 3:
        return None
    return sum(c["final_ret"] for c in prior_candles[-3:])


def multi_candle_return_6(prior_candles: list[dict]) -> float | None:
    """Cumulative log return over last 6 candles."""
    if len(prior_candles) < 6:
        return None
    return sum(c["final_ret"] for c in prior_candles[-6:])


# ===================================================================
# CATEGORY 2: BTC Intra-Candle Dynamics
# ===================================================================


def btc_move_from_open(candle_open: float, snapshots: list[dict]) -> float | None:
    """BTC $ move from candle open at current snapshot."""
    if not snapshots:
        return None
    return snapshots[-1]["btc_price"] - candle_open


def btc_velocity(snapshots: list[dict]) -> float | None:
    """Linear regression slope of BTC price over elapsed %."""
    if len(snapshots) < 3:
        return None
    elapsed = [s["elapsed_pct"] for s in snapshots]
    btc = [s["btc_price"] - snapshots[0]["btc_price"] for s in snapshots]
    return _linreg_slope(elapsed, btc)


def intra_candle_volatility(snapshots: list[dict]) -> float | None:
    """Std of tick-to-tick log returns within the candle so far."""
    if len(snapshots) < 5:
        return None
    prices = [s["btc_price"] for s in snapshots]
    rets = [_safe_log(prices[i], prices[i - 1]) for i in range(1, len(prices))]
    return _std(rets)


def peak_drawback(snapshots: list[dict]) -> float | None:
    """Retracement ratio: (peak_move - final_move) / peak_move."""
    if len(snapshots) < 5:
        return None
    moves = [s["btc_price"] - snapshots[0]["btc_price"] for s in snapshots]
    peak = max(abs(m) for m in moves)
    if peak == 0:
        return 0.0
    final = abs(moves[-1])
    return (peak - final) / peak


def btc_acceleration(snapshots: list[dict]) -> float | None:
    """2nd half BTC $ move minus 1st half $ move."""
    if len(snapshots) < 6:
        return None
    mid = len(snapshots) // 2
    first = snapshots[mid]["btc_price"] - snapshots[0]["btc_price"]
    second = snapshots[-1]["btc_price"] - snapshots[mid]["btc_price"]
    return second - first


def btc_direction_consistency(snapshots: list[dict]) -> float | None:
    """Fraction of ticks that agree with the overall direction."""
    if len(snapshots) < 5:
        return None
    prices = [s["btc_price"] for s in snapshots]
    overall = prices[-1] - prices[0]
    if overall == 0:
        return None
    overall_sign = 1 if overall > 0 else -1
    diffs = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    agreeing = sum(1 for d in diffs if (1 if d > 0 else -1 if d < 0 else 0) == overall_sign)
    return agreeing / len(diffs)


def intra_candle_skewness(snapshots: list[dict]) -> float | None:
    """Skewness of tick-to-tick returns. Positive = right tail, negative = left tail."""
    if len(snapshots) < 10:
        return None
    prices = [s["btc_price"] for s in snapshots]
    rets = [_safe_log(prices[i], prices[i - 1]) for i in range(1, len(prices))]
    n = len(rets)
    mu = _mean(rets)
    sigma = _std(rets)
    if sigma == 0:
        return 0.0
    return sum((r - mu) ** 3 for r in rets) / (n * sigma**3)


def intra_candle_kurtosis(snapshots: list[dict]) -> float | None:
    """Excess kurtosis of tick returns. >0 = fat tails (jump risk)."""
    if len(snapshots) < 10:
        return None
    prices = [s["btc_price"] for s in snapshots]
    rets = [_safe_log(prices[i], prices[i - 1]) for i in range(1, len(prices))]
    n = len(rets)
    mu = _mean(rets)
    sigma = _std(rets)
    if sigma == 0:
        return 0.0
    return sum((r - mu) ** 4 for r in rets) / (n * sigma**4) - 3.0


def hurst_exponent(snapshots: list[dict]) -> float | None:
    """Hurst exponent estimate via rescaled range. >0.5 = trending, <0.5 = mean-reverting."""
    if len(snapshots) < 20:
        return None
    prices = [s["btc_price"] for s in snapshots]
    rets = [_safe_log(prices[i], prices[i - 1]) for i in range(1, len(prices))]
    n = len(rets)
    mu = _mean(rets)
    devs = [sum(rets[j] - mu for j in range(i + 1)) for i in range(n)]
    r = max(devs) - min(devs)
    s = _std(rets)
    if s == 0 or r == 0:
        return 0.5
    # H = log(R/S) / log(n)
    return math.log(r / s) / math.log(n)


def market_efficiency_lag(snapshots: list[dict]) -> float | None:
    """How fast does UP token react to BTC moves?

    Cross-correlation at lag 0 vs lag 1. Higher = token reacts with delay.
    """
    btc_rets = []
    up_rets = []
    prev_btc = None
    prev_up = None
    for s in snapshots:
        mid = _snap_up_mid(s)
        if mid is not None and prev_btc is not None and prev_up is not None:
            btc_rets.append(s["btc_price"] - prev_btc)
            up_rets.append(mid - prev_up)
        prev_btc = s["btc_price"]
        prev_up = mid
    if len(btc_rets) < 10:
        return None
    # Correlation at lag 0
    corr_0 = _pearson(btc_rets, up_rets)
    # Correlation at lag 1 (BTC leads, token follows)
    corr_1 = _pearson(btc_rets[:-1], up_rets[1:])
    if corr_0 is None or corr_1 is None:
        return None
    return corr_1 - corr_0  # positive = token lags BTC


# ===================================================================
# CATEGORY 3: Token Orderbook
# ===================================================================


def up_implied_probability(snapshots: list[dict]) -> float | None:
    """UP token midpoint at current snapshot."""
    return _snap_up_mid(snapshots[-1]) if snapshots else None


def up_book_imbalance(snapshots: list[dict]) -> float | None:
    """Average UP bid_depth / ask_depth over all snapshots so far."""
    ratios = []
    for s in snapshots:
        if s["up_bids"] and s["up_asks"] and s["up_asks"][0][1] > 0:
            ratios.append(s["up_bids"][0][1] / s["up_asks"][0][1])
    return _mean(ratios) if ratios else None


def cross_book_flow(snapshots: list[dict]) -> float | None:
    """UP share of total liquidity minus 0.5. Centered at 0."""
    flows = []
    for s in snapshots:
        up_liq = (s["up_bids"][0][1] + s["up_asks"][0][1]) if s["up_bids"] and s["up_asks"] else 0
        dn_liq = (s["down_bids"][0][1] + s["down_asks"][0][1]) if s["down_bids"] and s["down_asks"] else 0
        total = up_liq + dn_liq
        if total > 0:
            flows.append(up_liq / total - 0.5)
    return _mean(flows) if flows else None


def up_spread_level(snapshots: list[dict]) -> float | None:
    """Average UP token spread (%) over snapshots so far."""
    spreads = []
    for s in snapshots:
        if s["up_bids"] and s["up_asks"] and s["up_asks"][0][0] > 0:
            spread = (s["up_asks"][0][0] - s["up_bids"][0][0]) / s["up_asks"][0][0]
            spreads.append(spread)
    return _mean(spreads) if spreads else None


def token_price_divergence(snapshots: list[dict]) -> float | None:
    """Average |UP_mid + DOWN_mid - 1.0| over snapshots so far."""
    divs = []
    for s in snapshots:
        up = _snap_up_mid(s)
        dn = _snap_down_mid(s)
        if up is not None and dn is not None:
            divs.append(abs(up + dn - 1.0))
    return _mean(divs) if divs else None


def up_risk_reward(snapshots: list[dict]) -> float | None:
    """R/R at current snapshot: (1 - ask) / ask."""
    s = snapshots[-1]
    if s["up_asks"] and s["up_asks"][0][0] > 0:
        ask = s["up_asks"][0][0]
        return (1.0 - ask) / ask
    return None


def up_token_velocity(snapshots: list[dict]) -> float | None:
    """Linear regression slope of UP mid over elapsed %."""
    elapsed = []
    mids = []
    for s in snapshots:
        mid = _snap_up_mid(s)
        if mid is not None:
            elapsed.append(s["elapsed_pct"])
            mids.append(mid)
    if len(elapsed) < 5:
        return None
    return _linreg_slope(elapsed, mids)


def down_implied_probability(snapshots: list[dict]) -> float | None:
    """DOWN token midpoint at current snapshot."""
    return _snap_down_mid(snapshots[-1]) if snapshots else None


def down_book_imbalance(snapshots: list[dict]) -> float | None:
    """Average DOWN bid_depth / ask_depth over all snapshots so far."""
    ratios = []
    for s in snapshots:
        if s["down_bids"] and s["down_asks"] and s["down_asks"][0][1] > 0:
            ratios.append(s["down_bids"][0][1] / s["down_asks"][0][1])
    return _mean(ratios) if ratios else None


def down_token_velocity(snapshots: list[dict]) -> float | None:
    """Linear regression slope of DOWN mid over elapsed %."""
    elapsed = []
    mids = []
    for s in snapshots:
        mid = _snap_down_mid(s)
        if mid is not None:
            elapsed.append(s["elapsed_pct"])
            mids.append(mid)
    if len(elapsed) < 5:
        return None
    return _linreg_slope(elapsed, mids)


def down_risk_reward(snapshots: list[dict]) -> float | None:
    """DOWN R/R at current snapshot: (1 - ask) / ask."""
    s = snapshots[-1]
    if s["down_asks"] and s["down_asks"][0][0] > 0:
        ask = s["down_asks"][0][0]
        return (1.0 - ask) / ask
    return None


def rr_spread(snapshots: list[dict]) -> float | None:
    """UP R/R minus DOWN R/R. Positive = UP is cheaper bet."""
    up_rr = up_risk_reward(snapshots)
    dn_rr = down_risk_reward(snapshots)
    if up_rr is None or dn_rr is None:
        return None
    return up_rr - dn_rr


def weighted_mid_price(snapshots: list[dict]) -> float | None:
    """Size-weighted UP mid vs simple mid at current snapshot.

    Weighted = (bid * ask_depth + ask * bid_depth) / (bid_depth + ask_depth).
    Returns difference from simple mid — positive = bid side is heavier.
    """
    s = snapshots[-1]
    if not s["up_bids"] or not s["up_asks"]:
        return None
    bid, bid_d = s["up_bids"][0]
    ask, ask_d = s["up_asks"][0]
    total = bid_d + ask_d
    if total == 0:
        return None
    simple_mid = (bid + ask) / 2
    weighted = (bid * ask_d + ask * bid_d) / total
    return weighted - simple_mid


# ===================================================================
# CATEGORY 4: Market Microstructure
# ===================================================================


def btc_token_correlation(snapshots: list[dict]) -> float | None:
    """Pearson correlation between BTC price and UP mid over snapshots so far."""
    btc_vals = []
    up_vals = []
    for s in snapshots:
        mid = _snap_up_mid(s)
        if mid is not None:
            btc_vals.append(s["btc_price"])
            up_vals.append(mid)
    if len(btc_vals) < 10:
        return None
    btc_m = _mean(btc_vals)
    up_m = _mean(up_vals)
    num = sum((b - btc_m) * (u - up_m) for b, u in zip(btc_vals, up_vals, strict=False))
    den_b = sum((b - btc_m) ** 2 for b in btc_vals) ** 0.5
    den_u = sum((u - up_m) ** 2 for u in up_vals) ** 0.5
    if den_b == 0 or den_u == 0:
        return None
    return num / (den_b * den_u)


def liquidity_decay(snapshots: list[dict]) -> float | None:
    """Slope of normalized market_volume over elapsed %."""
    if len(snapshots) < 5:
        return None
    first_vol = snapshots[0]["market_volume"]
    if first_vol <= 0:
        return None
    elapsed = [s["elapsed_pct"] for s in snapshots]
    vol_norm = [s["market_volume"] / first_vol for s in snapshots]
    return _linreg_slope(elapsed, vol_norm)


def imbalance_momentum(snapshots: list[dict]) -> float | None:
    """Slope of UP bid/ask depth ratio over elapsed %."""
    elapsed = []
    imbs = []
    for s in snapshots:
        if s["up_bids"] and s["up_asks"] and s["up_asks"][0][1] > 0:
            elapsed.append(s["elapsed_pct"])
            imbs.append(s["up_bids"][0][1] / s["up_asks"][0][1])
    if len(elapsed) < 5:
        return None
    return _linreg_slope(elapsed, imbs)


def spread_compression(snapshots: list[dict]) -> float | None:
    """Slope of UP spread over elapsed %. Negative = tightening."""
    elapsed = []
    spreads = []
    for s in snapshots:
        if s["up_bids"] and s["up_asks"]:
            elapsed.append(s["elapsed_pct"])
            spreads.append(s["up_asks"][0][0] - s["up_bids"][0][0])
    if len(elapsed) < 5:
        return None
    return _linreg_slope(elapsed, spreads)


# ===================================================================
# CATEGORY 5: Temporal
# ===================================================================


def observation_window(snapshots: list[dict]) -> float | None:
    """Elapsed range covered so far."""
    if not snapshots:
        return None
    return snapshots[-1]["elapsed_pct"] - snapshots[0]["elapsed_pct"]


def current_elapsed(snapshots: list[dict]) -> float | None:
    """Current elapsed % of the candle."""
    if not snapshots:
        return None
    return snapshots[-1]["elapsed_pct"]


def time_of_day_sin(snapshots: list[dict]) -> float | None:
    """Sine of hour-of-day (UTC). Captures cyclical time patterns."""
    if not snapshots:
        return None
    ts = snapshots[-1]["timestamp"]
    hour = (ts % 86400) / 3600  # hour of day [0, 24)
    return math.sin(2 * math.pi * hour / 24)


def time_of_day_cos(snapshots: list[dict]) -> float | None:
    """Cosine of hour-of-day (UTC). Paired with sin for full cycle."""
    if not snapshots:
        return None
    ts = snapshots[-1]["timestamp"]
    hour = (ts % 86400) / 3600
    return math.cos(2 * math.pi * hour / 24)


def imbalance_shift(snapshots: list[dict]) -> float | None:
    """Late imbalance minus early imbalance (last third vs first third)."""
    if len(snapshots) < 9:
        return None
    third = len(snapshots) // 3

    def avg_imb(snap_list: list[dict]) -> float | None:
        vals = []
        for s in snap_list:
            if s["up_bids"] and s["up_asks"] and s["up_asks"][0][1] > 0:
                vals.append(s["up_bids"][0][1] / s["up_asks"][0][1])
        return _mean(vals) if vals else None

    early = avg_imb(snapshots[:third])
    late = avg_imb(snapshots[-third:])
    if early is None or late is None:
        return None
    return late - early


# ===================================================================
# CATEGORY 6: Novel Composites
# ===================================================================


def smart_money_signal(snapshots: list[dict]) -> float | None:
    """Correlation breakdown: 2nd-half BTC-token corr minus 1st-half."""
    btc_vals = []
    up_vals = []
    for s in snapshots:
        mid = _snap_up_mid(s)
        if mid is not None:
            btc_vals.append(s["btc_price"])
            up_vals.append(mid)
    if len(btc_vals) < 10:
        return None
    mid_idx = len(btc_vals) // 2
    if mid_idx < 3:
        return None

    def _corr(xs: list[float], ys: list[float]) -> float | None:
        mx, my = _mean(xs), _mean(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
        dx = sum((x - mx) ** 2 for x in xs) ** 0.5
        dy = sum((y - my) ** 2 for y in ys) ** 0.5
        if dx == 0 or dy == 0:
            return None
        return num / (dx * dy)

    c1 = _corr(btc_vals[:mid_idx], up_vals[:mid_idx])
    c2 = _corr(btc_vals[mid_idx:], up_vals[mid_idx:])
    if c1 is None or c2 is None:
        return None
    return c2 - c1


def depth_absorption_rate(candle: dict, snapshots: list[dict]) -> float | None:
    """Depth coefficient of variation / price change ratio."""
    if len(snapshots) < 5:
        return None
    depths = []
    for s in snapshots:
        if s["up_bids"] and s["up_asks"]:
            depths.append(s["up_bids"][0][1] + s["up_asks"][0][1])
    if len(depths) < 5:
        return None
    depth_cv = _std(depths) / (_mean(depths) + 1e-10)
    price_chg = abs(snapshots[-1]["btc_price"] - snapshots[0]["btc_price"]) / (snapshots[0]["btc_price"] + 1e-10)
    if price_chg <= 0:
        return None
    return depth_cv / price_chg


def regime_score(prior_candles: list[dict], window: int = 6) -> float | None:
    """Trending vs choppy. Positive = trending up, negative = trending down."""
    if len(prior_candles) < window:
        return None
    recent = prior_candles[-window:]
    avg_vol = _mean([abs(c["final_ret"]) for c in recent])
    trend = sum(c["final_ret"] for c in recent)
    flips = sum(1 for i in range(1, len(recent)) if recent[i]["outcome"] != recent[i - 1]["outcome"])
    flip_ratio = flips / (window - 1)
    sign = 1 if trend > 0 else -1 if trend < 0 else 0
    return (1 - flip_ratio) * avg_vol * 1000 * sign


def ob_pressure_gradient(snapshots: list[dict]) -> float | None:
    """UP depth slope minus DOWN depth slope over elapsed %."""
    if len(snapshots) < 5:
        return None
    elapsed = []
    up_totals = []
    dn_totals = []
    for s in snapshots:
        u = (s["up_bids"][0][1] if s["up_bids"] else 0) + (s["up_asks"][0][1] if s["up_asks"] else 0)
        d = (s["down_bids"][0][1] if s["down_bids"] else 0) + (s["down_asks"][0][1] if s["down_asks"] else 0)
        elapsed.append(s["elapsed_pct"])
        up_totals.append(u)
        dn_totals.append(d)
    up_slope = _linreg_slope(elapsed, up_totals)
    dn_slope = _linreg_slope(elapsed, dn_totals)
    if up_slope is None or dn_slope is None:
        return None
    return up_slope - dn_slope


def conviction_score(snapshots: list[dict]) -> float | None:
    """mid * (1/spread) * imbalance_factor from recent snapshots."""
    recent = snapshots[-5:] if len(snapshots) >= 5 else snapshots
    mids, spreads, imbs = [], [], []
    for s in recent:
        if s["up_bids"] and s["up_asks"] and s["up_asks"][0][1] > 0:
            bid, ask = s["up_bids"][0][0], s["up_asks"][0][0]
            mids.append((bid + ask) / 2)
            spreads.append((ask - bid) / (ask + 1e-10))
            imbs.append(s["up_bids"][0][1] / s["up_asks"][0][1])
    if not mids:
        return None
    mid = _mean(mids)
    spread = _mean(spreads)
    imb = min(_mean(imbs), 3.0) / 3.0
    return mid * (1 / (spread + 0.001)) * imb


def price_path_entropy(snapshots: list[dict]) -> float | None:
    """Shannon entropy of tick direction (bits). 1.0 = pure noise, 0 = directional."""
    if len(snapshots) < 10:
        return None
    prices = [s["btc_price"] for s in snapshots]
    diffs = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    ups = sum(1 for d in diffs if d > 0)
    downs = sum(1 for d in diffs if d < 0)
    total = ups + downs
    if total == 0:
        return None
    entropy = 0.0
    for count in (ups, downs):
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)
    return entropy


def mean_reversion_signal(prior_candles: list[dict], lookback: int = 20) -> float | None:
    """Negative z-score of prior return. Positive = expect UP reversion."""
    if len(prior_candles) < lookback + 1:
        return None
    rets = [c["final_ret"] for c in prior_candles[-(lookback + 1) :]]
    mu = _mean(rets[:-1])
    sigma = _std(rets[:-1])
    if sigma == 0:
        return None
    return -(rets[-1] - mu) / sigma


# ===================================================================
# MASTER FUNCTION
# ===================================================================


def compute_all(
    prior_candles: list[dict],
    candle_open: float,
    snapshots_so_far: list[dict],
) -> dict[str, Any]:
    """Compute all indicators for a single snapshot moment.

    Args:
        prior_candles:    completed candles before this one (chronological)
        candle_open:      BTC open price of current candle
        snapshots_so_far: snapshots #0..#N in current candle (N = current)

    Returns:
        dict mapping indicator names to values (float or None)
    """
    s = snapshots_so_far  # shorthand

    return {
        # Cat 1: BTC cross-candle
        "prior_return": prior_return(prior_candles),
        "consecutive_streak": consecutive_streak(prior_candles),
        "streak_magnitude": streak_magnitude(prior_candles),
        "rolling_volatility": rolling_volatility(prior_candles),
        "candle_momentum": candle_momentum(prior_candles),
        "ma_crossover": ma_crossover(prior_candles),
        "trend_consistency": trend_consistency(prior_candles),
        "reversal_regime": reversal_regime(prior_candles),
        "rsi": rsi(prior_candles),
        "bollinger_pct_b": bollinger_pct_b(prior_candles),
        "stochastic_k": stochastic_k(prior_candles),
        "adx": adx(prior_candles),
        "return_autocorrelation": return_autocorrelation(prior_candles),
        "multi_candle_return_3": multi_candle_return_3(prior_candles),
        "multi_candle_return_6": multi_candle_return_6(prior_candles),
        # Cat 2: BTC intra-candle
        "btc_move_from_open": btc_move_from_open(candle_open, s),
        "btc_velocity": btc_velocity(s),
        "intra_candle_volatility": intra_candle_volatility(s),
        "peak_drawback": peak_drawback(s),
        "btc_acceleration": btc_acceleration(s),
        "btc_direction_consistency": btc_direction_consistency(s),
        "intra_candle_skewness": intra_candle_skewness(s),
        "intra_candle_kurtosis": intra_candle_kurtosis(s),
        "hurst_exponent": hurst_exponent(s),
        "market_efficiency_lag": market_efficiency_lag(s),
        # Cat 3: Token orderbook
        "up_implied_probability": up_implied_probability(s),
        "up_book_imbalance": up_book_imbalance(s),
        "cross_book_flow": cross_book_flow(s),
        "up_spread_level": up_spread_level(s),
        "token_price_divergence": token_price_divergence(s),
        "up_risk_reward": up_risk_reward(s),
        "up_token_velocity": up_token_velocity(s),
        "down_implied_probability": down_implied_probability(s),
        "down_book_imbalance": down_book_imbalance(s),
        "down_token_velocity": down_token_velocity(s),
        "down_risk_reward": down_risk_reward(s),
        "rr_spread": rr_spread(s),
        "weighted_mid_price": weighted_mid_price(s),
        # Cat 4: Microstructure
        "btc_token_correlation": btc_token_correlation(s),
        "liquidity_decay": liquidity_decay(s),
        "imbalance_momentum": imbalance_momentum(s),
        "spread_compression": spread_compression(s),
        # Cat 5: Temporal
        "observation_window": observation_window(s),
        "current_elapsed": current_elapsed(s),
        "time_of_day_sin": time_of_day_sin(s),
        "time_of_day_cos": time_of_day_cos(s),
        "imbalance_shift": imbalance_shift(s),
        # Cat 6: Novel composites
        "smart_money_signal": smart_money_signal(s),
        "depth_absorption_rate": depth_absorption_rate(
            {"open": candle_open, "close": s[-1]["btc_price"]} if s else {}, s
        ),
        "regime_score": regime_score(prior_candles),
        "ob_pressure_gradient": ob_pressure_gradient(s),
        "conviction_score": conviction_score(s),
        "price_path_entropy": price_path_entropy(s),
        "mean_reversion_signal": mean_reversion_signal(prior_candles),
    }
