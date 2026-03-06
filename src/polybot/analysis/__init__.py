"""Analysis package — replay, validation, and reporting tools."""

from polybot.analysis.engine import (
    build_decision_timeline,
    compute_ob_stats,
    fillability_scan,
    generate_insights,
    live_order_telemetry,
    post_cancel_recovery,
)
from polybot.analysis.replay import render_aggregate_summary, render_report, replay_all_candles, replay_candle

__all__ = [
    # engine — pure analysis functions
    "build_decision_timeline",
    "compute_ob_stats",
    "fillability_scan",
    "generate_insights",
    "live_order_telemetry",
    "post_cancel_recovery",
    # replay — orchestration & rendering
    "render_aggregate_summary",
    "render_report",
    "replay_all_candles",
    "replay_candle",
]
