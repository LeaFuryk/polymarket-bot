# resolution — Candle market winner determination

Determines who won each 5-minute BTC candle market by comparing open/close
prices, then verifies against Polymarket's on-chain resolution.

## Architecture

```
checker.py     Pure functions: determine_btc_winner, determine_polymarket_winner
verifier.py    Async verification against Polymarket token prices
tracker.py     ResolutionTracker — orchestrates open-price recording + resolution
constants.py   Price thresholds for winner determination
__init__.py    Re-exports for backward-compatible imports
```

## Resolution flow

```
1. record_candle_open(market, btc_price)    ← at candle start
2. resolve(market, current_btc_price)       ← at candle rotation
   ├─ determine_btc_winner(open, close)     ← pure, fast
   ├─ verify_winner(market, btc_winner)     ← async, checks Polymarket
   │   ├─ get_last_trade_price(UP token)
   │   ├─ get_last_trade_price(DOWN token)
   │   └─ determine_polymarket_winner(up, down)
   └─ return ResolutionRecord
```

## Winner determination

**BTC-based** (primary): `close >= open` → UP wins (tie goes to UP per Polymarket rules).

**Polymarket verification**: After resolution, winning token trades at ~$1, loser at ~$0.

| Signal strength | Winner price | Loser price |
|----------------|-------------|-------------|
| High confidence | > 0.85 | < 0.15 |
| Clear signal | > 0.65 | < 0.35 |
| Ambiguous | — | — → fall back to BTC |

If Polymarket disagrees with BTC, Polymarket is authoritative (resolves via Chainlink Data Streams).

## Error handling

- No live open price → fetch from Binance historical
- Binance unavailable → default to close price (UP wins on tie)
- Polymarket API failure → use BTC-based winner
- Ambiguous token prices → use BTC-based winner
