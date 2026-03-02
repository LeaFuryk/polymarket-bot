"""Live execution engine — real Polymarket CLOB orders via py-clob-client Level 2.

Uses GTC limit orders at the AI's evaluated price with a configurable TTL
(default 3s). If the order fills within the TTL, returns a SimulatedFill.
If not, cancels the order and returns None.

Returns the same SimulatedFill type as ExecutionSimulator, so everything
downstream (Portfolio, risk, dashboard, logs) works unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import partial

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType

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
    """Executes real trades on Polymarket CLOB via GTC limit orders.

    Safety layers:
    - Max order size cap
    - Min wallet balance check
    - Session kill switch (cumulative loss threshold)
    - GTC limit order with TTL (never pays more than AI's evaluated price)
    - Dry run mode (simulate limit order fill against live orderbook)
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
        funder = trading_config.proxy_wallet_address or None
        if not funder:
            logger.warning(
                "No proxy_wallet_address set — orders will use EOA as maker. "
                "Set POLYBOT_TRADING_PROXY_WALLET_ADDRESS to your Polymarket profile address."
            )
        else:
            logger.info("CLOB client funder (proxy wallet): %s", funder)
        self._client = ClobClient(
            host=api_config.polymarket_host,
            chain_id=trading_config.chain_id,
            key=trading_config.private_key,
            creds=creds,
            signature_type=2,  # POLY_GNOSIS_SAFE (Polymarket browser wallet proxy)
            funder=funder,     # proxy wallet address from polymarket.com/settings
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

        # Last skip reason (read by ai_decision.py for dashboard)
        self._last_skip_reason: str = ""

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

    @property
    def last_skip_reason(self) -> str:
        return self._last_skip_reason

    async def sync_balance(self) -> float:
        """Fetch real USDC balance from the CLOB."""
        loop = asyncio.get_event_loop()
        try:
            from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
            params = BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=2,
            )
            # On first sync, refresh server's cached allowance to ensure it's current
            if self._last_balance_sync == 0.0:
                try:
                    await loop.run_in_executor(
                        None, partial(self._client.update_balance_allowance, params)
                    )
                    logger.info("Refreshed COLLATERAL allowance on startup")
                except Exception:
                    logger.warning("Failed to refresh COLLATERAL allowance on startup", exc_info=True)

            result = await loop.run_in_executor(
                None, partial(self._client.get_balance_allowance, params)
            )
            # Balance and allowance are in raw USDC units (6 decimals)
            raw = float(result.get("balance", 0)) if isinstance(result, dict) else 0.0
            balance = raw / 1e6
            raw_allowance = float(result.get("allowance", 0)) if isinstance(result, dict) else 0.0
            allowance = raw_allowance / 1e6
            self._wallet_balance = balance
            self._last_balance_sync = time.time()
            if allowance < balance:
                logger.warning("USDC allowance $%.2f < balance $%.2f — orders may be rejected", allowance, balance)
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

        Places a GTC limit order at the AI's evaluated price (best_ask for BUY,
        best_bid for SELL) and waits up to limit_order_ttl_seconds for a fill.
        Cancels unfilled orders after timeout.

        Args:
            decision: The AI's trading decision.
            orderbook: The orderbook snapshot at AI decision time.

        Returns:
            SimulatedFill with real execution data, or None if skipped/failed.
        """
        self._last_skip_reason = ""

        if decision.action == Action.HOLD or decision.size <= 0:
            return None

        # --- Safety checks ---

        # Kill switch
        if self._kill_switch_active:
            self._last_skip_reason = "kill switch active"
            logger.warning("Live execution blocked: kill switch active")
            return None

        # Determine token ID
        from polybot.models import TokenSide
        if decision.token_side == TokenSide.DOWN:
            token_id = self._down_token_id
        else:
            token_id = self._up_token_id

        if not token_id:
            self._last_skip_reason = "no token_id"
            logger.error("Live execution blocked: no token_id for %s", decision.token_side.value)
            return None

        side = Side.BUY if decision.action == Action.BUY else Side.SELL

        # Determine limit price from the orderbook at AI decision time
        if side == Side.BUY:
            limit_price = orderbook.best_ask
        else:
            limit_price = orderbook.best_bid

        if limit_price is None:
            self._last_skip_reason = f"no {'ask' if side == Side.BUY else 'bid'} in orderbook"
            logger.warning("Live execution blocked: no %s in orderbook",
                           "ask" if side == Side.BUY else "bid")
            return None

        # Estimate order cost
        est_cost = limit_price * decision.size

        # Max order size cap
        if est_cost > self._config.max_order_size_usd:
            self._last_skip_reason = f"order ${est_cost:.2f} exceeds max ${self._config.max_order_size_usd:.2f}"
            logger.warning(
                "Live execution blocked: order $%.2f exceeds max $%.2f",
                est_cost, self._config.max_order_size_usd,
            )
            return None

        # Min wallet balance (BUY only, skipped in dry run)
        if side == Side.BUY and not self._config.dry_run and self._wallet_balance < self._config.min_wallet_balance_usd:
            self._last_skip_reason = f"wallet ${self._wallet_balance:.2f} below min ${self._config.min_wallet_balance_usd:.2f}"
            logger.warning(
                "Live execution blocked: wallet $%.2f below min $%.2f",
                self._wallet_balance, self._config.min_wallet_balance_usd,
            )
            return None

        # --- Submit limit order ---
        ttl = self._config.limit_order_ttl_seconds
        try:
            if self._config.dry_run:
                fill = await self._simulate_limit_order(
                    token_id=token_id,
                    side=side,
                    size=decision.size,
                    limit_price=limit_price,
                    ttl=ttl,
                )
            else:
                fill = await self._submit_limit_order(
                    token_id=token_id,
                    side=side,
                    size=decision.size,
                    limit_price=limit_price,
                    ttl=ttl,
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
                # Refresh CLOB server's cached balance/allowance after fill.
                # After BUY: server needs to know we hold conditional tokens (for future SELL).
                # After SELL: server needs to know we have more USDC (for future BUY).
                await self._refresh_allowance_after_fill(token_id, side)
            else:
                self._last_skip_reason = f"limit order timeout ({ttl}s)"
            return fill
        except Exception:
            logger.exception("Live execution failed")
            self._last_skip_reason = "execution error"
            return None

    async def _submit_limit_order(
        self,
        token_id: str,
        side: Side,
        size: float,
        limit_price: float,
        ttl: int,
    ) -> SimulatedFill | None:
        """Create and submit a GTC limit order, poll for fill, cancel on timeout."""
        loop = asyncio.get_event_loop()

        clob_side = "BUY" if side == Side.BUY else "SELL"

        order_args = OrderArgs(
            token_id=token_id,
            price=limit_price,
            size=size,
            side=clob_side,
            fee_rate_bps=0,
            expiration=0,
        )

        # Create the signed order
        signed_order = await loop.run_in_executor(
            None, partial(self._client.create_order, order_args)
        )

        # Post the order as GTC
        response = await loop.run_in_executor(
            None, partial(
                self._client.post_order,
                signed_order,
                OrderType.GTC,
            )
        )

        # Extract order ID from response
        order_id = None
        if isinstance(response, dict):
            order_id = response.get("orderID") or response.get("order_id") or response.get("id")
        else:
            order_id = getattr(response, "orderID", None) or getattr(response, "order_id", None) or getattr(response, "id", None)

        if not order_id:
            logger.warning("GTC order posted but no order_id in response: %s", response)
            # Try to parse as immediate fill
            return self._parse_order_response(response, side, size, limit_price)

        logger.info(
            "GTC limit order posted: %s %s %.1f @ %.4f (order_id=%s, ttl=%ds)",
            clob_side, token_id[:8], size, limit_price, order_id, ttl,
        )

        # Poll for fill
        for i in range(ttl):
            await asyncio.sleep(1.0)
            try:
                order_status = await loop.run_in_executor(
                    None, partial(self._client.get_order, order_id)
                )

                status = ""
                if isinstance(order_status, dict):
                    status = order_status.get("status", "").upper()
                else:
                    status = getattr(order_status, "status", "").upper()

                if status in ("MATCHED", "FILLED"):
                    logger.info("GTC order filled after %ds (order_id=%s)", i + 1, order_id)
                    # Cancel to clean up (already filled, but good hygiene)
                    try:
                        await loop.run_in_executor(
                            None, partial(self._client.cancel, order_id)
                        )
                    except Exception:
                        pass  # Already filled, cancel may fail — that's fine
                    return self._parse_order_response(order_status, side, size, limit_price)

                if status in ("CANCELLED", "EXPIRED", "REJECTED"):
                    logger.info("GTC order %s (order_id=%s)", status, order_id)
                    return None

            except Exception:
                logger.debug("Error polling order %s (attempt %d/%d)", order_id, i + 1, ttl, exc_info=True)

        # Timeout — cancel the order
        logger.info("GTC order timeout after %ds, cancelling (order_id=%s)", ttl, order_id)
        try:
            await loop.run_in_executor(
                None, partial(self._client.cancel, order_id)
            )
        except Exception:
            logger.warning("Failed to cancel timed-out order %s", order_id, exc_info=True)

        # Post-cancel verification: the order may have filled between last
        # poll and cancel. Re-check once to avoid missing a real fill.
        try:
            final_status = await loop.run_in_executor(
                None, partial(self._client.get_order, order_id)
            )
            status = ""
            if isinstance(final_status, dict):
                status = final_status.get("status", "").upper()
            else:
                status = getattr(final_status, "status", "").upper()

            if status in ("MATCHED", "FILLED"):
                logger.warning(
                    "GTC order filled AFTER cancel attempt (order_id=%s) — capturing fill",
                    order_id,
                )
                return self._parse_order_response(final_status, side, size, limit_price)
        except Exception:
            logger.warning("Post-cancel verification failed for %s", order_id, exc_info=True)

        return None

    async def _simulate_limit_order(
        self,
        token_id: str,
        side: Side,
        size: float,
        limit_price: float,
        ttl: int,
    ) -> SimulatedFill | None:
        """Dry run: simulate a limit order by polling the live orderbook.

        Re-fetches the orderbook up to `ttl` times (1s intervals). If the
        market crosses the limit price, returns a fill at the limit price.
        """
        logger.info(
            "DRY RUN: limit order simulation %s %.1f @ %.4f (ttl=%ds)",
            side.value, size, limit_price, ttl,
        )

        for i in range(ttl):
            fresh_ob = await self._refetch_orderbook(token_id)
            if fresh_ob is None:
                await asyncio.sleep(1.0)
                continue

            filled = False
            if side == Side.BUY:
                # BUY fills if fresh ask <= our limit price
                if fresh_ob.best_ask is not None and fresh_ob.best_ask <= limit_price:
                    filled = True
            else:
                # SELL fills if fresh bid >= our limit price
                if fresh_ob.best_bid is not None and fresh_ob.best_bid >= limit_price:
                    filled = True

            if filled:
                logger.info(
                    "DRY RUN: limit order filled after %ds (limit=%.4f)",
                    i, limit_price,
                )
                fee_bps = 20  # Polymarket taker fee
                notional = limit_price * size
                fee_amount = notional * (fee_bps / 10000)
                if side == Side.BUY:
                    total_cost = notional + fee_amount
                else:
                    total_cost = -(notional - fee_amount)
                return SimulatedFill(
                    side=side,
                    size=size,
                    fill_price=limit_price,
                    slippage_bps=0.0,
                    fee_amount=fee_amount,
                    total_cost=total_cost,
                )

            if i < ttl - 1:
                await asyncio.sleep(1.0)

        logger.info("DRY RUN: limit order timeout after %ds (limit=%.4f)", ttl, limit_price)
        return None

    async def _refetch_orderbook(self, token_id: str) -> OrderbookSnapshot | None:
        """Re-fetch orderbook from CLOB."""
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

    async def _refresh_allowance_after_fill(self, token_id: str, side: Side) -> None:
        """Refresh CLOB server's cached balance/allowance after a fill.

        After BUY: update CONDITIONAL allowance so the server knows we hold
        tokens and can SELL them later.
        After SELL: update COLLATERAL allowance so the server knows we have
        more USDC for future BUYs.
        """
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        loop = asyncio.get_event_loop()
        try:
            if side == Side.BUY:
                params = BalanceAllowanceParams(
                    asset_type=AssetType.CONDITIONAL,
                    token_id=token_id,
                    signature_type=2,
                )
            else:
                params = BalanceAllowanceParams(
                    asset_type=AssetType.COLLATERAL,
                    signature_type=2,
                )
            await loop.run_in_executor(
                None, partial(self._client.update_balance_allowance, params)
            )
            logger.info(
                "Refreshed %s allowance after %s fill",
                "conditional" if side == Side.BUY else "collateral",
                side.value,
            )
        except Exception:
            logger.warning("Failed to refresh allowance after %s fill", side.value, exc_info=True)

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

        if not success and status.upper() not in ("MATCHED", "FILLED"):
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
