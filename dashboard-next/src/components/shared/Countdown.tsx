"use client";

import { useEffect, useRef, useState } from "react";
import { formatCountdown } from "@/lib/format";

interface CountdownProps {
  seconds: number;
  className?: string;
}

export function Countdown({ seconds: initialSeconds, className = "" }: CountdownProps) {
  const [seconds, setSeconds] = useState(initialSeconds);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Sync from prop when it changes (new WS message)
  useEffect(() => {
    setSeconds(initialSeconds);
  }, [initialSeconds]);

  // Tick down every second while positive
  useEffect(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);

    if (seconds > 0) {
      intervalRef.current = setInterval(() => {
        setSeconds((s) => Math.max(0, s - 1));
      }, 1000);
    }

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [seconds > 0]); // eslint-disable-line react-hooks/exhaustive-deps

  const isUrgent = seconds < 30;

  return (
    <span
      className={`font-mono tabular-nums ${
        isUrgent ? "text-red-400 animate-pulse" : "text-zinc-200"
      } ${className}`}
    >
      {formatCountdown(seconds)}
    </span>
  );
}
