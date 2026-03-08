"use client";

import { useMemo } from "react";
import { useWSContext } from "@/components/layout/AppShell";
import { useTradingData } from "@/hooks/useTradingData";
import { PnLSummary } from "@/components/trading/PnLSummary";
import { MarketInfo } from "@/components/trading/MarketInfo";
import { PositionPanel } from "@/components/trading/PositionPanel";
import { BtcPanel } from "@/components/trading/BtcPanel";
import { ResolutionTable } from "@/components/trading/ResolutionTable";
import { RiskBar } from "@/components/trading/RiskBar";
import { ExecutionQualityBanner } from "@/components/trading/ExecutionQualityBanner";
import { AdaptiveEntryPanel } from "@/components/trading/AdaptiveEntryPanel";
import { MLModelPanel } from "@/components/trading/MLModelPanel";
import { EnsemblePanel } from "@/components/trading/EnsemblePanel";
import { CalibrationExitPanel } from "@/components/trading/CalibrationExitPanel";
import { MonitorPanel } from "@/components/trading/MonitorPanel";
import { ObservationsPanel } from "@/components/trading/ObservationsPanel";
import { MicrostructurePanel } from "@/components/trading/MicrostructurePanel";
import { CandleTimeline } from "@/components/candles/CandleTimeline";

export default function TradingPage() {
  const ws = useWSContext();
  const { currentMarket, currentPosition } = useTradingData(ws);

  const snapshot = ws.snapshot;

  // Deduplicate resolutions by slug (snapshot refresh can duplicate WS events)
  const dedupedResolutions = useMemo(() => {
    const all = [...(snapshot?.resolutions ?? []), ...ws.resolutions];
    const seen = new Set<string>();
    return all.filter((r) => {
      if (!r.slug || seen.has(r.slug)) return false;
      seen.add(r.slug);
      return true;
    });
  }, [snapshot?.resolutions, ws.resolutions]);

  // Compute aggregate open-candle unrealized PnL
  const openPnL = useMemo(() => {
    if (!currentPosition || !currentMarket) return null;
    const upMid = currentMarket.up_mid;
    const downMid = currentMarket.down_mid;
    if (upMid == null || downMid == null) return null;
    const upUnrealized =
      currentPosition.up_shares * (upMid - currentPosition.up_avg_entry);
    const downUnrealized =
      currentPosition.down_shares * (downMid - currentPosition.down_avg_entry);
    return upUnrealized + downUnrealized;
  }, [currentPosition, currentMarket]);

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

      {/* Execution Quality Banner */}
      <ExecutionQualityBanner trades={[...snapshot.trades, ...ws.trades]} />

      {/* Indicator Panels — 3-col grid */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <AdaptiveEntryPanel adaptiveEntry={snapshot.adaptive_entry} />
        <MLModelPanel mlModel={snapshot.ml_model} />
        <EnsemblePanel ensemble={snapshot.ensemble} />
        <CalibrationExitPanel
          calibration={snapshot.calibration}
          exitAnalysis={snapshot.exit_analysis}
        />
        <MonitorPanel monitor={snapshot.monitor} />
      </div>

      {/* Full-width panels */}
      <ObservationsPanel
        observations={snapshot.observations ?? null}
        resolutionsSinceReflection={snapshot.resolutions_since_reflection}
        totalResolutions={snapshot.knowledge_total_resolutions}
      />
      <MicrostructurePanel
        microstructure={snapshot.microstructure ?? null}
        reversalRegime={snapshot.reversal_regime}
      />

      {/* Open candle unrealized PnL */}
      {openPnL !== null && (
        <div className="flex items-center gap-2 rounded-lg border border-white/5 bg-[#131720] px-4 py-2">
          <span className="text-xs font-semibold tracking-wider text-zinc-500 uppercase">
            Open Candle PnL
          </span>
          <span
            className={`font-mono text-sm font-semibold ${
              openPnL >= 0 ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {openPnL >= 0 ? "+" : ""}
            {openPnL.toFixed(4)}
          </span>
        </div>
      )}

      {/* Candle Timeline */}
      {snapshot.candle_snapshots &&
        Object.keys(snapshot.candle_snapshots).length > 0 && (
          <CandleTimeline
            snapshots={snapshot.candle_snapshots}
            trades={[...snapshot.trades, ...ws.trades]}
          />
        )}

      {/* Resolutions */}
      <ResolutionTable resolutions={dedupedResolutions} />
    </div>
  );
}
