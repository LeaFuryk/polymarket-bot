"""Position monitor task — tracks P&L, triggers stop-loss/take-profit exits.

Runs every 1 second. Uses cached snapshot data (no API calls).
Pushes exit signals to the exit_trigger_queue when SL/TP thresholds are hit.

Dynamic SL/TP: computes adaptive thresholds from 5 factors (time, regime,
BTC velocity, ML alignment, entry price quality). Tighter when signals say
"you're wrong", wider when "market is noisy but you're likely right".
"""

from __future__ import annotations

import asyncio
import logging
import time

from polybot.config import AppConfig
from polybot.shared_state import EntryContext, SharedState
from polybot.simulator.portfolio import Portfolio

logger = logging.getLogger(__name__)


class PositionMonitor:
    """Monitors open positions and triggers SL/TP exits."""

    def __init__(
        self,
        config: AppConfig,
        shared: SharedState,
        portfolio: Portfolio,
    ) -> None:
        self._config = config
        self._shared = shared
        self._portfolio = portfolio
        self._interval = config.monitor.position_monitor_interval
        self._stop_loss_pct = config.monitor.stop_loss_pct
        self._take_profit_pct = config.monitor.take_profit_pct

        # Track which positions have already triggered (avoid re-triggering)
        self._triggered: dict[str, str] = {}  # token_side -> trigger_type

    async def run(self) -> None:
        """Main loop — checks positions every second."""
        logger.info(
            "PositionMonitor started (SL=%.0f%%, TP=+%.0f%%, dynamic_sl=%s, dynamic_tp=%s)",
            self._stop_loss_pct * 100,
            self._take_profit_pct * 100,
            self._config.monitor.dynamic_sl_enabled,
            self._config.monitor.dynamic_tp_enabled,
        )
        while not self._shared.shutdown:
            if self._shared.rotation_in_progress:
                await asyncio.sleep(0.2)
                continue

            try:
                await self._tick()
            except Exception:
                logger.debug("PositionMonitor tick error", exc_info=True)

            await asyncio.sleep(self._interval)

        logger.info("PositionMonitor stopped")

    def reset_triggers(self) -> None:
        """Reset triggered state on candle rotation."""
        self._triggered.clear()

    async def _tick(self) -> None:
        """Check P&L on open positions."""
        snapshot = self._shared.latest_snapshot
        if snapshot is None:
            return

        up_mid = snapshot.orderbook.midpoint
        down_mid = snapshot.down_orderbook.midpoint

        # Update mark-to-market
        if up_mid is not None:
            self._portfolio.mark_to_market(up_mid, down_mid)

        # Check UP position
        up_pos = self._portfolio.up_position
        if up_pos.shares > 0 and up_pos.avg_entry_price > 0:
            current_price = up_mid or 0.5
            pnl_pct = (current_price - up_pos.avg_entry_price) / up_pos.avg_entry_price
            self._shared.position_pnl_pct["up"] = pnl_pct
            await self._check_thresholds("up", pnl_pct)
        else:
            self._shared.position_pnl_pct.pop("up", None)
            self._triggered.pop("up", None)

        # Check DOWN position
        down_pos = self._portfolio.down_position
        if down_pos.shares > 0 and down_pos.avg_entry_price > 0:
            current_price = down_mid or 0.5
            pnl_pct = (current_price - down_pos.avg_entry_price) / down_pos.avg_entry_price
            self._shared.position_pnl_pct["down"] = pnl_pct
            await self._check_thresholds("down", pnl_pct)
        else:
            self._shared.position_pnl_pct.pop("down", None)
            self._triggered.pop("down", None)

    # --- BTC Velocity Helper ---

    def _btc_velocity(self, token_side: str) -> tuple[float, bool]:
        """Compute BTC velocity and whether it favors the position.

        Returns (velocity_magnitude, favors_position).
        velocity is the rate of change in btc_move_from_open over last ~10s.
        """
        history = list(self._shared.prefilter_history)
        if len(history) < 10:
            return 0.0, True  # no data → neutral

        recent = history[-1]
        earlier = history[-10]
        velocity = (recent.btc_move_from_open - earlier.btc_move_from_open) / 10.0

        # UP position benefits from positive BTC move, DOWN from negative
        if token_side == "up":
            favors = velocity >= 0
        else:
            favors = velocity <= 0

        return abs(velocity), favors

    # --- ML Alignment Helper ---

    def _ml_alignment_adj(self, token_side: str, ctx: EntryContext) -> float:
        """Compute ML alignment adjustment from entry context.

        ML agreed with position side → widen (give room).
        ML disagreed → tighten (less room for error).
        """
        prob = ctx.ml_up_probability
        if ctx.ml_confidence == "neutral":
            return 0.0

        if token_side == "up":
            if prob > 0.55:
                return -0.04  # ML agreed → widen 4%
            elif prob < 0.45:
                return 0.05  # ML disagreed → tighten 5%
        else:  # down
            if prob < 0.45:
                return -0.04  # ML agreed with DOWN → widen 4%
            elif prob > 0.55:
                return 0.05  # ML disagreed → tighten 5%

        return 0.0

    # --- Dynamic Stop-Loss (5 factors) ---

    def _dynamic_stop_loss(self, token_side: str) -> float:
        """Compute adaptive stop-loss from 5 factors.

        Factor 1: Time weighting (existing base — tighter near expiry)
        Factor 2: Regime (reversal rate → momentum tightens, choppy widens)
        Factor 3: BTC velocity (against position → tighten, favors → widen)
        Factor 4: ML alignment at entry (agreed → widen, disagreed → tighten)
        Factor 5: Entry price quality (expensive → tighten, cheap → widen)

        Returns a negative float (e.g., -0.45 for -45% SL).
        Falls back to time-weighted-only when dynamic_sl_enabled is false.
        """
        market = self._shared.current_market
        if market is None:
            return self._stop_loss_pct

        time_remaining = market.time_remaining()

        # Factor 1: Time-weighted base (preserved from existing logic)
        if time_remaining >= 240:
            time_sl = self._stop_loss_pct
        else:
            time_factor = max(0.0, min(1.0, time_remaining / 240.0))
            tight_stop = -0.20
            time_sl = tight_stop + (self._stop_loss_pct - tight_stop) * time_factor

        if not self._config.monitor.dynamic_sl_enabled:
            return time_sl

        # Factor 2: Regime (reversal rate)
        regime_adj = 0.0
        rr = self._shared.reversal_rate
        if rr > 0:  # have data
            if rr < 0.35:
                # MOMENTUM: drawdowns are real → tighten
                regime_adj = (0.35 - rr) / 0.35 * 0.12
            elif rr > 0.55:
                # CHOPPY: whipsaws expected → widen
                regime_adj = -((rr - 0.55) / 0.45 * 0.08)

        # Factor 3: BTC velocity
        vel_adj = 0.0
        vel_mag, favors = self._btc_velocity(token_side)
        if favors:
            vel_adj = -min(0.06, vel_mag / 25.0)  # widen up to 6%
        else:
            vel_adj = min(0.08, vel_mag / 15.0)  # tighten up to 8%

        # Factors 4 & 5: ML alignment + Entry price (need EntryContext)
        ml_adj = 0.0
        price_adj = 0.0
        ctx = self._shared.entry_context.get(token_side)
        if ctx is not None:
            # Factor 4: ML alignment
            ml_adj = self._ml_alignment_adj(token_side, ctx)

            # Factor 5: Entry price quality
            ep = ctx.entry_price
            if ep >= 0.75:
                price_adj = 0.06  # expensive → tighten 6%
            elif ep >= 0.60:
                price_adj = 0.03  # moderately expensive → tighten 3%
            elif ep <= 0.30:
                price_adj = -0.15  # very cheap → widen 15% (huge % swings are normal)
            elif ep <= 0.40:
                price_adj = -0.10  # cheap → widen 10%

        # Combine: positive adjustments = tighter (less negative SL), negative = wider
        raw_sl = time_sl + regime_adj + vel_adj + ml_adj + price_adj
        sl_floor = self._config.monitor.sl_floor
        sl_ceiling = self._config.monitor.sl_ceiling
        final_sl = max(sl_floor, min(sl_ceiling, raw_sl))

        # Store for dashboard
        self._shared.dynamic_sl[token_side] = final_sl

        return final_sl

    # --- Dynamic Take-Profit (3 adjustments) ---

    def _dynamic_take_profit(self, token_side: str) -> float:
        """Compute adaptive take-profit from time + 3 factors.

        Base: time-weighted TP (full TP with time, reduced near expiry)
        Adj 1: Regime (momentum → let winners run, choppy → take profits)
        Adj 2: BTC velocity (favors → raise TP, against → lower TP)
        Adj 3: Entry price (expensive → lower TP, cheap → raise TP)

        Returns a positive float (e.g., 0.60 for +60% TP).
        Falls back to static take_profit_pct when dynamic_tp_enabled is false.
        """
        if not self._config.monitor.dynamic_tp_enabled:
            return self._take_profit_pct

        market = self._shared.current_market
        if market is None:
            return self._take_profit_pct

        time_remaining = market.time_remaining()
        base_tp = self._take_profit_pct

        # Time-weighted base TP
        if time_remaining >= 180:
            time_tp = base_tp
        elif time_remaining >= 60:
            time_tp = base_tp * (0.60 + 0.40 * (time_remaining - 60) / 120.0)
        else:
            time_tp = base_tp * 0.40

        # Adjustment 1: Regime
        regime_adj = 0.0
        rr = self._shared.reversal_rate
        if rr > 0:
            if rr < 0.35:
                regime_adj = 0.10  # MOMENTUM → let winners run
            elif rr > 0.55:
                regime_adj = -0.15  # CHOPPY → take profits early

        # Adjustment 2: BTC velocity
        vel_adj = 0.0
        vel_mag, favors = self._btc_velocity(token_side)
        if favors:
            vel_adj = min(0.10, vel_mag / 20.0)  # accelerating in favor → raise TP
        else:
            vel_adj = -min(0.10, vel_mag / 20.0)  # turning against → lower TP

        # Adjustment 3: Entry price
        price_adj = 0.0
        ctx = self._shared.entry_context.get(token_side)
        if ctx is not None:
            ep = ctx.entry_price
            if ep > 0.70:
                price_adj = -0.15  # expensive → lower TP (less room to grow)
            elif ep < 0.40:
                price_adj = 0.10  # cheap → raise TP (more room to grow)

        # Combine
        raw_tp = time_tp + regime_adj + vel_adj + price_adj
        tp_floor = self._config.monitor.tp_floor
        tp_ceiling = self._config.monitor.tp_ceiling
        final_tp = max(tp_floor, min(tp_ceiling, raw_tp))

        # Store for dashboard
        self._shared.dynamic_tp[token_side] = final_tp

        return final_tp

    # --- Threshold Check ---

    def _btc_favors_position(self, token_side: str) -> bool:
        """Check if current BTC direction favors the position.

        UP position wins when BTC is above open, DOWN when below.
        If BTC favors the bet, a token price drop is likely orderbook
        noise — not a real loss — so stop-loss should be suppressed.
        """
        history = list(self._shared.prefilter_history)
        if not history:
            return False  # no data → don't suppress
        btc_move = history[-1].btc_move_from_open
        if token_side == "up":
            return btc_move > 0
        else:
            return btc_move < 0

    async def _check_thresholds(self, token_side: str, pnl_pct: float) -> None:
        """Check if P&L has hit stop-loss or take-profit thresholds."""
        if token_side in self._triggered:
            return  # Already triggered for this position

        dynamic_sl = self._dynamic_stop_loss(token_side)
        dynamic_tp = self._dynamic_take_profit(token_side)

        if pnl_pct <= dynamic_sl:
            # Suppress SL if BTC direction still favors the position —
            # the token price drop is orderbook noise, not a real loss
            if self._btc_favors_position(token_side):
                logger.info(
                    "SL suppressed: %s P&L=%.1f%% hit SL %.1f%% but BTC favors position",
                    token_side.upper(),
                    pnl_pct * 100,
                    dynamic_sl * 100,
                )
                return

            # Build component breakdown for log
            components = self._sl_components_str(token_side)
            logger.warning(
                "STOP-LOSS triggered: %s P&L=%.1f%% <= %.1f%% [%s]",
                token_side.upper(),
                pnl_pct * 100,
                dynamic_sl * 100,
                components,
            )
            self._triggered[token_side] = "stop_loss"
            await self._shared.exit_trigger_queue.put(
                {
                    "token_side": token_side,
                    "reason": f"stop_loss ({pnl_pct:+.1%}, dynamic SL={dynamic_sl:+.0%})",
                    "pnl_pct": pnl_pct,
                    "trigger_type": "stop_loss",
                }
            )

        # Reversal retracement: BTC retraced 80%+ from peak toward open
        # Triggers AI to decide: HOLD (SL stays active) or SELL + flip
        if "reversal" not in self._triggered.get(token_side, ""):
            # Minimum 30s hold time — early BTC noise can cross zero and
            # trigger a premature flip that guarantees a loss on the first leg
            entry_ctx = self._shared.entry_context.get(token_side)
            if entry_ctx and (time.time() - entry_ctx.entry_time) < 30:
                return  # Too early — let the position develop

            history = list(self._shared.prefilter_history)
            if len(history) >= 10:
                # Compute peak move in the position's favored direction
                if token_side == "up":
                    peak_move = max(s.btc_move_from_open for s in history)
                    current_move = history[-1].btc_move_from_open
                else:
                    peak_move = min(s.btc_move_from_open for s in history)
                    current_move = history[-1].btc_move_from_open

                # Need a meaningful peak ($25+) before checking retracement
                if abs(peak_move) >= 25.0:
                    # Retracement ratio: how much of the peak has been given back
                    # 0.0 = still at peak, 1.0 = back to open, >1.0 = crossed zero
                    if peak_move != 0:
                        retracement = 1.0 - (current_move / peak_move)
                    else:
                        retracement = 0.0

                    if retracement >= 0.80:
                        components = self._sl_components_str(token_side)
                        logger.info(
                            "REVERSAL RETRACEMENT: %s peak=$%+.0f, now=$%+.0f, retraced %.0f%% [%s]",
                            token_side.upper(),
                            peak_move,
                            current_move,
                            retracement * 100,
                            components,
                        )
                        self._triggered[token_side] = "reversal_retracement"
                        await self._shared.exit_trigger_queue.put(
                            {
                                "token_side": token_side,
                                "reason": (
                                    f"reversal_retracement (peak=${peak_move:+.0f}, "
                                    f"now=${current_move:+.0f}, {retracement:.0%} retraced)"
                                ),
                                "pnl_pct": pnl_pct,
                                "trigger_type": "reversal_retracement",
                            }
                        )
                        return  # Don't also check TP on same tick

        elif pnl_pct >= dynamic_tp:
            logger.info(
                "TAKE-PROFIT triggered: %s P&L=+%.1f%% >= +%.1f%% (dynamic TP)",
                token_side.upper(),
                pnl_pct * 100,
                dynamic_tp * 100,
            )
            self._triggered[token_side] = "take_profit"
            await self._shared.exit_trigger_queue.put(
                {
                    "token_side": token_side,
                    "reason": f"take_profit ({pnl_pct:+.1%}, dynamic TP=+{dynamic_tp:.0%})",
                    "pnl_pct": pnl_pct,
                    "trigger_type": "take_profit",
                }
            )

    def _sl_components_str(self, token_side: str) -> str:
        """Build a short string showing SL factor breakdown for logging."""
        market = self._shared.current_market
        parts = []

        if market:
            tr = market.time_remaining()
            parts.append(f"time={tr:.0f}s")

        rr = self._shared.reversal_rate
        if rr > 0:
            parts.append(f"rr={rr:.2f}")

        regime = self._shared.regime
        parts.append(f"regime={regime}")

        vel_mag, favors = self._btc_velocity(token_side)
        if vel_mag > 0.01:
            parts.append(f"vel={'fav' if favors else 'agn'} {vel_mag:.1f}")

        ctx = self._shared.entry_context.get(token_side)
        if ctx:
            parts.append(f"entry=${ctx.entry_price:.2f}")
            parts.append(f"ml={ctx.ml_confidence}")

        return ", ".join(parts)
