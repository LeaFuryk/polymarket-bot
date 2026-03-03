"""AI decision task — event-driven, makes trades when triggered.

Waits on ai_trigger_event (entry opportunity) or exit_trigger_queue
(stop-loss/take-profit). Contains the core decision logic extracted
from the old _run_cycle().
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from polybot.calibration import ConfidenceCalibrator
from polybot.config import AppConfig
from polybot.decision_engine.engine import DecisionEngine
from polybot.exit_tracker import ExitTracker
from polybot.indicators import (
    FeatureConfig,
    IndicatorResult,
    SessionContext,
    compute_indicators,
    format_indicators,
)
from polybot.knowledge import KnowledgeManager
from polybot.ml_scorer import MLScorer
from polybot.models import (
    Action,
    CandleMarket,
    FeatureVector,
    OrderType,
    ResolutionRecord,
    TokenSide,
    TradeRecord,
    TradingDecision,
)
from polybot.adaptive_entry import AdaptiveEntryTracker
from polybot.execution.live import LiveExecutionEngine
from polybot.prefilter import PreFilter
from polybot.shared_state import EntryContext, PreFilterSnapshot
from polybot.resolution import ResolutionTracker
from polybot.risk.manager import RiskManager
from polybot.shared_state import SharedState
from polybot.simulator.engine import ExecutionSimulator
from polybot.simulator.orderbook import SimulatedOrderBook
from polybot.simulator.portfolio import Portfolio
from polybot.logging.trade_log import TradeLog

logger = logging.getLogger(__name__)


def _compute_btc_trajectory(history: list[PreFilterSnapshot]) -> str | None:
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
    vel_dir = "accelerating" if abs(current_vel) > abs(earlier_vel) * 1.2 else "decelerating" if abs(current_vel) < abs(earlier_vel) * 0.8 else "steady"
    parts = [
        f"## BTC Trajectory (intra-candle)",
        f"- Velocity: ${current_vel:+.1f}/s ({vel_dir}, was ${earlier_vel:+.1f}/s)",
    ]
    if abs(drawback) >= 5.0:
        parts.append(f"- Peak drawback: peak was ${peak:+,.0f} from open, now ${current_move:+,.0f} (pulled back ${drawback:.0f})")
    else:
        parts.append(f"- No significant drawback (peak ${peak:+,.0f}, current ${current_move:+,.0f})")

    return "\n".join(parts)


def _compute_retracement_context(
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
        f"## Reversal Analysis (from per-second data)",
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


def _format_microstructure(history: list) -> str | None:
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
    spread_dir = "widening" if (spread_up_delta + spread_down_delta) > 0.002 else "narrowing" if (spread_up_delta + spread_down_delta) < -0.002 else "stable"

    # Volatility trend (BTC range per candle)
    ranges = [h.btc_range for h in history]
    avg_range = sum(ranges) / len(ranges)
    range_dir = "increasing" if recent.btc_range > avg_range * 1.2 else "decreasing" if recent.btc_range < avg_range * 0.8 else "stable"

    parts = [
        f"## Cross-Candle Microstructure (last {len(history)} candles)",
        f"- Spreads: {spread_dir} (UP avg {recent.avg_spread_up:.2%}, DOWN avg {recent.avg_spread_down:.2%})",
        f"- BTC intra-candle range: ${recent.btc_range:.0f} ({range_dir}, avg ${avg_range:.0f})",
    ]

    return "\n".join(parts)


def _compute_entry_timing_stats(
    session_trades: list,
    resolutions: list,
) -> str | None:
    """Compute win rate by entry-time bucket from this session's resolved trades.

    Returns a formatted prompt section showing WR per time-remaining bucket,
    or None if fewer than 3 resolved BUY trades exist.
    """
    # Build resolution lookup by slug
    res_by_slug: dict[str, object] = {}
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
        parts.append(
            f"- Best bucket: {best_bucket} ({best_wr:.0%} WR) "
            f"\u2014 consider patience on marginal setups"
        )

    return "\n".join(parts)


class AIDecision:
    """Event-driven AI decision maker."""

    def __init__(
        self,
        config: AppConfig,
        shared: SharedState,
        decision_engine: DecisionEngine,
        execution_sim: ExecutionSimulator,
        orderbook: SimulatedOrderBook,
        portfolio: Portfolio,
        risk: RiskManager,
        trade_log: TradeLog,
        prefilter: PreFilter,
        calibrator: ConfidenceCalibrator,
        exit_tracker: ExitTracker,
        ml_scorer: MLScorer,
        knowledge_manager: KnowledgeManager,
        feature_config: FeatureConfig,
        resolution_tracker: ResolutionTracker,
        # Mutable state references from agent
        recent_resolutions: list[ResolutionRecord],
        recent_trades: list[TradeRecord],
        session_trades: list[TradeRecord],
        pending_ml_features: dict[str, dict[str, float]],
        adaptive_entry: AdaptiveEntryTracker | None = None,
        live_engine: LiveExecutionEngine | None = None,
        shadow_portfolio: Portfolio | None = None,
    ) -> None:
        self._config = config
        self._shared = shared
        self._engine = decision_engine
        self._exec_sim = execution_sim
        self._orderbook = orderbook
        self._portfolio = portfolio
        self._risk = risk
        self._trade_log = trade_log
        self._prefilter = prefilter
        self._calibrator = calibrator
        self._exit_tracker = exit_tracker
        self._ml_scorer = ml_scorer
        self._knowledge = knowledge_manager
        self._feature_config = feature_config
        self._resolution_tracker = resolution_tracker
        self._adaptive_entry = adaptive_entry

        # Live trading engine (None in paper mode)
        self._live_engine = live_engine
        self._shadow_portfolio = shadow_portfolio
        self._live_mode = live_engine is not None

        # Optional SQLite analytics
        self._datastore = None  # set by agent if sqlite_enabled

        # Shared mutable state from agent
        self._recent_resolutions = recent_resolutions
        self._recent_trades = recent_trades
        self._session_trades = session_trades
        self._pending_ml_features = pending_ml_features

        # Optional callback for WS trade event push
        self.on_trade_callback = None  # set by agent: Callable[[TradeRecord], Awaitable[None]]

        # Track sold sides per candle to block side-flips (sell A → buy B)
        self._sold_sides: dict[str, set[str]] = {}  # slug → {UP, DOWN}
        # Track bought sides per candle to prevent double-entry on same side
        self._bought_sides: dict[str, set[str]] = {}  # slug → {UP, DOWN}

        # Internal counters (synced to agent via shared references)
        self._cycle_count = 0
        self._total_api_cost: float = 0.0
        self._contrarian_flip_active = False
        self._reversal_flip_side: str | None = None  # "up"/"down" during reversal retracement
        self._last_cycle_api_cost: float = 0.0

        # Session stats (agent reads these)
        self.session_wins: int = 0
        self.session_losses: int = 0
        self.session_resolution_pnl: float = 0.0

        # Dashboard state (agent reads these)
        self.last_action: str = "—"
        self.last_reasoning: str = ""
        self.last_risk_status: str = "OK"
        self.last_token_side: str = ""

        # Per-cycle screen tracking (None=no screen, True=passed, False=rejected)
        self._last_screen_passed: bool | None = None

        # Ensemble disagreement tracking
        self._screen_calls: int = 0
        self._screen_passes: int = 0  # Haiku said "trade"
        self._sonnet_trades: int = 0  # Sonnet actually traded after Haiku pass
        self._ml_sonnet_agree: int = 0  # ML and Sonnet picked same direction
        self._ml_sonnet_total: int = 0  # total decisions where both had a direction

    @property
    def total_api_cost(self) -> float:
        return self._total_api_cost

    @total_api_cost.setter
    def total_api_cost(self, value: float) -> None:
        self._total_api_cost = value

    @property
    def last_cycle_api_cost(self) -> float:
        return self._last_cycle_api_cost

    async def run(self) -> None:
        """Main loop — waits for triggers, makes decisions."""
        logger.info("AIDecision task started")
        while not self._shared.shutdown:
            try:
                # Wait for either AI trigger or exit trigger
                trigger_type = await self._wait_for_trigger()
                if trigger_type is None:
                    continue

                if self._shared.rotation_in_progress:
                    continue

                if trigger_type == "entry":
                    await self._handle_entry_trigger()
                elif trigger_type == "exit":
                    await self._handle_exit_trigger()

            except Exception:
                logger.exception("AIDecision error")
                await asyncio.sleep(1)

        logger.info("AIDecision task stopped")

    async def _wait_for_trigger(self) -> str | None:
        """Wait for an entry or exit trigger. Returns trigger type or None."""
        # Check exit queue first (non-blocking)
        try:
            exit_signal = self._shared.exit_trigger_queue.get_nowait()
            self._pending_exit = exit_signal
            return "exit"
        except asyncio.QueueEmpty:
            pass

        # Wait for entry trigger with timeout (so we can check exit queue periodically)
        try:
            await asyncio.wait_for(
                self._shared.ai_trigger_event.wait(),
                timeout=2.0,
            )
            self._shared.ai_trigger_event.clear()
            return "entry"
        except asyncio.TimeoutError:
            return None

    async def _handle_entry_trigger(self) -> None:
        """Handle an entry opportunity trigger from the market monitor."""
        # Record call time immediately to prevent MarketMonitor from
        # re-triggering during the async Haiku/Sonnet call
        self._record_ai_call_time()

        self._last_screen_passed = None  # Reset per cycle
        self._cycle_count += 1
        cycle = self._cycle_count
        logger.info("=== AI Decision Cycle %d (trigger: %s) ===", cycle, self._shared.ai_trigger_reason)

        snapshot = self._shared.latest_snapshot
        market = self._shared.current_market
        if snapshot is None or market is None:
            self.last_action = "SKIP (no data)"
            return

        time_remaining = market.time_remaining()
        buffer = self._config.agent.resolution_buffer_seconds
        if time_remaining < buffer:
            self.last_action = f"SKIP ({time_remaining:.0f}s to resolution)"
            return

        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook
        up_mid = up_ob.midpoint
        down_mid = down_ob.midpoint

        # Mark-to-market
        if up_mid is not None:
            self._portfolio.mark_to_market(up_mid, down_mid)
        portfolio_value = self._portfolio.total_value_at_market(up_mid or 0.5, down_mid)
        self._risk.update_portfolio_peak(portfolio_value)

        # Check pending limit order fills
        limit_fills = self._orderbook.check_fills(up_ob)
        for fill in limit_fills:
            self._portfolio.apply_fill(fill, TokenSide.UP)
            pnl = 0.0
            if fill.side.value == "SELL":
                pnl = (fill.fill_price - self._portfolio.up_position.avg_entry_price) * fill.size
            self._risk.record_trade(pnl, fill.fee_amount)
            logger.info("Limit fill: %s %.2f @ %.4f", fill.side.value, fill.size, fill.fill_price)

        # Pre-trade risk checks
        pre_checks = self._risk.pre_trade_checks(snapshot)
        pre_failed = [c for c in pre_checks if not c.passed]
        if pre_failed:
            reasons = "; ".join(c.reason for c in pre_failed)
            logger.warning("Pre-trade risk blocked: %s", reasons)
            self.last_action = "BLOCKED (pre-trade)"
            self.last_risk_status = reasons
            self._log_cycle(cycle, snapshot, risk_blocked=True, risk_reason=reasons)
            return

        await self._run_ai_decision(cycle, snapshot, market, time_remaining, portfolio_value)

    async def _handle_exit_trigger(self) -> None:
        """Handle a stop-loss/take-profit exit trigger from position monitor."""
        exit_signal = self._pending_exit
        self._cycle_count += 1
        cycle = self._cycle_count
        token_side_str = exit_signal.get("token_side", "up")
        reason = exit_signal.get("reason", "unknown")
        pnl_pct = exit_signal.get("pnl_pct", 0.0)
        logger.info(
            "=== AI Exit Decision Cycle %d (SL/TP: %s %s, P&L=%.1f%%) ===",
            cycle, token_side_str, reason, pnl_pct * 100,
        )

        # Exit trigger cooldown: skip if on cooldown and not a true emergency (> -30%)
        # Reversal retracement bypasses cooldown — it's time-sensitive
        trigger_type = exit_signal.get("trigger_type", "")
        cooldown = self._config.monitor.ai_cooldown_seconds
        elapsed = time.time() - self._shared.ai_last_call_time
        if elapsed < cooldown and pnl_pct > -0.30 and trigger_type != "reversal_retracement":
            logger.info(
                "Exit trigger on cooldown (%.0fs < %.0fs, pnl=%.1f%% > -30%%) — skipping",
                elapsed, cooldown, pnl_pct * 100,
            )
            return

        snapshot = self._shared.latest_snapshot
        market = self._shared.current_market
        if snapshot is None or market is None:
            return

        time_remaining = market.time_remaining()

        # Guard against selling winners near expiry: if position is profitable
        # and BTC direction matches position side and < 120s remaining, skip exit
        if pnl_pct > 0 and time_remaining < 120 and trigger_type != "reversal_retracement":
            btc_price_now = snapshot.btc_price.price_usd if snapshot.btc_price else None
            candle_open = self._shared.candle_open_btc
            if btc_price_now is not None and candle_open is not None:
                btc_diff = btc_price_now - candle_open
                btc_favors_up = btc_diff >= 0
                position_is_up = token_side_str.lower() == "up"
                direction_matches = (position_is_up and btc_favors_up) or (
                    not position_is_up and not btc_favors_up
                )
                if direction_matches:
                    logger.info(
                        "Skipping exit on winning %s position (P&L=%.1f%%, BTC %s$%.0f, "
                        "%.0fs left) — let it ride to resolution",
                        token_side_str, pnl_pct * 100,
                        "+" if btc_diff >= 0 else "", btc_diff, time_remaining,
                    )
                    return

        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook
        up_mid = up_ob.midpoint
        down_mid = down_ob.midpoint

        if up_mid is not None:
            self._portfolio.mark_to_market(up_mid, down_mid)
        portfolio_value = self._portfolio.total_value_at_market(up_mid or 0.5, down_mid)

        # Add exit context to the AI call
        sold_up = token_side_str.lower() == "up"
        opposite_side = "DOWN" if sold_up else "UP"

        if trigger_type == "reversal_retracement":
            # Single AI call: HOLD (keep position) or BUY opposite (auto-close + flip)
            # Compute rich retracement analytics from per-second prefilter history
            retracement_ctx = _compute_retracement_context(
                list(self._shared.prefilter_history),
                token_side_str,
                snapshot,
            )

            opp_ob = snapshot.down_orderbook if sold_up else snapshot.orderbook
            opp_ask = opp_ob.best_ask
            opp_line = f"- {opposite_side} ask: ${opp_ask:.2f}\n" if opp_ask else ""
            exit_context = (
                f"\n## REVERSAL RETRACEMENT — HOLD OR FLIP?\n"
                f"- Position: {token_side_str.upper()}\n"
                f"- Current P&L: {pnl_pct:+.1%}\n"
                f"{opp_line}"
                f"{retracement_ctx}\n"
                f"\n### Decision Guide\n"
                f"- The RETRACEMENT PATTERN is the signal — do NOT evaluate the current BTC move as a standalone entry.\n"
                f"- Zero crossing (BTC moved to opposite side) = strong flip signal.\n"
                f"- Accelerating retreat + time since peak > 30s = likely real reversal.\n"
                f"- Decelerating retreat or very recent peak = likely pullback, consider HOLD.\n"
                f"- **HOLD** = keep position open, stop-loss remains active.\n"
                f"- **BUY {opposite_side}** = close {token_side_str.upper()} and flip to {opposite_side}.\n"
            )
            # Set flag so anti-hedge auto-closes current position instead of blocking
            self._reversal_flip_side = token_side_str.lower()
            self._contrarian_flip_active = True
            try:
                await self._run_ai_decision(
                    cycle, snapshot, market, time_remaining, portfolio_value,
                    extra_context=exit_context,
                    # No forced_exit_side — AI chooses HOLD or BUY opposite
                )
            finally:
                self._reversal_flip_side = None
                self._contrarian_flip_active = False
        else:
            exit_context = (
                f"\n## EXIT TRIGGER\n"
                f"- Token: {token_side_str.upper()}\n"
                f"- Reason: {reason}\n"
                f"- Current P&L: {pnl_pct:+.1%}\n"
                f"- Action needed: Evaluate whether to SELL this position NOW.\n"
            )

            await self._run_ai_decision(
                cycle, snapshot, market, time_remaining, portfolio_value,
                extra_context=exit_context,
                forced_exit_side=token_side_str,
            )

            # Safeguard #3: Record stop-loss exit for cooldown warning
            if trigger_type == "stop_loss":
                self._shared.last_stop_loss = {
                    "token_side": token_side_str,
                    "pnl_pct": pnl_pct,
                    "timestamp": time.time(),
                }

            # --- Contrarian flip (post-SL only) ---
            # After SL, if position closed and BTC confirms reversal,
            # trigger a second AI call for the opposite side.
            if trigger_type == "stop_loss":
                pos = (self._portfolio.up_position if sold_up
                       else self._portfolio.down_position)
                if pos.shares <= 0:
                    await self._try_contrarian_flip(token_side_str, pnl_pct, trigger_type)

    async def _try_contrarian_flip(
        self,
        token_side_str: str,
        pnl_pct: float,
        trigger_type: str,
    ) -> None:
        """After exiting a position, evaluate buying the opposite side.

        Triggered after stop-loss or reversal-retracement exits. Checks that
        BTC confirms the reversal and enough time remains, then calls AI to
        decide BUY or HOLD. The anti-flip guard is bypassed for this call.
        """
        snap = self._shared.latest_snapshot
        mkt = self._shared.current_market
        if snap is None or mkt is None:
            return

        tr = mkt.time_remaining()
        btc_now = snap.btc_price.price_usd if snap.btc_price else None
        candle_open = self._shared.candle_open_btc

        # Determine opposite side and its ask price
        sold_up = token_side_str.lower() == "up"
        opposite_side = "DOWN" if sold_up else "UP"
        opp_ob = snap.down_orderbook if sold_up else snap.orderbook
        opp_ask = opp_ob.best_ask

        # BTC confirms reversal: move is against the sold position
        btc_confirms = False
        btc_move = 0.0
        if btc_now is not None and candle_open is not None:
            btc_move = btc_now - candle_open
            # If we sold UP, BTC should be dropping (btc_move < 0)
            # If we sold DOWN, BTC should be rising (btc_move > 0)
            btc_confirms = (sold_up and btc_move < 0) or (not sold_up and btc_move > 0)

        # Log skip reasons for debugging
        skip_reasons = []
        if tr < 60:
            skip_reasons.append(f"time={tr:.0f}s<60s")
        if not btc_confirms:
            skip_reasons.append(f"BTC {'$' if btc_move >= 0 else '-$'}{abs(btc_move):.0f} doesn't confirm reversal")

        if skip_reasons:
            logger.info("Contrarian flip: skip — %s", ", ".join(skip_reasons))
            return

        reason_label = "stop-loss" if trigger_type == "stop_loss" else "reversal exit"
        logger.info(
            "Contrarian flip: triggering %s entry after %s (BTC %s$%.0f, %s ask=$%.2f, %.0fs left)",
            opposite_side, reason_label,
            "+" if btc_move >= 0 else "", btc_move,
            opposite_side, opp_ask or 0, tr,
        )
        flip_context = (
            f"\n## CONTRARIAN FLIP OPPORTUNITY\n"
            f"- Just exited {token_side_str.upper()} at {pnl_pct:+.1%} ({reason_label})\n"
            f"- BTC reversed: ${btc_move:+.0f} from candle open\n"
            f"- {opposite_side} ask = ${opp_ask:.2f}\n"
            f"- Consider buying {opposite_side} to recover — the reversal is confirmed.\n"
        )
        # Re-read portfolio value
        up_mid2 = snap.orderbook.midpoint
        down_mid2 = snap.down_orderbook.midpoint
        if up_mid2 is not None:
            self._portfolio.mark_to_market(up_mid2, down_mid2)
        pv = self._portfolio.total_value_at_market(up_mid2 or 0.5, down_mid2)

        self._contrarian_flip_active = True
        try:
            self._cycle_count += 1
            await self._run_ai_decision(
                self._cycle_count, snap, mkt, tr, pv,
                extra_context=flip_context,
            )
        finally:
            self._contrarian_flip_active = False

    async def _auto_close_for_flip(
        self,
        close_side: str,  # "up" or "down"
        market: CandleMarket | None,
        time_remaining: float,
        snapshot,
        cycle: int = 0,
    ) -> bool:
        """Auto-close a position as part of reversal flip. Returns True if closed."""
        token_side = TokenSide.UP if close_side == "up" else TokenSide.DOWN
        position = self._portfolio.get_position(token_side)
        if position.shares <= 0:
            return True

        ob = snapshot.orderbook if close_side == "up" else snapshot.down_orderbook
        sell_decision = TradingDecision(
            action=Action.SELL,
            order_type=OrderType.MARKET,
            size=position.shares,
            confidence=0.5,
            reasoning="Auto-close for reversal flip",
            market_view="",
            token_side=token_side,
        )

        fill = None
        if self._live_mode and self._live_engine:
            live_result = await self._live_engine.execute(sell_decision, ob)
            fill = live_result.fill if live_result else None
            paper_fill = self._exec_sim.execute(sell_decision, ob)
            if paper_fill and self._shadow_portfolio:
                self._shadow_portfolio.apply_fill(paper_fill, token_side)
        else:
            fill = self._exec_sim.execute(sell_decision, ob)

        if not fill:
            logger.warning("Reversal flip: failed to close %s position", close_side.upper())
            return False

        self._portfolio.apply_fill(fill, token_side)
        realized = (fill.fill_price - position.avg_entry_price) * fill.size
        self._risk.record_trade(realized, fill.fee_amount)

        if market:
            self._exit_tracker.register_exit(
                slug=market.slug,
                token_side=token_side.value,
                entry_price=position.avg_entry_price,
                exit_price=fill.fill_price,
                exit_size=fill.size,
                time_remaining=time_remaining,
            )
            self._sold_sides.setdefault(market.slug, set()).add(token_side.value)

        self._shared.entry_context.pop(token_side.value, None)
        self._shared.dynamic_sl.pop(token_side.value, None)
        self._shared.dynamic_tp.pop(token_side.value, None)

        logger.info(
            "Reversal flip: auto-closed %s (%.1f shares @ $%.4f, P&L $%.2f)",
            close_side.upper(), fill.size, fill.fill_price, realized,
        )
        self._log_cycle(cycle, snapshot, decision=sell_decision, fill=fill)
        return True

    async def _run_ai_decision(
        self,
        cycle: int,
        snapshot,
        market: CandleMarket,
        time_remaining: float,
        portfolio_value: float,
        extra_context: str = "",
        forced_exit_side: str | None = None,
    ) -> None:
        """Core AI decision logic — shared between entry and exit triggers."""
        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook
        up_mid = up_ob.midpoint
        down_mid = down_ob.midpoint

        candle_open_btc = self._shared.candle_open_btc

        # Build feature vector
        features = FeatureVector(
            market=snapshot,
            position=self._portfolio.position,
            up_position=self._portfolio.up_position,
            down_position=self._portfolio.down_position,
            risk=self._risk.state,
            portfolio_cash=self._portfolio.cash,
            portfolio_total_value=portfolio_value,
            cycle_number=cycle,
            time_remaining=time_remaining,
        )

        exit_summary = self._exit_tracker.get_summary()
        calibration_summary = self._calibrator.get_calibration_summary()
        if exit_summary:
            calibration_summary = calibration_summary + "\n" + exit_summary

        feedback_context = self._knowledge.build_feedback_context(
            self._recent_resolutions,
            self.session_wins,
            self.session_losses,
            self.session_resolution_pnl,
            calibration_summary=calibration_summary,
            recent_trades=self._recent_trades,
        )
        if extra_context:
            feedback_context = extra_context + "\n" + feedback_context

        # Compute indicators
        self._feature_config.load()
        session_ctx = SessionContext(
            wins=self.session_wins,
            losses=self.session_losses,
            candle_open_btc=candle_open_btc,
        )
        indicator_results = compute_indicators(snapshot, self._feature_config, session_ctx)
        indicators_text = format_indicators(indicator_results)

        # ML prediction
        btc_price_val = snapshot.btc_price.price_usd if snapshot.btc_price else None
        ml_features = self._ml_scorer.extract_features(
            candles=snapshot.btc_candles,
            btc_price=btc_price_val,
            candle_open=candle_open_btc,
            up_mid=up_mid,
            down_mid=down_mid,
            up_bid_depth=snapshot.orderbook.bid_depth,
            up_ask_depth=snapshot.orderbook.ask_depth,
            reversal_rate=self._adaptive_entry.rolling_reversal_rate if self._adaptive_entry else 0.0,
        )
        ml_prediction = self._ml_scorer.predict(ml_features)
        if market:
            self._pending_ml_features[market.slug] = ml_features

        if ml_prediction.model_trained:
            # Show top 3 feature drivers so the AI knows WHY the ML predicts a direction
            top_feats = sorted(
                ml_prediction.feature_contributions.items(),
                key=lambda x: abs(x[1]),
                reverse=True,
            )[:3]
            drivers = ", ".join(f"{n}: {v:+.2f}" for n, v in top_feats)
            ml_line = (
                f"- ML Baseline: {ml_prediction.up_probability:.0%} UP probability "
                f"({ml_prediction.confidence}) — drivers: {drivers}"
            )
        else:
            ml_line = f"- ML Baseline: {self._ml_scorer.get_summary()}"
        if indicators_text:
            indicators_text += "\n" + ml_line
        else:
            indicators_text = "## Computed Indicators\n" + ml_line

        # Inject adaptive entry reversal context (visible to both Haiku screen and Sonnet)
        if self._adaptive_entry is not None:
            # Compute abs BTC move for UNCERTAIN regime gating
            abs_btc_move = 0.0
            if candle_open_btc is not None and snapshot.btc_price:
                abs_btc_move = abs(snapshot.btc_price.price_usd - candle_open_btc)
            reversal_ctx = self._adaptive_entry.get_ai_context(abs_btc_move=abs_btc_move)
            if reversal_ctx:
                indicators_text = indicators_text + "\n\n" + reversal_ctx if indicators_text else reversal_ctx

        # Inject BTC trajectory (velocity + peak drawback) from prefilter snapshots
        trajectory_ctx = _compute_btc_trajectory(list(self._shared.prefilter_history))
        if trajectory_ctx:
            indicators_text = indicators_text + "\n\n" + trajectory_ctx if indicators_text else trajectory_ctx

        # Cross-candle microstructure memory
        micro_ctx = _format_microstructure(self._shared.microstructure_history)
        if micro_ctx:
            indicators_text = indicators_text + "\n\n" + micro_ctx if indicators_text else micro_ctx

        # Entry timing performance (WR by time-remaining bucket)
        timing_ctx = _compute_entry_timing_stats(self._session_trades, self._recent_resolutions)
        if timing_ctx:
            indicators_text = indicators_text + "\n\n" + timing_ctx if indicators_text else timing_ctx

        # Safeguard #1: Chainlink divergence warning
        if snapshot.btc_price and snapshot.btc_price.price_divergence is not None:
            divergence = snapshot.btc_price.price_divergence
            if abs(divergence) > 100:
                chainlink_warning = (
                    f"\n\n## CHAINLINK DIVERGENCE WARNING\n"
                    f"Chainlink vs Binance divergence: ${divergence:+.0f} — "
                    f"resolution source may differ significantly.\n"
                    f"Consider reducing confidence. Trades near candle boundaries are especially risky."
                )
                indicators_text = indicators_text + chainlink_warning if indicators_text else chainlink_warning

        # Safeguard #6: Counter-trend accuracy context
        trend_result = next(
            (r for r in indicator_results if r.name == "Market Trend"), None,
        )
        if trend_result and abs(trend_result.value) >= 0.3:
            weak_side = "DOWN" if trend_result.value > 0 else "UP"
            trend_label = "BULLISH" if trend_result.value > 0 else "BEARISH"
            counter_trend_advisory = (
                f"\n\n## Counter-Trend Advisory\n"
                f"Strong {trend_label} trend detected (score={trend_result.value:+.2f}). "
                f"{weak_side} trades are counter-trend.\n"
                f"Historical counter-trend accuracy: ~55-60% (vs ~75% trend-aligned).\n"
                f"If going counter-trend, require higher conviction and use smaller size."
            )
            indicators_text = indicators_text + counter_trend_advisory if indicators_text else counter_trend_advisory

        # Safeguard #3: Post-stop-loss cooldown warning
        if self._shared.last_stop_loss is not None:
            sl_info = self._shared.last_stop_loss
            sl_warning = (
                f"\n\n## POST-STOP-LOSS WARNING\n"
                f"A stop-loss exit just occurred on this candle "
                f"({sl_info['token_side'].upper()} at {sl_info['pnl_pct']:+.1%}).\n"
                f"Re-entering immediately is high-risk — the price moved against you and may continue.\n"
                f"If you choose to re-enter, use smaller size and higher conviction threshold."
            )
            indicators_text = indicators_text + sl_warning if indicators_text else sl_warning

        # Two-pass screening (entry only, not exits)
        has_position = (
            self._portfolio.up_position.shares > 0
            or self._portfolio.down_position.shares > 0
        )
        if self._config.ai.two_pass_enabled and not has_position and not extra_context:
            should_trade, screen_reason, screen_cost = await self._engine.screen(
                features, indicators_text=indicators_text,
                candle_open_btc=candle_open_btc,
            )
            self._portfolio.cash -= screen_cost
            self._total_api_cost += screen_cost
            self._last_cycle_api_cost = screen_cost
            self._screen_calls += 1

            if not should_trade:
                self._last_screen_passed = False
                self.last_action = f"HOLD (screen: {screen_reason[:60]})"
                self.last_reasoning = screen_reason
                # Build a lightweight decision so reasoning + screen context
                # are captured in the trade record for the dashboard
                from polybot.decision_engine.prompts import format_screening_context
                screen_input = format_screening_context(
                    features, indicators_text, candle_open_btc=candle_open_btc,
                )
                screen_decision = TradingDecision(
                    action=Action.HOLD,
                    order_type=OrderType.MARKET,
                    size=0.0,
                    confidence=0.0,
                    reasoning=screen_reason,
                    market_view="",
                    token_side=TokenSide.UP,
                )
                self._log_cycle(
                    cycle, snapshot, decision=screen_decision,
                    risk_blocked=False, risk_reason="",
                    screen_input=screen_input,
                )
                return

            self._last_screen_passed = True
            self._screen_passes += 1
            # Pass screening reasoning to Sonnet — free "second opinion" context
            indicators_text += f"\n\n## Pre-Screening Note (fast model)\n{screen_reason}"

        # Full AI decision
        decision, latency_ms, api_cost = await self._engine.decide(
            features, feedback_context=feedback_context, indicators_text=indicators_text,
            ai_cycle_cost=self._last_cycle_api_cost, ai_session_cost=self._total_api_cost,
            candle_open_btc=candle_open_btc,
        )

        self._portfolio.cash -= api_cost
        self._total_api_cost += api_cost
        self._last_cycle_api_cost = api_cost
        logger.info("API cost: $%.4f (session total: $%.4f)", api_cost, self._total_api_cost)

        # Ensemble tracking: ML vs Sonnet direction agreement
        if decision.action == Action.BUY and ml_prediction.model_trained:
            self._sonnet_trades += 1
            ml_dir = "up" if ml_prediction.up_probability > 0.5 else "down"
            sonnet_dir = decision.token_side.value
            self._ml_sonnet_total += 1
            if ml_dir == sonnet_dir:
                self._ml_sonnet_agree += 1
            else:
                logger.info(
                    "Ensemble disagreement: ML=%s (%.0f%%) vs Sonnet=%s (conf=%.2f)",
                    ml_dir, ml_prediction.up_probability * 100,
                    sonnet_dir, decision.confidence,
                )

        # Clamp sell size to actual held shares (fixes rounding bug where
        # position sizing creates fractional shares like 30.6 but the AI
        # sees "31 shares" due to :.0f formatting and requests sell 31)
        if decision.action == Action.SELL:
            held = self._portfolio.get_position(decision.token_side).shares
            if decision.size > held and held > 0:
                logger.info(
                    "Clamping sell size: %.2f → %.2f (held) for %s",
                    decision.size, held, decision.token_side.value,
                )
                decision = TradingDecision(
                    action=decision.action,
                    order_type=decision.order_type,
                    size=held,
                    confidence=decision.confidence,
                    reasoning=decision.reasoning,
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                    hypothetical_direction=decision.hypothetical_direction,
                    confidence_drivers=decision.confidence_drivers,
                )

        # Force token_side on exit triggers: don't trust AI's token_side for SELLs
        # This prevents the anti-flip guard from tracking the wrong side
        if forced_exit_side and decision.action == Action.SELL:
            correct_side = TokenSide(forced_exit_side.lower())
            if decision.token_side != correct_side:
                logger.warning(
                    "Forcing exit token_side: AI said %s but exit trigger is %s",
                    decision.token_side.value, correct_side.value,
                )
                decision = TradingDecision(
                    action=decision.action,
                    order_type=decision.order_type,
                    size=decision.size,
                    confidence=decision.confidence,
                    reasoning=decision.reasoning,
                    market_view=decision.market_view,
                    token_side=correct_side,
                    hypothetical_direction=decision.hypothetical_direction,
                    confidence_drivers=decision.confidence_drivers,
                )

        # Hard confidence gate (BUY only)
        min_conf = self._config.agent.min_confidence
        if decision.action == Action.BUY and decision.confidence < min_conf:
            logger.info(
                "Overriding %s to HOLD — confidence %.2f < %.2f",
                decision.action.value, decision.confidence, min_conf,
            )
            decision = TradingDecision(
                action=Action.HOLD,
                order_type=OrderType.MARKET,
                size=0.0,
                confidence=decision.confidence,
                reasoning=f"Overridden: confidence {decision.confidence:.2f} below {min_conf}. "
                          f"Original: {decision.reasoning[:100]}",
                market_view=decision.market_view,
                token_side=decision.token_side,
                hypothetical_direction=decision.hypothetical_direction,
                confidence_drivers=decision.confidence_drivers,
            )

        # Calibration gate (BUY only)
        if decision.action == Action.BUY:
            cal = self._calibrator.check(decision.confidence)
            if cal.is_reliable and not cal.should_trade:
                logger.info(
                    "Calibration override to HOLD — stated %.2f but actual %.0f%%",
                    decision.confidence, cal.calibrated_win_rate * 100,
                )
                decision = TradingDecision(
                    action=Action.HOLD,
                    order_type=OrderType.MARKET,
                    size=0.0,
                    confidence=decision.confidence,
                    reasoning=f"Calibration override: {cal.reason}. Original: {decision.reasoning[:80]}",
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                    hypothetical_direction=decision.hypothetical_direction,
                    confidence_drivers=decision.confidence_drivers,
                )

        # Anti-hedging guard: don't buy one side while holding the other
        # When _reversal_flip_side is set, auto-close the held position instead of blocking
        if decision.action == Action.BUY:
            if decision.token_side == TokenSide.DOWN and self._portfolio.up_position.shares > 0:
                if self._reversal_flip_side:
                    closed = await self._auto_close_for_flip("up", market, time_remaining, snapshot, cycle)
                    if not closed:
                        decision = TradingDecision(
                            action=Action.HOLD,
                            order_type=OrderType.MARKET,
                            size=0.0,
                            confidence=decision.confidence,
                            reasoning=f"Reversal flip: failed to close UP position. Original: {decision.reasoning[:80]}",
                            market_view=decision.market_view,
                            token_side=decision.token_side,
                            hypothetical_direction=decision.hypothetical_direction,
                            confidence_drivers=decision.confidence_drivers,
                        )
                else:
                    logger.info(
                        "Anti-hedge block: skipping DOWN buy while holding %.1f UP shares",
                        self._portfolio.up_position.shares,
                    )
                    decision = TradingDecision(
                        action=Action.HOLD,
                        order_type=OrderType.MARKET,
                        size=0.0,
                        confidence=decision.confidence,
                        reasoning=f"Anti-hedge: holding UP shares, blocked DOWN buy. Original: {decision.reasoning[:80]}",
                        market_view=decision.market_view,
                        token_side=decision.token_side,
                        hypothetical_direction=decision.hypothetical_direction,
                        confidence_drivers=decision.confidence_drivers,
                    )
            elif decision.token_side == TokenSide.UP and self._portfolio.down_position.shares > 0:
                if self._reversal_flip_side:
                    closed = await self._auto_close_for_flip("down", market, time_remaining, snapshot, cycle)
                    if not closed:
                        decision = TradingDecision(
                            action=Action.HOLD,
                            order_type=OrderType.MARKET,
                            size=0.0,
                            confidence=decision.confidence,
                            reasoning=f"Reversal flip: failed to close DOWN position. Original: {decision.reasoning[:80]}",
                            market_view=decision.market_view,
                            token_side=decision.token_side,
                            hypothetical_direction=decision.hypothetical_direction,
                            confidence_drivers=decision.confidence_drivers,
                        )
                else:
                    logger.info(
                        "Anti-hedge block: skipping UP buy while holding %.1f DOWN shares",
                        self._portfolio.down_position.shares,
                    )
                    decision = TradingDecision(
                        action=Action.HOLD,
                        order_type=OrderType.MARKET,
                        size=0.0,
                        confidence=decision.confidence,
                        reasoning=f"Anti-hedge: holding DOWN shares, blocked UP buy. Original: {decision.reasoning[:80]}",
                        market_view=decision.market_view,
                        token_side=decision.token_side,
                        hypothetical_direction=decision.hypothetical_direction,
                        confidence_drivers=decision.confidence_drivers,
                    )

        # Anti-flip guard: block buying opposite side after selling on same candle
        # Same-side re-entry (adding back) is still allowed
        # Bypassed during contrarian flip (post-SL reversal entry)
        if decision.action == Action.BUY and market and not self._contrarian_flip_active:
            sold = self._sold_sides.get(market.slug, set())
            opposite = "UP" if decision.token_side == TokenSide.DOWN else "DOWN"
            if opposite in sold:
                logger.info(
                    "Anti-flip block: already sold %s on %s, blocking %s buy",
                    opposite, market.slug, decision.token_side.value,
                )
                decision = TradingDecision(
                    action=Action.HOLD,
                    order_type=OrderType.MARKET,
                    size=0.0,
                    confidence=decision.confidence,
                    reasoning=f"Anti-flip: sold {opposite} on this candle, blocked {decision.token_side.value} buy. Original: {decision.reasoning[:80]}",
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                    hypothetical_direction=decision.hypothetical_direction,
                    confidence_drivers=decision.confidence_drivers,
                )

        # Safeguard #2: Single-entry-per-side — block buying same side twice on same candle
        if decision.action == Action.BUY and market:
            side_key = decision.token_side.value.upper()
            if side_key in self._bought_sides.get(market.slug, set()):
                logger.info(
                    "Single-entry block: already bought %s on %s, overriding to HOLD",
                    side_key, market.slug,
                )
                decision = TradingDecision(
                    action=Action.HOLD,
                    order_type=OrderType.MARKET,
                    size=0.0,
                    confidence=decision.confidence,
                    reasoning=f"Single-entry: already bought {side_key} on this candle. Original: {decision.reasoning[:80]}",
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                    hypothetical_direction=decision.hypothetical_direction,
                    confidence_drivers=decision.confidence_drivers,
                )

        # Entry price hard cap: block entries at $0.85+ (R/R < 0.18, negative avg PnL)
        if decision.action == Action.BUY:
            cap_ob = down_ob if decision.token_side == TokenSide.DOWN else up_ob
            cap_price = cap_ob.best_ask or 0.5
            if cap_price >= 0.85:
                logger.info(
                    "Entry price cap: %s ask $%.2f >= $0.85 (R/R=%.2f), overriding to HOLD",
                    decision.token_side.value, cap_price,
                    (1.0 - cap_price) / cap_price,
                )
                decision = TradingDecision(
                    action=Action.HOLD,
                    order_type=OrderType.MARKET,
                    size=0.0,
                    confidence=decision.confidence,
                    reasoning=f"Entry price cap: ${cap_price:.2f} >= $0.85 (R/R too low). Original: {decision.reasoning[:80]}",
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                    hypothetical_direction=decision.hypothetical_direction,
                    confidence_drivers=decision.confidence_drivers,
                )

        # Extended R/R position sizing (no hard block)
        if decision.action == Action.BUY:
            target_ob = down_ob if decision.token_side == TokenSide.DOWN else up_ob
            est_fill = target_ob.best_ask or 0.5
            reward = 1.0 - est_fill
            risk_val = est_fill
            rr_ratio = reward / risk_val if risk_val > 0 else 0

            # R/R scale — gentle nudge only (0.75-1.0 range)
            # Data shows cheap entries (high R/R) often lose — they're contrarian traps.
            # Expensive entries (low R/R) win ~85% because price reflects conviction.
            # So we don't reward cheap entries with bigger positions.
            if rr_ratio >= 1.0:
                rr_scale = 1.0
            elif rr_ratio >= 0.3:
                rr_scale = 0.75 + 0.25 * (rr_ratio - 0.3) / 0.7  # 75%-100%
            else:
                rr_scale = 0.75  # minimum 75%

            # Move-magnitude scaling (raised floors — small moves still get decent size)
            move_scale = 1.0
            btc_price_now = snapshot.btc_price.price_usd if snapshot.btc_price else None
            btc_move = 0.0
            if candle_open_btc is not None and btc_price_now is not None:
                btc_move = abs(btc_price_now - candle_open_btc)
                if btc_move < 10:
                    move_scale = 0.80
                elif btc_move < 30:
                    move_scale = 0.90
                elif btc_move < 60:
                    move_scale = 1.0

            # Counter-trend size scaling (trend-aware position reduction)
            trend_result = next(
                (r for r in indicator_results if r.name == "Market Trend"), None,
            )
            trend_scale = 1.0
            if trend_result is not None:
                trend_score = trend_result.value
                is_counter = (
                    (decision.token_side == TokenSide.DOWN and trend_score > 0.3)
                    or (decision.token_side == TokenSide.UP and trend_score < -0.3)
                )
                if is_counter:
                    abs_score = abs(trend_score)
                    trend_scale = 0.50 if abs_score >= 0.7 else 0.70
                    trend_label = (
                        "STRONG BULLISH" if trend_score >= 0.5
                        else "BULLISH" if trend_score >= 0.2
                        else "NEUTRAL" if trend_score > -0.2
                        else "BEARISH" if trend_score > -0.5
                        else "STRONG BEARISH"
                    )
                    logger.info(
                        "Counter-trend sizing: %s in %s trend (score=%.2f) → %.0f%%",
                        decision.token_side.value, trend_label, trend_score,
                        trend_scale * 100,
                    )

            combined_scale = rr_scale * move_scale * trend_scale
            if combined_scale < 1.0:
                original_size = decision.size
                scaled_size = round(decision.size * combined_scale, 1)
                if scaled_size >= 1.0:
                    decision = TradingDecision(
                        action=decision.action,
                        order_type=decision.order_type,
                        size=scaled_size,
                        confidence=decision.confidence,
                        reasoning=decision.reasoning,
                        market_view=decision.market_view,
                        token_side=decision.token_side,
                        limit_price=decision.limit_price,
                    )
                    logger.info(
                        "Position sizing: %.1f → %.1f (R/R=%.2f×%.0f%%, move=$%.0f×%.0f%%)",
                        original_size, scaled_size, rr_ratio, rr_scale * 100,
                        btc_move, move_scale * 100,
                    )

            # Enforce minimum position size (lower floor for counter-trend)
            min_shares = 20 if trend_scale < 1.0 else 40
            if decision.size < min_shares:
                logger.info(
                    "Min size floor: %.1f → %d shares%s",
                    decision.size, min_shares,
                    " (counter-trend)" if trend_scale < 1.0 else "",
                )
                decision = TradingDecision(
                    action=decision.action,
                    order_type=decision.order_type,
                    size=min_shares,
                    confidence=decision.confidence,
                    reasoning=decision.reasoning,
                    market_view=decision.market_view,
                    token_side=decision.token_side,
                    limit_price=decision.limit_price,
                )

        # Shadow predictions for HOLD
        if decision.action == Action.HOLD and decision.hypothetical_direction and market:
            self._calibrator.register_shadow(
                market.slug,
                decision.hypothetical_direction,
                decision.confidence,
            )

        self.last_action = f"{decision.action.value} {decision.token_side.value} {decision.size:.1f}"
        self.last_reasoning = decision.reasoning[:120]
        self.last_token_side = decision.token_side.value

        # Post-trade risk checks
        risk_blocked = False
        risk_reason = ""
        if decision.action != Action.HOLD:
            token_position = self._portfolio.get_position(decision.token_side)
            post_checks = self._risk.post_trade_checks(
                decision, token_position,
                self._portfolio.cash, portfolio_value, snapshot,
            )
            post_failed = [c for c in post_checks if not c.passed]
            if post_failed:
                risk_reason = "; ".join(c.reason for c in post_failed)
                logger.warning("Post-trade risk blocked %s %s: %s",
                               decision.action.value, decision.token_side.value, risk_reason)
                self.last_action = f"BLOCKED ({decision.action.value} {decision.token_side.value})"
                self.last_risk_status = risk_reason
                risk_blocked = True

        # Execute (paper_fill is only set in live mode for shadow comparison)
        fill = None
        paper_fill = None
        live_result = None  # LiveOrderResult telemetry (live mode only)
        if not risk_blocked and decision.action != Action.HOLD:
            target_ob = down_ob if decision.token_side == TokenSide.DOWN else up_ob

            if self._live_mode and self._live_engine and decision.order_type == OrderType.MARKET:
                # Live mode: execute on CLOB + shadow paper sim
                live_result = await self._live_engine.execute(decision, target_ob)
                fill = live_result.fill if live_result else None
                paper_fill = self._exec_sim.execute(decision, target_ob)

                # Apply shadow paper fill to shadow portfolio
                if paper_fill and self._shadow_portfolio:
                    self._shadow_portfolio.apply_fill(paper_fill, decision.token_side)

                if fill and paper_fill:
                    drift_pct = ((fill.fill_price - paper_fill.fill_price) / paper_fill.fill_price * 100) if paper_fill.fill_price > 0 else 0
                    logger.info(
                        "Live fill $%.4f vs Paper fill $%.4f (drift %+.1f%%)",
                        fill.fill_price, paper_fill.fill_price, drift_pct,
                    )
                elif not fill and paper_fill:
                    logger.info(
                        "Live SKIPPED but Paper would have filled at $%.4f",
                        paper_fill.fill_price,
                    )

                # Mark unfilled live trades as blocked for dashboard visibility
                if fill is None and not risk_blocked:
                    risk_blocked = True
                    risk_reason = self._live_engine.last_skip_reason or "limit order timeout"
            elif decision.order_type == OrderType.MARKET:
                # Paper mode: execute on simulator only
                fill = self._exec_sim.execute(decision, target_ob)
            elif decision.order_type == OrderType.LIMIT:
                self._orderbook.add_order(decision)

        # Apply fill
        if fill:
            self._portfolio.apply_fill(fill, decision.token_side)
            token_pos = self._portfolio.get_position(decision.token_side)
            realized = 0.0
            if fill.side.value == "SELL":
                realized = (fill.fill_price - token_pos.avg_entry_price) * fill.size
            self._risk.record_trade(realized, fill.fee_amount)

            if decision.action == Action.BUY and market:
                self._calibrator.register_trade(
                    slug=market.slug,
                    confidence=decision.confidence,
                    token_side=decision.token_side.value,
                    entry_price=fill.fill_price,
                )
                # Safeguard #2: Track bought side to block double-entry
                self._bought_sides.setdefault(market.slug, set()).add(
                    decision.token_side.value.upper(),
                )
                # Store entry context for dynamic SL/TP
                btc_move_now = 0.0
                if candle_open_btc and snapshot.btc_price:
                    btc_move_now = snapshot.btc_price.price_usd - candle_open_btc
                self._shared.entry_context[decision.token_side.value] = EntryContext(
                    entry_price=fill.fill_price,
                    entry_time=time.time(),
                    ml_up_probability=ml_prediction.up_probability if ml_prediction.model_trained else 0.5,
                    ml_confidence=ml_prediction.confidence if ml_prediction.model_trained else "neutral",
                    btc_move_at_entry=btc_move_now,
                    reversal_rate_at_entry=self._shared.reversal_rate,
                    confidence_at_entry=decision.confidence,
                )

            if decision.action == Action.SELL and market:
                self._exit_tracker.register_exit(
                    slug=market.slug,
                    token_side=decision.token_side.value,
                    entry_price=token_pos.avg_entry_price,
                    exit_price=fill.fill_price,
                    exit_size=fill.size,
                    time_remaining=time_remaining,
                )
                # Track sold side to block side-flips on this candle
                self._sold_sides.setdefault(market.slug, set()).add(
                    decision.token_side.value,
                )
                # Clear entry context for dynamic SL/TP
                self._shared.entry_context.pop(decision.token_side.value, None)
                self._shared.dynamic_sl.pop(decision.token_side.value, None)
                self._shared.dynamic_tp.pop(decision.token_side.value, None)

        # Post-fill mark-to-market
        if up_mid is not None:
            self._portfolio.mark_to_market(up_mid, down_mid)
        portfolio_value = self._portfolio.total_value_at_market(up_mid or 0.5, down_mid)
        self._risk.update_portfolio_peak(portfolio_value)
        self.last_risk_status = "HALTED" if self._risk.state.is_halted else "OK"

        # Log
        self._log_cycle(
            cycle, snapshot,
            decision=decision, latency_ms=latency_ms,
            fill=fill, risk_blocked=risk_blocked, risk_reason=risk_reason,
            paper_fill=paper_fill, live_result=live_result,
        )

        self._record_ai_call_time()

    def _record_ai_call_time(self) -> None:
        """Record the time of the last AI call for cooldown tracking."""
        self._shared.ai_last_call_time = time.time()

    def _log_cycle(
        self, cycle, snapshot, decision=None, latency_ms=0.0,
        fill=None, risk_blocked=False, risk_reason="",
        paper_fill=None, screen_input=None, live_result=None,
    ) -> None:
        """Log a cycle to trade log and update trade history."""
        ob = snapshot.orderbook
        pos = self._portfolio.position
        mid = ob.midpoint
        down_mid = snapshot.down_orderbook.midpoint

        record = TradeRecord(
            cycle_number=cycle,
            midpoint=ob.midpoint,
            spread=ob.spread,
            spread_pct=ob.spread_pct,
            best_bid=ob.best_bid,
            best_ask=ob.best_ask,
            bid_depth=ob.bid_depth,
            ask_depth=ob.ask_depth,
            last_trade_price=snapshot.last_trade_price,
            btc_price_usd=snapshot.btc_price.price_usd if snapshot.btc_price else None,
            volume_24h=snapshot.volume_24h,
            position_shares=pos.shares,
            position_avg_entry=pos.avg_entry_price,
            cash=self._portfolio.cash,
            portfolio_value=self._portfolio.total_value_at_market(mid or 0.5, down_mid),
            realized_pnl=pos.realized_pnl,
            unrealized_pnl=pos.unrealized_pnl,
            daily_pnl=self._risk.state.daily_pnl,
            risk_halted=self._risk.state.is_halted,
            risk_blocked=risk_blocked,
            risk_block_reason=risk_reason,
        )

        market = self._shared.current_market
        if market:
            record.candle_slug = market.slug
            record.extra["time_remaining"] = market.time_remaining()

        record.extra["screen_passed"] = self._last_screen_passed
        if screen_input:
            record.extra["screen_input"] = screen_input

        if decision:
            record.action = decision.action
            record.order_type = decision.order_type
            record.token_side = decision.token_side
            record.decision_size = decision.size
            record.limit_price = decision.limit_price
            record.confidence = decision.confidence
            record.reasoning = decision.reasoning
            record.market_view = decision.market_view
            record.ai_latency_ms = latency_ms
            record.ai_cost = self._last_cycle_api_cost
            if decision.hypothetical_direction:
                record.extra["hypothetical_direction"] = decision.hypothetical_direction
            if decision.confidence_drivers:
                record.extra["confidence_drivers"] = decision.confidence_drivers
            # Capture opposite-side context for side-selection learning
            if decision.action.value == "BUY":
                if decision.token_side.value == "up":
                    opp_ask = snapshot.down_orderbook.best_ask
                else:
                    opp_ask = snapshot.orderbook.best_ask
                if opp_ask is not None:
                    record.extra["opposite_ask"] = round(opp_ask, 4)
                record.extra["signal_type"] = self._shared.signal_type
                record.extra["reversal_rate"] = round(self._shared.reversal_rate, 2)

        if fill:
            record.fill_price = fill.fill_price
            record.fill_size = fill.size
            record.slippage_bps = fill.slippage_bps
            record.fee_amount = fill.fee_amount

        if paper_fill:
            record.paper_fill_price = paper_fill.fill_price
            record.paper_total_cost = paper_fill.total_cost

        if live_result:
            # Override limit_price with the actual submitted limit price
            record.limit_price = live_result.limit_price
            # Store full telemetry blob (excluding the nested fill to avoid duplication)
            record.extra["live_order"] = live_result.model_dump(exclude={"fill"})

        self._trade_log.write(record)

        # Queue decision for SQLite analytics
        if self._datastore is not None and self._datastore.current_candle_id is not None:
            self._queue_decision(cycle, snapshot, decision, latency_ms, fill, risk_blocked, risk_reason, live_result=live_result)

        self._recent_trades.append(record)
        if len(self._recent_trades) > 50:
            del self._recent_trades[:-50]
        self._session_trades.append(record)

        # Push trade event to WS clients
        if self.on_trade_callback is not None:
            try:
                await self.on_trade_callback(record)
            except Exception:
                logger.debug("on_trade_callback failed", exc_info=True)

    def _queue_decision(
        self, cycle, snapshot, decision=None, latency_ms=0.0,
        fill=None, risk_blocked=False, risk_reason="",
        live_result=None,
    ) -> None:
        """Build a DecisionRow and queue it for SQLite analytics."""
        import json
        from polybot.datastore import DecisionRow

        # Compute indicators for the decision context
        indicators_dict: dict = {}
        try:
            self._feature_config.load()
            session_ctx = SessionContext(
                wins=self.session_wins,
                losses=self.session_losses,
                candle_open_btc=self._shared.candle_open_btc,
            )
            results = compute_indicators(snapshot, self._feature_config, session_ctx)
            indicators_dict = {
                r.name: {"value": r.value, "label": r.label}
                for r in results
            }
        except Exception:
            logger.debug("Indicator computation failed for decision", exc_info=True)

        row = DecisionRow(
            candle_id=self._datastore.current_candle_id,
            timestamp=time.time(),
            cycle=cycle,
            trigger_type="entry",
            action=decision.action.value if decision else "HOLD",
            token_side=decision.token_side.value if decision else "up",
            confidence=decision.confidence if decision else 0.0,
            reasoning=decision.reasoning if decision else "",
            market_view=decision.market_view if decision else "",
            decision_size=decision.size if decision else 0.0,
            fill_price=fill.fill_price if fill else None,
            fill_size=fill.size if fill else None,
            slippage_bps=fill.slippage_bps if fill else None,
            fee_amount=fill.fee_amount if fill else 0.0,
            risk_blocked=risk_blocked,
            risk_reason=risk_reason,
            cash=self._portfolio.cash,
            portfolio_value=self._portfolio.total_value,
            up_shares=self._portfolio.up_position.shares,
            down_shares=self._portfolio.down_position.shares,
            ai_cost=self._last_cycle_api_cost,
            ai_latency_ms=latency_ms,
            indicators_json=json.dumps(indicators_dict) if indicators_dict else "{}",
            live_order_json=json.dumps(live_result.model_dump(exclude={"fill"})) if live_result else "",
        )
        self._datastore.queue_decision(row)
