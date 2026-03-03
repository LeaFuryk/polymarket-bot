"""Agent state persistence — load/save agent state and history from disk."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from polybot.agent.helpers import compute_pnl_from_trades

if TYPE_CHECKING:
    from polybot.agent.context import AgentContext


class StatePersistence:
    """Handles loading and saving agent state, history, and pending bet resolution."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._log = logger or logging.getLogger(__name__)

    def load_agent_state(self, ctx: AgentContext) -> None:
        """Load persisted state from disk."""
        try:
            if ctx.state_path.exists():
                data = json.loads(ctx.state_path.read_text())
                ctx.resolutions_since_reflection = data.get("resolutions_since_reflection", 0)
                ctx.knowledge_manager.load_state(data.get("knowledge", {}))
                self._log.info(
                    "Loaded agent state: resolutions_since_reflection=%d",
                    ctx.resolutions_since_reflection,
                )
        except Exception:
            self._log.warning("Could not load agent state, starting fresh")

        ctx.historical_resolutions = []
        ctx.historical_trades = []
        self.load_history_from_logs(ctx)

    def load_history_from_logs(self, ctx: AgentContext) -> None:
        """Load past resolutions and trades from JSONL log files."""
        log_dir = Path(ctx.config.logging.log_dir)

        for res_file in sorted(log_dir.glob("resolutions_*.jsonl")):
            try:
                for line in res_file.read_text().strip().split("\n"):
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    ctx.historical_resolutions.append(
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
                self._log.debug("Could not load resolution file %s", res_file, exc_info=True)

        for trade_file in sorted(log_dir.glob("trades_*.jsonl")):
            try:
                for line in trade_file.read_text().strip().split("\n"):
                    if not line.strip():
                        continue
                    t = json.loads(line)
                    ctx.historical_trades.append(
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
                                f"https://polymarket.com/event/{t.get('candle_slug', '')}"
                                if t.get("candle_slug")
                                else ""
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
                self._log.debug("Could not load trade file %s", trade_file, exc_info=True)

        if ctx.historical_resolutions:
            self._log.info("Loaded %d historical resolutions from logs", len(ctx.historical_resolutions))
        if ctx.historical_trades:
            self._log.info("Loaded %d historical trades from logs", len(ctx.historical_trades))

    def save_agent_state(self, ctx: AgentContext) -> None:
        """Save agent state to disk after each market transition."""
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
            self._log.warning("Could not save agent state")

    async def resolve_pending_bets(self, ctx: AgentContext) -> None:
        """Check for trades with no matching resolution and resolve them."""
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
        self._log.info("Found %d unresolved candle(s) with fills: %s", len(unresolved), unresolved)

        for slug in unresolved:
            try:
                await self._resolve_single_pending_bet(ctx, slug, trades_by_slug[slug])
            except Exception:
                self._log.exception("Failed to resolve pending bet: %s", slug)

    async def _resolve_single_pending_bet(self, ctx: AgentContext, slug: str, trades: list[dict]) -> None:
        """Resolve a single pending bet by looking up the actual outcome."""
        market = await ctx.discovery.fetch_market_by_slug(slug)
        if market is None:
            self._log.warning("Could not fetch market for pending bet: %s (may be delisted)", slug)
            return

        now = time.time()
        if market.end_time > now:
            self._log.info("Skipping pending bet %s — candle still live (ends in %.0fs)", slug, market.end_time - now)
            return

        btc_open = await ctx.market_data.btc_feed.get_price_at(market.start_time)
        btc_close = await ctx.market_data.btc_feed.get_price_at(market.end_time)

        if btc_open is None or btc_close is None:
            self._log.warning(
                "Could not fetch BTC prices for pending bet: %s (open=%s close=%s)", slug, btc_open, btc_close
            )
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

        self._log.info(
            "Resolving pending bet: %s — winner=%s, pnl=%.4f (open=$%.2f close=$%.2f)",
            slug,
            resolution.winner,
            pnl,
            btc_open,
            btc_close,
        )

    @staticmethod
    def compute_iteration_label() -> str:
        """Determine current iteration label from archive count."""
        archive_dir = Path.cwd() / "archive"
        if not archive_dir.exists():
            return "iter_001"
        existing = sorted(d.name for d in archive_dir.iterdir() if d.is_dir() and d.name.startswith("iter_"))
        if not existing:
            return "iter_001"
        last_num = max(int(d.split("_")[1]) for d in existing)
        return f"iter_{last_num + 1:03d}"
