"use client";

import { useEffect, useRef, useState } from "react";
import type {
  MarketUpdate,
  PositionUpdate,
  ResolutionEvent,
  SnapshotData,
  StatusUpdate,
  TradeEvent,
  WSMessage,
} from "@/lib/types";
import { RECONNECT_INTERVALS, WS_URL } from "@/lib/constants";

export type WSState =
  | "connecting"
  | "connected"
  | "disconnected"
  | "reconnecting";

export interface WSData {
  state: WSState;
  snapshot: SnapshotData | null;
  market: MarketUpdate | null;
  position: PositionUpdate | null;
  status: StatusUpdate | null;
  trades: TradeEvent[];
  resolutions: ResolutionEvent[];
}

export function useWebSocket(url: string = WS_URL): WSData {
  const [state, setState] = useState<WSState>("disconnected");
  const [snapshot, setSnapshot] = useState<SnapshotData | null>(null);
  const [market, setMarket] = useState<MarketUpdate | null>(null);
  const [position, setPosition] = useState<PositionUpdate | null>(null);
  const [status, setStatus] = useState<StatusUpdate | null>(null);
  const [trades, setTrades] = useState<TradeEvent[]>([]);
  const [resolutions, setResolutions] = useState<ResolutionEvent[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const retryCount = useRef(0);
  const retryTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let disposed = false;

    function scheduleReconnect() {
      if (disposed) return;
      const delay = Math.min(
        RECONNECT_INTERVALS.initial *
          RECONNECT_INTERVALS.multiplier ** retryCount.current,
        RECONNECT_INTERVALS.max,
      );
      retryCount.current += 1;
      retryTimeout.current = setTimeout(connect, delay);
    }

    function connect() {
      if (disposed) return;
      if (wsRef.current?.readyState === WebSocket.OPEN) return;

      setState(retryCount.current > 0 ? "reconnecting" : "connecting");

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (disposed) return;
        setState("connected");
        retryCount.current = 0;
      };

      ws.onmessage = (event) => {
        if (disposed) return;
        try {
          const msg: WSMessage = JSON.parse(event.data);
          switch (msg.type) {
            case "snapshot":
              setSnapshot(msg.data as SnapshotData);
              break;
            case "market":
              setMarket(msg.data as MarketUpdate);
              break;
            case "position":
              setPosition(msg.data as PositionUpdate);
              break;
            case "status":
              setStatus(msg.data as StatusUpdate);
              break;
            case "trade":
              setTrades((prev) => [...prev.slice(-99), msg.data as TradeEvent]);
              break;
            case "resolution":
              setResolutions((prev) => [
                ...prev.slice(-49),
                msg.data as ResolutionEvent,
              ]);
              break;
          }
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (disposed) return;
        setState("disconnected");
        wsRef.current = null;
        scheduleReconnect();
      };

      ws.onerror = () => {
        ws.close();
      };
    }

    connect();

    return () => {
      disposed = true;
      if (retryTimeout.current) clearTimeout(retryTimeout.current);
      wsRef.current?.close();
    };
  }, [url]);

  return { state, snapshot, market, position, status, trades, resolutions };
}
