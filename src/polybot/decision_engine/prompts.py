"""System prompt and feature vector formatting for the AI decision engine."""

from __future__ import annotations

import statistics

from polybot.models import BtcCandle, FeatureVector

SYSTEM_PROMPT = """\
You are an AI trading agent operating on Polymarket BTC 5-minute candle prediction markets. \
You make paper-trading decisions based on market data analysis.

## BTC 5-Min Candle Market Mechanics
- Each market has TWO tokens: **Up** (BTC goes up) and **Down** (BTC goes down)
- Resolution source: **Chainlink BTC/USD data stream** (NOT Binance, NOT CoinGecko)
- Resolves to "Up" if BTC price at end **>=** price at start. Otherwise "Down". \
  (Equal price = Up wins.)
- At resolution (every 5 minutes), the winning token pays $1, the losing token pays $0
- Prices represent implied probabilities (0.01 to 0.99)
- Up token price + Down token price ≈ $1 (minus spread)
- You can BUY or SELL either the Up or Down token
- The BTC price shown to you comes from the same Chainlink feed used for resolution

## CRITICAL: Time Awareness for 5-Minute Candles
- These candles last ONLY 5 minutes (300 seconds). You MUST act within this window.
- **> 120s remaining**: Good time to enter. Evaluate and trade if you have an edge.
- **60-120s remaining**: Still tradeable. Act on strong signals.
- **15-60s remaining**: Late but possible for high-conviction trades with tight spreads.
- **< 15 seconds remaining**: Do NOT trade (resolution too close).
- HOLDING every cycle means you never trade and never profit. If you see an edge, TAKE IT.
- You are a paper trading bot — the whole point is to make trades and learn from outcomes.

## Order Type: ALWAYS Use MARKET Orders
- These are 5-minute markets. LIMIT orders almost never fill before the candle expires.
- ALWAYS use order_type: "MARKET" unless the spread is extremely wide (>8%).
- Limit orders in fast-rotating markets are wasted decisions.

## Your Decision Framework
1. **Assess BTC direction for THIS 5-min candle**: Use the 5-min candle history, NOT the 24h change. \
Even on a -3% day, ~40% of 5-min candles are UP. Focus on recent micro-momentum (last 3-6 candles). \
The 24h change tells you the daily trend but is NOT predictive for the next 5-min candle.
2. **Choose your token**: BUY Up if bullish, BUY Down if bearish
3. **Check the spread**: Wide spreads eat into profit, but moderate spreads (2-5%) are normal here
4. **Size appropriately**: 20-100 shares is a reasonable range. Scale with confidence.
5. **Act decisively**: If you have >= 0.6 confidence and > 60s remaining, TRADE.

## Risk Rules (MUST FOLLOW)
- NEVER recommend buying if cash is insufficient
- NEVER recommend selling more shares than currently held for that token
- If the spread is extremely wide (>8%), prefer HOLD
- If confidence is below 0.6, HOLD
- Size should be proportional to confidence and edge
- Maximum position should not exceed the risk limits provided
- If time_remaining < 15 seconds, HOLD (resolution too close)
- Each decision cycle costs ~$0.005 in API fees, deducted from your cash.
  A trade must have enough expected edge to cover trading fees + AI costs.
  Minimum expected profit per trade should exceed $0.01.

## Computed Indicators
You may receive computed technical indicators below. These are dynamically selected \
based on past performance. Use them as supporting signals, not sole decision drivers.

## Output Guidelines
- action: BUY, SELL, or HOLD
- token_side: "up" or "down" — which token to trade
- order_type: always "MARKET" (do NOT use LIMIT)
- size: number of shares (20-100 range typical). Use 0 for HOLD.
- confidence: your actual confidence (0.0-1.0)
- reasoning: explain your analysis concisely
- market_view: "bullish"/"bearish"/"neutral" + one-sentence thesis
"""


def format_feature_vector(
    fv: FeatureVector, feedback_context: str = "", indicators_text: str = "",
    ai_cycle_cost: float = 0.0, ai_session_cost: float = 0.0,
) -> str:
    """Format a FeatureVector into a clear prompt for Claude."""
    up_ob = fv.market.orderbook
    down_ob = fv.market.down_orderbook

    lines = [
        "## Current Candle Market",
        f"- Condition ID: {fv.market.condition_id}",
        f"- Time Remaining: {fv.time_remaining:.0f}s",
        "",
        "### Up Token (BTC goes up)",
        f"- Token ID: {fv.market.up_token_id[:12]}...",
        f"- Best Bid: {up_ob.best_bid or 'N/A'}",
        f"- Best Ask: {up_ob.best_ask or 'N/A'}",
        f"- Midpoint: {up_ob.midpoint or 'N/A'}",
        f"- Spread: {up_ob.spread or 'N/A'}"
        + (f" ({up_ob.spread_pct:.2%})" if up_ob.spread_pct else ""),
        f"- Bid Depth (USDC): {up_ob.bid_depth:.2f}",
        f"- Ask Depth (USDC): {up_ob.ask_depth:.2f}",
        "",
        "### Down Token (BTC goes down)",
        f"- Token ID: {fv.market.down_token_id[:12]}...",
        f"- Best Bid: {down_ob.best_bid or 'N/A'}",
        f"- Best Ask: {down_ob.best_ask or 'N/A'}",
        f"- Midpoint: {down_ob.midpoint or 'N/A'}",
        f"- Spread: {down_ob.spread or 'N/A'}"
        + (f" ({down_ob.spread_pct:.2%})" if down_ob.spread_pct else ""),
        f"- Bid Depth (USDC): {down_ob.bid_depth:.2f}",
        f"- Ask Depth (USDC): {down_ob.ask_depth:.2f}",
    ]

    # Last trade price (Up token)
    lines.append(f"- Last Trade Price (Up): {fv.market.last_trade_price or 'N/A'}")

    # Price history for trend (Up token midpoints)
    if fv.market.price_history:
        recent = fv.market.price_history[-10:]
        lines.append(f"- Recent Up Midpoints (last {len(recent)}): {recent}")
        if len(recent) >= 2:
            trend = recent[-1] - recent[0]
            lines.append(f"- Price Trend: {'UP' if trend > 0 else 'DOWN'} ({trend:+.4f})")

    # BTC context
    if fv.market.btc_price:
        lines.extend([
            "",
            "## BTC Context (Chainlink BTC/USD — resolution source)",
            f"- BTC Price: ${fv.market.btc_price.price_usd:,.2f}",
            f"- BTC 24h Change: {fv.market.btc_price.change_24h_pct:+.2f}% "
            "(⚠ NOT predictive for 5-min candles — ~40% go opposite to daily trend)",
        ])

    # BTC 5-min candle history
    candles = fv.market.btc_candles
    if candles:
        lines.extend(["", "## BTC 5-Min Candle History"])

        # Last 12 candles up/down ratio
        last_12 = candles[-12:] if len(candles) >= 12 else candles
        up_count = sum(1 for c in last_12 if c.direction == "up")
        down_count = len(last_12) - up_count
        lines.append(f"- Last {len(last_12)} candles: {up_count} UP / {down_count} DOWN")

        # Last 6 candles as compact OHLC table
        last_6 = candles[-6:] if len(candles) >= 6 else candles
        lines.append("")
        lines.append("Last candles (newest last):")
        lines.append("| # | Open | Close | Direction | Body% |")
        lines.append("|---|------|-------|-----------|-------|")
        for i, c in enumerate(last_6, 1):
            lines.append(
                f"| {i} | ${c.open:,.0f} | ${c.close:,.0f} | {c.direction.upper()} | {c.body_pct:+.3f}% |"
            )

        # MA5 vs MA12 crossover
        closes = [c.close for c in candles]
        if len(closes) >= 12:
            ma5 = statistics.mean(closes[-5:])
            ma12 = statistics.mean(closes[-12:])
            cross_signal = "BULLISH" if ma5 > ma12 else "BEARISH"
            lines.append(f"- MA5: ${ma5:,.0f} vs MA12: ${ma12:,.0f} → {cross_signal} crossover")

        # MA50 if enough data
        if len(closes) >= 50:
            ma50 = statistics.mean(closes[-50:])
            trend = "above" if closes[-1] > ma50 else "below"
            lines.append(f"- MA50: ${ma50:,.0f} (price {trend} MA50)")

        # Last 15min net BTC move (3 candles)
        if len(candles) >= 3:
            net_move = candles[-1].close - candles[-3].open
            lines.append(f"- Last 15min net BTC move: ${net_move:+,.0f}")

    # Positions (both tokens)
    lines.extend([
        "",
        "## Your Current Positions",
        "### Up Token Position",
        f"- Shares Held: {fv.up_position.shares:.2f}",
        f"- Avg Entry Price: {fv.up_position.avg_entry_price:.4f}",
        f"- Unrealized PnL: ${fv.up_position.unrealized_pnl:.4f}",
        f"- Realized PnL: ${fv.up_position.realized_pnl:.4f}",
        "### Down Token Position",
        f"- Shares Held: {fv.down_position.shares:.2f}",
        f"- Avg Entry Price: {fv.down_position.avg_entry_price:.4f}",
        f"- Unrealized PnL: ${fv.down_position.unrealized_pnl:.4f}",
        f"- Realized PnL: ${fv.down_position.realized_pnl:.4f}",
    ])

    # Portfolio
    lines.extend([
        "",
        "## Portfolio",
        f"- Cash Available: ${fv.portfolio_cash:.2f}",
        f"- Total Portfolio Value: ${fv.portfolio_total_value:.2f}",
        f"- AI Operating Cost This Cycle: ~${ai_cycle_cost:.4f}",
        f"- Total AI Costs This Session: ${ai_session_cost:.4f}",
    ])

    # Risk state
    lines.extend([
        "",
        "## Risk State",
        f"- Daily PnL: ${fv.risk.daily_pnl:.4f}",
        f"- Daily Trades: {fv.risk.daily_trades}",
        f"- Daily Fees: ${fv.risk.daily_fees:.4f}",
        f"- Max Drawdown: ${fv.risk.max_drawdown:.4f}",
        f"- Risk Halted: {fv.risk.is_halted}",
    ])

    if indicators_text:
        lines.extend(["", indicators_text])

    if feedback_context:
        lines.extend([
            "",
            "## Performance Feedback & Learnings",
            feedback_context,
        ])

    lines.extend([
        "",
        f"## Cycle #{fv.cycle_number}",
        "What is your trading decision? Choose which token (up/down) and action. "
        "Respond with the structured JSON output.",
    ])

    return "\n".join(lines)
