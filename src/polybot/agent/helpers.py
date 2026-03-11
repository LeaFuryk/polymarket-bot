"""Agent helper functions — PnL reconstruction, state persistence, pending bet resolution."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polybot.agent.context import AgentContext


def save_agent_state(ctx: AgentContext, log: logging.Logger | None = None) -> None:
    """Write ``agent_state.json`` to ``ctx.state_path``.

    Persists bot_version, resolutions_since_reflection, and the
    KnowledgeManager's serialised state so the next session can resume.
    Called by RotationManager after every market transition.
    """
    _log = log or logging.getLogger(__name__)
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
        _log.warning("Could not save agent state")


async def resolve_pending_bets(ctx: AgentContext, log: logging.Logger | None = None) -> None:
    """Resolve trades from a previous session that have no matching resolution.

    Cross-references ``ctx.historical_trades`` against ``ctx.historical_resolutions``
    to find candle slugs with fills but no recorded outcome.  For each unresolved
    candle whose end_time has passed, fetches the market result from Polymarket,
    computes PnL, and writes the resolution to the trade log.

    Called once at the start of ``TradingAgent.run()`` after feeds are live.
    """
    _log = log or logging.getLogger(__name__)

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
    _log.info("Found %d unresolved candle(s) with fills: %s", len(unresolved), unresolved)

    for slug in unresolved:
        try:
            await _resolve_single_pending_bet(ctx, slug, trades_by_slug[slug], _log)
        except Exception:
            _log.exception("Failed to resolve pending bet: %s", slug)


async def _resolve_single_pending_bet(ctx: AgentContext, slug: str, trades: list[dict], log: logging.Logger) -> None:
    """Fetch the outcome of a single expired candle and record its resolution.

    Skips candles that are still live or whose BTC prices cannot be fetched.
    """
    market = await ctx.discovery.fetch_market_by_slug(slug)
    if market is None:
        log.warning("Could not fetch market for pending bet: %s (may be delisted)", slug)
        return

    now = time.time()
    if market.end_time > now:
        log.info("Skipping pending bet %s — candle still live (ends in %.0fs)", slug, market.end_time - now)
        return

    btc_open = await ctx.market_data.btc_feed.get_price_at(market.start_time)
    btc_close = await ctx.market_data.btc_feed.get_price_at(market.end_time)

    if btc_open is None or btc_close is None:
        log.warning("Could not fetch BTC prices for pending bet: %s (open=%s close=%s)", slug, btc_open, btc_close)
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

    log.info(
        "Resolving pending bet: %s — winner=%s, pnl=%.4f (open=$%.2f close=$%.2f)",
        slug,
        resolution.winner,
        pnl,
        btc_open,
        btc_close,
    )


def compute_pnl_from_trades(trades: list[dict], winner: str) -> float:
    """Reconstruct PnL for a candle from its logged trades.

    Accumulates share counts and costs for both up/down token sides, then
    settles at $1 for the winning token and $0 for the losing token.

    Args:
        trades: List of trade dicts (must contain action, fill_price, token_side).
        winner: ``"up"`` or ``"down"`` — which token paid out $1.

    Returns:
        Net profit/loss in dollars.
    """
    up_shares = 0.0
    up_cost = 0.0
    down_shares = 0.0
    down_cost = 0.0

    for t in trades:
        if t.get("risk_blocked") or not t.get("fill_price"):
            continue
        size = t.get("fill_size") or t.get("size") or t.get("decision_size") or 0
        price = t["fill_price"]
        side = t.get("token_side", "up")
        action = t.get("action", "HOLD")

        if action == "BUY":
            if side == "up":
                up_shares += size
                up_cost += size * price
            else:
                down_shares += size
                down_cost += size * price
        elif action == "SELL":
            if side == "up":
                up_shares -= size
                up_cost -= size * price
            else:
                down_shares -= size
                down_cost -= size * price

    # Settlement: winning token pays $1, losing pays $0
    if winner == "up":
        pnl = (up_shares * 1.0 - up_cost) + (0 - down_cost)
    else:
        pnl = (0 - up_cost) + (down_shares * 1.0 - down_cost)

    return pnl
