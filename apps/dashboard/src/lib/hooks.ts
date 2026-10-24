"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";

export interface Resource<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

/** Tiny SWR-like hook: fetch on mount / key change, keep stale data while reloading. */
export function useApi<T>(path: string | null, intervalMs?: number): Resource<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(Boolean(path));
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((x) => x + 1), []);
  const latest = useRef(0);

  useEffect(() => {
    if (!path) return;
    const id = ++latest.current;
    const ctrl = new AbortController();
    setLoading(true);
    api<T>(path, { signal: ctrl.signal })
      .then((d) => {
        if (id === latest.current) {
          setData(d);
          setError(undefined);
        }
      })
      .catch((e: unknown) => {
        if (id === latest.current && !(e instanceof DOMException && e.name === "AbortError")) setError(e as Error);
      })
      .finally(() => id === latest.current && setLoading(false));
    return () => ctrl.abort();
  }, [path, tick]);

  useEffect(() => {
    if (!intervalMs || !path) return;
    const h = setInterval(reload, intervalMs);
    return () => clearInterval(h);
  }, [intervalMs, path, reload]);

  return { data, error, loading, reload };
}

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const h = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(h);
  }, [intervalMs]);
  return now;
}
