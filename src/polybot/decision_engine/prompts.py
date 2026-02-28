"""System prompt and feature vector formatting for the AI decision engine."""

from __future__ import annotations

import statistics

from polybot.models import BtcCandle, FeatureVector

SCREENING_PROMPT = """\
You are a fast screening agent for a Polymarket BTC 5-minute candle prediction market bot.

Your job: quickly decide if the current market conditions have a STRONG trade setup.
You are NOT making the trade — just screening. Be aggressive about filtering out weak setups.

A $0 BTC move is NEVER a trade setup. No movement = no signal = no trade.

IMPORTANT: The BTC move is shown as a signed value (e.g., $-80.00 means DOWN, $+50.00 means UP).
When comparing against thresholds, use the ABSOLUTE VALUE of the move. $-80 has magnitude $80, which is >$15.

Say should_trade=true if ANY of these apply:
- BTC move magnitude >$15 from candle open (momentum OR contrarian signal — check reversal context)
- Entry prices are very attractive (either token ask < $0.40)
- Clear candle streak of 4+ consecutive same-direction candles (mean reversion setup)
- Reversal rate is high (>60%) AND BTC has moved — contrarian entry opportunity
- Reversal rate is uncertain (40-60%) AND prices are balanced (both asks $0.35-$0.65) AND BTC move magnitude >$15 — cheap-side entry opportunity

Say should_trade=false if ANY of these apply:
- BTC move magnitude < $15 AND no streak (< 3 same-direction) AND time < 120s AND reversal rate < 40%
- Both token asks are > $0.50 (unattractive entries) AND BTC move magnitude < $15 AND reversal rate < 40%
- BTC move is $0 (no signal at all)

When in doubt, say false. Save the budget for setups with a clear directional signal.
"""

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
5. **Wait for price action before entering**: At candle open, BTC is always "flat" — that tells you
   nothing. Wait until BTC has moved meaningfully from open (check "Current move" in BTC Context)
   before deciding direction. A $0 move at t=280s is not a signal — it's the absence of one.
6. **Act decisively when you have a signal**: If BTC has moved and confirms your thesis, trade.
   Don't overthink. But never trade purely because "it's flat and ties go to UP" — that's not an edge.

## Risk Rules (MUST FOLLOW)
- NEVER recommend buying if cash is insufficient
- NEVER recommend selling more shares than currently held for that token
- If the spread is extremely wide (>8%), prefer HOLD
- Size should be proportional to confidence and edge
- Use the FULL confidence range — don't anchor at a single number:
  - **0.55-0.60**: Marginal edge — weak or mixed signals, only worth trading with excellent R/R (entry < $0.30)
  - **0.60-0.70**: Good setup — multiple confirming signals align (momentum + orderbook + price action)
  - **0.70-0.80**: Strong conviction — clear directional move confirmed by price, volume, and trend
  - **0.80+**: Exceptional — overwhelming evidence (large BTC move in your direction with time left)
  If every trade gets the same confidence, the number is meaningless. Vary it based on actual signal strength.
- If you already hold shares on this candle, do NOT buy more of the same token. One entry per candle per side.
- Maximum position should not exceed the risk limits provided
- If time_remaining < 15 seconds, HOLD (resolution too close)
- Each decision cycle costs ~$0.005 in API fees, deducted from your cash.
  A trade must have enough expected edge to cover trading fees + AI costs.
  Minimum expected profit per trade should exceed $0.01.

## Risk/Reward Discipline
- Every BUY is a binary bet: win pays $1, lose pays $0.
- Risk/reward ratio = (1 - entry_price) / entry_price
- NO hard R/R block — all entries allowed, position size scales with R/R:
  - R/R >= 2.0 (entry <= $0.33): full size (100%)
  - R/R 1.0 (entry $0.50): ~80% size
  - R/R 0.5 (entry $0.67): ~55% size
  - R/R < 0.3 (entry > $0.77): ~20% size (small position)
- The market monitor triggers AI only when R/R >= 1.0.
- Prefer entries with R/R >= 1.5 ($0.40 or below). Higher R/R means losses are smaller than wins.
- **BEWARE the cheap entry trap**: A token priced at $0.15 has 5.7x R/R — but it's cheap because \
  the market thinks it has ~15% chance of winning. High R/R ≠ good trade. Only buy cheap tokens \
  when you have STRONG evidence the market is wrong (confirmed BTC move in your direction, not \
  just "it's cheap so I should buy it"). Direction > entry price.
- Late-candle momentum plays at high prices (>$0.70) are an exception — but those carry \
  inherently higher risk and should use smaller sizes.

## Mid-Candle Signal Reliability
- BTC moves >$15 magnitude from candle open tend to continue to close (applies to both directions: $+50 UP or $-80 DOWN).
- Larger moves are more reliable; small moves (<$15 magnitude) are noisy.
- Earlier entries on moderate moves get better prices than waiting for extreme moves.
- Run `polybot-validate` for current continuation/reversal rates from accumulated data.

## Computed Indicators
You may receive computed technical indicators below. These are dynamically selected \
based on past performance. Use them as supporting signals, not sole decision drivers.

## Data Format Notes (for interpreting the market data below)
- "Chainlink On-Chain Price" is the resolution source — divergence from Binance is the pricing risk
- BTC 24h change is NOT predictive for 5-min candles (~40% go opposite to daily trend)
- DOWN tokens often have wider spreads — prefer the token with tighter spread when both sides are viable
- "Condition ID" and "Token ID" are internal identifiers, not trading signals

## Output Guidelines
- action: BUY, SELL, or HOLD
- token_side: "up" or "down" — which token to trade
- order_type: always "MARKET" (do NOT use LIMIT)
- size: number of shares (20-100 range typical). Use 0 for HOLD.
- confidence: your actual confidence (0.0-1.0)
- reasoning: explain your analysis concisely
- market_view: "bullish"/"bearish"/"neutral" + one-sentence thesis
- hypothetical_direction: even on HOLD, predict which side ("up" or "down") you think will win \
this candle. This builds calibration data without risking capital.
- confidence_drivers: For BUY: state what would make this trade LOSE (pre-mortem). \
What scenario would cause BTC to move against your prediction? If you can't identify a clear \
loss scenario, your confidence should be higher. If the loss scenario is likely, reconsider the trade. \
For HOLD: explain what would need to change for you to trade.
"""


def format_feature_vector(
    fv: FeatureVector, feedback_context: str = "", indicators_text: str = "",
    ai_cycle_cost: float = 0.0, ai_session_cost: float = 0.0,
    candle_open_btc: float | None = None,
) -> str:
    """Format a FeatureVector into a clear prompt for Claude."""
    up_ob = fv.market.orderbook
    down_ob = fv.market.down_orderbook

    # Lead with the most important signal: where is BTC vs candle open?
    btc_move_line = ""
    if fv.market.btc_price and candle_open_btc is not None:
        diff = fv.market.btc_price.price_usd - candle_open_btc
        abs_diff = abs(diff)
        if abs_diff < 5:
            move_desc = "FLAT (no signal yet — wait for movement)"
        elif abs_diff < 15:
            move_desc = "SMALL move — low conviction"
        elif abs_diff < 30:
            move_desc = "MODERATE move — tradeable signal"
        else:
            move_desc = "STRONG move — high conviction signal"
        who_winning = "UP winning" if diff >= 0 else "DOWN winning"
        btc_move_line = (
            f"## >>> PRIMARY SIGNAL: BTC vs Candle Open <<<\n"
            f"BTC move: **${diff:+,.2f}** ({who_winning}) — {move_desc}\n"
            f"BTC NOW: ${fv.market.btc_price.price_usd:,.2f} | Candle Open: ${candle_open_btc:,.2f} | "
            f"Time left: {fv.time_remaining:.0f}s\n"
        )

    lines = []
    if btc_move_line:
        lines.append(btc_move_line)

    # Compact orderbook — data only, explanations in system prompt
    up_spread_str = f"{up_ob.spread_pct:.2%}" if up_ob.spread_pct else "N/A"
    down_spread_str = f"{down_ob.spread_pct:.2%}" if down_ob.spread_pct else "N/A"
    lines.extend([
        "## Current Market",
        f"Time remaining: {fv.time_remaining:.0f}s",
        "",
        f"**UP token**: ask={up_ob.best_ask or 'N/A'} bid={up_ob.best_bid or 'N/A'} "
        f"mid={up_ob.midpoint or 'N/A'} spread={up_spread_str} "
        f"depth: ${up_ob.bid_depth:.0f}bid/${up_ob.ask_depth:.0f}ask",
        f"**DOWN token**: ask={down_ob.best_ask or 'N/A'} bid={down_ob.best_bid or 'N/A'} "
        f"mid={down_ob.midpoint or 'N/A'} spread={down_spread_str} "
        f"depth: ${down_ob.bid_depth:.0f}bid/${down_ob.ask_depth:.0f}ask",
        f"Spreads: UP={up_spread_str} DOWN={down_spread_str}",
    ])

    # Price history for trend (Up token midpoints)
    if fv.market.price_history:
        recent = fv.market.price_history[-10:]
        lines.append(f"- Recent Up Midpoints (last {len(recent)}): {recent}")
        if len(recent) >= 2:
            trend = recent[-1] - recent[0]
            lines.append(f"- Price Trend: {'UP' if trend > 0 else 'DOWN'} ({trend:+.4f})")

    # BTC context — compact, explanations in system prompt
    if fv.market.btc_price:
        lines.extend(["", "## BTC Context"])
        btc_parts = [f"NOW: ${fv.market.btc_price.price_usd:,.2f}"]
        if candle_open_btc is not None:
            diff = fv.market.btc_price.price_usd - candle_open_btc
            who_winning = "UP winning" if diff >= 0 else "DOWN winning"
            btc_parts.append(f"Open: ${candle_open_btc:,.2f} → **move: ${diff:+,.2f} ({who_winning})**")
        if fv.market.btc_price.chainlink_price is not None:
            btc_parts.append(
                f"Chainlink: ${fv.market.btc_price.chainlink_price:,.2f} "
                f"(div: ${fv.market.btc_price.price_divergence:+,.2f})"
            )
        btc_parts.append(f"24h: {fv.market.btc_price.change_24h_pct:+.2f}%")
        lines.append(" | ".join(btc_parts))

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

        # Market trend (EMA-based regime detection)
        if len(candles) >= 50:
            from polybot.indicators import _ema

            closes_all = [c.close for c in candles]
            ema20 = _ema(closes_all, 20)
            ema50 = _ema(closes_all, 50)
            price_now = closes_all[-1]
            ema_cross = "BULLISH" if ema20 > ema50 else "BEARISH"
            price_pos = f"${abs(price_now - ema50):,.0f} {'ABOVE' if price_now > ema50 else 'BELOW'}"

            # Compute trend score (same logic as indicator)
            ema_sig = max(-1, min(1, (ema20 - ema50) / 100))
            price_sig = max(-1, min(1, (price_now - ema50) / 150))
            last12 = candles[-12:]
            up_r = sum(1 for c in last12 if c.direction == "up") / len(last12)
            candle_sig = (up_r - 0.5) * 2
            t_score = max(-1, min(1, 0.4 * ema_sig + 0.35 * price_sig + 0.25 * candle_sig))

            if t_score >= 0.5:
                t_label = "STRONG BULLISH"
            elif t_score >= 0.2:
                t_label = "BULLISH"
            elif t_score > -0.2:
                t_label = "NEUTRAL"
            elif t_score > -0.5:
                t_label = "BEARISH"
            else:
                t_label = "STRONG BEARISH"

            lines.extend(["", "## Market Trend"])
            lines.append(f"- EMA20: ${ema20:,.0f} vs EMA50: ${ema50:,.0f} → {ema_cross}")
            lines.append(f"- Price: ${price_now:,.0f} ({price_pos} EMA50)")
            lines.append(f"- Trend Score: {t_score:+.2f} ({t_label})")
            if abs(t_score) >= 0.3:
                weak_side = "DOWN" if t_score > 0 else "UP"
                reduce_pct = "50%" if abs(t_score) >= 0.7 else "30%"
                lines.append(
                    f"- Counter-trend ({weak_side}) positions size-reduced by {reduce_pct}"
                )

    # Positions — compact
    lines.extend(["", "## Positions"])
    if fv.up_position.shares > 0:
        lines.append(
            f"- UP: {fv.up_position.shares:.1f} shares @ {fv.up_position.avg_entry_price:.4f} "
            f"(unrealized: ${fv.up_position.unrealized_pnl:.4f}, realized: ${fv.up_position.realized_pnl:.4f})"
        )
    else:
        lines.append("- UP: no position")
    if fv.down_position.shares > 0:
        lines.append(
            f"- DOWN: {fv.down_position.shares:.1f} shares @ {fv.down_position.avg_entry_price:.4f} "
            f"(unrealized: ${fv.down_position.unrealized_pnl:.4f}, realized: ${fv.down_position.realized_pnl:.4f})"
        )
    else:
        lines.append("- DOWN: no position")

    # Portfolio + Risk — compact
    lines.extend([
        "",
        f"## Portfolio & Risk",
        f"Cash: ${fv.portfolio_cash:.2f} | Portfolio: ${fv.portfolio_total_value:.2f} | "
        f"AI cost: ${ai_session_cost:.4f}",
        f"Daily PnL: ${fv.risk.daily_pnl:.4f} | Trades: {fv.risk.daily_trades} | "
        f"Fees: ${fv.risk.daily_fees:.4f} | Drawdown: ${fv.risk.max_drawdown:.4f}"
        + (f" | **HALTED**" if fv.risk.is_halted else ""),
    ])

    if indicators_text:
        lines.extend(["", indicators_text])

    if feedback_context:
        lines.extend([
            "",
            "## Performance Feedback & Observations",
            feedback_context,
        ])

    lines.extend([
        "",
        f"## Cycle #{fv.cycle_number}",
        "What is your trading decision? Choose which token (up/down) and action. "
        "Respond with the structured JSON output.",
    ])

    return "\n".join(lines)


def format_screening_context(
    fv: FeatureVector,
    indicators_text: str = "",
    candle_open_btc: float | None = None,
) -> str:
    """Format context for the Pass-1 screening model (Haiku).

    Compact but includes all key signals needed for a TRADE/HOLD gate.
    """
    up_ob = fv.market.orderbook
    down_ob = fv.market.down_orderbook

    lines = [f"Time remaining: {fv.time_remaining:.0f}s"]

    # PRIMARY SIGNAL: BTC vs candle open
    if fv.market.btc_price and candle_open_btc is not None:
        diff = fv.market.btc_price.price_usd - candle_open_btc
        who = "UP winning" if diff >= 0 else "DOWN winning"
        lines.append(
            f"BTC: ${fv.market.btc_price.price_usd:,.2f} | "
            f"Candle open: ${candle_open_btc:,.2f} | "
            f"Move: ${diff:+,.2f} ({who})"
        )
    elif fv.market.btc_price:
        lines.append(f"BTC: ${fv.market.btc_price.price_usd:,.2f}")

    # Orderbooks with depth
    if up_ob.spread_pct is not None:
        up_rr = (1.0 - up_ob.best_ask) / up_ob.best_ask if up_ob.best_ask and up_ob.best_ask > 0 else 0
        lines.append(
            f"UP token: ask={up_ob.best_ask} bid={up_ob.best_bid} "
            f"spread={up_ob.spread_pct:.2%} "
            f"depth=${up_ob.bid_depth:.0f}b/${up_ob.ask_depth:.0f}a "
            f"R/R={up_rr:.2f}"
        )
    else:
        lines.append("UP token: no data")
    if down_ob.spread_pct is not None:
        dn_rr = (1.0 - down_ob.best_ask) / down_ob.best_ask if down_ob.best_ask and down_ob.best_ask > 0 else 0
        lines.append(
            f"DOWN token: ask={down_ob.best_ask} bid={down_ob.best_bid} "
            f"spread={down_ob.spread_pct:.2%} "
            f"depth=${down_ob.bid_depth:.0f}b/${down_ob.ask_depth:.0f}a "
            f"R/R={dn_rr:.2f}"
        )
    else:
        lines.append("DOWN token: no data")

    # BTC candle history
    candles = fv.market.btc_candles
    if candles:
        last_6 = candles[-6:] if len(candles) >= 6 else candles
        up_count = sum(1 for c in last_6 if c.direction == "up")
        lines.append(f"Last {len(last_6)} candles: {up_count} UP / {len(last_6) - up_count} DOWN")
        if len(candles) >= 3:
            net_move = candles[-1].close - candles[-3].open
            lines.append(f"Last 15min net BTC move: ${net_move:+,.0f}")

    # Positions
    has_pos = fv.up_position.shares > 0 or fv.down_position.shares > 0
    if has_pos:
        lines.append("Has open position: YES (may need exit decision)")
    else:
        lines.append("Has open position: NO")

    if indicators_text:
        lines.extend(["", indicators_text])

    lines.append("\nShould the full AI be called for a trade decision?")
    return "\n".join(lines)
