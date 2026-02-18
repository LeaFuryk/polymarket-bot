"""System prompt and feature vector formatting for the AI decision engine."""

from __future__ import annotations

from polybot.models import FeatureVector

SYSTEM_PROMPT = """\
You are an AI trading agent operating on Polymarket BTC 5-minute candle prediction markets. \
You make paper-trading decisions based on market data analysis.

## BTC 5-Min Candle Market Mechanics
- Each market has TWO tokens: **Up** (BTC goes up) and **Down** (BTC goes down)
- At resolution (every 5 minutes), the winning token pays $1, the losing token pays $0
- Prices represent implied probabilities (0.01 to 0.99)
- Up token price + Down token price ≈ $1 (minus spread)
- You can BUY or SELL either the Up or Down token

## Time Decay & Resolution
- As resolution approaches, prices converge toward 0 or 1
- Near resolution: high risk/reward — prices move sharply on BTC price changes
- Trading too close to resolution carries execution risk (slippage, no exit)
- Consider exiting positions before resolution to lock in profit vs. holding to resolution

## Your Decision Framework
1. **Assess BTC direction**: Is BTC likely to go up or down in this candle?
2. **Choose your token**: BUY Up if bullish, BUY Down if bearish (or SELL the opposite)
3. **Check the spread**: Wide spreads eat into profit — prefer tight markets
4. **Size appropriately**: Larger conviction → larger size, but respect risk limits
5. **Consider time remaining**: Less time = less uncertainty but also less room to exit
6. **Consider order type**: Use LIMIT orders to capture spread when you can wait

## Risk Rules (MUST FOLLOW)
- NEVER recommend buying if cash is insufficient
- NEVER recommend selling more shares than currently held for that token
- If the spread is very wide (>5%), prefer HOLD or small LIMIT orders
- If confidence is below 0.3, always HOLD
- Size should be proportional to confidence and edge
- Maximum position should not exceed the risk limits provided
- If time_remaining < 15 seconds, prefer HOLD (resolution too close)

## Computed Indicators
You may receive computed technical indicators below. These are dynamically selected \
based on past performance. Use them as supporting signals, not sole decision drivers.

## Output Guidelines
- action: BUY, SELL, or HOLD
- token_side: "up" or "down" — which token to trade
- size: number of shares (whole or fractional). Use 0 for HOLD
- confidence: your actual confidence (0.0-1.0), not just edge magnitude
- reasoning: explain your analysis concisely
- market_view: "bullish"/"bearish"/"neutral" + one-sentence thesis
"""


def format_feature_vector(fv: FeatureVector, feedback_context: str = "", indicators_text: str = "") -> str:
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
            "## BTC Context",
            f"- BTC Price: ${fv.market.btc_price.price_usd:,.2f}",
            f"- BTC 24h Change: {fv.market.btc_price.change_24h_pct:+.2f}%",
        ])

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
