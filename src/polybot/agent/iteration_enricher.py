"""Enriches archived iteration summaries with derived analytics from dashboard data.

# TODO(prompt-rethink): REVISIT THIS ENTIRE FILE
# This module exists because the dashboard data model is poorly structured —
# it stores raw trades/resolutions as flat lists and we have to re-derive
# analytics (calibration, exit analysis, trade stats, etc.) on every load.
# After the prompt overhaul and data model redesign, most of this enrichment
# should be unnecessary — the data should already be stored in the right shape.
# Delete or radically simplify this file once the new models are in place.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from polybot.ml_scorer.constants import MIN_TRAINING_SAMPLES


def _extract(source: dict, fields: list[tuple[str, Any]]) -> dict:
    """Pull *fields* from *source*, applying defaults for missing keys."""
    return {name: source.get(name, default) for name, default in fields}


class IterationSummaryEnricher:
    """Mutates a summary dict with analytics derived from dashboard data.

    Each ``_enrich_*`` method adds one section to the summary. The public
    entry point is :meth:`enrich`.
    """

    def __init__(self, summary: dict, dd: dict, archive_dir: Path | None = None) -> None:
        self._summary = summary
        self._dd = dd
        self._archive_dir = archive_dir

    def enrich(self) -> None:
        """Run all enrichment steps."""
        self._enrich_calibration()
        self._enrich_exit_analysis()
        self._enrich_ml_model()
        self._enrich_trade_analysis()
        self._enrich_execution_quality()
        self._enrich_resolution_analysis()
        self._enrich_live_trading()
        if self._archive_dir:
            self._enrich_observations()
            self._enrich_session_history()
            self._enrich_candle_snapshots()

    def _enrich_calibration(self) -> None:
        self._summary["calibration"] = _extract(
            self._dd.get("calibration", {}),
            [
                ("total_records", 0),
                ("shadow_accuracy", None),
                ("shadow_total", 0),
                ("bins", []),
            ],
        )

    def _enrich_exit_analysis(self) -> None:
        self._summary["exit_analysis"] = _extract(
            self._dd.get("exit_analysis", {}),
            [
                ("total_exits", 0),
                ("good_exit_rate", 0),
                ("good_exits", 0),
                ("total_saved", 0),
                ("total_missed", 0),
            ],
        )

    def _enrich_ml_model(self) -> None:
        ml = self._dd.get("ml_model", {})
        samples = ml.get("training_samples", 0)
        self._summary["ml_model"] = {
            "training_samples": samples,
            "model_trained": samples >= MIN_TRAINING_SAMPLES,
            "weights": ml.get("weights"),
            "bias": ml.get("bias"),
        }

    def _enrich_trade_analysis(self) -> None:
        trades = self._dd.get("trades", [])
        buys = [t for t in trades if t.get("action") == "BUY" and not t.get("risk_blocked")]
        sells = [t for t in trades if t.get("action") == "SELL" and not t.get("risk_blocked")]
        holds = [t for t in trades if t.get("action") == "HOLD"]
        fills = [t["fill_price"] for t in buys if t.get("fill_price")]
        confs = [t["confidence"] for t in buys if t.get("confidence")]

        avg_fill = sum(fills) / len(fills) if fills else 0
        avg_conf = sum(confs) / len(confs) if confs else 0

        self._summary["trade_analysis"] = {
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

    def _enrich_execution_quality(self) -> None:
        trades = self._dd.get("trades", [])
        live_orders = [t.get("live_order") for t in trades if t.get("live_order")]
        if not live_orders:
            return
        filled = [lo for lo in live_orders if lo.get("fill_source")]
        by_source: dict[str, int] = {}
        for lo in filled:
            src = lo.get("fill_source", "")
            by_source[src] = by_source.get(src, 0) + 1
        matched_sizes = [lo.get("size_matched", 0) for lo in filled if lo.get("size_matched")]
        self._summary["execution_quality"] = {
            "total_orders": len(live_orders),
            "filled_count": len(filled),
            "fill_rate": round(len(filled) / len(live_orders), 3) if live_orders else 0,
            "timeout_count": len(live_orders) - len(filled),
            "by_fill_source": by_source,
            "avg_size_matched": round(sum(matched_sizes) / len(matched_sizes), 4) if matched_sizes else 0,
        }

    def _enrich_resolution_analysis(self) -> None:
        ress = self._dd.get("resolutions", [])
        btc_moves = [abs(r.get("btc_move", 0)) for r in ress]
        pnls = [r.get("pnl", 0) for r in ress]
        win_pnls = [p for p in pnls if p > 0.001]
        loss_pnls = [p for p in pnls if p < -0.001]

        self._summary["resolution_analysis"] = {
            "total": len(ress),
            "avg_btc_move": round(sum(btc_moves) / len(btc_moves), 1) if btc_moves else 0,
            "max_btc_move": round(max(btc_moves), 1) if btc_moves else 0,
            "avg_win_pnl": round(sum(win_pnls) / len(win_pnls), 4) if win_pnls else 0,
            "avg_loss_pnl": round(sum(loss_pnls) / len(loss_pnls), 4) if loss_pnls else 0,
            "biggest_win": round(max(win_pnls), 4) if win_pnls else 0,
            "biggest_loss": round(min(loss_pnls), 4) if loss_pnls else 0,
            "cumulative_pnl": [round(sum(pnls[: i + 1]), 4) for i in range(len(pnls))],
        }

        self._summary["resolutions_detail"] = [
            _extract(r, [("slug", ""), ("pnl", 0), ("btc_move", 0), ("resolution", "")]) for r in ress
        ]

    def _enrich_live_trading(self) -> None:
        lt = self._dd.get("live_trading")
        if lt:
            self._summary["trading_mode"] = "dry_run" if lt.get("dry_run") else "live"
            self._summary["live_trading"] = _extract(
                lt,
                [
                    ("mode", "live"),
                    ("dry_run", False),
                    ("wallet_balance", 0),
                    ("shadow_paper_pnl", 0),
                    ("execution_cost", 0),
                ],
            )
        elif "trading_mode" not in self._summary:
            self._summary["trading_mode"] = self._dd.get("trading_mode", "paper")

    def _enrich_observations(self) -> None:
        assert self._archive_dir is not None
        obs_file = self._archive_dir / "data" / "knowledge" / "observations.jsonl"
        if not obs_file.exists():
            return
        observations = []
        for line in obs_file.read_text().splitlines():
            if line.strip():
                try:
                    rec = json.loads(line)
                    observations.append(_extract(rec, [("category", ""), ("text", ""), ("timestamp", "")]))
                except json.JSONDecodeError:
                    pass
        self._summary["observations"] = observations

    def _enrich_session_history(self) -> None:
        assert self._archive_dir is not None
        sh_file = self._archive_dir / "data" / "knowledge" / "session_history.md"
        if sh_file.exists():
            self._summary["session_history"] = sh_file.read_text()

    def _enrich_candle_snapshots(self) -> None:
        assert self._archive_dir is not None
        db_path = self._archive_dir / "logs" / "polybot.db"
        if not db_path.exists():
            return
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
                self._summary["candle_snapshots"] = candle_snapshots
        except Exception:
            pass
