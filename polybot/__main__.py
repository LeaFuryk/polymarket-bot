"""Entry point — run MarketStateService and print full v3 prompt."""

import asyncio
import logging
import os

from dotenv import load_dotenv
from pyee.asyncio import AsyncIOEventEmitter

from polybot.adapters.binance_volume import BinanceVolumeAdapter
from polybot.adapters.chainlink_streams import ChainlinkStreamsAdapter
from polybot.adapters.polymarket import PolymarketAdapter
from polybot.adapters.sqlite_store import SqliteStore
from polybot.domain.models import Candle, MarketSnapshot, OrderBook, PromptState
from polybot.services.candle_aggregator import CandleAggregator
from polybot.services.data_collector import DataCollector
from polybot.services.market_state import MarketStateService
from polybot.services.technicals import (
    ma_crossover,
    reversal_regime,
    trend_score,
    velocity_conflict,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


def _f(val: float | None, d: int = 2, sign: bool = False) -> str:
    if val is None:
        return "n/a"
    return f"{val:+.{d}f}" if sign else f"{val:.{d}f}"


def _fi(val: float | None) -> str:
    return "n/a" if val is None else f"{val:.0f}"


def _fd(val: float | None) -> str:
    """Format dollar amount with comma separator."""
    return "n/a" if val is None else f"${val:,.2f}"


def _ob_line(label: str, book: OrderBook) -> str:
    ask = book.best_ask
    bid = book.best_bid
    mid = book.midpoint
    spread = f"{book.spread_pct:.2f}%" if book.spread_pct is not None else "n/a"
    rr = f"{(1 - ask) / ask:.2f}" if ask and ask > 0 else "n/a"
    return (
        f"{label}: ask={ask or 'n/a'} bid={bid or 'n/a'} mid={_f(mid, 3)} "
        f"spread={spread} depth: ${book.bid_depth:.0f}bid/${book.ask_depth:.0f}ask  R/R={rr}"
    )


def format_prompt(
    state: PromptState,
    snapshot: MarketSnapshot,
    closed: tuple[Candle, ...],
    midpoint_history: list[float],
    cycle: int,
) -> str:
    cc = state.current_candle
    t = state.technicals
    m = state.microstructure
    lines: list[str] = []

    # --- PRIMARY SIGNAL ---
    btc_open = cc.open
    btc_last = cc.last_price
    if btc_open is not None and btc_last is not None:
        diff = btc_last - btc_open
        abs_diff = abs(diff)
        who = "UP winning" if diff >= 0 else "DOWN winning"
        if abs_diff >= 50:
            label = "STRONG move"
        elif abs_diff >= 15:
            label = "MODERATE move"
        else:
            label = "WEAK move"
        lines.append("## PRIMARY SIGNAL")
        lines.append(f"BTC move: ${diff:+,.2f} ({who}) — {label}")
        lines.append(
            f"BTC NOW: ${btc_last:,.2f} | Candle open: ${btc_open:,.2f} | Time left: {cc.time_remaining_sec:.0f}s"
        )
    else:
        lines.append("## PRIMARY SIGNAL")
        lines.append("BTC move: n/a (no candle data yet)")

    # --- PRE-COMPUTED FLAGS ---
    vc_label, vc_sev = velocity_conflict(btc_last, btc_open, list(closed))
    rr_label, rr_score = reversal_regime(list(closed))

    lines.append("")
    lines.append("## Pre-computed Flags")
    if vc_label == "NONE":
        lines.append("- Velocity conflict: NONE")
    else:
        scale = "50%" if vc_label == "STRONG" else "75%"
        lines.append(f"- Velocity conflict: {vc_label} (severity {vc_sev:.2f}) → size auto-scaled {scale}")

    if rr_label == "DIRECTIONAL":
        lines.append(f"- Reversal regime:   DIRECTIONAL (score {rr_score:.2f})")
    else:
        scale = "50%" if rr_label == "HIGH" else "75%"
        lines.append(f"- Reversal regime:   {rr_label} (score {rr_score:.2f}) → size auto-scaled {scale}")

    # --- MARKET ---
    lines.append("")
    lines.append("## Market")
    lines.append(_ob_line("UP token  ", snapshot.up_book))
    lines.append(_ob_line("DOWN token", snapshot.down_book))

    lines.append("")
    if midpoint_history:
        recent = midpoint_history[-10:]
        lines.append(f"Recent UP midpoints (last {len(recent)}): {[round(m, 3) for m in recent]}")
        if len(recent) >= 2:
            trend = recent[-1] - recent[0]
            direction = "UP" if trend > 0 else "DOWN" if trend < 0 else "FLAT"
            lines.append(f"Midpoint trend: {direction} ({trend:+.3f})")
    else:
        lines.append("Recent UP midpoints: n/a")
        lines.append("Midpoint trend: n/a")

    # --- CANDLE HISTORY ---
    lines.append("")
    lines.append("## Candle History (newest last)")
    if closed:
        lines.append("")
        lines.append("## Candle History (newest last)")
        last_12 = closed[-12:] if len(closed) >= 12 else closed
        up_count = sum(1 for c in last_12 if c.close >= c.open)
        down_count = len(last_12) - up_count
        lines.append(f"Last {len(last_12)} candles: {up_count} UP / {down_count} DOWN")
        lines.append("")

        last_6 = closed[-6:] if len(closed) >= 6 else closed
        lines.append("| # | Open | Close | Dir | Body% |")
        lines.append("|---|------|-------|-----|-------|")
        for i, c in enumerate(last_6, 1):
            direction = "UP" if c.close >= c.open else "DOWN"
            body_pct = (c.close - c.open) / c.open * 100 if c.open > 0 else 0
            lines.append(f"| {i} | ${c.open:,.0f} | ${c.close:,.0f} | {direction} | {body_pct:+.3f}% |")

        closes = [c.close for c in closed]
        mac = ma_crossover(closes)
        if mac:
            lines.append("")
            lines.append(f"MA5: ${mac[0]:,.0f} vs MA12: ${mac[1]:,.0f} → {mac[2]} crossover")

        ts = trend_score(list(closed))
        if ts is not None:
            if ts >= 0.5:
                ts_label = "STRONG BULLISH"
            elif ts >= 0.2:
                ts_label = "BULLISH"
            elif ts > -0.2:
                ts_label = "NEUTRAL"
            elif ts > -0.5:
                ts_label = "BEARISH"
            else:
                ts_label = "STRONG BEARISH"
            lines.append(f"Trend score: {ts:+.2f} ({ts_label})")
    else:
        lines.append("No candle history yet")

    # --- SESSION CONTEXT ---
    lines.append("")
    lines.append("## Session Context")

    tc = t.trend_consistency
    tc_desc = "trending" if tc is not None and abs(tc) > 0.3 else "choppy" if tc is not None else "n/a"
    lines.append(f"Trend consistency: {_f(tc, sign=True)} ({tc_desc})")

    rp = t.range_position
    if rp is not None:
        if rp > 0.85:
            rp_desc = "extended high — reversal risk"
        elif rp < 0.15:
            rp_desc = "extended low — reversal risk"
        else:
            rp_desc = "mid-range"
        lines.append(f"Range position:    {_f(rp)} ({rp_desc})")
    else:
        lines.append("Range position:    n/a")

    yes_ob_desc = "buyers dominant" if m.yes_ob > 0.1 else "sellers dominant" if m.yes_ob < -0.1 else "balanced"
    no_ob_desc = "buyers dominant" if m.no_ob > 0.1 else "sellers dominant" if m.no_ob < -0.1 else "balanced"
    lines.append(f"YES ob imbalance:  {_f(m.yes_ob, sign=True)} ({yes_ob_desc})")
    lines.append(f"NO ob imbalance:   {_f(m.no_ob, sign=True)} ({no_ob_desc})")

    vt = m.vol_timing
    if vt is not None:
        vt_desc = "early informed flow" if vt < 0.4 else "late crowd" if vt > 0.65 else "mid-candle"
        lines.append(f"Vol timing:        {_f(vt)} ({vt_desc})")
    else:
        lines.append("Vol timing:        n/a")

    # --- POSITIONS ---
    lines.append("")
    lines.append("## Positions")
    lines.append("UP: 0 shares | DOWN: 0 shares")

    # --- PORTFOLIO ---
    lines.append("")
    lines.append("## Portfolio")
    lines.append("Cash: $1000.00 | PnL: $0.00 | Trades: 0 | Fees: $0.00 | Drawdown: $0.00")

    # --- CYCLE ---
    lines.append("")
    lines.append(f"## Cycle #{cycle}")

    return "\n".join(lines)


async def poll_state(service: MarketStateService) -> None:
    await asyncio.sleep(2)
    while True:
        state = await service.get_state()
        if state is not None and service._last_snapshot is not None:
            prompt = format_prompt(
                state=state,
                snapshot=service._last_snapshot,
                closed=service._last_closed,
                midpoint_history=service._midpoint_history[-10:],
                cycle=service._cycle_count,
            )
            print(prompt)
            print("---")
        else:
            print("Waiting for market data...")
        await asyncio.sleep(30)


async def main() -> None:
    load_dotenv()
    price_stream = ChainlinkStreamsAdapter(
        user_id=os.environ["CH_STREAM_USER_ID"],
        secret=os.environ["CH_STREAM_SECRETS"],
    )
    volume_feed = BinanceVolumeAdapter()
    market_feed = PolymarketAdapter()

    store = SqliteStore("data/collection.db")
    await store.init()

    # Shared event bus — aggregator publishes, collector subscribes
    events = AsyncIOEventEmitter()
    aggregator = CandleAggregator(price_stream, volume_feed, events=events)
    collector = DataCollector(aggregator, market_feed, store, events=events)

    # service = MarketStateService(aggregator, market_feed)
    await price_stream.connect()
    try:
        await asyncio.gather(
            aggregator.run(),
            # poll_state(service),
            collector.run(),
        )
    finally:
        await price_stream.disconnect()
        await volume_feed.close()
        await market_feed.close()
        await store.close()


if __name__ == "__main__":
    asyncio.run(main())
