"""Domain models for raw data collection. No indicators -- pure market state."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Snapshot:
    """Single point-in-time market observation. Collected every ~5 seconds."""

    timestamp: float
    tick_timestamp: float
    candle_id: str
    elapsed_pct: float
    btc_price: float
    btc_bid: float
    btc_ask: float
    up_bids: tuple[tuple[float, float], ...]
    up_asks: tuple[tuple[float, float], ...]
    down_bids: tuple[tuple[float, float], ...]
    down_asks: tuple[tuple[float, float], ...]
    up_last_trade: float | None
    down_last_trade: float | None
    market_volume: float


@dataclass(frozen=True)
class CandleRecord:
    """One completed candle with outcome. Snapshots linked by candle_id in DB."""

    candle_id: str
    start_time: float
    end_time: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    outcome: str  # "UP" | "DOWN"
    final_ret: float  # ln(close / open)

    @classmethod
    def from_ws(cls, d: dict) -> CandleRecord:
        """Decode a candle_close WS message into a CandleRecord."""
        return cls(
            candle_id=d.get("candle_id", ""),
            start_time=d.get("start_time", 0.0),
            end_time=d.get("end_time", 0.0),
            open=d["open"],
            high=d["high"],
            low=d["low"],
            close=d["close"],
            volume=d["volume"],
            outcome=d["outcome"],
            final_ret=d["final_ret"],
        )
