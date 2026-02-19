"""BTC spot price feed — Binance real-time (primary) + Chainlink on-chain (cross-reference).

Polymarket resolves using Chainlink BTC/USD Data Streams, but the on-chain
Chainlink Price Feed aggregator only updates every ~1 hour or 0.5% deviation —
far too stale for 5-minute candle resolution. We use Binance BTCUSDT spot price
as the primary source since Chainlink Data Streams aggregate from major CEXs
including Binance, giving us a close approximation at real-time frequency.

Chainlink on-chain price is fetched as a secondary cross-reference and logged.
CoinGecko provides 24h change percentage.
"""

from __future__ import annotations

import logging
import time

import httpx

from polybot.config import ApiConfig
from polybot.models import BtcCandle, BtcPrice

logger = logging.getLogger(__name__)

CACHE_TTL = 30  # seconds

# Chainlink BTC/USD Price Feed on Ethereum mainnet
# latestRoundData() function selector
LATEST_ROUND_DATA_SELECTOR = "0xfeaf968c"
# Chainlink BTC/USD uses 8 decimal places
CHAINLINK_DECIMALS = 8


class BtcPriceFeed:
    """Fetches BTC/USD price from Chainlink on-chain, with CoinGecko fallback."""

    # Full candle history refresh interval (seconds)
    _CANDLE_REFRESH_INTERVAL = 600  # 10 minutes

    def __init__(self, api_config: ApiConfig) -> None:
        self._coingecko_url = api_config.coingecko_url
        self._rpc_url = api_config.ethereum_rpc_url
        self._chainlink_address = api_config.chainlink_btcusd_address
        self._client = httpx.AsyncClient(timeout=10.0)
        self._cache: BtcPrice | None = None
        self._cache_time: float = 0.0
        self._candles: list[BtcCandle] = []
        self._candle_refresh_time: float = 0.0
        # Separate cache for 24h change from CoinGecko (updates less frequently)
        self._24h_change_pct: float = 0.0
        self._24h_change_time: float = 0.0

    @property
    def candles(self) -> list[BtcCandle]:
        """Return only completed candles (close_time in the past)."""
        now = time.time()
        return [c for c in self._candles if c.close_time < now]

    # --- 5-min candle history (Binance — for trend analysis only) ---

    async def load_candle_history(self, limit: int = 200) -> None:
        """Fetch historical 5-min OHLCV candles from Binance."""
        try:
            resp = await self._client.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "5m",
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            self._candles = [
                BtcCandle(
                    open_time=float(k[0]) / 1000,
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    close_time=float(k[6]) / 1000,
                )
                for k in data
            ]
            # Drop the last candle — Binance always includes the in-progress
            # (incomplete) candle whose close/high/low will change before it
            # finalizes.  Keeping it would give the AI a wrong direction signal
            # that append_latest_candle() can never correct.
            if self._candles:
                self._candles.pop()
            self._candle_refresh_time = time.time()
            logger.info("Loaded %d 5-min BTC candles from Binance", len(self._candles))
        except Exception:
            logger.exception("Failed to load BTC candle history")

    async def append_latest_candle(self) -> None:
        """Fetch the latest 2 candles and append the completed one if new.

        Also triggers a full refresh every _CANDLE_REFRESH_INTERVAL seconds
        to correct any accumulated drift.
        """
        # Periodic full refresh to correct any stale data
        if time.time() - self._candle_refresh_time > self._CANDLE_REFRESH_INTERVAL:
            logger.info("Periodic candle history refresh (every %ds)", self._CANDLE_REFRESH_INTERVAL)
            await self.load_candle_history(200)
            return

        try:
            resp = await self._client.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "5m",
                    "limit": 2,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return
            # The first candle is the most recently completed one
            completed = data[0]
            candle = BtcCandle(
                open_time=float(completed[0]) / 1000,
                open=float(completed[1]),
                high=float(completed[2]),
                low=float(completed[3]),
                close=float(completed[4]),
                volume=float(completed[5]),
                close_time=float(completed[6]) / 1000,
            )
            # Append if newer, or replace the last entry if same open_time
            # (corrects a stale incomplete candle from the initial load)
            if not self._candles or candle.open_time > self._candles[-1].open_time:
                self._candles.append(candle)
            elif candle.open_time == self._candles[-1].open_time:
                self._candles[-1] = candle
                # Cap at 200
                if len(self._candles) > 200:
                    self._candles = self._candles[-200:]
        except Exception:
            logger.exception("Failed to append latest BTC candle")

    # --- Chainlink on-chain price (primary — matches Polymarket resolution source) ---

    async def _fetch_chainlink_price(self) -> float | None:
        """Read latestRoundData() from Chainlink BTC/USD aggregator on Ethereum.

        Returns BTC price in USD or None on failure.
        """
        try:
            resp = await self._client.post(
                self._rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [
                        {
                            "to": self._chainlink_address,
                            "data": LATEST_ROUND_DATA_SELECTOR,
                        },
                        "latest",
                    ],
                    "id": 1,
                },
            )
            resp.raise_for_status()
            result = resp.json()

            if "error" in result:
                logger.warning("Chainlink RPC error: %s", result["error"])
                return None

            hex_data = result.get("result", "")
            if not hex_data or hex_data == "0x" or len(hex_data) < 66:
                logger.warning("Chainlink returned empty/invalid data")
                return None

            # latestRoundData returns: (uint80 roundId, int256 answer, uint256 startedAt,
            #                           uint256 updatedAt, uint80 answeredInRound)
            # Each value is 32 bytes (64 hex chars). answer is at offset 32-64 bytes.
            # Strip "0x" prefix, then answer starts at char 64 (second 32-byte word)
            hex_clean = hex_data[2:]
            answer_hex = hex_clean[64:128]
            answer_int = int(answer_hex, 16)

            # Handle signed int256 (if somehow negative, which shouldn't happen for price)
            if answer_int >= 2**255:
                answer_int -= 2**256

            price = answer_int / (10 ** CHAINLINK_DECIMALS)

            if price <= 0:
                logger.warning("Chainlink returned non-positive price: %s", price)
                return None

            logger.debug("Chainlink BTC/USD: $%.2f", price)
            return price

        except Exception:
            logger.exception("Failed to fetch Chainlink BTC/USD price")
            return None

    # --- CoinGecko (fallback + 24h change) ---

    async def _fetch_coingecko_24h_change(self) -> float:
        """Fetch 24h change % from CoinGecko. Returns 0.0 on failure."""
        now = time.time()
        # Only refresh every 5 minutes — 24h change is a slow-moving metric
        if (now - self._24h_change_time) < 300:
            return self._24h_change_pct

        try:
            resp = await self._client.get(
                f"{self._coingecko_url}/simple/price",
                params={
                    "ids": "bitcoin",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                },
            )
            resp.raise_for_status()
            data = resp.json().get("bitcoin", {})
            self._24h_change_pct = data.get("usd_24h_change", 0.0)
            self._24h_change_time = now
            return self._24h_change_pct
        except Exception:
            logger.debug("CoinGecko 24h change fetch failed, using cached value")
            return self._24h_change_pct

    async def _fetch_coingecko_price(self) -> float | None:
        """Fallback: fetch BTC price from CoinGecko if Chainlink is unavailable."""
        try:
            resp = await self._client.get(
                f"{self._coingecko_url}/simple/price",
                params={
                    "ids": "bitcoin",
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                },
            )
            resp.raise_for_status()
            data = resp.json().get("bitcoin", {})
            self._24h_change_pct = data.get("usd_24h_change", 0.0)
            self._24h_change_time = time.time()
            return data.get("usd")
        except Exception:
            logger.exception("CoinGecko price fetch also failed")
            return None

    # --- Binance real-time spot price (primary) ---

    async def _fetch_binance_price(self) -> float | None:
        """Fetch BTC/USDT spot price from Binance. Fast and real-time."""
        try:
            resp = await self._client.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": "BTCUSDT"},
            )
            resp.raise_for_status()
            price = float(resp.json()["price"])
            logger.debug("Binance BTC/USDT: $%.2f", price)
            return price
        except Exception:
            logger.exception("Failed to fetch Binance BTC/USDT price")
            return None

    # --- Main price method ---

    async def get_price(self) -> BtcPrice | None:
        """Get current BTC/USD price. Binance primary, CoinGecko fallback.

        Also fetches Chainlink on-chain as cross-reference (logged but not used
        for resolution, since the on-chain feed is too stale for 5-min candles).
        """
        now = time.time()
        if self._cache and (now - self._cache_time) < CACHE_TTL:
            return self._cache

        # Primary: Binance real-time spot price
        price_usd = await self._fetch_binance_price()
        source = "binance"

        if price_usd is None:
            # Fallback to CoinGecko
            logger.warning("Binance unavailable, falling back to CoinGecko")
            price_usd = await self._fetch_coingecko_price()
            source = "coingecko"

        if price_usd is None:
            logger.error("All BTC price sources failed")
            return self._cache  # return stale cache

        # Cross-reference: fetch Chainlink on-chain (async, non-blocking, just for logging)
        chainlink_price = await self._fetch_chainlink_price()
        if chainlink_price is not None and price_usd:
            diff = abs(price_usd - chainlink_price)
            logger.debug(
                "Price cross-ref: Binance=$%.2f Chainlink=$%.2f diff=$%.2f",
                price_usd, chainlink_price, diff,
            )

        # Get 24h change from CoinGecko (non-blocking, cached separately)
        change_24h = await self._fetch_coingecko_24h_change()

        price = BtcPrice(
            price_usd=price_usd,
            change_24h_pct=change_24h,
        )
        self._cache = price
        self._cache_time = now

        logger.debug("BTC price: $%.2f (source=%s, 24h=%+.2f%%)", price_usd, source, change_24h)
        return price

    async def get_price_at(self, timestamp: float) -> float | None:
        """Get BTC price at a specific timestamp via Binance klines API.

        Used as fallback for resolution when live open price wasn't captured.
        Returns the close price of the 1-minute candle containing the timestamp,
        or None on failure.
        """
        ts_ms = int(timestamp * 1000)
        try:
            resp = await self._client.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "startTime": ts_ms,
                    "limit": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data and len(data) > 0:
                close_price = float(data[0][4])
                return close_price
        except Exception:
            logger.exception("Failed to fetch historical BTC price at %.0f", timestamp)
        return None

    async def close(self) -> None:
        await self._client.aclose()
