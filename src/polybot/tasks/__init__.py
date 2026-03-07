"""Tasks package — event-driven trading tasks and extracted helpers.

The main entry point is `AIDecision`, the event-driven AI decision maker.
Pure helper modules extracted from the original monolith are re-exported here.
"""

from polybot.tasks.ai_decision import AIDecision
from polybot.tasks.context_builder import (
    append_section,
    build_chainlink_warning,
    build_counter_trend_advisory,
    build_stop_loss_warning,
    build_velocity_conflict_warning,
    format_ml_line,
)
from polybot.tasks.decision_guards import (
    apply_anti_flip,
    apply_confidence_gate,
    apply_entry_price_cap,
    apply_position_sizing,
    apply_single_entry,
    apply_velocity_conflict_scaling,
    clamp_sell_size,
    compute_position_scale,
    force_exit_side,
    override_to_hold,
)
from polybot.tasks.prompt_context import (
    VelocityConflict,
    compute_btc_trajectory,
    compute_entry_timing_stats,
    compute_retracement_context,
    detect_velocity_magnitude_conflict,
    format_microstructure,
)
from polybot.tasks.trade_logger import build_decision_row, build_trade_record

__all__ = [
    # Core task
    "AIDecision",
    # Context builder
    "append_section",
    "build_chainlink_warning",
    "build_counter_trend_advisory",
    "build_stop_loss_warning",
    "build_velocity_conflict_warning",
    "format_ml_line",
    # Decision guards
    "apply_anti_flip",
    "apply_confidence_gate",
    "apply_entry_price_cap",
    "apply_position_sizing",
    "apply_single_entry",
    "apply_velocity_conflict_scaling",
    "clamp_sell_size",
    "compute_position_scale",
    "force_exit_side",
    "override_to_hold",
    # Prompt context
    "VelocityConflict",
    "compute_btc_trajectory",
    "compute_entry_timing_stats",
    "compute_retracement_context",
    "detect_velocity_magnitude_conflict",
    "format_microstructure",
    # Trade logger
    "build_decision_row",
    "build_trade_record",
]
