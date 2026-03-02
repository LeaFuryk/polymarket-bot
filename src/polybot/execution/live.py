"""Live execution engine — real Polymarket CLOB orders via py-clob-client Level 2.

Uses GTC limit orders at the AI's evaluated price with a configurable TTL
(default 3s). Returns a LiveOrderResult with full execution telemetry
(orderbook snapshots, poll progression, fill source, balances) for every
limit order attempt. The SimulatedFill is nested inside LiveOrderResult.fill.
Returns None only for safety-check skips (kill switch, no token_id, etc.).
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import partial
from typing import Any

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType

from polybot.config import TradingConfig, ApiConfig
from polybot.models import (
    Action,
    LiveOrderResult,
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
            result = await loop.run_in_executor(
                None, partial(self._client.get_balance_allowance, params)
            )
            # Balance is in raw USDC units (6 decimals)
            raw = float(result.get("balance", 0)) if isinstance(result, dict) else 0.0
            balance = raw / 1e6
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

    @staticmethod
    def _snapshot_ob(ob: OrderbookSnapshot | None) -> dict[str, Any]:
        """Convert OrderbookSnapshot to compact telemetry dict."""
        if ob is None:
            return {}
        return {
            "best_bid": ob.best_bid,
            "best_ask": ob.best_ask,
            "bid_depth": round(ob.bid_depth, 2),
            "ask_depth": round(ob.ask_depth, 2),
            "spread_pct": round(ob.spread_pct, 4) if ob.spread_pct is not None else None,
        }

    async def execute(
        self,
        decision: TradingDecision,
        orderbook: OrderbookSnapshot,
    ) -> LiveOrderResult | None:
        """Execute a real CLOB order with safety checks.

        Places a GTC limit order at the AI's evaluated price (best_ask for BUY,
        best_bid for SELL) and waits up to limit_order_ttl_seconds for a fill.
        Cancels unfilled orders after timeout.

        Args:
            decision: The AI's trading decision.
            orderbook: The orderbook snapshot at AI decision time.

        Returns:
            LiveOrderResult with full telemetry, or None if skipped/failed.
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

        # --- Determine order size ---
        order_size = decision.size

        # For live SELLs, cap size to actual on-chain conditional token balance.
        # The paper portfolio tracks shares but on-chain balance may differ due
        # to rounding in the exchange contract's fill math.
        if side == Side.SELL and not self._config.dry_run:
            actual = await self._get_conditional_balance(token_id)
            if actual is not None and actual < order_size:
                logger.info(
                    "SELL size capped: %.4f → %.4f (on-chain balance)",
                    order_size, actual,
                )
                order_size = actual
            if actual is not None and actual <= 0:
                self._last_skip_reason = "no on-chain token balance"
                logger.warning("Live SELL blocked: no on-chain balance for token %s", token_id[:8])
                return None

        # --- Submit limit order ---
        ttl = self._config.limit_order_ttl_seconds
        try:
            if self._config.dry_run:
                result = await self._simulate_limit_order(
                    token_id=token_id,
                    side=side,
                    size=decision.size,
                    limit_price=limit_price,
                    ttl=ttl,
                )
            else:
                result = await self._submit_limit_order(
                    token_id=token_id,
                    side=side,
                    size=order_size,
                    limit_price=limit_price,
                    ttl=ttl,
                )

            # Populate decision-time orderbook on the result
            result.decision_ob_ask = orderbook.best_ask
            result.decision_ob_bid = orderbook.best_bid

            if result.fill:
                # Update wallet balance estimate
                if side == Side.BUY:
                    self._wallet_balance -= result.fill.total_cost
                else:
                    self._wallet_balance += abs(result.fill.total_cost)
                logger.info(
                    "LIVE %s %s %.1f @ %.4f (cost=$%.2f, fee=$%.4f)",
                    side.value, decision.token_side.value,
                    result.fill.size, result.fill.fill_price,
                    result.fill.total_cost, result.fill.fee_amount,
                )
                # Refresh CLOB server's cached balance/allowance after fill.
                await self._refresh_allowance_after_fill(token_id, side)
            else:
                self._last_skip_reason = f"limit order timeout ({ttl}s)"
            return result
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
    ) -> LiveOrderResult:
        """Create and submit a GTC limit order, poll for fill, cancel on timeout.

        The CLOB REST API has an async status propagation delay — an order can
        be matched by the matching engine while ``get_order`` still reports
        status "LIVE" for 1-3 seconds.  To avoid missing real fills we check
        *both* the ``status`` field **and** ``size_matched`` > 0 during polling,
        and after a timeout we verify via an on-chain balance check.

        Returns a LiveOrderResult with full telemetry regardless of fill outcome.
        """
        loop = asyncio.get_event_loop()
        result = LiveOrderResult(limit_price=limit_price, ttl_used=ttl)

        clob_side = "BUY" if side == Side.BUY else "SELL"

        # Snapshot pre-order balance so we can detect stealth fills later
        pre_balance = await self._get_conditional_balance(token_id)
        result.pre_balance = pre_balance

        # Snapshot orderbook at submit time
        fresh_ob = await self._refetch_orderbook(token_id)
        result.ob_at_submit = self._snapshot_ob(fresh_ob)

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
        result.submit_ts = time.time()

        # Extract order ID from response
        order_id = None
        if isinstance(response, dict):
            order_id = response.get("orderID") or response.get("order_id") or response.get("id")
        else:
            order_id = getattr(response, "orderID", None) or getattr(response, "order_id", None) or getattr(response, "id", None)

        if not order_id:
            logger.warning("GTC order posted but no order_id in response: %s", response)
            # Try to parse as immediate fill
            fill = self._parse_order_response(response, side, size, limit_price)
            if fill:
                result.fill = fill
                result.fill_ts = time.time()
                result.fill_source = "immediate"
            return result

        result.order_id = order_id
        logger.info(
            "GTC limit order posted: %s %s %.1f @ %.4f (order_id=%s, ttl=%ds)",
            clob_side, token_id[:8], size, limit_price, order_id, ttl,
        )

        # Poll for fill — check both status AND size_matched
        for i in range(ttl):
            await asyncio.sleep(1.0)
            try:
                order_status = await loop.run_in_executor(
                    None, partial(self._client.get_order, order_id)
                )

                status, sm = self._extract_order_fill_info(order_status)
                result.polls.append({"ts": time.time(), "status": status, "size_matched": sm})

                if status in ("MATCHED", "FILLED") or sm > 0:
                    fill_source = "status_poll" if status in ("MATCHED", "FILLED") else "size_matched"
                    logger.info(
                        "GTC order filled after %ds (order_id=%s, status=%s, size_matched=%.4f)",
                        i + 1, order_id, status, sm,
                    )
                    # Cancel to clean up (already filled, but good hygiene)
                    try:
                        await loop.run_in_executor(
                            None, partial(self._client.cancel, order_id)
                        )
                    except Exception:
                        pass  # Already filled, cancel may fail — that's fine

                    fill = self._parse_order_response(order_status, side, size, limit_price)
                    result.fill = fill
                    result.fill_ts = time.time()
                    result.fill_source = fill_source
                    result.final_order_status = status
                    result.size_matched = sm

                    # Snapshot orderbook at fill
                    end_ob = await self._refetch_orderbook(token_id)
                    result.ob_at_end = self._snapshot_ob(end_ob)

                    # Post-fill balance
                    result.post_balance = await self._get_conditional_balance(token_id)
                    return result

                if status in ("CANCELLED", "EXPIRED", "REJECTED"):
                    logger.info("GTC order %s (order_id=%s)", status, order_id)
                    result.final_order_status = status
                    result.cancel_ts = time.time()
                    end_ob = await self._refetch_orderbook(token_id)
                    result.ob_at_end = self._snapshot_ob(end_ob)
                    return result

            except Exception:
                logger.debug("Error polling order %s (attempt %d/%d)", order_id, i + 1, ttl, exc_info=True)
                result.polls.append({"ts": time.time(), "status": "ERROR", "size_matched": 0})

        # Timeout — cancel the order
        logger.info("GTC order timeout after %ds, cancelling (order_id=%s)", ttl, order_id)
        result.cancel_ts = time.time()
        try:
            await loop.run_in_executor(
                None, partial(self._client.cancel, order_id)
            )
        except Exception:
            logger.warning("Failed to cancel timed-out order %s", order_id, exc_info=True)

        # Snapshot orderbook at timeout
        end_ob = await self._refetch_orderbook(token_id)
        result.ob_at_end = self._snapshot_ob(end_ob)

        # Post-cancel verification: the CLOB API status update is async and
        # can lag 1-3s behind the matching engine.  Wait briefly, then check
        # both the order status and the on-chain balance.
        await asyncio.sleep(1.0)

        # Snapshot orderbook post-cancel (did price come back?)
        post_cancel_ob = await self._refetch_orderbook(token_id)
        result.ob_post_cancel = self._snapshot_ob(post_cancel_ob)

        try:
            final_status = await loop.run_in_executor(
                None, partial(self._client.get_order, order_id)
            )
            status, sm = self._extract_order_fill_info(final_status)
            result.final_order_status = status
            result.size_matched = sm

            if status in ("MATCHED", "FILLED") or sm > 0:
                logger.warning(
                    "GTC order filled AFTER cancel attempt (order_id=%s, status=%s, "
                    "size_matched=%.4f) — capturing fill",
                    order_id, status, sm,
                )
                fill = self._parse_order_response(final_status, side, size, limit_price)
                result.fill = fill
                result.fill_ts = time.time()
                result.fill_source = "post_cancel"
                result.post_balance = await self._get_conditional_balance(token_id)
                return result
        except Exception:
            logger.warning("Post-cancel status check failed for %s", order_id, exc_info=True)

        # Nuclear fallback: compare on-chain balance to detect stealth fills
        # where the CLOB API status never propagated to MATCHED.
        stealth_fill, post_bal = await self._detect_stealth_fill(
            token_id, side, size, limit_price, pre_balance, order_id,
        )
        result.post_balance = post_bal
        if stealth_fill:
            result.fill = stealth_fill
            result.fill_ts = time.time()
            result.fill_source = "stealth_balance"

        return result

    @staticmethod
    def _extract_order_fill_info(order_status) -> tuple[str, float]:
        """Extract status and size_matched from a get_order response.

        The CLOB API may update ``size_matched`` before the ``status``
        field transitions to MATCHED, so we always check both.
        """
        if isinstance(order_status, dict):
            status = order_status.get("status", "").upper()
            # size_matched comes as a string decimal from the CLOB API
            raw_sm = order_status.get("size_matched", order_status.get("sizeMatched", "0"))
        else:
            status = getattr(order_status, "status", "").upper()
            raw_sm = getattr(order_status, "size_matched", getattr(order_status, "sizeMatched", "0"))
        try:
            size_matched = float(raw_sm) if raw_sm else 0.0
        except (ValueError, TypeError):
            size_matched = 0.0
        return status, size_matched

    async def _detect_stealth_fill(
        self,
        token_id: str,
        side: Side,
        size: float,
        limit_price: float,
        pre_balance: float | None,
        order_id: str,
    ) -> tuple[SimulatedFill | None, float | None]:
        """Detect a fill by comparing on-chain balance before vs after order.

        If the CLOB API status never propagated (stays LIVE / goes CANCELLED)
        but the matching engine actually filled the order, the on-chain
        balance will differ from the pre-order snapshot.

        Returns (fill_or_none, post_balance).
        """
        if pre_balance is None:
            return None, None

        post_balance = await self._get_conditional_balance(token_id)
        if post_balance is None:
            return None, None

        if side == Side.BUY:
            # BUY: we should have MORE conditional tokens
            delta = post_balance - pre_balance
            if delta >= size * 0.9:  # allow 10% tolerance for rounding
                logger.warning(
                    "STEALTH FILL detected via balance check (order_id=%s): "
                    "pre=%.4f post=%.4f delta=%.4f (expected ~%.4f)",
                    order_id, pre_balance, post_balance, delta, size,
                )
                return self._make_fill_from_balance(side, delta, limit_price), post_balance
        else:
            # SELL: we should have FEWER conditional tokens
            delta = pre_balance - post_balance
            if delta >= size * 0.9:
                logger.warning(
                    "STEALTH FILL detected via balance check (order_id=%s): "
                    "pre=%.4f post=%.4f delta=%.4f (expected ~%.4f)",
                    order_id, pre_balance, post_balance, delta, size,
                )
                return self._make_fill_from_balance(side, delta, limit_price), post_balance

        return None, post_balance

    def _make_fill_from_balance(
        self, side: Side, fill_size: float, limit_price: float,
    ) -> SimulatedFill:
        """Construct a SimulatedFill from a balance-detected fill."""
        notional = limit_price * fill_size
        fee_bps = 20
        fee_amount = notional * (fee_bps / 10000)
        if side == Side.BUY:
            total_cost = notional + fee_amount
        else:
            total_cost = -(notional - fee_amount)
        return SimulatedFill(
            side=side,
            size=fill_size,
            fill_price=limit_price,
            slippage_bps=0.0,
            fee_amount=fee_amount,
            total_cost=total_cost,
        )

    async def _simulate_limit_order(
        self,
        token_id: str,
        side: Side,
        size: float,
        limit_price: float,
        ttl: int,
    ) -> LiveOrderResult:
        """Dry run: simulate a limit order by polling the live orderbook.

        Re-fetches the orderbook up to `ttl` times (1s intervals). If the
        market crosses the limit price, returns a fill at the limit price.
        Returns LiveOrderResult with available telemetry.
        """
        result = LiveOrderResult(limit_price=limit_price, ttl_used=ttl)
        result.submit_ts = time.time()

        logger.info(
            "DRY RUN: limit order simulation %s %.1f @ %.4f (ttl=%ds)",
            side.value, size, limit_price, ttl,
        )

        # Snapshot initial orderbook
        first_ob = await self._refetch_orderbook(token_id)
        result.ob_at_submit = self._snapshot_ob(first_ob)

        for i in range(ttl):
            fresh_ob = await self._refetch_orderbook(token_id)
            if fresh_ob is None:
                result.polls.append({"ts": time.time(), "status": "NO_OB", "size_matched": 0})
                await asyncio.sleep(1.0)
                continue

            ob_snap = self._snapshot_ob(fresh_ob)
            result.polls.append({
                "ts": time.time(),
                "status": "POLLING",
                "size_matched": 0,
                "best_ask": ob_snap.get("best_ask"),
                "best_bid": ob_snap.get("best_bid"),
            })

            filled = False
            if side == Side.BUY:
                if fresh_ob.best_ask is not None and fresh_ob.best_ask <= limit_price:
                    filled = True
            else:
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
                result.fill = SimulatedFill(
                    side=side,
                    size=size,
                    fill_price=limit_price,
                    slippage_bps=0.0,
                    fee_amount=fee_amount,
                    total_cost=total_cost,
                )
                result.fill_ts = time.time()
                result.fill_source = "dry_run"
                result.ob_at_end = ob_snap
                return result

            if i < ttl - 1:
                await asyncio.sleep(1.0)

        logger.info("DRY RUN: limit order timeout after %ds (limit=%.4f)", ttl, limit_price)
        result.cancel_ts = time.time()
        # Snapshot final orderbook
        end_ob = await self._refetch_orderbook(token_id)
        result.ob_at_end = self._snapshot_ob(end_ob)
        return result

    async def _get_conditional_balance(self, token_id: str) -> float | None:
        """Query actual on-chain conditional token balance from the CLOB server."""
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        loop = asyncio.get_event_loop()
        try:
            params = BalanceAllowanceParams(
                asset_type=AssetType.CONDITIONAL,
                token_id=token_id,
                signature_type=2,
            )
            result = await loop.run_in_executor(
                None, partial(self._client.get_balance_allowance, params)
            )
            raw = float(result.get("balance", 0)) if isinstance(result, dict) else 0.0
            # Conditional token balance is in 6-decimal units (like USDC)
            balance = raw / 1e6
            logger.debug("Conditional balance for %s: %.4f (raw=%s)", token_id[:8], balance, raw)
            return balance
        except Exception:
            logger.warning("Failed to query conditional balance for %s", token_id[:8], exc_info=True)
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
