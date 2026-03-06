"""Dashboard data assembly, JSON writer, and WS broadcast loops."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.agent.context import AgentContext

logger = logging.getLogger(__name__)


def enrich_iteration_summary(summary: dict, dd: dict, archive_dir: Path | None = None) -> None:
    """Add calibration, exit, trade, and resolution analysis to a summary."""
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

    # ML model
    ml = dd.get("ml_model", {})
    summary["ml_model"] = {
        "training_samples": ml.get("training_samples", 0),
        "model_trained": ml.get("model_trained", False),
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
    """Load archived iteration summaries enriched with analysis data."""
    _log = log or logger
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


class DashboardAssembler:
    """Assembles dashboard data and manages dashboard-related async loops."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger(__name__)

    def sync_from_ai_decision(self, ctx: AgentContext) -> None:
        """Sync dashboard state from the AIDecision task."""
        if ctx.ai_decision is None:
            return
        ctx.last_action = ctx.ai_decision.last_action
        ctx.last_reasoning = ctx.ai_decision.last_reasoning
        ctx.last_risk_status = ctx.ai_decision.last_risk_status
        ctx.last_token_side = ctx.ai_decision.last_token_side
        ctx.session_wins = ctx.ai_decision.session_wins
        ctx.session_losses = ctx.ai_decision.session_losses
        ctx.session_resolution_pnl = ctx.ai_decision.session_resolution_pnl
        ctx.total_api_cost = ctx.ai_decision.total_api_cost
        ctx.last_cycle_api_cost = ctx.ai_decision.last_cycle_api_cost

        # Sync adaptive entry signals → SharedState for dynamic SL/TP
        if ctx.adaptive_entry is not None:
            ctx.shared.reversal_rate = ctx.adaptive_entry.rolling_reversal_rate
            ctx.shared.signal_type = ctx.adaptive_entry.signal_type
            ctx.shared.regime = ctx.adaptive_entry.regime

    @staticmethod
    def compute_market_trend(snapshot) -> dict:
        """Compute market trend data for dashboard. Returns empty dict if not enough data."""
        if snapshot is None or len(snapshot.btc_candles) < 50:
            return {}
        from polybot.indicators import _ema

        closes = [c.close for c in snapshot.btc_candles]
        ema20 = _ema(closes, 20)
        ema50 = _ema(closes, 50)
        price = closes[-1]

        ema_sig = max(-1, min(1, (ema20 - ema50) / 100))
        price_sig = max(-1, min(1, (price - ema50) / 150))
        last12 = snapshot.btc_candles[-12:]
        up_r = sum(1 for c in last12 if c.direction == "up") / len(last12)
        candle_sig = (up_r - 0.5) * 2
        score = max(-1, min(1, 0.4 * ema_sig + 0.35 * price_sig + 0.25 * candle_sig))

        if score >= 0.5:
            label = "STRONG BULL"
        elif score >= 0.2:
            label = "BULL"
        elif score > -0.2:
            label = "NEUTRAL"
        elif score > -0.5:
            label = "BEAR"
        else:
            label = "STRONG BEAR"

        return {
            "market_trend": round(score, 3),
            "market_trend_label": label,
        }

    def assemble_dashboard_data(self, ctx: AgentContext) -> dict:
        """Assemble full dashboard state as a dict (used by both JSON writer and WS)."""
        snapshot = ctx.shared.latest_snapshot
        up_mid = snapshot.orderbook.midpoint if snapshot else None
        down_mid = snapshot.down_orderbook.midpoint if snapshot else None
        portfolio_value = ctx.portfolio.total_value_at_market(up_mid or 0.5, down_mid)

        total_games = ctx.session_wins + ctx.session_losses
        win_rate = (ctx.session_wins / total_games * 100) if total_games > 0 else 0.0

        # Build current market info
        current_market = {}
        if ctx.current_market:
            m = ctx.current_market
            current_market = {
                "slug": m.slug,
                "title": m.title,
                "polymarket_url": f"https://polymarket.com/event/{m.slug}",
                "time_remaining": m.time_remaining(),
                "up_mid": up_mid,
                "down_mid": down_mid,
            }

        # BTC info
        btc_info = {}
        if snapshot and snapshot.btc_price:
            btc_info = {
                "price_usd": snapshot.btc_price.price_usd,
                "change_24h_pct": snapshot.btc_price.change_24h_pct,
                "last_candle_direction": (snapshot.btc_candles[-1].direction if snapshot.btc_candles else "unknown"),
                "chainlink_price": snapshot.btc_price.chainlink_price,
                "price_divergence": snapshot.btc_price.price_divergence,
                "price_source": snapshot.btc_price.price_source,
                "candle_sources": {
                    "chainlink": sum(1 for c in snapshot.btc_candles if c.source == "chainlink_ws"),
                    "binance": sum(1 for c in snapshot.btc_candles if c.source == "binance"),
                    "total": len(snapshot.btc_candles),
                },
            }

        # Positions
        positions = {
            "up_shares": ctx.portfolio.up_position.shares,
            "up_avg_entry": ctx.portfolio.up_position.avg_entry_price,
            "down_shares": ctx.portfolio.down_position.shares,
            "down_avg_entry": ctx.portfolio.down_position.avg_entry_price,
        }

        # Position P&L from position monitor
        position_pnl = dict(ctx.shared.position_pnl_pct)

        # Dynamic SL/TP from position monitor
        dynamic_sl = dict(ctx.shared.dynamic_sl)
        dynamic_tp = dict(ctx.shared.dynamic_tp)

        # Trades list
        trades = []
        for t in ctx.session_trades:
            trade_entry = {
                "timestamp": datetime.fromtimestamp(t.timestamp, tz=UTC).isoformat(),
                "cycle": t.cycle_number,
                "action": t.action.value,
                "token_side": t.token_side.value,
                "size": t.decision_size,
                "fill_price": t.fill_price,
                "confidence": t.confidence,
                "reasoning": t.reasoning,
                "market_view": t.market_view,
                "candle_slug": t.candle_slug,
                "polymarket_url": (f"https://polymarket.com/event/{t.candle_slug}" if t.candle_slug else ""),
                "time_remaining_at_trade": t.extra.get("time_remaining", 0),
                "risk_blocked": t.risk_blocked,
                "risk_block_reason": t.risk_block_reason,
                "cash": t.cash,
                "portfolio_value": t.portfolio_value,
                "fee": t.fee_amount,
                "realized_pnl": t.realized_pnl,
                "unrealized_pnl": t.unrealized_pnl,
                "ai_cost": t.ai_cost,
                "screen_passed": t.extra.get("screen_passed"),
                "screen_input": t.extra.get("screen_input"),
                "live_order": t.extra.get("live_order"),
            }
            trades.append(trade_entry)

        # Resolutions list (use uncapped session list, not the reflection window)
        resolutions = []
        for r in ctx.session_resolutions:
            resolutions.append(
                {
                    "timestamp": datetime.fromtimestamp(r.timestamp, tz=UTC).isoformat(),
                    "slug": r.slug,
                    "winner": r.winner,
                    "btc_open": r.btc_open,
                    "btc_close": r.btc_close,
                    "btc_move": r.btc_close - r.btc_open,
                    "pnl": r.total_pnl,
                }
            )

        # Merge historical + current session data (dedup resolutions by slug)
        all_trades = ctx.historical_trades + trades
        seen_slugs: set[str] = set()
        all_resolutions: list[dict] = []
        for r in ctx.historical_resolutions + resolutions:
            slug = r.get("slug", "")
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                all_resolutions.append(r)
            elif not slug:
                all_resolutions.append(r)

        all_time_pnl = sum(r.get("pnl", 0) for r in all_resolutions)
        all_time_wins = sum(1 for r in all_resolutions if r.get("pnl", 0) > 0.001)
        all_time_losses = sum(1 for r in all_resolutions if r.get("pnl", 0) < -0.001)
        all_time_total = all_time_wins + all_time_losses
        all_time_win_rate = (all_time_wins / all_time_total * 100) if all_time_total > 0 else 0.0

        # Build candle snapshot timelines from datastore
        candle_snapshots: dict = {}
        if ctx.datastore and ctx.datastore._conn:
            try:
                cursor = ctx.datastore._conn.execute("""
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
                    if sample_counter % 10 == 0:  # downsample ~every 10s
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
            except Exception:
                self._log.debug("Failed to build candle snapshots", exc_info=True)

        data = {
            "bot_version": ctx.bot_version,
            "updated_at": datetime.now(UTC).isoformat(),
            "session": {
                "wins": ctx.session_wins,
                "losses": ctx.session_losses,
                "win_rate": win_rate,
                "total_pnl": ctx.session_resolution_pnl,
                "total_fees": ctx.portfolio.total_fees,
                "total_ai_cost": ctx.total_api_cost,
                "cash": ctx.portfolio.cash,
                "portfolio_value": portfolio_value,
                "initial_cash": ctx.config.agent.initial_cash,
                "market_trading_pnl": ctx.portfolio.market_trading_pnl,
                "cycles_run": ctx.ai_decision._cycle_count if ctx.ai_decision else 0,
                "prefilter_skip_rate": ctx.prefilter.skip_rate,
                "prefilter_skipped": ctx.prefilter.total_skipped,
                "prefilter_checked": ctx.prefilter.total_checks,
                "calibration_records": ctx.calibrator.total_records,
            },
            "all_time": {
                "wins": all_time_wins,
                "losses": all_time_losses,
                "win_rate": all_time_win_rate,
                "total_pnl": all_time_pnl,
                "total_resolutions": len(all_resolutions),
                "total_trades": len(all_trades),
            },
            "current_market": current_market,
            "btc": btc_info,
            "positions": positions,
            "position_pnl": position_pnl,
            "dynamic_sl": dynamic_sl,
            "dynamic_tp": dynamic_tp,
            "trades": all_trades,
            "resolutions": all_resolutions,
            "risk": {
                "daily_pnl": ctx.risk.state.daily_pnl,
                "daily_trades": ctx.risk.state.daily_trades,
                "daily_fees": ctx.risk.state.daily_fees,
                "max_drawdown": ctx.risk.state.max_drawdown,
                "is_halted": ctx.risk.state.is_halted,
            },
            "ml_model": {
                "training_samples": ctx.ml_scorer._training_samples,
                "model_trained": ctx.ml_scorer._training_samples >= ctx.ml_scorer._min_samples,
            },
            "calibration": {
                "total_records": ctx.calibrator.total_records,
                "shadow_correct": ctx.calibrator._shadow_correct,
                "shadow_total": ctx.calibrator._shadow_total,
                "shadow_accuracy": round(ctx.calibrator._shadow_correct / ctx.calibrator._shadow_total, 3)
                if ctx.calibrator._shadow_total > 0
                else None,
                "bins": [
                    {
                        "range": f"{b.bin_lower:.0%}-{b.bin_upper:.0%}",
                        "wins": b.wins,
                        "losses": b.losses,
                        "win_rate": round(b.win_rate, 3),
                        "reliable": b.is_reliable,
                    }
                    for b in ctx.calibrator._bins.values()
                    if b.total > 0
                ],
            },
            "exit_analysis": {
                "total_exits": ctx.exit_tracker._total_exits,
                "good_exits": ctx.exit_tracker._exits_better_than_hold,
                "good_exit_rate": round(ctx.exit_tracker.good_exit_rate, 3),
                "total_saved": round(ctx.exit_tracker._total_saved, 4),
                "total_missed": round(ctx.exit_tracker._total_missed, 4),
            },
            "monitor": {
                "prefilter_snapshots": len(ctx.shared.prefilter_history),
                "ai_cooldown_remaining": max(
                    0, ctx.config.monitor.ai_cooldown_seconds - (time.time() - ctx.shared.ai_last_call_time)
                ),
                "last_trigger_reason": ctx.shared.ai_trigger_reason,
                "status": ctx.shared.monitor_status,
            },
            "adaptive_entry": {
                "enabled": ctx.config.monitor.adaptive_entry_enabled,
                "btc_threshold": ctx.adaptive_entry.btc_threshold,
                "max_entry_price": round(ctx.adaptive_entry.max_entry_price, 4),
                "reversal_rate": round(ctx.adaptive_entry.rolling_reversal_rate, 4),
                "regime": ctx.adaptive_entry.regime,
                "signal_type": ctx.adaptive_entry.signal_type,
                "has_enough_history": ctx.adaptive_entry.has_enough_history,
                "window_size": ctx.adaptive_entry._window,
                "history_count": len(ctx.adaptive_entry._history),
                **self.compute_market_trend(snapshot),
                **ctx.adaptive_entry.fakeout_stats,
            },
            "ensemble": {
                "screen_calls": ctx.ai_decision._screen_calls,
                "screen_passes": ctx.ai_decision._screen_passes,
                "screen_pass_rate": round(ctx.ai_decision._screen_passes / max(1, ctx.ai_decision._screen_calls), 3),
                "sonnet_trades": ctx.ai_decision._sonnet_trades,
                "ml_sonnet_agree": ctx.ai_decision._ml_sonnet_agree,
                "ml_sonnet_total": ctx.ai_decision._ml_sonnet_total,
                "ml_sonnet_agree_rate": round(
                    ctx.ai_decision._ml_sonnet_agree / max(1, ctx.ai_decision._ml_sonnet_total), 3
                ),
            },
            "outage": {
                "is_down": ctx.outage_start is not None,
                "since": ctx.outage_start,
                "duration": (time.time() - ctx.outage_start) if ctx.outage_start else 0,
                "failures": ctx.discovery_failures,
                "recovered": ctx.outage_recovered is not None,
                "last_outage_duration": ctx.last_outage_duration,
            },
            "iterations": ctx.iteration_summaries,
            "candle_snapshots": candle_snapshots,
        }

        # Explicit trading mode (paper / live / dry_run)
        if ctx.config.trading.mode == "live" and ctx.config.trading.dry_run:
            data["trading_mode"] = "dry_run"
        else:
            data["trading_mode"] = ctx.config.trading.mode  # "paper" or "live"

        # Live trading section (only in live mode)
        if ctx.live_mode and ctx.live_engine:
            shadow_pnl = 0.0
            if ctx.shadow_portfolio:
                shadow_pnl = ctx.shadow_portfolio.cash - ctx.config.agent.initial_cash
            data["live_trading"] = {
                "mode": ctx.config.trading.mode,
                "dry_run": ctx.config.trading.dry_run,
                "wallet_balance": ctx.live_engine.wallet_balance,
                "kill_switch_active": ctx.live_engine.kill_switch_active,
                "max_order_size_usd": ctx.config.trading.max_order_size_usd,
                "max_session_loss_usd": ctx.config.trading.max_session_loss_usd,
                "shadow_paper_pnl": shadow_pnl,
                "execution_cost": ctx.session_resolution_pnl - shadow_pnl,
            }

        return data

    def write_dashboard_json(self, ctx: AgentContext) -> None:
        """Write dashboard_data.json for the web dashboard."""
        try:
            dashboard_path = Path(ctx.config.logging.log_dir) / "dashboard_data.json"
            dashboard_path.parent.mkdir(parents=True, exist_ok=True)

            data = self.assemble_dashboard_data(ctx)
            dashboard_path.write_text(json.dumps(data, indent=2) + "\n")

            # Write iterations sidecar for dashboard
            if ctx.iteration_summaries:
                iter_path = dashboard_path.parent / "iterations.json"
                iter_path.write_text(json.dumps(ctx.iteration_summaries, indent=2) + "\n")
        except Exception:
            self._log.debug("Failed to write dashboard JSON", exc_info=True)

    async def dashboard_loop(self, ctx: AgentContext) -> None:
        """Writes dashboard JSON + broadcasts WS snapshot (every 2s)."""
        self._log.info("DashboardLoop started")
        while not ctx.shared.shutdown:
            try:
                self.sync_from_ai_decision(ctx)
                snapshot = ctx.shared.latest_snapshot
                if snapshot is not None:
                    self.write_dashboard_json(ctx)
                    # Broadcast snapshot + status to WS clients
                    if ctx.ws_broadcaster and ctx.ws_broadcaster.has_clients:
                        from polybot.ws.protocol import MSG_SNAPSHOT, make_message

                        data = self.assemble_dashboard_data(ctx)
                        data["ws_clients"] = ctx.ws_broadcaster.client_count
                        await ctx.ws_broadcaster.broadcast(make_message(MSG_SNAPSHOT, data))
                        await ctx.ws_broadcaster.broadcast(ctx.ws_broadcaster.build_status_update(ctx))
                        ctx.shared.ws_client_count = ctx.ws_broadcaster.client_count
            except Exception:
                self._log.debug("DashboardLoop error", exc_info=True)
            await asyncio.sleep(2.0)
        self._log.info("DashboardLoop stopped")

    async def ws_broadcast_loop(self, ctx: AgentContext) -> None:
        """Push lightweight market + position updates via WS (every 1s)."""
        self._log.info("WSBroadcastLoop started")
        while not ctx.shared.shutdown:
            try:
                if ctx.ws_broadcaster and ctx.ws_broadcaster.has_clients:
                    await ctx.ws_broadcaster.broadcast(ctx.ws_broadcaster.build_market_update(ctx))
                    await ctx.ws_broadcaster.broadcast(ctx.ws_broadcaster.build_position_update(ctx))
            except Exception:
                self._log.debug("WSBroadcastLoop error", exc_info=True)
            await asyncio.sleep(1.0)
        self._log.info("WSBroadcastLoop stopped")
