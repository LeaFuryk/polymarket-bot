"""Pure replay analysis functions — stateless, no I/O, independently testable.

All functions take pre-loaded data (dicts/lists) and return analysis results.
No database, filesystem, or console access.
"""

from __future__ import annotations

from statistics import mean, stdev

from polybot.analysis.constants import RECOVERY_WINDOW_SECONDS, TTL_COUNTERFACTUAL_VALUES


def compute_ob_stats(snapshots: list[dict], side: str) -> dict:
    """Compute orderbook summary statistics for the traded side."""
    prefix = "up_" if side == "up" else "down_"
    bids = [s[f"{prefix}best_bid"] for s in snapshots if s.get(f"{prefix}best_bid") is not None]
    asks = [s[f"{prefix}best_ask"] for s in snapshots if s.get(f"{prefix}best_ask") is not None]
    mids = [s[f"{prefix}mid"] for s in snapshots if s.get(f"{prefix}mid") is not None]
    spreads = [s[f"{prefix}spread_pct"] for s in snapshots if s.get(f"{prefix}spread_pct") is not None]
    btc_prices = [s["btc_price"] for s in snapshots if s.get("btc_price")]

    def _stats(values: list[float]) -> dict:
        if not values:
            return {"min": None, "max": None, "mean": None, "stdev": None}
        return {
            "min": min(values),
            "max": max(values),
            "mean": mean(values),
            "stdev": stdev(values) if len(values) > 1 else 0.0,
        }

    return {
        "best_bid": _stats(bids),
        "best_ask": _stats(asks),
        "mid": _stats(mids),
        "spread_pct": _stats(spreads),
        "btc_price": _stats(btc_prices),
        "total_snapshots": len(snapshots),
        "duration_s": snapshots[-1]["timestamp"] - snapshots[0]["timestamp"] if len(snapshots) > 1 else 0,
    }


def fillability_scan(
    snapshots: list[dict],
    side: str,
    ttl: int,
    limit_price: float,
) -> dict:
    """For each second, simulate placing a limit order and check fillability.

    BUY fills if any ask in [t, t+TTL] <= limit price.
    """
    prefix = "up_" if side == "up" else "down_"
    ask_key = f"{prefix}best_ask"

    fillable_seconds = 0
    total_seconds = 0
    fill_windows: list[dict] = []
    entry_prices: list[float] = []

    use_fixed_price = limit_price > 0

    for i, snap in enumerate(snapshots):
        if use_fixed_price:
            price = limit_price
        else:
            price = snap.get(ask_key)

        if price is None:
            continue

        total_seconds += 1
        t0 = snap["timestamp"]

        filled = False
        fill_at: float | None = None
        fill_price_actual: float | None = None
        for j in range(i, len(snapshots)):
            if snapshots[j]["timestamp"] - t0 > ttl:
                break
            future_ask = snapshots[j].get(ask_key)

            if future_ask is not None and future_ask <= price:
                filled = True
                fill_at = snapshots[j]["timestamp"] - t0
                fill_price_actual = future_ask
                break

        if filled:
            fillable_seconds += 1
            entry_prices.append(fill_price_actual if fill_price_actual is not None else price)
            fill_windows.append(
                {
                    "entry_second": i,
                    "entry_ts": t0,
                    "limit_price": price,
                    "fill_price": fill_price_actual,
                    "fill_delay": fill_at,
                }
            )

    best_entry = min(entry_prices) if entry_prices else None
    worst_entry = max(entry_prices) if entry_prices else None

    all_asks = [s.get(ask_key) for s in snapshots if s.get(ask_key) is not None]
    book_best_ask = min(all_asks) if all_asks else None
    book_worst_ask = max(all_asks) if all_asks else None

    return {
        "fillable_seconds": fillable_seconds,
        "total_seconds": total_seconds,
        "fill_rate": fillable_seconds / total_seconds if total_seconds else 0,
        "best_entry": best_entry,
        "worst_entry": worst_entry,
        "book_best_ask": book_best_ask,
        "book_worst_ask": book_worst_ask,
        "fill_windows": fill_windows,
        "ttl": ttl,
        "reference_price": limit_price if use_fixed_price else None,
    }


def build_decision_timeline(
    snapshots: list[dict],
    decisions: list[dict],
    side: str,
) -> list[dict]:
    """Build a timeline of what the AI decided vs what the book showed."""
    prefix = "up_" if side == "up" else "down_"
    ask_key = f"{prefix}best_ask"
    bid_key = f"{prefix}best_bid"

    if not snapshots:
        return []

    t0 = snapshots[0]["timestamp"]
    timeline = []

    for d in decisions:
        d_ts = d["timestamp"]
        closest = min(snapshots, key=lambda s: abs(s["timestamp"] - d_ts))

        timeline.append(
            {
                "action": d["action"],
                "token_side": d.get("token_side", "?"),
                "confidence": d.get("confidence", 0),
                "fill_price": d.get("fill_price"),
                "fill_size": d.get("fill_size"),
                "decision_ts": d_ts,
                "offset_s": d_ts - t0,
                "book_ask": closest.get(ask_key),
                "book_bid": closest.get(bid_key),
                "book_mid": closest.get(f"{prefix}mid"),
                "btc_price": closest.get("btc_price"),
                "time_remaining": closest.get("time_remaining"),
            }
        )

    return timeline


def post_cancel_recovery(
    snapshots: list[dict],
    decisions: list[dict],
    side: str,
) -> dict | None:
    """Analyze price trajectory after a cancelled/unfilled order.

    Looks for decisions with no fill and checks if the book returned
    to a fillable price within the recovery window.
    """
    prefix = "up_" if side == "up" else "down_"
    ask_key = f"{prefix}best_ask"

    missed_buys = [
        d for d in decisions if d["action"] == "BUY" and (d.get("fill_price") is None or d.get("risk_blocked"))
    ]

    if not missed_buys:
        return None

    missed = missed_buys[-1]
    missed_ts = missed["timestamp"]

    closest = min(snapshots, key=lambda s: abs(s["timestamp"] - missed_ts))
    decision_ask = closest.get(ask_key)

    if decision_ask is None:
        return None

    recovery_window = [s for s in snapshots if 0 <= s["timestamp"] - missed_ts <= RECOVERY_WINDOW_SECONDS]

    if not recovery_window:
        return None

    recovery_asks = [s.get(ask_key) for s in recovery_window if s.get(ask_key) is not None]

    if not recovery_asks:
        return None

    min_ask_after = min(recovery_asks)
    recovered = min_ask_after <= decision_ask

    return {
        "decision_ts": missed_ts,
        "decision_ask": decision_ask,
        "action": missed["action"],
        "reason": missed.get("risk_reason", "unfilled/cancelled"),
        "window_seconds": RECOVERY_WINDOW_SECONDS,
        "min_ask_after": min_ask_after,
        "max_ask_after": max(recovery_asks),
        "mean_ask_after": mean(recovery_asks),
        "recovered": recovered,
        "recovery_depth": decision_ask - min_ask_after,
        "snapshots_in_window": len(recovery_window),
    }


def live_order_telemetry(
    decisions: list[dict],
    snapshots: list[dict],
    side: str,
) -> dict | None:
    """Extract and overlay live order telemetry from decisions."""
    lo_decisions = [d for d in decisions if d.get("_live_order")]
    if not lo_decisions:
        return None

    prefix = "up_" if side == "up" else "down_"
    ask_key = f"{prefix}best_ask"
    bid_key = f"{prefix}best_bid"

    results = []
    t0 = snapshots[0]["timestamp"] if snapshots else 0

    for d in lo_decisions:
        lo = d["_live_order"]
        submit_ts = lo.get("submit_ts", 0)
        fill_ts = lo.get("fill_ts")
        cancel_ts = lo.get("cancel_ts")

        def _book_at(ts: float) -> dict:
            if not ts or not snapshots:
                return {}
            closest = min(snapshots, key=lambda s: abs(s["timestamp"] - ts))
            return {
                "ask": closest.get(ask_key),
                "bid": closest.get(bid_key),
                "mid": closest.get(f"{prefix}mid"),
            }

        results.append(
            {
                "order_id": lo.get("order_id", "?"),
                "limit_price": lo.get("limit_price"),
                "submit_ts": submit_ts,
                "submit_offset": submit_ts - t0 if submit_ts and t0 else None,
                "fill_ts": fill_ts,
                "cancel_ts": cancel_ts,
                "fill_source": lo.get("fill_source", ""),
                "ttl_used": lo.get("ttl_used"),
                "polls": lo.get("polls", []),
                "ob_at_submit": lo.get("ob_at_submit", {}),
                "ob_at_end": lo.get("ob_at_end", {}),
                "ob_post_cancel": lo.get("ob_post_cancel"),
                "decision_ob_ask": lo.get("decision_ob_ask"),
                "decision_ob_bid": lo.get("decision_ob_bid"),
                "book_at_submit": _book_at(submit_ts),
                "book_at_fill": _book_at(fill_ts) if fill_ts else None,
                "book_at_cancel": _book_at(cancel_ts) if cancel_ts else None,
                "filled": bool(fill_ts),
            }
        )

    return {"orders": results}


def generate_insights(
    candle: dict,
    snapshots: list[dict],
    decisions: list[dict],
    ob_stats: dict,
    fill_scan: dict,
    post_cancel: dict | None,
    side: str,
    ttl: int,
) -> list[str]:
    """Auto-generate key insights from the replay analysis."""
    insights = []
    prefix = "up_" if side == "up" else "down_"
    ask_key = f"{prefix}best_ask"

    if not snapshots:
        return ["No snapshot data available for analysis."]

    t0 = snapshots[0]["timestamp"]

    # 1. Best entry point
    best_ask = fill_scan.get("book_best_ask")
    if best_ask is not None:
        for s in snapshots:
            if s.get(ask_key) == best_ask:
                offset = s["timestamp"] - t0
                insights.append(f"Best entry was at T+{offset:.0f}s (ask={best_ask:.3f})")
                break

    # 2. Compare actual trade to best entry
    fill_decisions = [d for d in decisions if d["action"] == "BUY" and d.get("fill_price")]
    if fill_decisions and best_ask is not None:
        actual_price = fill_decisions[0]["fill_price"]
        if actual_price > best_ask:
            savings = actual_price - best_ask
            insights.append(
                f"Actual fill at {actual_price:.3f} vs best available {best_ask:.3f} "
                f"(could have saved {savings:.3f}/share)"
            )
        elif actual_price <= best_ask:
            insights.append(f"Actual fill at {actual_price:.3f} — matched or beat the best ask ({best_ask:.3f})")

    # 3. Fill rate analysis
    fill_rate = fill_scan.get("fill_rate", 0)
    total = fill_scan.get("total_seconds", 0)
    fillable = fill_scan.get("fillable_seconds", 0)
    if total > 0:
        insights.append(f"Fillability: {fillable}/{total} seconds ({fill_rate:.0%}) would fill within {ttl}s TTL")

    # 4. TTL counterfactual
    missed_buys = [
        d for d in decisions if d["action"] == "BUY" and d.get("fill_price") is None and not d.get("risk_blocked")
    ]
    if missed_buys:
        missed_ts = missed_buys[-1]["timestamp"]
        for extra_ttl in TTL_COUNTERFACTUAL_VALUES:
            window = [s for s in snapshots if 0 <= s["timestamp"] - missed_ts <= extra_ttl]
            closest = min(snapshots, key=lambda s: abs(s["timestamp"] - missed_ts))
            decision_ask = closest.get(ask_key)
            if decision_ask is not None and window:
                future_asks = [s.get(ask_key) for s in window if s.get(ask_key) is not None]
                if future_asks and min(future_asks) <= decision_ask:
                    insights.append(
                        f"Missed order would have filled with TTL={extra_ttl}s (ask dropped to {min(future_asks):.3f})"
                    )
                    break

    # 5. Post-cancel recovery
    if post_cancel and post_cancel.get("recovered"):
        depth = post_cancel["recovery_depth"]
        insights.append(
            f"Price recovered to fillable {post_cancel['snapshots_in_window']}s after cancel (ask dropped {depth:+.3f})"
        )
    elif post_cancel and not post_cancel.get("recovered"):
        insights.append(
            f"Price did NOT recover after cancel — min ask was {post_cancel['min_ask_after']:.3f} "
            f"vs decision ask {post_cancel['decision_ask']:.3f}"
        )

    # 6. Winner outcome
    winner = candle.get("winner")
    if winner:
        correct = winner == side
        insights.append(
            f"Candle winner: {winner.upper()} — traded side {side.upper()} was {'CORRECT' if correct else 'WRONG'}"
        )

    if not insights:
        insights.append("No notable insights — limited data for this candle.")

    return insights
