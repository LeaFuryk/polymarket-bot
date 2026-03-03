"use client";

import { AnimatedNumber } from "@/components/shared/AnimatedNumber";
import { Countdown } from "@/components/shared/Countdown";
import { StatusBadge } from "@/components/shared/StatusBadge";

interface MarketInfoProps {
  market: {
    slug: string;
    title: string;
    polymarket_url: string;
    time_remaining: number;
    up_mid: number | null;
    down_mid: number | null;
    btc_price: number;
    price_source: string;
  } | null;
}

export function MarketInfo({ market }: MarketInfoProps) {
  if (!market) {
    return (
      <div className="rounded-lg bg-[#131720] border border-white/5 p-4">
        <div className="text-zinc-500 text-sm">Waiting for market...</div>
      </div>
    );
  }

  return (
    <div className="rounded-lg bg-[#131720] border border-white/5 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-xs uppercase tracking-wider text-zinc-500 font-semibold mb-1">
            Current Candle
          </h3>
          <a
            href={market.polymarket_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-cyan-400 hover:text-cyan-300 transition-colors"
          >
            {market.title || market.slug}
          </a>
        </div>
        <div className="text-right">
          <div className="text-[11px] uppercase tracking-wider text-zinc-500 mb-1">
            Time Left
          </div>
          <Countdown seconds={market.time_remaining} className="text-2xl" />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <div className="text-[11px] uppercase tracking-wider text-zinc-500">UP</div>
          <div className="font-mono text-green-400 text-lg">
            {market.up_mid !== null ? (
              <AnimatedNumber
                value={market.up_mid}
                format={(n) => `$${n.toFixed(4)}`}
              />
            ) : (
              "---"
            )}
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wider text-zinc-500">DOWN</div>
          <div className="font-mono text-red-400 text-lg">
            {market.down_mid !== null ? (
              <AnimatedNumber
                value={market.down_mid}
                format={(n) => `$${n.toFixed(4)}`}
              />
            ) : (
              "---"
            )}
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wider text-zinc-500">Source</div>
          <StatusBadge
            label={market.price_source}
            variant={market.price_source === "chainlink_ws" ? "green" : "amber"}
          />
        </div>
      </div>
    </div>
  );
}
