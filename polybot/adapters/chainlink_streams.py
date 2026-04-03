"""Adapter: Chainlink Data Streams WebSocket client."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator

import websockets

from polybot.domain.models import BtcTick

WS_BASE_URL = "wss://ws.dataengine.chain.link"
WS_PATH = "/api/v1/ws"

# ABI types for two-stage report decoding
_OUTER_ABI = ["bytes32[3]", "bytes", "bytes32[]", "bytes32[]", "bytes32"]
_V3_ABI = [
    "bytes32",  # feedId
    "uint32",  # validFromTimestamp
    "uint32",  # observationsTimestamp
    "uint192",  # nativeFee
    "uint192",  # linkFee
    "uint32",  # expiresAt
    "int192",  # benchmarkPrice
    "int192",  # bid
    "int192",  # ask
]
_PRICE_DECIMALS = 10**18

# BTC/USD Crypto Streams feed
BTC_USD_FEED_ID = "0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8"


class ChainlinkStreamsAdapter:
    """PriceStream implementation using Chainlink Data Streams WebSocket.

    Connects to the Chainlink Data Streams WebSocket, authenticates via
    HMAC-SHA256 headers during the HTTP upgrade, and yields decoded
    BtcTick objects for each incoming V3 report.
    """

    def __init__(
        self,
        user_id: str,
        secret: str,
        feed_id: str = BTC_USD_FEED_ID,
        ws_base_url: str = WS_BASE_URL,
        max_reconnect_retries: int = 5,
        logger: logging.Logger | None = None,
    ) -> None:
        self._user_id = user_id
        self._secret = secret
        self._feed_id = feed_id
        self._ws_base_url = ws_base_url
        self._max_reconnect_retries = max_reconnect_retries
        self._log = logger or logging.getLogger(__name__)
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._running = False

    # -- Public interface (PriceStream) ------------------------------------

    async def connect(self) -> None:
        """Open WebSocket and authenticate via HMAC headers."""
        path = f"{WS_PATH}?feedIDs={self._feed_id}"
        url = f"{self._ws_base_url}{path}"
        headers = self._build_auth_headers("GET", path)

        self._log.info("Connecting to Chainlink Data Streams: %s", url)
        self._ws = await websockets.connect(url, additional_headers=headers)
        self._running = True
        self._log.info("🔗 Connected to Chainlink Data Streams")

    async def disconnect(self) -> None:
        """Close WebSocket connection."""
        self._running = False
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
            self._log.info("Disconnected from Chainlink Data Streams")

    async def ticks(self) -> AsyncIterator[BtcTick]:
        """Yield BtcTick for each incoming V3 report."""
        if self._ws is None:
            raise RuntimeError("Not connected — call connect() first")

        while self._running:
            try:
                raw = await self._ws.recv()
                tick = self._parse_message(raw)
                if tick is not None:
                    yield tick
            except websockets.ConnectionClosed:
                self._log.warning("WebSocket connection closed")
                if self._running:
                    await self._reconnect()
            except Exception:
                self._log.exception("Error processing WebSocket message")

    # -- Auth --------------------------------------------------------------

    def _build_auth_headers(self, method: str, path: str, body: bytes = b"") -> dict[str, str]:
        """Generate the 3 HMAC-SHA256 authentication headers."""
        timestamp = int(time.time() * 1000)
        body_hash = hashlib.sha256(body).hexdigest()
        string_to_sign = f"{method} {path} {body_hash} {self._user_id} {timestamp}"
        signature = hmac.new(
            self._secret.encode(),
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()

        return {
            "Authorization": self._user_id,
            "X-Authorization-Timestamp": str(timestamp),
            "X-Authorization-Signature-SHA256": signature,
        }

    # -- Parsing -----------------------------------------------------------

    def _parse_message(self, raw: str | bytes) -> BtcTick | None:
        """Parse a WebSocket message into a BtcTick."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._log.warning("Non-JSON message received: %s", raw[:100])
            return None

        report = data.get("report")
        if report is None:
            self._log.debug("Message without report key: %s", data)
            return None

        full_report_hex = report.get("fullReport")
        if full_report_hex is None:
            self._log.warning("Report missing fullReport field")
            return None

        return self._decode_v3_report(full_report_hex)

    def _decode_v3_report(self, full_report_hex: str) -> BtcTick | None:
        """Decode ABI-encoded V3 report into BtcTick."""
        from eth_abi import decode

        try:
            hex_str = full_report_hex
            if hex_str.startswith("0x") or hex_str.startswith("0X"):
                hex_str = hex_str[2:]

            report_bytes = bytes.fromhex(hex_str)
            _, report_blob, _, _, _ = decode(_OUTER_ABI, report_bytes)
            v3 = decode(_V3_ABI, report_blob)

            return BtcTick(
                price=float(v3[6]) / _PRICE_DECIMALS,
                bid=float(v3[7]) / _PRICE_DECIMALS,
                ask=float(v3[8]) / _PRICE_DECIMALS,
                timestamp=float(v3[2]),
            )
        except Exception:
            self._log.exception("Failed to decode V3 report")
            return None

    # -- Reconnect ---------------------------------------------------------

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        self._ws = None
        base_delay = 1.0

        for attempt in range(1, self._max_reconnect_retries + 1):
            delay = base_delay * 2 ** (attempt - 1)
            self._log.info("Reconnect attempt %d/%d in %.1fs", attempt, self._max_reconnect_retries, delay)
            await asyncio.sleep(delay)
            try:
                await self.connect()
                return
            except Exception:
                self._log.warning("Reconnect attempt %d/%d failed", attempt, self._max_reconnect_retries)

        self._log.error("All reconnect attempts exhausted, stopping stream")
        self._running = False
