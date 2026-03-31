"""Core domain models — pure data, no external dependencies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BtcTick:
    """A single BTC/USD price observation from Chainlink Data Streams."""

    price: float
    bid: float
    ask: float
    timestamp: float  # observationsTimestamp (seconds since epoch)
