"""Pure functions that build AI prompt context sections.

Each function takes raw data and returns a formatted string (or None)
for injection into the AI decision prompt.  They are stateless and have
no side effects, making them trivially unit-testable.
"""

from __future__ import annotations

from polybot.models import Action, ResolutionRecord
from polybot.shared_state import PreFilterSnapshot


def compute_btc_trajectory(history: list[PreFilterSnapshot]) -> str | None:
    """Compute BTC velocity and peak-drawback from prefilter snapshots.

    Returns a compact trajectory section for the AI prompt, or None
    if insufficient data.
    """
    if len(history) < 15:
        return None

    moves = [s.btc_move_from_open for s in history]

    # Velocity: rate of change over last ~10s vs ~20-30s ago
    recent = moves[-10:]
    earlier = moves[-30:-20] if len(moves) >= 30 else moves[:10]

    if len(recent) < 2 or len(earlier) < 2:
        return None

    current_vel = (recent[-1] - recent[0]) / len(recent)
    earlier_vel = (earlier[-1] - earlier[0]) / len(earlier)

    # Peak drawback: furthest BTC move vs current
    current_move = moves[-1]
    # Find peak in the direction of the current move
    if current_move >= 0:
        peak = max(moves)
        drawback = peak - current_move
    else:
        peak = min(moves)
        drawback = abs(peak) - abs(current_move)

    # Format
    vel_dir = (
        "accelerating"
        if abs(current_vel) > abs(earlier_vel) * 1.2
        else "decelerating"
        if abs(current_vel) < abs(earlier_vel) * 0.8
        else "steady"
    )
    parts = [
        "## BTC Trajectory (intra-candle)",
        f"- Velocity: ${current_vel:+.1f}/s ({vel_dir}, was ${earlier_vel:+.1f}/s)",
    ]
    if abs(drawback) >= 5.0:
        parts.append(
            f"- Peak drawback: peak was ${peak:+,.0f} from open, now ${current_move:+,.0f} (pulled back ${drawback:.0f})"
        )
    else:
        parts.append(f"- No significant drawback (peak ${peak:+,.0f}, current ${current_move:+,.0f})")

    return "\n".join(parts)


def compute_retracement_context(
    history: list[PreFilterSnapshot],
    position_side: str,
    snapshot,
) -> str:
    """Compute rich retracement analytics for reversal HOLD-or-FLIP decisions.

    Returns a formatted prompt section with peak move, retracement %, zero
    crossing, retreat velocity/acceleration, and opposite-side ask.
    """
    if len(history) < 5:
        return ""

    moves = [s.btc_move_from_open for s in history]
    timestamps = [s.timestamp for s in history]
    now_ts = timestamps[-1]
    current_move = moves[-1]

    # Determine peak in the direction that favours the held position
    # UP position profits when BTC goes up (positive moves)
    # DOWN position profits when BTC goes down (negative moves)
    is_up = position_side.lower() == "up"
    if is_up:
        peak_val = max(moves)
        peak_idx = moves.index(peak_val)
    else:
        peak_val = min(moves)
        peak_idx = moves.index(peak_val)

    peak_ts = timestamps[peak_idx]
    peak_age = now_ts - peak_ts

    # Retracement %: how much of the peak move has been given back
    if abs(peak_val) > 0.01:
        retracement_pct = (1.0 - current_move / peak_val) * 100 if is_up else (1.0 - current_move / peak_val) * 100
    else:
        retracement_pct = 0.0
    retracement_pct = max(0.0, min(retracement_pct, 200.0))  # clamp

    # Zero crossing: has BTC switched sides?
    if is_up:
        crossed_zero = current_move < 0
    else:
        crossed_zero = current_move > 0

    # Retreat velocity: rate of change over last 10-15 snapshots
    # Positive velocity = moving AWAY from position's favoured direction
    tail = moves[-15:] if len(moves) >= 15 else moves[-10:]
    if len(tail) >= 5:
        recent_chunk = tail[-5:]
        earlier_chunk = tail[:5]
        vel_recent = (recent_chunk[-1] - recent_chunk[0]) / len(recent_chunk)
        vel_earlier = (earlier_chunk[-1] - earlier_chunk[0]) / len(earlier_chunk)

        # For UP position, negative velocity = retreating (bad)
        # For DOWN position, positive velocity = retreating (bad)
        if is_up:
            retreat_vel = -vel_recent  # positive = retreating from UP
        else:
            retreat_vel = vel_recent  # positive = retreating from DOWN

        # Acceleration: is retreat speeding up or slowing down?
        if is_up:
            retreat_vel_earlier = -vel_earlier
        else:
            retreat_vel_earlier = vel_earlier

        if retreat_vel > 0 and retreat_vel_earlier > 0:
            if retreat_vel > retreat_vel_earlier * 1.2:
                accel_label = "ACCELERATING (retreat speeding up)"
            elif retreat_vel < retreat_vel_earlier * 0.8:
                accel_label = "DECELERATING (retreat slowing)"
            else:
                accel_label = "steady"
        elif retreat_vel > 0:
            accel_label = "ACCELERATING (newly retreating)"
        else:
            accel_label = "not retreating"
    else:
        retreat_vel = 0.0
        accel_label = "insufficient data"

    # Opposite side ask price
    is_sold_up = is_up
    opp_ob = snapshot.down_orderbook if is_sold_up else snapshot.orderbook
    opp_ask = opp_ob.best_ask
    opp_side = "DOWN" if is_sold_up else "UP"

    # Build prompt section
    parts = [
        "## Reversal Analysis (from per-second data)",
        f"- Peak BTC move: ${peak_val:+,.0f} from open (at t={peak_idx}s, {peak_age:.0f}s ago)",
        f"- Current BTC move: ${current_move:+,.0f} from open",
        f"- Retracement: {retracement_pct:.0f}% of peak given back",
        f"- Zero crossing: {'YES — BTC has switched sides (strong flip signal)' if crossed_zero else 'NO — BTC still on original side'}",
        f"- Retreat velocity: ${retreat_vel:+.1f}/s ({accel_label})",
        f"- Time since peak: {peak_age:.0f}s ({'sustained retreat' if peak_age > 30 else 'recent peak'})",
    ]
    if opp_ask is not None:
        rr = (1.0 - opp_ask) / opp_ask if opp_ask > 0 else 0
        parts.append(f"- {opp_side} ask: ${opp_ask:.2f} (R/R = {rr:.2f}x if flipping)")

    return "\n".join(parts)


def format_microstructure(history: list) -> str | None:
    """Format cross-candle microstructure summary for the AI prompt.

    Takes SharedState.microstructure_history (list of CandleMicrostructure).
    Returns None if insufficient data (< 2 candles).
    """
    if len(history) < 2:
        return None

    recent = history[-1]
    prev = history[-2]

    # Spread trend
    spread_up_delta = recent.avg_spread_up - prev.avg_spread_up
    spread_down_delta = recent.avg_spread_down - prev.avg_spread_down
    spread_dir = (
        "widening"
        if (spread_up_delta + spread_down_delta) > 0.002
        else "narrowing"
        if (spread_up_delta + spread_down_delta) < -0.002
        else "stable"
    )

    # Volatility trend (BTC range per candle)
    ranges = [h.btc_range for h in history]
    avg_range = sum(ranges) / len(ranges)
    range_dir = (
        "increasing"
        if recent.btc_range > avg_range * 1.2
        else "decreasing"
        if recent.btc_range < avg_range * 0.8
        else "stable"
    )

    parts = [
        f"## Cross-Candle Microstructure (last {len(history)} candles)",
        f"- Spreads: {spread_dir} (UP avg {recent.avg_spread_up:.2%}, DOWN avg {recent.avg_spread_down:.2%})",
        f"- BTC intra-candle range: ${recent.btc_range:.0f} ({range_dir}, avg ${avg_range:.0f})",
    ]

    return "\n".join(parts)


def compute_entry_timing_stats(
    session_trades: list,
    resolutions: list,
) -> str | None:
    """Compute win rate by entry-time bucket from this session's resolved trades.

    Returns a formatted prompt section showing WR per time-remaining bucket,
    or None if fewer than 3 resolved BUY trades exist.
    """
    # Build resolution lookup by slug
    res_by_slug: dict[str, ResolutionRecord] = {}
    for r in resolutions:
        res_by_slug[r.slug] = r

    # Buckets: label -> [wins, losses]
    buckets: dict[str, list[int]] = {
        ">200s": [0, 0],
        "150-200s": [0, 0],
        "100-150s": [0, 0],
        "<100s": [0, 0],
    }

    # Collect resolved tuples for trailing window
    resolved_tuples: list[tuple[float, bool]] = []

    resolved_count = 0
    for trade in session_trades:
        if trade.action != Action.BUY or trade.fill_price is None:
            continue
        tr = trade.extra.get("time_remaining")
        if tr is None:
            continue
        res = res_by_slug.get(trade.candle_slug)
        if res is None:
            continue  # unresolved (current candle)

        # Determine bucket
        if tr > 200:
            bucket = ">200s"
        elif tr > 150:
            bucket = "150-200s"
        elif tr > 100:
            bucket = "100-150s"
        else:
            bucket = "<100s"

        # Win = bought the winning side
        won = trade.token_side.value == res.winner
        if won:
            buckets[bucket][0] += 1
        else:
            buckets[bucket][1] += 1
        resolved_count += 1
        resolved_tuples.append((tr, won))

    if resolved_count < 3:
        return None

    parts = ["## Entry Timing Performance (recent | session)"]

    # Trailing-10 buckets (recent trades first to prevent anchoring on stale session stats)
    trailing = resolved_tuples[-10:]
    t_buckets: dict[str, list[int]] = {
        ">200s": [0, 0],
        "150-200s": [0, 0],
        "100-150s": [0, 0],
        "<100s": [0, 0],
    }
    for tr, won in trailing:
        if tr > 200:
            b = ">200s"
        elif tr > 150:
            b = "150-200s"
        elif tr > 100:
            b = "100-150s"
        else:
            b = "<100s"
        if won:
            t_buckets[b][0] += 1
        else:
            t_buckets[b][1] += 1

    parts.append(f"Recent {len(trailing)} trades:")
    for label, (wins, losses) in t_buckets.items():
        total = wins + losses
        if total == 0:
            parts.append(f"- {label} remaining: \u2014")
        else:
            wr = wins / total
            parts.append(f"- {label} remaining: {wins}W/{losses}L ({wr:.0%})")

    parts.append(f"Full session ({resolved_count} trades):")
    best_bucket = None
    best_wr = -1.0
    for label, (wins, losses) in buckets.items():
        total = wins + losses
        if total == 0:
            parts.append(f"- {label} remaining: \u2014")
        else:
            wr = wins / total
            parts.append(f"- {label} remaining: {wins}W/{losses}L ({wr:.0%})")
            if total >= 2 and wr > best_wr:
                best_wr = wr
                best_bucket = label

    if best_bucket is not None:
        parts.append(f"- Best bucket: {best_bucket} ({best_wr:.0%} WR) \u2014 consider patience on marginal setups")

    return "\n".join(parts)
