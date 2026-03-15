"""PrefilterChecker — runs the prefilter gate and builds a snapshot record."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from polybot.indicators.helpers import compute_rr
from polybot.prefilter.result import PreFilterResult
from polybot.shared_state import PreFilterSnapshot

if TYPE_CHECKING:
    from polybot.models import MarketSnapshot
    from polybot.prefilter.composite import PreFilter


@dataclass
class CheckResult:
    """Outcome of a single prefilter check."""

    passed: bool
    snapshot: PreFilterSnapshot
    prefilter: PreFilterResult


class PrefilterChecker:
    """Runs the prefilter pipeline on a snapshot and records the result.

    Receives a snapshot and scalar context values, runs the ``PreFilter``
    gate, computes R/R and BTC-move-from-open, builds a
    ``PreFilterSnapshot``, and returns a ``CheckResult`` with a boolean
    ``passed`` field the caller can branch on.
    """

    def __init__(self, prefilter: PreFilter) -> None:
        self._prefilter = prefilter

    def check(
        self,
        snapshot: MarketSnapshot,
        time_remaining: float,
        *,
        has_open_position: bool,
        candle_open_btc: float | None,
    ) -> CheckResult:
        up_ob = snapshot.orderbook
        down_ob = snapshot.down_orderbook

        rr_up = compute_rr(up_ob.best_ask or 1.0)
        rr_down = compute_rr(down_ob.best_ask or 1.0)

        btc_move = 0.0
        btc_price_val = snapshot.btc_price.price_usd if snapshot.btc_price else 0.0
        if candle_open_btc is not None and btc_price_val > 0:
            btc_move = btc_price_val - candle_open_btc

        pf_result = self._prefilter.check(time_remaining, snapshot, has_open_position)

        pf_snapshot = PreFilterSnapshot(
            timestamp=time.time(),
            time_remaining=time_remaining,
            checks={
                "time_ok": time_remaining >= 45,
                "spread_ok": not pf_result.should_skip or "spread" not in pf_result.reason.lower(),
                "depth_ok": not pf_result.should_skip or "thin" not in pf_result.reason.lower(),
                "choppy_ok": not pf_result.should_skip or "choppy" not in pf_result.reason.lower(),
                "setup_ok": not pf_result.should_skip or "setup" not in pf_result.reason.lower(),
                "prefilter_passed": not pf_result.should_skip,
            },
            reasons=[pf_result.reason] if pf_result.reason else [],
            best_entry_up=up_ob.best_ask or 1.0,
            best_entry_down=down_ob.best_ask or 1.0,
            rr_up=rr_up,
            rr_down=rr_down,
            btc_price=btc_price_val,
            up_mid=up_ob.midpoint,
            down_mid=down_ob.midpoint,
            up_spread_pct=up_ob.spread_pct,
            down_spread_pct=down_ob.spread_pct,
            streak=pf_result.consecutive_streak,
            streak_direction=pf_result.streak_direction,
            btc_move_from_open=btc_move,
        )

        return CheckResult(
            passed=not pf_result.should_skip,
            snapshot=pf_snapshot,
            prefilter=pf_result,
        )
