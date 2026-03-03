"use client";

import { AnimatedNumber } from "@/components/shared/AnimatedNumber";
import { StatusBadge } from "@/components/shared/StatusBadge";
import { formatBtcPrice, formatPercent, pnlColor } from "@/lib/format";
import type { BtcInfo } from "@/lib/types";

interface BtcPanelProps {
  btc: BtcInfo | null;
  realtimePrice?: number;
}

export function BtcPanel({ btc, realtimePrice }: BtcPanelProps) {
  if (!btc) return null;

  const price = realtimePrice ?? btc.price_usd;

  return (
    <div className="rounded-lg bg-[#131720] border border-white/5 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs uppercase tracking-wider text-zinc-500 font-semibold">
          Bitcoin
        </h3>
        <StatusBadge
          label={btc.price_source}
          variant={btc.price_source === "chainlink_ws" ? "green" : "amber"}
        />
      </div>

      <div className="flex items-end gap-4">
        <div className="font-mono text-2xl text-zinc-100">
          <AnimatedNumber value={price} format={formatBtcPrice} />
        </div>
        <div className={`font-mono text-sm ${pnlColor(btc.change_24h_pct)}`}>
          {formatPercent(btc.change_24h_pct)} 24h
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 text-xs">
        <div>
          <div className="text-zinc-500">Chainlink</div>
          <div className="font-mono text-zinc-300">
            {btc.chainlink_price ? formatBtcPrice(btc.chainlink_price) : "---"}
          </div>
        </div>
        <div>
          <div className="text-zinc-500">Divergence</div>
          <div className="font-mono text-zinc-300">
            {btc.price_divergence !== null
              ? `${btc.price_divergence.toFixed(2)}%`
              : "---"}
          </div>
        </div>
        <div>
          <div className="text-zinc-500">Last Candle</div>
          <StatusBadge
            label={btc.last_candle_direction}
            variant={btc.last_candle_direction === "up" ? "green" : "red"}
          />
        </div>
      </div>
    </div>
  );
}
