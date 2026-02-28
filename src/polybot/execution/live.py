"""Live execution engine — real Polymarket CLOB orders via py-clob-client Level 2.

Returns the same SimulatedFill type as ExecutionSimulator, so everything
downstream (Portfolio, risk, dashboard, logs) works unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import partial

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, MarketOrderArgs, OrderType

from polybot.config import TradingConfig, ApiConfig
from polybot.models import (
    Action,
    OrderbookSnapshot,
    Side,
    SimulatedFill,
    TradingDecision,
)

logger = logging.getLogger(__name__)


class LiveExecutionEngine:
    """Executes real trades on Polymarket CLOB via FOK market orders.

    Safety layers:
    - Max order size cap
    - Min wallet balance check
    - Session kill switch (cumulative loss threshold)
    - Stale price mitigation (re-fetch + drift check)
    - Dry run mode (sign but don't post)
    """

    def __init__(self, trading_config: TradingConfig, api_config: ApiConfig) -> None:
        self._config = trading_config
        self._api_config = api_config

        # Create Level 2 CLOB client
        creds = ApiCreds(
            api_key=trading_config.api_key,
            api_secret=trading_config.api_secret,
            api_passphrase=trading_config.api_passphrase,
        )
        self._client = ClobClient(
            host=api_config.polymarket_host,
            chain_id=trading_config.chain_id,
            key=trading_config.private_key,
            creds=creds,
        )

        # Token IDs for current market (set before each execute call)
        self._up_token_id: str = ""
        self._down_token_id: str = ""

        # Kill switch state
        self._kill_switch_active: bool = False
        self._session_pnl: float = 0.0

        # Wallet balance (synced periodically)
        self._wallet_balance: float = 0.0
        self._last_balance_sync: float = 0.0

    def set_current_token_ids(self, up_id: str, down_id: str) -> None:
        """Set token IDs for the current candle market."""
        self._up_token_id = up_id
        self._down_token_id = down_id

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    @property
    def wallet_balance(self) -> float:
        return self._wallet_balance

    async def sync_balance(self) -> float:
        """Fetch real USDC balance from the CLOB."""
        loop = asyncio.get_event_loop()
        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            params = BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
            )
            result = await loop.run_in_executor(
                None, partial(self._client.get_balance_allowance, params)
            )
            balance = float(result.get("balance", 0)) if isinstance(result, dict) else 0.0
            self._wallet_balance = balance
            self._last_balance_sync = time.time()
            return balance
        except Exception:
            logger.exception("Failed to sync wallet balance")
            return self._wallet_balance

    def check_kill_switch(self, session_pnl: float) -> bool:
        """Activate kill switch if session loss exceeds threshold."""
        self._session_pnl = session_pnl
        if session_pnl < -self._config.max_session_loss_usd:
            if not self._kill_switch_active:
                logger.critical(
                    "KILL SWITCH ACTIVATED: session PnL $%.2f exceeds -$%.2f limit",
                    session_pnl, self._config.max_session_loss_usd,
                )
                self._kill_switch_active = True
            return True
        return False

    async def cancel_all_orders(self) -> int:
        """Cancel all open orders on the CLOB."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, self._client.cancel_all
            )
            cancelled = len(result) if isinstance(result, list) else 0
            if cancelled:
                logger.info("Cancelled %d live CLOB orders", cancelled)
            return cancelled
        except Exception:
            logger.exception("Failed to cancel CLOB orders")
            return 0

    async def execute(
        self,
        decision: TradingDecision,
        orderbook: OrderbookSnapshot,
    ) -> SimulatedFill | None:
        """Execute a real CLOB order with safety checks.

        Args:
            decision: The AI's trading decision.
            orderbook: The orderbook snapshot at AI decision time (used for drift check).

        Returns:
            SimulatedFill with real execution data, or None if skipped/failed.
        """
        if decision.action == Action.HOLD or decision.size <= 0:
            return None

        # --- Safety checks ---

        # Kill switch
        if self._kill_switch_active:
            logger.warning("Live execution blocked: kill switch active")
            return None

        # Determine token ID
        from polybot.models import TokenSide
        if decision.token_side == TokenSide.DOWN:
            token_id = self._down_token_id
        else:
            token_id = self._up_token_id

        if not token_id:
            logger.error("Live execution blocked: no token_id for %s", decision.token_side.value)
            return None

        side = Side.BUY if decision.action == Action.BUY else Side.SELL

        # --- Stale price mitigation: re-fetch orderbook ---
        fresh_ob = await self._refetch_orderbook(token_id)
        if fresh_ob is None:
            logger.warning("Live execution blocked: could not re-fetch orderbook")
            return None

        # Get the fresh price to use
        if side == Side.BUY:
            fresh_price = fresh_ob.best_ask
            stale_price = orderbook.best_ask
        else:
            fresh_price = fresh_ob.best_bid
            stale_price = orderbook.best_bid

        if fresh_price is None:
            logger.warning("Live execution blocked: no %s in fresh orderbook",
                           "ask" if side == Side.BUY else "bid")
            return None

        # Drift check
        if stale_price is not None and stale_price > 0:
            drift = abs(fresh_price - stale_price) / stale_price
            if drift > self._config.max_price_drift_pct:
                logger.warning(
                    "Live execution SKIPPED: price drifted %.1f%% (stale=%.4f fresh=%.4f, max=%.1f%%)",
                    drift * 100, stale_price, fresh_price,
                    self._config.max_price_drift_pct * 100,
                )
                return None

        # Estimate order cost
        est_cost = fresh_price * decision.size

        # Max order size cap
        if est_cost > self._config.max_order_size_usd:
            logger.warning(
                "Live execution blocked: order $%.2f exceeds max $%.2f",
                est_cost, self._config.max_order_size_usd,
            )
            return None

        # Min wallet balance (BUY only, skipped in dry run)
        if side == Side.BUY and not self._config.dry_run and self._wallet_balance < self._config.min_wallet_balance_usd:
            logger.warning(
                "Live execution blocked: wallet $%.2f below min $%.2f",
                self._wallet_balance, self._config.min_wallet_balance_usd,
            )
            return None

        # --- Submit FOK order ---
        try:
            fill = await self._submit_fok_order(
                token_id=token_id,
                side=side,
                size=decision.size,
                price=fresh_price,
            )
            if fill:
                # Update wallet balance estimate
                if side == Side.BUY:
                    self._wallet_balance -= fill.total_cost
                else:
                    self._wallet_balance += abs(fill.total_cost)
                logger.info(
                    "LIVE %s %s %.1f @ %.4f (cost=$%.2f, fee=$%.4f)",
                    side.value, decision.token_side.value,
                    fill.size, fill.fill_price, fill.total_cost, fill.fee_amount,
                )
            return fill
        except Exception:
            logger.exception("Live execution failed")
            return None

    async def _refetch_orderbook(self, token_id: str) -> OrderbookSnapshot | None:
        """Re-fetch orderbook for stale price check."""
        from polybot.models import OrderbookLevel
        loop = asyncio.get_event_loop()
        try:
            raw = await loop.run_in_executor(
                None, partial(self._client.get_order_book, token_id)
            )
            raw_bids = raw.bids if hasattr(raw, "bids") else (raw.get("bids") or [])
            raw_asks = raw.asks if hasattr(raw, "asks") else (raw.get("asks") or [])

            def _parse(item) -> OrderbookLevel:
                if hasattr(item, "price"):
                    return OrderbookLevel(price=float(item.price), size=float(item.size))
                return OrderbookLevel(price=float(item["price"]), size=float(item["size"]))

            bids = sorted([_parse(b) for b in raw_bids], key=lambda x: x.price, reverse=True)
            asks = sorted([_parse(a) for a in raw_asks], key=lambda x: x.price)
            return OrderbookSnapshot(bids=bids, asks=asks)
        except Exception:
            logger.exception("Failed to re-fetch orderbook for %s", token_id)
            return None

    async def _submit_fok_order(
        self,
        token_id: str,
        side: Side,
        size: float,
        price: float,
    ) -> SimulatedFill | None:
        """Create and submit a FOK market order, returning a SimulatedFill."""
        loop = asyncio.get_event_loop()

        clob_side = "BUY" if side == Side.BUY else "SELL"

        # For BUY: amount is in USDC (dollar amount to spend)
        # For SELL: amount is in shares (number of shares to sell)
        if side == Side.BUY:
            amount = size * price  # convert shares to USDC amount
        else:
            amount = size  # shares

        order_args = MarketOrderArgs(
            token_id=token_id,
            amount=amount,
            side=clob_side,
            fee_rate_bps=0,
            price=price,
        )

        # Create the signed order
        signed_order = await loop.run_in_executor(
            None, partial(self._client.create_market_order, order_args)
        )

        if self._config.dry_run:
            # Dry run: don't post, simulate the fill
            logger.info("DRY RUN: order signed but not posted (side=%s, amount=%.2f)", clob_side, amount)
            fee_bps = 20  # Polymarket taker fee
            notional = price * size
            fee_amount = notional * (fee_bps / 10000)
            if side == Side.BUY:
                total_cost = notional + fee_amount
            else:
                total_cost = -(notional - fee_amount)
            return SimulatedFill(
                side=side,
                size=size,
                fill_price=price,
                slippage_bps=0.0,
                fee_amount=fee_amount,
                total_cost=total_cost,
            )

        # Post the order
        response = await loop.run_in_executor(
            None, partial(
                self._client.post_order,
                signed_order,
                OrderType.FOK,
            )
        )

        return self._parse_order_response(response, side, size, price)

    def _parse_order_response(
        self,
        response,
        side: Side,
        requested_size: float,
        requested_price: float,
    ) -> SimulatedFill | None:
        """Parse CLOB order response into a SimulatedFill."""
        if response is None:
            logger.warning("CLOB order returned None response")
            return None

        # Response may be a dict or object
        if isinstance(response, dict):
            success = response.get("success", False)
            status = response.get("status", "")
        else:
            success = getattr(response, "success", False)
            status = getattr(response, "status", "")

        if not success and status not in ("matched", "MATCHED"):
            logger.warning("CLOB order not filled: %s", response)
            return None

        # Extract fill details from response
        # The response structure varies — extract what we can
        fill_price = requested_price  # Use requested if not in response
        fill_size = requested_size

        if isinstance(response, dict):
            # Try to get actual fill data
            if "averagePrice" in response:
                fill_price = float(response["averagePrice"])
            if "filledAmount" in response:
                fill_size = float(response["filledAmount"])
        else:
            if hasattr(response, "averagePrice"):
                fill_price = float(response.averagePrice)
            if hasattr(response, "filledAmount"):
                fill_size = float(response.filledAmount)

        # Compute costs
        slippage_bps = abs(fill_price - requested_price) / requested_price * 10000 if requested_price > 0 else 0
        notional = fill_price * fill_size
        fee_bps = 20  # Polymarket taker fee
        fee_amount = notional * (fee_bps / 10000)

        if side == Side.BUY:
            total_cost = notional + fee_amount
        else:
            total_cost = -(notional - fee_amount)

        return SimulatedFill(
            side=side,
            size=fill_size,
            fill_price=fill_price,
            slippage_bps=slippage_bps,
            fee_amount=fee_amount,
            total_cost=total_cost,
        )
