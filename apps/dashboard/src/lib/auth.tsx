"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { ApiError, api } from "./api";
import type { SiteInfo, UserInfo } from "./contracts.gen";

interface Auth {
  user: UserInfo | null;
  sites: SiteInfo[];
  site: SiteInfo | null;
  setSiteId: (id: string) => void;
  ready: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (perm: string) => boolean;
}

const Ctx = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [sites, setSites] = useState<SiteInfo[]>([]);
  const [siteId, setSiteIdState] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const load = useCallback(async () => {
    try {
      const me = await api<UserInfo>("/v1/auth/me");
      setUser(me);
      const list = me.permissions.includes("sites:read") ? await api<SiteInfo[]>("/v1/sites") : [];
      setSites(list);
      let saved: string | null = null;
      try {
        saved = window.localStorage.getItem("jikimi.site");
      } catch {
        /* ignore */
      }
      setSiteIdState(list.find((s) => s.id === saved)?.id ?? list[0]?.id ?? null);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 401)) console.error(e);
      setUser(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const value = useMemo<Auth>(
    () => ({
      user,
      sites,
      site: sites.find((s) => s.id === siteId) ?? null,
      setSiteId: (id) => {
        setSiteIdState(id);
        try {
          window.localStorage.setItem("jikimi.site", id);
        } catch {
          /* ignore */
        }
      },
      ready,
      login: async (username, password) => {
        await api("/v1/auth/login", { body: { username, password } });
        await load();
      },
      logout: async () => {
        await api("/v1/auth/logout", { method: "POST" });
        setUser(null);
        setSites([]);
      },
      can: (perm) => Boolean(user?.permissions.includes(perm)),
    }),
    [user, sites, siteId, ready, load],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): Auth {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}
