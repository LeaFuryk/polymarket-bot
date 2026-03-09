"""Rotation manager — market discovery and candle transitions."""

from __future__ import annotations

import logging
import statistics
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.agent.context import AgentContext
    from polybot.models import CandleMarket

from polybot.shared_state import CandleMicrostructure


class RotationManager:
    """Discovers markets and handles candle transitions."""

    def __init__(self, ctx: AgentContext, logger: logging.Logger | None = None) -> None:
        self._ctx = ctx
        self._log = logger or logging.getLogger(__name__)

    async def discover_market(self) -> CandleMarket | None:
        """Discover the current candle market, handling rotation and outages."""
        ctx = self._ctx
        new_market = await ctx.discovery.get_current_market()
        if new_market is None:
            new_market = await ctx.discovery.get_next_market()

        if new_market is None:
            ctx.discovery_failures += 1
            if ctx.discovery_failures >= 3 and ctx.outage_start is None:
                ctx.outage_start = time.time()
                self._log.warning(
                    "Polymarket outage detected: %d consecutive discovery failures",
                    ctx.discovery_failures,
                )
            elif ctx.outage_start is not None:
                elapsed = time.time() - ctx.outage_start
                if ctx.discovery_failures % 12 == 0:  # every ~60s
                    self._log.warning(
                        "Polymarket outage ongoing: %.0fs elapsed (%d failures)",
                        elapsed,
                        ctx.discovery_failures,
                    )
            return ctx.current_market

        # Market found — clear outage state
        recovering_from_outage = ctx.outage_start is not None
        if recovering_from_outage:
            duration = time.time() - ctx.outage_start
            ctx.last_outage_duration = duration
            ctx.outage_recovered = time.time()
            self._log.info(
                "Polymarket outage recovered after %.0fs (%d failures)",
                duration,
                ctx.discovery_failures,
            )
        ctx.discovery_failures = 0
        ctx.outage_start = None
        # Clear recovery banner after 60s
        if ctx.outage_recovered and time.time() - ctx.outage_recovered > 60:
            ctx.outage_recovered = None

        # Check if market has rotated
        if ctx.current_market and new_market.condition_id != ctx.current_market.condition_id:
            if recovering_from_outage:
                # After outage: skip resolution of missed candles — just jump to new market
                self._log.info(
                    "Post-outage recovery: skipping resolution of %s, jumping to %s",
                    ctx.current_market.slug,
                    new_market.slug,
                )
                # Cancel any stale orders from the pre-outage market
                cancelled = ctx.orderbook.cancel_all()
                if cancelled:
                    self._log.info("Cancelled %d stale orders from pre-outage market", cancelled)
            else:
                self._log.info(
                    "Market rotation: %s → %s",
                    ctx.current_market.slug,
                    new_market.slug,
                )
                await self._handle_market_transition()

        if ctx.current_market is None or new_market.condition_id != ctx.current_market.condition_id:
            ctx.current_market = new_market
            ctx.market_data.set_market(new_market)

            # Update shared state
            ctx.shared.current_market = new_market

            # Set token IDs on live engine for CLOB orders
            if ctx.live_engine:
                ctx.live_engine.set_current_token_ids(
                    new_market.up_token_id,
                    new_market.down_token_id,
                )

            self._log.info("Active market: %s (ends in %.0fs)", new_market.title, new_market.time_remaining())

            # Record BTC price at candle open
            btc_snapshot = await ctx.market_data.btc_feed.get_price()
            if btc_snapshot:
                ctx.resolution_tracker.record_candle_open(new_market, btc_snapshot.price_usd)
                ctx.shared.candle_open_btc = btc_snapshot.price_usd

                # Begin candle in SQLite analytics
                if ctx.datastore is not None:
                    ctx.datastore.begin_candle(
                        condition_id=new_market.condition_id,
                        slug=new_market.slug,
                        title=new_market.title,
                        start_time=new_market.start_time,
                        end_time=new_market.end_time,
                        btc_open=btc_snapshot.price_usd,
                    )

                # Begin candle in persistent market history
                ctx.market_history.begin_candle(
                    condition_id=new_market.condition_id,
                    slug=new_market.slug,
                    start_time=new_market.start_time,
                    end_time=new_market.end_time,
                    btc_open=btc_snapshot.price_usd,
                )

        return ctx.current_market

    async def _handle_market_transition(self) -> None:
        """Handle transition between candle markets — resolve winner via BTC price."""
        from polybot.agent.state import StatePersistence

        ctx = self._ctx

        # Pause other tasks during rotation
        ctx.shared.rotation_in_progress = True

        try:
            # Cancel pending limit orders
            cancelled = ctx.orderbook.cancel_all()
            if cancelled:
                self._log.info("Cancelled %d pending orders on market rotation", cancelled)

            # Cancel live CLOB orders on rotation
            if ctx.live_mode and ctx.live_engine:
                await ctx.live_engine.cancel_all_orders()

            # Resolve candle winner
            if ctx.current_market is not None:
                btc_snapshot = await ctx.market_data.btc_feed.get_price()
                btc_price = btc_snapshot.price_usd if btc_snapshot else 0.0

                resolution = await ctx.resolution_tracker.resolve(
                    ctx.current_market,
                    btc_price,
                )

                resolution_pnl = ctx.portfolio.resolve_market(resolution.winner)
                resolution.total_pnl = resolution_pnl
                resolution.up_pnl = ctx.portfolio.up_position.realized_pnl
                resolution.down_pnl = ctx.portfolio.down_position.realized_pnl

                # Shadow portfolio resolution (live mode)
                if ctx.shadow_portfolio is not None:
                    shadow_pnl = ctx.shadow_portfolio.resolve_market(resolution.winner)
                    self._log.info(
                        "Shadow paper PnL: $%.4f | Live PnL: $%.4f | Diff: $%.4f",
                        shadow_pnl,
                        resolution_pnl,
                        resolution_pnl - shadow_pnl,
                    )

                ctx.trade_log.write_resolution(resolution)
                ctx.last_resolution = resolution

                ctx.calibrator.record_outcome(resolution.slug, resolution.winner)
                ctx.exit_tracker.record_outcome(resolution.slug, resolution.winner)
                ctx.adaptive_entry.record_outcome(
                    slug=resolution.slug,
                    winner=resolution.winner,
                    btc_open=resolution.btc_open,
                    btc_close=resolution.btc_close,
                    prefilter_history=list(ctx.shared.prefilter_history),
                )

                # Train ML model
                ml_feats = ctx.pending_ml_features.pop(resolution.slug, None)
                if ml_feats:
                    ctx.ml_scorer.train(ml_feats, up_won=(resolution.winner == "up"))

                # Update session stats
                had_position = resolution_pnl != 0.0
                if had_position:
                    if resolution_pnl > 0:
                        ctx.session_wins += 1
                    else:
                        ctx.session_losses += 1
                    ctx.session_resolution_pnl += resolution_pnl

                # Resolve candle in SQLite analytics
                if ctx.datastore is not None and ctx.datastore.current_candle_id is not None:
                    ctx.datastore.resolve_candle(
                        candle_id=ctx.datastore.current_candle_id,
                        btc_close=resolution.btc_close,
                        winner=resolution.winner,
                        resolution_pnl=resolution_pnl,
                    )

                # Resolve candle in persistent market history
                if ctx.market_history.current_candle_id is not None:
                    ctx.market_history.resolve_candle(
                        candle_id=ctx.market_history.current_candle_id,
                        btc_close=resolution.btc_close,
                        winner=resolution.winner,
                    )

                # Sync stats to AI decision task
                if ctx.ai_decision:
                    ctx.ai_decision.session_wins = ctx.session_wins
                    ctx.ai_decision.session_losses = ctx.session_losses
                    ctx.ai_decision.session_resolution_pnl = ctx.session_resolution_pnl

                # Sync stats to SharedState for indicator computation in MarketMonitor
                ctx.shared.session_wins = ctx.session_wins
                ctx.shared.session_losses = ctx.session_losses

                self._log.info(
                    "Resolution: %s winner=%s pnl=%.4f | Session: W%d/L%d total_pnl=%.4f",
                    resolution.slug,
                    resolution.winner,
                    resolution_pnl,
                    ctx.session_wins,
                    ctx.session_losses,
                    ctx.session_resolution_pnl,
                )

                ctx.recent_resolutions.append(resolution)
                ctx.session_resolutions.append(resolution)  # uncapped — for dashboard

                # Push resolution event to WS clients
                if ctx.ws_broadcaster and ctx.ws_broadcaster.has_clients:
                    await ctx.ws_broadcaster.broadcast(ctx.ws_broadcaster.build_resolution_event(resolution))

                if len(ctx.recent_resolutions) > 20:
                    ctx.recent_resolutions[:] = ctx.recent_resolutions[-20:]

                ctx.resolutions_since_reflection += 1
                StatePersistence(logger=self._log).save_agent_state(ctx)

                # Adaptive reflection: faster when losing, normal when profitable
                recent_pnl = sum(r.total_pnl for r in ctx.recent_resolutions[-5:])
                reflection_threshold = 5 if recent_pnl < -10.0 else 10

                if ctx.resolutions_since_reflection >= reflection_threshold:
                    self._log.info(
                        "Triggering reflection after %d resolutions (threshold=%d, recent_pnl=$%.2f)",
                        ctx.resolutions_since_reflection,
                        reflection_threshold,
                        recent_pnl,
                    )
                    ctx.resolutions_since_reflection = 0
                    await ctx.knowledge_manager.reflect(
                        ctx.recent_resolutions,
                        ctx.recent_trades,
                    )
                    reflection_cost = ctx.knowledge_manager.last_reflection_cost
                    if reflection_cost > 0:
                        ctx.portfolio.cash -= reflection_cost
                        ctx.total_api_cost += reflection_cost
                        if ctx.ai_decision:
                            ctx.ai_decision.total_api_cost = ctx.total_api_cost
                        self._log.info(
                            "Reflection API cost: $%.4f (session total: $%.4f)",
                            reflection_cost,
                            ctx.total_api_cost,
                        )

            # Reset positions and triggers for new market
            ctx.portfolio.reset_positions()
            if ctx.shadow_portfolio is not None:
                ctx.shadow_portfolio.reset_positions()
            # Save microstructure summary before clearing
            self._save_candle_microstructure()

            # Reset shared state for new candle
            ctx.shared.candle_open_btc = None
            ctx.shared.position_pnl_pct.clear()
            ctx.shared.prefilter_history.clear()
            ctx.shared.last_stop_loss = None
            ctx.shared.entry_context.clear()
            ctx.shared.dynamic_sl.clear()
            ctx.shared.dynamic_tp.clear()

        finally:
            ctx.shared.rotation_in_progress = False

    def _save_candle_microstructure(self) -> None:
        """Compute and save microstructure summary from current candle's prefilter history."""
        ctx = self._ctx
        history = list(ctx.shared.prefilter_history)
        if len(history) < 10:
            return

        spreads_up = [s.up_spread_pct for s in history if s.up_spread_pct is not None]
        spreads_down = [s.down_spread_pct for s in history if s.down_spread_pct is not None]
        moves = [s.btc_move_from_open for s in history]

        btc_range = max(moves) - min(moves) if moves else 0.0
        btc_final_move = moves[-1] if moves else 0.0

        # Zero crossings: count sign changes in BTC move (skip noise < $1)
        crossings = 0
        for i in range(1, len(moves)):
            if moves[i - 1] * moves[i] < 0 and abs(moves[i]) >= 1.0 and abs(moves[i - 1]) >= 1.0:
                crossings += 1

        # Reversal intensity: 0 = directional, 1 = full whipsaw
        if btc_range > 1.0:
            rev_intensity = 1.0 - abs(btc_final_move) / btc_range
        else:
            rev_intensity = 0.0

        summary = CandleMicrostructure(
            timestamp=time.time(),
            avg_spread_up=statistics.mean(spreads_up) if spreads_up else 0.0,
            avg_spread_down=statistics.mean(spreads_down) if spreads_down else 0.0,
            avg_depth=0.0,  # filled from snapshot if available
            avg_imbalance=1.0,
            btc_range=btc_range,
            btc_final_move=btc_final_move,
            zero_crossings=crossings,
            reversal_intensity=rev_intensity,
        )

        ctx.shared.microstructure_history.append(summary)
        # Keep last 5 candles
        if len(ctx.shared.microstructure_history) > 5:
            ctx.shared.microstructure_history = ctx.shared.microstructure_history[-5:]
