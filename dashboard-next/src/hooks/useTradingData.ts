"use client";

import { useMemo } from "react";
import type { WSData } from "./useWebSocket";

/** Derive trading-oriented state from WS data. */
export function useTradingData(ws: WSData) {
  const { snapshot, market, position } = ws;

  // Use real-time market update if available, otherwise fall back to snapshot
  const currentMarket = useMemo(() => {
    if (market?.slug) {
      return {
        slug: market.slug,
        time_remaining: market.time_remaining ?? 0,
        up_mid: market.up_mid ?? snapshot?.current_market?.up_mid ?? null,
        down_mid: market.down_mid ?? snapshot?.current_market?.down_mid ?? null,
        btc_price: market.btc_price ?? snapshot?.btc?.price_usd ?? 0,
        price_source: market.price_source ?? snapshot?.btc?.price_source ?? "",
        title: snapshot?.current_market?.title ?? "",
        polymarket_url: snapshot?.current_market?.polymarket_url ?? "",
      };
    }
    if (snapshot?.current_market?.slug) {
      return {
        slug: snapshot.current_market.slug,
        time_remaining: snapshot.current_market.time_remaining,
        up_mid: snapshot.current_market.up_mid,
        down_mid: snapshot.current_market.down_mid,
        btc_price: snapshot.btc?.price_usd ?? 0,
        price_source: snapshot.btc?.price_source ?? "",
        title: snapshot.current_market.title,
        polymarket_url: snapshot.current_market.polymarket_url,
      };
    }
    return null;
  }, [market, snapshot]);

  // Use real-time position if available
  const currentPosition = useMemo(() => {
    if (position) {
      return {
        up_shares: position.up_shares,
        up_avg_entry: position.up_avg_entry,
        down_shares: position.down_shares,
        down_avg_entry: position.down_avg_entry,
        cash: position.cash,
        pnl: position.position_pnl,
        dynamic_sl: position.dynamic_sl,
        dynamic_tp: position.dynamic_tp,
      };
    }
    if (snapshot) {
      return {
        up_shares: snapshot.positions.up_shares,
        up_avg_entry: snapshot.positions.up_avg_entry,
        down_shares: snapshot.positions.down_shares,
        down_avg_entry: snapshot.positions.down_avg_entry,
        cash: snapshot.session.cash,
        pnl: snapshot.position_pnl,
        dynamic_sl: snapshot.dynamic_sl,
        dynamic_tp: snapshot.dynamic_tp,
      };
    }
    return null;
  }, [position, snapshot]);

  return { currentMarket, currentPosition };
}
