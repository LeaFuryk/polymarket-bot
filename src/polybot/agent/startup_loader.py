"""Startup data loading — reads persisted state from disk before AgentContext is built."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from polybot.ml_scorer.constants import MIN_TRAINING_SAMPLES
from polybot.utils import read_json, read_jsonl

if TYPE_CHECKING:
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


class StartupLoader:
    """Loads persisted state from disk before AgentContext is built.

    Reads five sources and packs them into a :class:`StartupData`:
      1. ``agent_state.json``  → resolutions_since_reflection, knowledge_state
      2. ``resolutions_*.jsonl`` → historical_resolutions
      3. ``trades_*.jsonl``      → historical_trades
      4. ``archive/*/summary.json`` → iteration_summaries
      5. ``archive/iter_*`` dirs    → iteration_label
    """

    def __init__(self, config: AppConfig, log: logging.Logger) -> None:
        self._log_dir = Path(config.logging.log_dir)
        self._archive_dir = self._log_dir.parent / "archive"
        self._log = log

    def load(self) -> StartupData:
        """Return a fully-populated :class:`StartupData`."""
        resolutions_since, knowledge = self._load_agent_state()
        return StartupData(
            resolutions_since_reflection=resolutions_since,
            knowledge_state=knowledge,
            historical_resolutions=self._load_resolutions(),
            historical_trades=self._load_trades(),
            iteration_summaries=self._load_iteration_summaries(),
            iteration_label=self._compute_iteration_label(),
        )

    def _load_agent_state(self) -> tuple[int, dict]:
        """Load ``agent_state.json`` from the log directory."""
        raw = read_json(self._log_dir, "agent_state.json", self._log)
        if raw is None:
            return 0, {}
        resolutions = raw.get("resolutions_since_reflection", 0)
        knowledge = raw.get("knowledge", {})
        self._log.info("Loaded agent state: resolutions_since_reflection=%d", resolutions)
        return resolutions, knowledge

    def _load_resolutions(self) -> list[dict]:
        """Parse ``resolutions_*.jsonl`` from the log directory."""
        records = read_jsonl(self._log_dir, "resolutions_*.jsonl", self._log)
        resolutions = [
            {
                "timestamp": datetime.fromtimestamp(r.get("timestamp", 0), tz=UTC).isoformat(),
                "slug": r.get("slug", ""),
                "winner": r.get("winner", ""),
                "btc_open": r.get("btc_open", 0),
                "btc_close": r.get("btc_close", 0),
                "btc_move": r.get("btc_close", 0) - r.get("btc_open", 0),
                "pnl": r.get("total_pnl", 0),
            }
            for r in records
        ]
        if resolutions:
            self._log.info("Loaded %d historical resolutions from logs", len(resolutions))
        return resolutions

    def _load_trades(self) -> list[dict]:
        """Parse ``trades_*.jsonl`` from the log directory."""
        records = read_jsonl(self._log_dir, "trades_*.jsonl", self._log)
        trades = [
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
            for t in records
        ]
        if trades:
            self._log.info("Loaded %d historical trades from logs", len(trades))
        return trades

    def _load_iteration_summaries(self) -> list[dict]:
        """Load and enrich all archived iteration summaries from ``archive/*/summary.json``."""
        archive_dir = self._archive_dir
        summaries: list[dict] = []
        if not archive_dir.exists():
            return summaries
        for iter_dir in sorted(d for d in archive_dir.iterdir() if d.is_dir()):
            data = read_json(iter_dir, "summary.json", self._log)
            if data is None:
                continue
            dd = read_json(iter_dir / "logs", "dashboard_data.json", self._log)
            if dd is not None:
                enrich_iteration_summary(data, dd, iter_dir)
            summaries.append(data)
        if summaries:
            self._log.info("Loaded %d iteration summaries from archive", len(summaries))
        return summaries

    def _compute_iteration_label(self) -> str:
        """Determine the current iteration label from the ``archive/`` directory."""
        archive_dir = self._archive_dir
        if not archive_dir.exists():
            return "iter_001"
        existing = sorted(d.name for d in archive_dir.iterdir() if d.is_dir() and d.name.startswith("iter_"))
        if not existing:
            return "iter_001"
        last_num = max(int(d.split("_")[1]) for d in existing)
        return f"iter_{last_num + 1:03d}"


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
