"use client";

import { useEffect, useRef, useMemo } from "react";
import { useDashboard } from "@/context/DashboardContext";
import { Countdown } from "@/components/shared/Countdown";
import { THEME } from "@/lib/constants";
import {
  createChart,
  CandlestickSeries,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type Time,
  ColorType,
  CrosshairMode,
} from "lightweight-charts";

export function CandleChart() {
  const { candles, currentSnapshots, latestSnapshot, currentCandleId } =
    useDashboard();

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  // Create chart once
  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: THEME.bg.raised },
        textColor: "rgba(255, 255, 255, 0.4)",
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "rgba(255, 255, 255, 0.03)" },
        horzLines: { color: "rgba(255, 255, 255, 0.03)" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "rgba(255, 255, 255, 0.1)",
          labelBackgroundColor: "#131720",
        },
        horzLine: {
          color: "rgba(255, 255, 255, 0.1)",
          labelBackgroundColor: "#131720",
        },
      },
      rightPriceScale: {
        borderColor: "rgba(255, 255, 255, 0.05)",
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        borderColor: "rgba(255, 255, 255, 0.05)",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 2,
      },
      handleScroll: true,
      handleScale: true,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: THEME.colors.green,
      downColor: THEME.colors.red,
      borderUpColor: THEME.colors.green,
      borderDownColor: THEME.colors.red,
      wickUpColor: THEME.colors.green,
      wickDownColor: THEME.colors.red,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        chart.applyOptions({ width, height });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
    };
  }, []);

  // Build candle data from resolved candles
  const candleData = useMemo<CandlestickData<Time>[]>(() => {
    return candles.map((c) => ({
      time: c.start_time as Time,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));
  }, [candles]);

  // Build current live candle from snapshots
  const liveCandle = useMemo<CandlestickData<Time> | null>(() => {
    if (!latestSnapshot || currentSnapshots.length === 0) return null;
    const prices = currentSnapshots.map((s) => s.btc_price);
    const candleStart = Math.floor(
      latestSnapshot.timestamp - latestSnapshot.elapsed_pct * 300,
    );
    return {
      time: candleStart as Time,
      open: prices[0],
      high: Math.max(...prices),
      low: Math.min(...prices),
      close: prices[prices.length - 1],
    };
  }, [latestSnapshot, currentSnapshots]);

  // Track the price line so we can remove it before creating a new one
  const priceLineRef = useRef<ReturnType<
    ISeriesApi<"Candlestick">["createPriceLine"]
  > | null>(null);

  // Update candle series + "price to beat" line
  useEffect(() => {
    if (!candleSeriesRef.current) return;
    const allCandles = [...candleData];
    if (liveCandle) allCandles.push(liveCandle);
    candleSeriesRef.current.setData(allCandles);

    // Fit all candles into view (start from left)
    chartRef.current?.timeScale().fitContent();

    // Remove previous price line
    if (priceLineRef.current) {
      candleSeriesRef.current.removePriceLine(priceLineRef.current);
      priceLineRef.current = null;
    }

    // "Price to beat" = current candle's open price (dashed red line)
    if (liveCandle) {
      priceLineRef.current = candleSeriesRef.current.createPriceLine({
        price: liveCandle.open,
        color: THEME.colors.red,
        lineWidth: 1,
        lineStyle: 2, // Dashed
        axisLabelVisible: true,
        title: "",
      });
    }
  }, [candleData, liveCandle]);

  // Derive header info
  const currentPrice = latestSnapshot?.btc_price;
  const priceToBeat = liveCandle?.open;
  const priceChange =
    currentPrice && priceToBeat ? currentPrice - priceToBeat : null;
  const isUp = priceChange != null && priceChange >= 0;
  const timeRemaining = latestSnapshot
    ? Math.max(0, (1 - latestSnapshot.elapsed_pct) * 300)
    : 0;

  return (
    <div className="rounded-lg bg-[#0d1017] p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-6">
          <h2 className="font-mono text-sm font-semibold text-white/70">
            Candle History
          </h2>
          {priceToBeat && (
            <div className="flex items-center gap-4 font-mono text-xs">
              <div>
                <span className="text-white/40">Price To Beat </span>
                <span className="text-white/70">
                  $
                  {priceToBeat.toLocaleString(undefined, {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}
                </span>
              </div>
              {currentPrice && (
                <div>
                  <span className="text-white/40">Current Price </span>
                  <span className={isUp ? "text-green-400" : "text-red-400"}>
                    {isUp ? "▲" : "▼"} ${Math.abs(priceChange!).toFixed(2)}
                  </span>{" "}
                  <span className={isUp ? "text-green-400" : "text-red-400"}>
                    $
                    {currentPrice.toLocaleString(undefined, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    })}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
        <div className="flex items-center gap-4">
          {latestSnapshot &&
            latestSnapshot.up_asks?.[0] &&
            latestSnapshot.down_asks?.[0] && (
              <div className="flex items-center gap-2 font-mono text-xs">
                <span className="rounded bg-green-500/20 px-2 py-1 font-bold text-green-400">
                  Up {(latestSnapshot.up_asks[0][0] * 100).toFixed(0)}¢
                </span>
                <span className="rounded bg-red-500/20 px-2 py-1 font-bold text-red-400">
                  Down {(latestSnapshot.down_asks[0][0] * 100).toFixed(0)}¢
                </span>
              </div>
            )}
          {currentCandleId && <Countdown seconds={timeRemaining} />}
        </div>
      </div>
      <div ref={containerRef} style={{ height: 350, width: "100%" }} />
    </div>
  );
}
