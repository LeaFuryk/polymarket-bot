"""Deep post-run analysis functions — stateless, no I/O.

Each function takes pre-loaded trade/resolution dicts and returns
structured analysis results.  Used by the ``polybot-analyze-deep``
pipeline and the dashboard iteration history view.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Entry quality
# ---------------------------------------------------------------------------


def analyze_entry_quality(trades: list[dict]) -> dict:
    """Analyse fill-price distribution and entry quality for BUY trades.

    Args:
        trades: Trade dicts with at least ``action``, ``fill_price``,
            ``risk_blocked``, and optionally ``confidence``.

    Returns:
        Dict with fill-price breakdown, averages, and R/R histogram.
    """
    buys = [t for t in trades if t.get("action") == "BUY" and not t.get("risk_blocked")]
    fills = [t["fill_price"] for t in buys if t.get("fill_price") is not None]

    cheap = [f for f in fills if f < 0.40]
    ok = [f for f in fills if 0.40 <= f < 0.55]
    expensive = [f for f in fills if 0.55 <= f < 0.70]
    very_expensive = [f for f in fills if f >= 0.70]

    avg_fill = sum(fills) / len(fills) if fills else 0.0
    confs = [t["confidence"] for t in buys if t.get("confidence") is not None]
    avg_conf = sum(confs) / len(confs) if confs else 0.0

    # Entry gap: how far fill_price is from 0.50 (fair value)
    gaps = [abs(f - 0.50) for f in fills]
    avg_gap = sum(gaps) / len(gaps) if gaps else 0.0

    return {
        "total_buys": len(buys),
        "total_fills": len(fills),
        "avg_fill_price": round(avg_fill, 4),
        "avg_confidence": round(avg_conf, 4),
        "avg_entry_gap": round(avg_gap, 4),
        "cheap": len(cheap),
        "ok": len(ok),
        "expensive": len(expensive),
        "very_expensive": len(very_expensive),
    }


# ---------------------------------------------------------------------------
# Side accuracy
# ---------------------------------------------------------------------------


def analyze_side_accuracy(
    trades: list[dict],
    resolutions: list[dict],
) -> dict:
    """Compute per-side (UP/DOWN) win rates and PnL.

    Matches trades to resolutions by ``candle_slug`` / ``slug``.

    Args:
        trades: Trade dicts with ``action``, ``token_side``, ``candle_slug``,
            ``fill_price``, ``risk_blocked``.
        resolutions: Resolution dicts with ``slug``, ``winner``, ``pnl``.

    Returns:
        Dict with per-side trade counts, win rates, and avg PnL.
    """
    res_by_slug: dict[str, dict] = {r["slug"]: r for r in resolutions if "slug" in r}

    sides: dict[str, dict] = {}
    for t in trades:
        if t.get("action") not in ("BUY", "SELL") or t.get("risk_blocked"):
            continue
        side = t.get("token_side", "unknown")
        if side not in sides:
            sides[side] = {"trades": 0, "wins": 0, "losses": 0, "pnls": []}

        sides[side]["trades"] += 1
        slug = t.get("candle_slug", "")
        res = res_by_slug.get(slug)
        if res is None:
            continue
        pnl = res.get("pnl", 0)
        sides[side]["pnls"].append(pnl)
        if pnl > 0.001:
            sides[side]["wins"] += 1
        elif pnl < -0.001:
            sides[side]["losses"] += 1

    result: dict[str, dict] = {}
    for side, data in sides.items():
        total_decided = data["wins"] + data["losses"]
        result[side] = {
            "trades": data["trades"],
            "wins": data["wins"],
            "losses": data["losses"],
            "win_rate": round(data["wins"] / total_decided, 3) if total_decided else 0.0,
            "avg_pnl": round(sum(data["pnls"]) / len(data["pnls"]), 4) if data["pnls"] else 0.0,
            "total_pnl": round(sum(data["pnls"]), 4),
        }
    return result


# ---------------------------------------------------------------------------
# Missed opportunities
# ---------------------------------------------------------------------------


def analyze_missed_opportunities(
    trades: list[dict],
    resolutions: list[dict],
) -> dict:
    """Identify candles with no trades and quantify missed BTC moves.

    A "high-move missed" candle had ``abs(btc_move) >= threshold`` but the
    bot held.  A "low-move skipped" candle had a small move — skipping was
    likely correct.

    Args:
        trades: Trade dicts with ``action``, ``candle_slug``, ``risk_blocked``.
        resolutions: Resolution dicts with ``slug``, ``btc_move``, ``winner``.

    Returns:
        Dict with hold count, categorised misses, and biggest missed move.
    """
    high_move_threshold = 50.0  # $50 BTC move

    traded_slugs: set[str] = set()
    hold_slugs: set[str] = set()
    for t in trades:
        slug = t.get("candle_slug", "")
        if not slug:
            continue
        if t.get("action") in ("BUY", "SELL") and not t.get("risk_blocked"):
            traded_slugs.add(slug)
        elif t.get("action") == "HOLD":
            hold_slugs.add(slug)

    missed: list[dict] = []
    for r in resolutions:
        slug = r.get("slug", "")
        if slug in traded_slugs:
            continue
        move = abs(r.get("btc_move", 0))
        missed.append(
            {
                "slug": slug,
                "btc_move": r.get("btc_move", 0),
                "abs_move": round(move, 1),
                "winner": r.get("winner", ""),
                "category": "high_move_missed" if move >= high_move_threshold else "low_move_skipped",
            }
        )

    high = [m for m in missed if m["category"] == "high_move_missed"]
    low = [m for m in missed if m["category"] == "low_move_skipped"]

    return {
        "total_candles": len(resolutions),
        "traded_candles": len(traded_slugs),
        "missed_candles": len(missed),
        "high_move_missed": len(high),
        "low_move_skipped": len(low),
        "biggest_missed_move": round(max((m["abs_move"] for m in missed), default=0.0), 1),
        "missed_details": missed,
    }
