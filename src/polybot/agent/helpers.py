"""Agent helper functions — logging setup, PnL reconstruction, state persistence."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from polybot.ml_scorer.constants import MIN_TRAINING_SAMPLES

if TYPE_CHECKING:
    from polybot.agent.context import AgentContext
    from polybot.config import AppConfig


@dataclass
class StartupData:
    """Data loaded from disk at startup, before AgentContext is built."""

    resolutions_since_reflection: int = 0
    knowledge_state: dict = field(default_factory=dict)
    historical_resolutions: list[dict] = field(default_factory=list)
    historical_trades: list[dict] = field(default_factory=list)
    iteration_summaries: list[dict] = field(default_factory=list)
    iteration_label: str = "iter_001"


def load_startup_data(config: AppConfig, log: logging.Logger | None = None) -> StartupData:
    """Collect all persisted data from disk before AgentContext is built.

    Reads four sources and packs them into a single StartupData object:
      1. ``agent_state.json`` → resolutions_since_reflection, knowledge_state
      2. ``resolutions_*.jsonl`` / ``trades_*.jsonl`` → historical_resolutions, historical_trades
      3. ``archive/*/summary.json`` → iteration_summaries (enriched via enrich_iteration_summary)
      4. ``archive/iter_*`` directory count → iteration_label (e.g. "iter_003")

    Returns:
        A fully-populated StartupData that ContextFactory.build() uses to
        pre-populate AgentContext fields and seed the KnowledgeManager.
    """
    _log = log or logging.getLogger(__name__)
    data = StartupData()

    # Load agent_state.json
    state_path = Path(config.logging.log_dir) / "agent_state.json"
    try:
        if state_path.exists():
            raw = json.loads(state_path.read_text())
            data.resolutions_since_reflection = raw.get("resolutions_since_reflection", 0)
            data.knowledge_state = raw.get("knowledge", {})
            _log.info(
                "Loaded agent state: resolutions_since_reflection=%d",
                data.resolutions_since_reflection,
            )
    except Exception:
        _log.warning("Could not load agent state, starting fresh")

    # Load JSONL history (resolutions + trades)
    _load_history_from_logs(config, data, _log)

    # Load archived iteration summaries
    data.iteration_summaries = load_iteration_summaries(log=_log)

    # Compute iteration label
    data.iteration_label = compute_iteration_label()

    return data


def _load_history_from_logs(config: AppConfig, data: StartupData, log: logging.Logger) -> None:
    """Parse ``resolutions_*.jsonl`` and ``trades_*.jsonl`` from the log directory.

    Appends normalised dicts to ``data.historical_resolutions`` and
    ``data.historical_trades`` in chronological file order.
    """
    log_dir = Path(config.logging.log_dir)

    for res_file in sorted(log_dir.glob("resolutions_*.jsonl")):
        try:
            for line in res_file.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                r = json.loads(line)
                data.historical_resolutions.append(
                    {
                        "timestamp": datetime.fromtimestamp(r.get("timestamp", 0), tz=UTC).isoformat(),
                        "slug": r.get("slug", ""),
                        "winner": r.get("winner", ""),
                        "btc_open": r.get("btc_open", 0),
                        "btc_close": r.get("btc_close", 0),
                        "btc_move": r.get("btc_close", 0) - r.get("btc_open", 0),
                        "pnl": r.get("total_pnl", 0),
                    }
                )
        except Exception:
            log.debug("Could not load resolution file %s", res_file, exc_info=True)

    for trade_file in sorted(log_dir.glob("trades_*.jsonl")):
        try:
            for line in trade_file.read_text().strip().split("\n"):
                if not line.strip():
                    continue
                t = json.loads(line)
                data.historical_trades.append(
                    {
                        "timestamp": datetime.fromtimestamp(t.get("timestamp", 0), tz=UTC).isoformat(),
                        "cycle": t.get("cycle_number", 0),
                        "action": t.get("action", "HOLD"),
                        "token_side": t.get("token_side", "up"),
                        "size": t.get("decision_size", 0),
                        "fill_price": t.get("fill_price"),
                        "confidence": t.get("confidence", 0),
                        "reasoning": t.get("reasoning", ""),
                        "market_view": t.get("market_view", ""),
                        "candle_slug": t.get("candle_slug", ""),
                        "polymarket_url": (
                            f"https://polymarket.com/event/{t.get('candle_slug', '')}" if t.get("candle_slug") else ""
                        ),
                        "time_remaining_at_trade": t.get("extra", {}).get("time_remaining", 0),
                        "risk_blocked": t.get("risk_blocked", False),
                        "risk_block_reason": t.get("risk_block_reason", ""),
                        "cash": t.get("cash"),
                        "portfolio_value": t.get("portfolio_value"),
                        "fee": t.get("fee_amount", 0),
                        "realized_pnl": t.get("realized_pnl", 0),
                        "unrealized_pnl": t.get("unrealized_pnl", 0),
                        "ai_cost": t.get("ai_cost", 0),
                        "live_order": t.get("extra", {}).get("live_order"),
                    }
                )
        except Exception:
            log.debug("Could not load trade file %s", trade_file, exc_info=True)

    if data.historical_resolutions:
        log.info("Loaded %d historical resolutions from logs", len(data.historical_resolutions))
    if data.historical_trades:
        log.info("Loaded %d historical trades from logs", len(data.historical_trades))


def save_agent_state(ctx: AgentContext, log: logging.Logger | None = None) -> None:
    """Write ``agent_state.json`` to ``ctx.state_path``.

    Persists bot_version, resolutions_since_reflection, and the
    KnowledgeManager's serialised state so the next session can resume.
    Called by RotationManager after every market transition.
    """
    _log = log or logging.getLogger(__name__)
    try:
        ctx.state_path.parent.mkdir(parents=True, exist_ok=True)
        ctx.state_path.write_text(
            json.dumps(
                {
                    "bot_version": ctx.bot_version,
                    "resolutions_since_reflection": ctx.resolutions_since_reflection,
                    "knowledge": ctx.knowledge_manager.save_state(),
                },
                indent=2,
            )
            + "\n"
        )
    except Exception:
        _log.warning("Could not save agent state")


async def resolve_pending_bets(ctx: AgentContext, log: logging.Logger | None = None) -> None:
    """Resolve trades from a previous session that have no matching resolution.

    Cross-references ``ctx.historical_trades`` against ``ctx.historical_resolutions``
    to find candle slugs with fills but no recorded outcome.  For each unresolved
    candle whose end_time has passed, fetches the market result from Polymarket,
    computes PnL, and writes the resolution to the trade log.

    Called once at the start of ``TradingAgent.run()`` after feeds are live.
    """
    _log = log or logging.getLogger(__name__)

    trades_by_slug: dict[str, list[dict]] = {}
    for t in ctx.historical_trades:
        slug = t.get("candle_slug", "")
        if not slug or slug == "unknown":
            continue
        trades_by_slug.setdefault(slug, []).append(t)

    resolved_slugs = {r.get("slug", "") for r in ctx.historical_resolutions}

    unresolved = []
    for slug, trades in trades_by_slug.items():
        if slug in resolved_slugs:
            continue
        has_fill = any(t.get("action") in ("BUY", "SELL") and t.get("fill_price") for t in trades)
        if not has_fill:
            continue
        unresolved.append(slug)

    if not unresolved:
        return

    unresolved.sort(key=lambda s: int(s.rsplit("-", 1)[-1]) if s.rsplit("-", 1)[-1].isdigit() else 0)
    _log.info("Found %d unresolved candle(s) with fills: %s", len(unresolved), unresolved)

    for slug in unresolved:
        try:
            await _resolve_single_pending_bet(ctx, slug, trades_by_slug[slug], _log)
        except Exception:
            _log.exception("Failed to resolve pending bet: %s", slug)


async def _resolve_single_pending_bet(ctx: AgentContext, slug: str, trades: list[dict], log: logging.Logger) -> None:
    """Fetch the outcome of a single expired candle and record its resolution.

    Skips candles that are still live or whose BTC prices cannot be fetched.
    """
    market = await ctx.discovery.fetch_market_by_slug(slug)
    if market is None:
        log.warning("Could not fetch market for pending bet: %s (may be delisted)", slug)
        return

    now = time.time()
    if market.end_time > now:
        log.info("Skipping pending bet %s — candle still live (ends in %.0fs)", slug, market.end_time - now)
        return

    btc_open = await ctx.market_data.btc_feed.get_price_at(market.start_time)
    btc_close = await ctx.market_data.btc_feed.get_price_at(market.end_time)

    if btc_open is None or btc_close is None:
        log.warning("Could not fetch BTC prices for pending bet: %s (open=%s close=%s)", slug, btc_open, btc_close)
        return

    resolution = await ctx.resolution_tracker.resolve(market, btc_close)
    resolution.btc_open = btc_open
    resolution.btc_close = btc_close

    pnl = compute_pnl_from_trades(trades, resolution.winner)
    resolution.total_pnl = pnl

    ctx.trade_log.write_resolution(resolution)

    ctx.historical_resolutions.append(
        {
            "timestamp": datetime.fromtimestamp(resolution.timestamp, tz=UTC).isoformat(),
            "slug": resolution.slug,
            "winner": resolution.winner,
            "btc_open": resolution.btc_open,
            "btc_close": resolution.btc_close,
            "btc_move": resolution.btc_close - resolution.btc_open,
            "pnl": resolution.total_pnl,
        }
    )

    log.info(
        "Resolving pending bet: %s — winner=%s, pnl=%.4f (open=$%.2f close=$%.2f)",
        slug,
        resolution.winner,
        pnl,
        btc_open,
        btc_close,
    )


def compute_iteration_label() -> str:
    """Determine the current iteration label from the ``archive/`` directory.

    Scans ``archive/iter_*`` folders and returns the next sequential label
    (e.g. ``"iter_003"`` when ``iter_001`` and ``iter_002`` exist).
    Returns ``"iter_001"`` when no archive directory exists.
    """
    archive_dir = Path.cwd() / "archive"
    if not archive_dir.exists():
        return "iter_001"
    existing = sorted(d.name for d in archive_dir.iterdir() if d.is_dir() and d.name.startswith("iter_"))
    if not existing:
        return "iter_001"
    last_num = max(int(d.split("_")[1]) for d in existing)
    return f"iter_{last_num + 1:03d}"


def compute_pnl_from_trades(trades: list[dict], winner: str) -> float:
    """Reconstruct PnL for a candle from its logged trades.

    Accumulates share counts and costs for both up/down token sides, then
    settles at $1 for the winning token and $0 for the losing token.

    Args:
        trades: List of trade dicts (must contain action, fill_price, token_side).
        winner: ``"up"`` or ``"down"`` — which token paid out $1.

    Returns:
        Net profit/loss in dollars.
    """
    up_shares = 0.0
    up_cost = 0.0
    down_shares = 0.0
    down_cost = 0.0

    for t in trades:
        if t.get("risk_blocked") or not t.get("fill_price"):
            continue
        size = t.get("fill_size") or t.get("size") or t.get("decision_size") or 0
        price = t["fill_price"]
        side = t.get("token_side", "up")
        action = t.get("action", "HOLD")

        if action == "BUY":
            if side == "up":
                up_shares += size
                up_cost += size * price
            else:
                down_shares += size
                down_cost += size * price
        elif action == "SELL":
            if side == "up":
                up_shares -= size
                up_cost -= size * price
            else:
                down_shares -= size
                down_cost -= size * price

    # Settlement: winning token pays $1, losing pays $0
    if winner == "up":
        pnl = (up_shares * 1.0 - up_cost) + (0 - down_cost)
    else:
        pnl = (0 - up_cost) + (down_shares * 1.0 - down_cost)

    return pnl


# ── Iteration summary helpers (moved from dashboard.py) ──────────────────────


def enrich_iteration_summary(summary: dict, dd: dict, archive_dir: Path | None = None) -> None:
    """Enrich an iteration summary dict with analytics derived from dashboard data.

    Adds calibration stats, exit analysis, ML model state, trade breakdown,
    execution quality, resolution analysis, observations, session history,
    candle snapshots (from archived SQLite), and live-trading metrics.

    Args:
        summary: The summary dict to mutate (typically loaded from ``summary.json``).
        dd: Dashboard data dict (from ``dashboard_data.json``).
        archive_dir: Path to the iteration's archive folder (for observations,
            session history, and SQLite snapshots).  ``None`` skips those sections.
    """
    # Calibration
    cal = dd.get("calibration", {})
    summary["calibration"] = {
        "total_records": cal.get("total_records", 0),
        "shadow_accuracy": cal.get("shadow_accuracy"),
        "shadow_total": cal.get("shadow_total", 0),
        "bins": cal.get("bins", []),
    }

    # Exit analysis
    ex = dd.get("exit_analysis", {})
    summary["exit_analysis"] = {
        "total_exits": ex.get("total_exits", 0),
        "good_exit_rate": ex.get("good_exit_rate", 0),
        "good_exits": ex.get("good_exits", 0),
        "total_saved": ex.get("total_saved", 0),
        "total_missed": ex.get("total_missed", 0),
    }

    # ML model — recompute model_trained from threshold; preserve weights/bias
    ml = dd.get("ml_model", {})
    samples = ml.get("training_samples", 0)
    summary["ml_model"] = {
        "training_samples": samples,
        "model_trained": samples >= MIN_TRAINING_SAMPLES,
        "weights": ml.get("weights"),
        "bias": ml.get("bias"),
    }

    # Trade analysis
    trades = dd.get("trades", [])
    buys = [t for t in trades if t.get("action") == "BUY" and not t.get("risk_blocked")]
    sells = [t for t in trades if t.get("action") == "SELL" and not t.get("risk_blocked")]
    holds = [t for t in trades if t.get("action") == "HOLD"]
    fills = [t["fill_price"] for t in buys if t.get("fill_price")]
    confs = [t["confidence"] for t in buys if t.get("confidence")]

    avg_fill = sum(fills) / len(fills) if fills else 0
    avg_conf = sum(confs) / len(confs) if confs else 0

    summary["trade_analysis"] = {
        "total_buys": len(buys),
        "total_sells": len(sells),
        "total_holds": len(holds),
        "avg_fill_price": round(avg_fill, 4),
        "cheap_entries": len([f for f in fills if f < 0.40]),
        "mid_entries": len([f for f in fills if 0.40 <= f < 0.60]),
        "expensive_entries": len([f for f in fills if f >= 0.60]),
        "avg_confidence": round(avg_conf, 4),
        "hold_rate": round(len(holds) / len(trades), 3) if trades else 0,
    }

    # Execution quality (live-order fill analysis)
    live_orders = [t.get("live_order") for t in trades if t.get("live_order")]
    if live_orders:
        filled = [lo for lo in live_orders if lo.get("fill_source")]
        by_source: dict[str, int] = {}
        for lo in filled:
            src = lo.get("fill_source", "")
            by_source[src] = by_source.get(src, 0) + 1
        matched_sizes = [lo.get("size_matched", 0) for lo in filled if lo.get("size_matched")]
        summary["execution_quality"] = {
            "total_orders": len(live_orders),
            "filled_count": len(filled),
            "fill_rate": round(len(filled) / len(live_orders), 3) if live_orders else 0,
            "timeout_count": len(live_orders) - len(filled),
            "by_fill_source": by_source,
            "avg_size_matched": round(sum(matched_sizes) / len(matched_sizes), 4) if matched_sizes else 0,
        }

    # Resolution analysis
    ress = dd.get("resolutions", [])
    btc_moves = [abs(r.get("btc_move", 0)) for r in ress]
    pnls = [r.get("pnl", 0) for r in ress]
    win_pnls = [p for p in pnls if p > 0.001]
    loss_pnls = [p for p in pnls if p < -0.001]

    summary["resolution_analysis"] = {
        "total": len(ress),
        "avg_btc_move": round(sum(btc_moves) / len(btc_moves), 1) if btc_moves else 0,
        "max_btc_move": round(max(btc_moves), 1) if btc_moves else 0,
        "avg_win_pnl": round(sum(win_pnls) / len(win_pnls), 4) if win_pnls else 0,
        "avg_loss_pnl": round(sum(loss_pnls) / len(loss_pnls), 4) if loss_pnls else 0,
        "biggest_win": round(max(win_pnls), 4) if win_pnls else 0,
        "biggest_loss": round(min(loss_pnls), 4) if loss_pnls else 0,
        "cumulative_pnl": [round(sum(pnls[: i + 1]), 4) for i in range(len(pnls))],
    }

    # Per-resolution detail for table view
    summary["resolutions_detail"] = [
        {
            "slug": r.get("slug", ""),
            "pnl": r.get("pnl", 0),
            "btc_move": r.get("btc_move", 0),
            "resolution": r.get("resolution", ""),
        }
        for r in ress
    ]

    # Observations from knowledge base
    if archive_dir:
        obs_file = archive_dir / "data" / "knowledge" / "observations.jsonl"
        if obs_file.exists():
            observations = []
            for line in obs_file.read_text().splitlines():
                if line.strip():
                    try:
                        rec = json.loads(line)
                        observations.append(
                            {
                                "category": rec.get("category", ""),
                                "text": rec.get("text", ""),
                                "timestamp": rec.get("timestamp", ""),
                            }
                        )
                    except json.JSONDecodeError:
                        pass
            summary["observations"] = observations

        # Session history markdown
        sh_file = archive_dir / "data" / "knowledge" / "session_history.md"
        if sh_file.exists():
            summary["session_history"] = sh_file.read_text()

        # Candle snapshot timelines from archived database
        db_path = archive_dir / "logs" / "polybot.db"
        if db_path.exists():
            import sqlite3

            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.execute("""
                    SELECT c.slug, c.winner, c.btc_open,
                           s.time_remaining, s.up_mid, s.down_mid,
                           s.btc_move_from_open, s.prefilter_passed, s.prefilter_reasons,
                           s.indicators_json, s.up_spread_pct, s.down_spread_pct,
                           s.up_bid_depth, s.down_bid_depth, s.btc_price,
                           s.up_best_ask, s.down_best_ask,
                           s.rr_up, s.rr_down,
                           s.streak, s.streak_direction
                    FROM snapshots s
                    JOIN candles c ON s.candle_id = c.candle_id
                    ORDER BY c.candle_id, s.timestamp
                """)
                candle_snapshots: dict = {}
                current_slug = None
                sample_counter = 0
                for row in cursor:
                    slug = row[0]
                    if slug != current_slug:
                        current_slug = slug
                        sample_counter = 0
                        candle_snapshots[slug] = {
                            "winner": row[1],
                            "btc_open": row[2],
                            "points": [],
                        }
                    sample_counter += 1
                    if sample_counter % 10 == 0:
                        candle_snapshots[slug]["points"].append(
                            {
                                "tr": round(row[3], 0),
                                "up": round(row[4], 4) if row[4] else None,
                                "dn": round(row[5], 4) if row[5] else None,
                                "btc_mv": round(row[6], 1) if row[6] else None,
                                "pf": row[7],
                                "pfr": row[8],
                                "ind": row[9],
                                "u_sp": round(row[10], 2) if row[10] else None,
                                "d_sp": round(row[11], 2) if row[11] else None,
                                "u_dep": round(row[12], 1) if row[12] else None,
                                "d_dep": round(row[13], 1) if row[13] else None,
                                "btc": round(row[14], 2) if row[14] else None,
                                "u_ask": round(row[15], 4) if row[15] else None,
                                "d_ask": round(row[16], 4) if row[16] else None,
                                "rr_u": round(row[17], 3) if row[17] else None,
                                "rr_d": round(row[18], 3) if row[18] else None,
                                "stk": row[19],
                                "stk_d": row[20],
                            }
                        )
                conn.close()
                if candle_snapshots:
                    summary["candle_snapshots"] = candle_snapshots
            except Exception:
                pass

    # Live trading mode + metrics
    lt = dd.get("live_trading")
    if lt:
        summary["trading_mode"] = "dry_run" if lt.get("dry_run") else "live"
        summary["live_trading"] = {
            "mode": lt.get("mode", "live"),
            "dry_run": lt.get("dry_run", False),
            "wallet_balance": lt.get("wallet_balance", 0),
            "shadow_paper_pnl": lt.get("shadow_paper_pnl", 0),
            "execution_cost": lt.get("execution_cost", 0),
        }
    elif "trading_mode" not in summary:
        summary["trading_mode"] = dd.get("trading_mode", "paper")


def load_iteration_summaries(log: logging.Logger | None = None) -> list[dict]:
    """Load and enrich all archived iteration summaries from ``archive/*/summary.json``.

    Each summary is enriched with its co-located ``dashboard_data.json`` via
    ``enrich_iteration_summary()``.

    Returns:
        List of enriched summary dicts, sorted by archive folder name.
    """
    _log = log or logging.getLogger(__name__)
    archive_dir = Path.cwd() / "archive"
    summaries = []
    if not archive_dir.exists():
        return summaries
    for summary_path in sorted(archive_dir.glob("*/summary.json")):
        try:
            data = json.loads(summary_path.read_text())
            iter_dir = summary_path.parent
            # Enrich with data from archived dashboard_data.json
            dash_path = iter_dir / "logs" / "dashboard_data.json"
            if dash_path.exists():
                dd = json.loads(dash_path.read_text())
                enrich_iteration_summary(data, dd, iter_dir)
            summaries.append(data)
        except Exception:
            _log.debug("Could not load summary: %s", summary_path, exc_info=True)
    if summaries:
        _log.info("Loaded %d iteration summaries from archive", len(summaries))
    return summaries
