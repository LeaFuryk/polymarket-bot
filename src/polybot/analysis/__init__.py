"""Analysis package — replay, validation, and reporting tools."""

from polybot.analysis.deep import (
    analyze_entry_quality,
    analyze_flips,
    analyze_losses,
    analyze_missed_opportunities,
    analyze_side_accuracy,
    analyze_timing,
    analyze_trends,
    generate_recommendations,
)
from polybot.analysis.deep_report import build_deep_report, render_deep_report, write_markdown_report
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
    # deep_report — report builder, rendering, and markdown output
    "build_deep_report",
    "render_deep_report",
    "write_markdown_report",
    # deep — post-run analysis functions
    "analyze_entry_quality",
    "analyze_flips",
    "analyze_losses",
    "analyze_missed_opportunities",
    "analyze_side_accuracy",
    "analyze_timing",
    "analyze_trends",
    "generate_recommendations",
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
