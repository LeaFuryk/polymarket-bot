import { CandleChart } from "@/components/candles/CandleChart";
import { BetTimeline } from "@/components/current-bet/BetTimeline";
import { BetPnlPanel } from "@/components/current-bet/BetPnlPanel";
import { EquityChart } from "@/components/portfolios/EquityChart";
import { PortfolioCards } from "@/components/portfolios/PortfolioCards";
import { BetList } from "@/components/history/BetList";

export default function DashboardPage() {
  return (
    <div className="space-y-4">
      {/* Section 1: Candle History */}
      <CandleChart />

      {/* Section 2: Current Bet */}
      <div className="grid grid-cols-[1fr_280px] gap-4">
        <BetTimeline />
        <BetPnlPanel />
      </div>

      {/* Section 3: Portfolio Comparison */}
      <EquityChart />
      <PortfolioCards />

      {/* Section 4: Previous Bets */}
      <BetList />
    </div>
  );
}
