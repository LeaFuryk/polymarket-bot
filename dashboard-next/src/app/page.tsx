"use client";

import { useWSContext } from "@/components/layout/AppShell";
import { useTradingData } from "@/hooks/useTradingData";
import { PnLSummary } from "@/components/trading/PnLSummary";
import { MarketInfo } from "@/components/trading/MarketInfo";
import { PositionPanel } from "@/components/trading/PositionPanel";
import { BtcPanel } from "@/components/trading/BtcPanel";
import { TradeTimeline } from "@/components/trading/TradeTimeline";
import { ResolutionTable } from "@/components/trading/ResolutionTable";
import { RiskBar } from "@/components/trading/RiskBar";

export default function TradingPage() {
  const ws = useWSContext();
  const { currentMarket, currentPosition } = useTradingData(ws);

  const snapshot = ws.snapshot;

  if (!snapshot) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="animate-pulse text-sm text-zinc-500">
          Connecting to bot...
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6">
      {/* Risk bar */}
      <RiskBar risk={snapshot.risk} />

      {/* Top row: Market + BTC */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <MarketInfo market={currentMarket} />
        <BtcPanel btc={snapshot.btc} realtimePrice={ws.market?.btc_price} />
      </div>

      {/* PnL Summary */}
      <PnLSummary session={snapshot.session} allTime={snapshot.all_time} />

      {/* Positions */}
      <PositionPanel position={currentPosition} />

      {/* Bottom row: Trades + Resolutions */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TradeTimeline trades={snapshot.trades} />
        <ResolutionTable resolutions={snapshot.resolutions} />
      </div>
    </div>
  );
}
