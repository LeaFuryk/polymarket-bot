# iter_035 Timeout Analysis — Second-by-Second Order Timelines

> **Date:** 2026-03-08 | **Session:** iter_035 (first live execution session)
> **Orders:** 5 total, 3 filled, 2 pure timeouts + 1 partial fill lost = **3 problematic orders**
> **Root cause:** 15–18s AI latency makes decision-time orderbook stale by the time the order reaches the exchange.

---

## Overview

| # | Decision | Action | Token | AI Latency | Limit Price | Market at Submit | Drift   | Filled               | Candle Winner |
|---|----------|--------|-------|------------|-------------|------------------|---------|----------------------|---------------|
| 1 | #4       | BUY    | DOWN  | 16.0s      | $0.56       | ask=$0.57        | +1.8%   | 37/40 (93%) but lost | UP            |
| 2 | #6       | BUY    | UP    | 18.1s      | $0.61       | ask=$0.70        | +14.8%  | 0/51                 | DOWN          |
| 3 | #10      | SELL   | UP    | 14.9s      | $0.52       | bid=$0.19        | -63.5%  | 0/40                 | DOWN          |

---

## Order #1 — BUY DOWN @ $0.56 (partial fill, treated as timeout)

**Candle:** `btc-updown-5m-1772928300` (00:05:00–00:10:00 UTC)
**Winner:** UP
**Order ID:** `0x277cac4b...`

### Timeline

```
 SEC   TIME (UTC)  T-LEFT  DOWN ask/bid    UP ask/bid     BTC MOVE    STATUS
─────┼────────────┼───────┼──────────────┼──────────────┼───────────┼──────────────────────────────
  0  │ 00:06:41   │ 200s  │ $0.56/$0.55  │ $0.45/$0.44  │ +$5.83    │ Market monitor reads OB
  2  │ 00:06:43   │ 198s  │ $0.52/$0.51  │ $0.45/$0.44  │ +$5.82    │   ·
  5  │ 00:06:46   │ 196s  │ $0.50/$0.49  │ $0.51/$0.50  │ +$5.83    │   ·
  8  │ 00:06:49   │ 193s  │ $0.51/$0.50  │ $0.50/$0.49  │ +$5.83    │ ◆ OB snapshot: ask=$0.56
     │            │       │              │              │           │ ╔══════════════════════════╗
     │            │       │              │              │           │ ║ AI CALL STARTS (Sonnet)  ║
     │            │       │              │              │           │ ╚══════════════════════════╝
 11  │ 00:06:52   │ 190s  │ $0.50/$0.49  │ $0.51/$0.50  │ +$5.83    │ thinking...
 14  │ 00:06:55   │ 187s  │ $0.50/$0.49  │ $0.51/$0.50  │ +$5.82    │
 16  │ 00:06:57   │ 184s  │ $0.56/$0.55  │ $0.45/$0.44  │ +$5.82    │ DOWN ask jumps → $0.56
 19  │ 00:07:00   │ 182s  │ $0.56/$0.55  │ $0.45/$0.44  │ +$5.81    │
 22  │ 00:07:03   │ 179s  │ $0.57/$0.56  │ $0.44/$0.43  │ +$5.82    │ DOWN ask → $0.57 (+1.8%)
     │            │       │              │              │           │ ╔══════════════════════════╗
     │            │       │              │              │           │ ║ AI RETURNS (16.0s)       ║
     │            │       │              │              │           │ ╚══════════════════════════╝
 22  │ 00:07:03   │       │              │              │           │ ▶ ORDER SUBMITTED @ $0.56
     │            │       │              │              │           │   ob_at_submit: ask=$0.57
     │            │       │              │              │           │   limit=$0.56 vs market=$0.57
 23  │ 00:07:04   │ 176s  │ $0.57/$0.56  │ $0.44/$0.43  │ +$5.82    │ POLL 1: status=LIVE
     │            │       │              │              │           │         size_matched=37.15/40
     │            │       │              │              │           │         (93% filled!)
 24  │ 00:07:05   │       │              │              │           │ fill detected via size_matched
 25  │ 00:07:06   │ 176s  │ $0.57/$0.56  │ $0.44/$0.43  │ +$5.82    │   ·
 27  │ 00:07:08   │ 173s  │ $0.56/$0.55  │ $0.45/$0.44  │ +$5.81    │   ·
```

### What happened

| Phase | Detail |
|-------|--------|
| **OB read** | Monitor snapshots DOWN ask=$0.56, passes to AI |
| **AI latency** | 16.0 seconds. Market barely moves (BTC flat at +$5.8) |
| **At submit** | DOWN ask drifted $0.56 → $0.57 (+1.8%). Small drift. |
| **Order** | Limit at $0.56, market at $0.57. Order sits below best ask. |
| **Fill** | 37.15/40 shares matched after 1s (93% fill rate) |
| **Bug** | CLOB status stayed `LIVE` (not `MATCHED`). `parse_order_response()` returned `None`. Fill was **lost**. |
| **Outcome** | Candle winner = UP. Had fill been captured: **would have lost** (-$22.40) |

### Fix mapping

- **Partial fill fallback** → captures the 37.15 shares (status=LIVE but size_matched > 0)
- **BUY reprice** → would have repriced to $0.57 (within 5% drift cap)

---

## Order #2 — BUY UP @ $0.61 (pure timeout, 0 shares filled)

**Candle:** `btc-updown-5m-1772928600` (00:10:00–00:15:00 UTC)
**Winner:** DOWN
**Order ID:** `0x73c04089...`

### Timeline

```
 SEC   TIME (UTC)  T-LEFT  UP ask/bid     DOWN ask/bid    BTC MOVE    STATUS
─────┼────────────┼───────┼─────────────┼───────────────┼───────────┼──────────────────────────────
  0  │ 00:10:12   │ 290s  │ $0.61/$0.59  │  ──           │  +$9.05  │ Market monitor reads OB
  2  │ 00:10:14   │ 287s  │ $0.61/$0.60  │  ──           │ +$21.79  │ ◆ OB snapshot: ask=$0.61
     │            │       │              │               │          │   BTC surging (+$12.7/s)
     │            │       │              │               │          │ ╔══════════════════════════╗
     │            │       │              │               │          │ ║ AI CALL STARTS (Sonnet)  ║
     │            │       │              │               │          │ ╚══════════════════════════╝
  5  │ 00:10:17   │ 285s  │ $0.66/$0.63  │ $0.34/$0.32   │ +$26.15  │ │ thinking... ask → $0.66
     │            │       │              │               │          │ │ (+8.2% from decision)
  8  │ 00:10:20   │ 282s  │ $0.69/$0.67  │ $0.34/$0.32   │ +$27.04  │ │ ask → $0.69 (+13%)
 10  │ 00:10:22   │ 279s  │ $0.69/$0.67  │ $0.33/$0.30   │ +$41.01  │ │ BTC +$41 from open
 13  │ 00:10:25   │ 277s  │ $0.75/$0.72  │ $0.29/$0.28   │ +$41.01  │ │ ask → $0.75 (+23%!)
 16  │ 00:10:28   │ 274s  │ $0.73/$0.72  │ $0.28/$0.27   │ +$39.39  │ │ slight pullback
 18  │ 00:10:30   │ 272s  │ $0.71/$0.69  │ $0.30/$0.29   │ +$37.70  │ │ ask settles ~$0.71
 21  │ 00:10:33   │ 269s  │ $0.71/$0.69  │ $0.31/$0.29   │ +$37.70  │ │
     │            │       │              │               │          │ ╔══════════════════════════╗
     │            │       │              │               │          │ ║ AI RETURNS (18.1s)       ║
     │            │       │              │               │          │ ╚══════════════════════════╝
 24  │ 00:10:36   │ 266s  │ $0.70/$0.69  │ $0.31/$0.30   │ +$37.69  │ ▶ ORDER SUBMITTED @ $0.61
     │            │       │              │               │          │   ob_at_submit: ask=$0.70
     │            │       │              │               │          │   limit=$0.61 vs market=$0.70
     │            │       │              │               │          │   DRIFT: +14.8%
     │            │       │              │               │          │   ($0.09 below the market)
 26  │ 00:10:38   │ 263s  │ $0.70/$0.69  │ $0.31/$0.30   │ +$37.69  │ POLL 1: LIVE, matched=0
 27  │ 00:10:39   │ 263s  │ $0.70/$0.69  │ $0.31/$0.30   │ +$37.69  │ POLL 2: LIVE, matched=0
 28  │ 00:10:40   │       │              │               │          │ POLL 3: LIVE, matched=0
     │            │       │              │               │          │ ╔══════════════════════════╗
     │            │       │              │               │          │ ║ TIMEOUT → CANCEL (3s)   ║
     │            │       │              │               │          │ ╚══════════════════════════╝
 31  │ 00:10:43   │ 259s  │ $0.72/$0.71  │ $0.30/$0.29   │ +$37.70  │ post-cancel: ask=$0.72
 34  │ 00:10:46   │ 256s  │ $0.71/$0.70  │ $0.31/$0.29   │ +$37.70  │   ·
```

### What happened

| Phase | Detail |
|-------|--------|
| **OB read** | Monitor snapshots UP ask=$0.61 with BTC at +$21.79 |
| **AI latency** | 18.1 seconds. BTC surges +$16 more during this time. |
| **Price movement** | UP ask: $0.61 → $0.75 (peak) → $0.70 (at submit). **+14.8% drift.** |
| **At submit** | Limit=$0.61 is $0.09 below the market ask of $0.70. No seller will fill at $0.61. |
| **Polls** | 3 polls over 3s, all LIVE with 0 matched. Market ask never came back down. |
| **Cancel** | After 3s TTL, order canceled. Market continues at $0.71-0.72. |
| **Outcome** | Candle winner = DOWN. Had it filled at $0.70: **would have lost** (-$35.70). Lucky miss. |

### Fix mapping

- **Drift guard** → would have **SKIPPED** this order (14.8% drift > 5% max)
- **BUY reprice** → moot (skipped before reprice)

---

## Order #3 — SELL UP @ $0.52 (failed stop-loss, 0 shares filled)

**Candle:** `btc-updown-5m-1772929200` (00:20:00–00:25:00 UTC)
**Winner:** DOWN
**Order ID:** `0xfd5d0d19...`
**Context:** Bot held 40 UP shares (bought at $0.74 in decision #9). Stop-loss triggered at -28.4%.

### Timeline

```
 SEC   TIME (UTC)  T-LEFT  UP ask/bid     DOWN ask/bid    BTC MOVE    STATUS
─────┼────────────┼───────┼─────────────┼───────────────┼───────────┼──────────────────────────────
  0  │ 00:23:12   │ 109s  │ $0.57/$0.34  │ $0.68/$0.54   │ -$25.94  │ Market monitor reads OB
     │            │       │ spread=51%   │               │          │ (already wide)
  3  │ 00:23:15   │ 107s  │ $0.46/$0.32  │  ──           │ -$26.91  │ ◆ OB snapshot: bid=$0.52
     │            │       │              │               │          │   stop-loss: -28.4% > -19%
     │            │       │              │               │          │ ╔══════════════════════════╗
     │            │       │              │               │          │ ║ AI CALL STARTS (Sonnet)  ║
     │            │       │              │               │          │ ╚══════════════════════════╝
  6  │ 00:23:18   │ 104s  │ $0.38/$0.26  │ $0.75/$0.62   │ -$42.35  │ │ thinking...
     │            │       │              │               │          │ │ BTC crashing, bid → $0.26
  8  │ 00:23:20   │ 101s  │ $0.19/$0.18  │ $0.83/$0.80   │ -$56.58  │ │ ★ FLASH CRASH
     │            │       │ spread=5.4%  │               │          │ │   bid=$0.18, ask=$0.19
     │            │       │              │               │          │ │   BTC -$57 from open
 10  │ 00:23:22   │  99s  │ $0.25/$0.23  │ $0.78/$0.75   │ -$56.58  │ │ bounce: bid=$0.23
 13  │ 00:23:25   │  97s  │ $0.26/$0.24  │ $0.85/$0.73   │ -$43.57  │ │ BTC recovering (+$13)
     │            │       │              │               │          │ │ bid=$0.24
     │            │       │              │               │          │ ╔══════════════════════════╗
     │            │       │              │               │          │ ║ AI RETURNS (14.9s)       ║
     │            │       │              │               │          │ ╚══════════════════════════╝
 16  │ 00:23:28   │       │              │               │          │ ▶ ORDER SUBMITTED: SELL @ $0.52
     │            │       │              │               │          │   ob_at_submit: bid=$0.19
     │            │       │              │               │          │   ask=$0.24, spread=23.3%
     │            │       │              │               │          │   limit=$0.52 vs market=$0.19
     │            │       │              │               │          │   DRIFT: -63.5%
     │            │       │              │               │          │   ($0.33 ABOVE market bid)
 17  │ 00:23:29   │  90s  │ $0.31/$0.28  │ $0.74/$0.73   │ -$28.03  │ POLL 1: LIVE, matched=0
     │            │       │              │               │          │   BTC recovering, bid=$0.28
 19  │ 00:23:31   │  90s  │ $0.31/$0.28  │ $0.74/$0.73   │ -$28.03  │ POLL 2: LIVE, matched=0
 20  │ 00:23:32   │       │              │               │          │ POLL 3: LIVE, matched=0
     │            │       │              │               │          │ ╔══════════════════════════╗
     │            │       │              │               │          │ ║ TIMEOUT → CANCEL (3s)   ║
     │            │       │              │               │          │ ╚══════════════════════════╝
 23  │ 00:23:35   │  87s  │ $0.24/$0.23  │ $0.77/$0.76   │ -$15.42  │ post-cancel: BTC recovering
 26  │ 00:23:38   │  84s  │ $0.29/$0.28  │ $0.69/$0.68   │ -$15.41  │ bid back to $0.28
     │            │       │              │               │          │
     │            │       │              │               │          │ HELD TO RESOLUTION
     │            │       │              │               │          │ Winner = DOWN
     │            │       │              │               │          │ 40 UP shares → $0.00
     │            │       │              │               │          │ Loss: -$29.60
```

### What happened

| Phase | Detail |
|-------|--------|
| **OB read** | Monitor snapshots UP bid=$0.52. Stop-loss triggers at -28.4% (threshold -19%). |
| **AI latency** | 14.9 seconds. BTC crashes from -$26 to -$57 and partially recovers during AI thinking. |
| **Price movement** | UP bid: $0.52 → $0.18 (flash crash low) → $0.19 (at submit). **-63.5% drift.** |
| **At submit** | SELL limit=$0.52 is $0.33 above the market bid of $0.19. No buyer at $0.52. Spread = 23.3%. |
| **Polls** | 3 polls over 3s, all LIVE with 0 matched. Market bid was $0.19-0.28 — nowhere near $0.52. |
| **Cancel** | After 3s TTL, order canceled. BTC continues recovering. |
| **Outcome** | Stop-loss **failed**. 40 UP shares held to resolution. DOWN won. **Full loss: -$29.60.** |
| **Counterfactual** | SELL at $0.19 (fresh bid) would have salvaged $0.19 × 40 = $7.60 vs $0.00. |

### Fix mapping

- **SELL reprice** → would have repriced to fresh bid $0.19 (no drift cap on SELLs)
- **Spread guard** → does NOT block SELLs by design (exits must go through)

---

## Price Drift Visualization

```
Order #1 (BUY DOWN)                         Order #2 (BUY UP)
drift: +1.8%                                drift: +14.8%

$0.57 ─ ─ ─ ─ ─ ─ ─ ─ ─ ▪ submit          $0.75 ─ ─ ─ ─ ─ ─ ─ ─ peak
$0.56 ▪ decision           │                $0.70 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ▪ submit
      │                    │                $0.61 ▪ decision             │
      │◄── 16s AI ────────►│                      │                     │
                                                  │◄──── 18s AI ──────►│


Order #3 (SELL UP)
drift: -63.5%

$0.52 ▪ decision
      │
      │
      │          ◄── 15s AI ──►
      │                        │
$0.19 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ▪ submit (bid)
$0.18 ─ ─ ─ ─ ─ flash crash low
```

---

## Fix Impact Summary

```
                            Order #1          Order #2          Order #3
                            BUY DOWN          BUY UP            SELL UP
                            ─────────         ──────            ───────
AI latency                  16.0s             18.1s             14.9s
Decision price              ask=$0.56         ask=$0.61         bid=$0.52
Submit price                ask=$0.57         ask=$0.70         bid=$0.19
Drift                       +1.8%             +14.8%            -63.5%
Spread at submit            1.8%              1.4%              23.3%
Shares filled               37.15/40          0/51              0/40

FIX: Partial fill fallback  ★ CAPTURES 37.15   ·                ·
FIX: Drift guard (>5%)       ·                ★ SKIPS            n/a (SELL)
FIX: Spread guard (>5%)      ·                 ·                n/a (SELL)
FIX: SELL reprice             ·                 ·               ★ → $0.19
FIX: BUY reprice             ★ → $0.57        (skipped)         n/a

Candle winner               UP                DOWN              DOWN
Would fill have won?        NO (-$22.40)      NO (-$35.70)      n/a (exit)
Actual loss from timeout    $0 (lucky)        $0 (lucky)        -$29.60 (held to 0)
```

### Net effect of fixes on iter_035

| Fix | Orders affected | Financial impact |
|-----|----------------|------------------|
| **Partial fill fallback** | #1 | Captures 37.15 shares. Would have lost here, but systemically prevents silent fill drops. |
| **BUY drift guard** | #2 | Skips a 14.8% stale order. Saved -$35.70 loss (lucky, but correct behavior). |
| **SELL reprice** | #3 | Reprices from $0.52 → $0.19. Salvages ~$7.60 instead of -$29.60 total loss. **Biggest impact.** |
| **BUY reprice** | #1 | Reprices from $0.56 → $0.57. Marginal improvement on fill likelihood. |
| **Spread guard** | None triggered | Would catch future cases where BUY spread > 5% at submit time. |
