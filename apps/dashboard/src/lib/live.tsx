"use client";

// One WebSocket per tab: alert.created / alert.updated / alert.notify / health.updated ...
import { createContext, useContext, useEffect, useRef, useState } from "react";

export interface LiveMessage {
  event: string;
  site_id: string | null;
  data: Record<string, unknown>;
}

type Listener = (m: LiveMessage) => void;

interface Live {
  status: "connecting" | "open" | "closed";
  subscribe: (fn: Listener) => () => void;
}

const Ctx = createContext<Live | null>(null);

export function LiveProvider({ enabled, children }: { enabled: boolean; children: React.ReactNode }) {
  const [status, setStatus] = useState<Live["status"]>("closed");
  const listeners = useRef(new Set<Listener>());

  useEffect(() => {
    if (!enabled) return;
    let ws: WebSocket | null = null;
    let stopped = false;
    let retry = 1000;
    let ping: ReturnType<typeof setInterval> | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      setStatus("connecting");
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const devApi = process.env.NODE_ENV !== "production" ? (process.env.NEXT_PUBLIC_WS_ORIGIN ?? `${proto}://${location.hostname}:8000`) : null;
      ws = new WebSocket(`${devApi ?? `${proto}://${location.host}`}/v1/ws`);
      ws.onopen = () => {
        retry = 1000;
        setStatus("open");
        ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 25000);
      };
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data as string) as LiveMessage;
          listeners.current.forEach((fn) => fn(msg));
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        clearInterval(ping);
        setStatus("closed");
        if (!stopped) timer = setTimeout(connect, retry);
        retry = Math.min(retry * 2, 15000);
      };
    };
    connect();
    return () => {
      stopped = true;
      clearInterval(ping);
      clearTimeout(timer);
      ws?.close();
    };
  }, [enabled]);

  const value: Live = {
    status,
    subscribe: (fn) => {
      listeners.current.add(fn);
      return () => {
        listeners.current.delete(fn);
      };
    },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLive(): Live {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLive outside LiveProvider");
  return v;
}

/** Re-run ``fn`` whenever a matching live event arrives. */
export function useLiveEvent(events: string[], fn: (m: LiveMessage) => void): void {
  const { subscribe } = useLive();
  const ref = useRef(fn);
  ref.current = fn;
  const key = events.join(",");
  useEffect(() => subscribe((m) => key.split(",").includes(m.event) && ref.current(m)), [subscribe, key]);
}
