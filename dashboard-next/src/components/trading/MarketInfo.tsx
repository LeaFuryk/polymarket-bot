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
      <div className="rounded-lg border border-white/5 bg-[#131720] p-4">
        <div className="text-sm text-zinc-500">Waiting for market...</div>
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border border-white/5 bg-[#131720] p-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="mb-1 text-xs font-semibold tracking-wider text-zinc-500 uppercase">
            Current Candle
          </h3>
          <a
            href={market.polymarket_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-cyan-400 transition-colors hover:text-cyan-300"
          >
            {market.title || market.slug}
          </a>
        </div>
        <div className="text-right">
          <div className="mb-1 text-[11px] tracking-wider text-zinc-500 uppercase">
            Time Left
          </div>
          <Countdown seconds={market.time_remaining} className="text-2xl" />
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <div className="text-[11px] tracking-wider text-zinc-500 uppercase">
            UP
          </div>
          <div className="font-mono text-lg text-green-400">
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
          <div className="text-[11px] tracking-wider text-zinc-500 uppercase">
            DOWN
          </div>
          <div className="font-mono text-lg text-red-400">
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
          <div className="text-[11px] tracking-wider text-zinc-500 uppercase">
            Source
          </div>
          <StatusBadge
            label={market.price_source}
            variant={market.price_source === "chainlink_ws" ? "green" : "amber"}
          />
        </div>
      </div>
    </div>
  );
}
