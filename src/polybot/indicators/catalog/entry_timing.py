"""Entry timing indicator — win rate by entry-time bucket."""

from __future__ import annotations

from polybot.indicators.context import IndicatorContext
from polybot.indicators.core import IndicatorResult


class EntryTimingIndicator:
    name = "entry_timing"
    display_name = "Entry Timing"

    def compute(self, ctx: IndicatorContext) -> IndicatorResult | None:
        session_trades = ctx.session_trades
        resolutions = ctx.session_resolutions
        if not session_trades or not resolutions:
            return None

        # Build resolution lookup
        res_by_slug: dict[str, object] = {}
        for r in resolutions:
            res_by_slug[r.slug] = r

        # Buckets: label -> [wins, losses]
        buckets: dict[str, list[int]] = {
            ">200s": [0, 0],
            "150-200s": [0, 0],
            "100-150s": [0, 0],
            "<100s": [0, 0],
        }

        resolved_count = 0
        for trade in session_trades:
            if trade.action.value != "BUY" or trade.fill_price is None:
                continue
            tr = trade.extra.get("time_remaining")
            if tr is None:
                continue
            res = res_by_slug.get(trade.candle_slug)
            if res is None:
                continue

            if tr > 200:
                bucket = ">200s"
            elif tr > 150:
                bucket = "150-200s"
            elif tr > 100:
                bucket = "100-150s"
            else:
                bucket = "<100s"

            won = trade.token_side.value == res.winner
            if won:
                buckets[bucket][0] += 1
            else:
                buckets[bucket][1] += 1
            resolved_count += 1

        if resolved_count < 3:
            return None

        # Find best bucket
        best_wr = -1.0
        best_bucket = ""
        parts = []
        for bname, (wins, losses) in buckets.items():
            total = wins + losses
            if total > 0:
                wr = wins / total
                parts.append(f"{bname}: {wins}W/{losses}L ({wr:.0%})")
                if total >= 2 and wr > best_wr:
                    best_wr = wr
                    best_bucket = bname

        label = f"{resolved_count} trades — " + ", ".join(parts)
        if best_bucket:
            label += f" | best: {best_bucket} ({best_wr:.0%})"

        return IndicatorResult(name=self.display_name, value=best_wr, label=label)
