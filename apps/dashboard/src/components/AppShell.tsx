"use client";

import { Activity, Bell, FileCheck2, Languages, LayoutDashboard, ListChecks, LogOut, Moon, Search, ShieldCheck, Smartphone, Sun, Video } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";
import { useLive, useLiveEvent } from "@/lib/live";

import { HangulMark } from "./HangulMark";
import { Logo } from "./Logo";
import { useTheme } from "./Providers";
import { Spinner, cx } from "./ui";

const NAV = [
  { href: "/", key: "overview", icon: LayoutDashboard, perm: "alerts:read" },
  { href: "/alerts/", key: "alerts", icon: Bell, perm: "alerts:read" },
  { href: "/analyst/", key: "analyst", icon: Search, perm: "search" },
  { href: "/evidence/", key: "evidence", icon: FileCheck2, perm: "evidence:read" },
  { href: "/rules/", key: "rules", icon: ListChecks, perm: "rules:read" },
  { href: "/live/", key: "live", icon: Video, perm: "alerts:read" },
  { href: "/health/", key: "health", icon: Activity, perm: "health:read" },
  { href: "/guard/", key: "guard", icon: Smartphone, perm: "alerts:ack" },
  { href: "/verify/", key: "verify", icon: ShieldCheck, perm: null },
] as const;

function ConnectionDot() {
  const { status } = useLive();
  const { t } = useI18n();
  const label = status === "open" ? t.common.live : status === "connecting" ? t.common.reconnecting : t.common.offline;
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-slate-500/10 px-2.5 py-1 text-xs font-medium text-slate-600 dark:text-slate-300">
      <span className={cx("size-2 rounded-full", status === "open" ? "bg-emerald-500 shadow-[0_0_0_3px] shadow-emerald-500/25" : status === "connecting" ? "animate-pulse bg-amber-500" : "bg-red-500")} />
      {label}
    </span>
  );
}

function NewAlertToast() {
  const { t, lang } = useI18n();
  const [msg, setMsg] = useState<{ text: string; id: string } | null>(null);
  useLiveEvent(["alert.created"], (m) => {
    const a = m.data.alert as { id: string; explanation_ur?: string; explanation_en?: string; severity?: string; status?: string } | undefined;
    if (!a || a.status === "logged_only") return;
    setMsg({ id: a.id, text: (lang === "ur" ? a.explanation_ur : a.explanation_en) ?? "" });
  });
  useEffect(() => {
    if (!msg) return;
    const h = setTimeout(() => setMsg(null), 8000);
    return () => clearTimeout(h);
  }, [msg]);
  if (!msg) return null;
  return (
    <Link
      href={`/alerts/view/?id=${msg.id}`}
      className="fixed bottom-5 start-5 z-50 flex max-w-md items-start gap-3 rounded-2xl border border-red-500/40 bg-white/95 p-4 shadow-2xl backdrop-blur dark:bg-slate-900/95"
    >
      <span className="mt-1 size-2.5 shrink-0 animate-ping rounded-full bg-red-500" />
      <span>
        <span className="block text-xs font-semibold text-red-600 dark:text-red-300">{t.nav.alerts}</span>
        <span className={cx("block text-sm text-slate-800 dark:text-slate-100", lang === "ur" && "urdu")}>{msg.text}</span>
      </span>
    </Link>
  );
}

export function AppShell({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  const { user, ready, site, sites, setSiteId, logout, can } = useAuth();
  const { t, lang, toggle } = useI18n();
  const theme = useTheme();
  const path = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (ready && !user) router.replace(`/login/?next=${encodeURIComponent(path)}`);
  }, [ready, user, router, path]);

  if (!ready || !user) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner label={t.common.loading} />
      </div>
    );
  }

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[17rem_1fr]">
      <aside className="sticky top-0 z-30 hidden h-screen flex-col border-e border-slate-200/70 bg-white/70 p-4 backdrop-blur-xl lg:flex dark:border-white/[0.06] dark:bg-slate-950/60">
        <Link href="/" className="mb-6 flex items-center gap-3 px-2">
          <Logo className="size-10" />
          <span>
            <span className={cx("block text-lg font-bold text-slate-900 dark:text-white", lang === "ur" && "urdu-h font-normal")}>{t.appName}</span>
            <span className="flex items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
              <HangulMark className="h-2.5 w-auto text-brand-500" /> · {t.tagline}
            </span>
          </span>
        </Link>
        <nav className="flex flex-1 flex-col gap-1" aria-label="main">
          {NAV.filter((n) => n.perm === null || can(n.perm)).map(({ href, key, icon: Icon }) => {
            const active = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cx(
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition",
                  active ? "bg-brand-500/15 text-brand-700 ring-1 ring-brand-500/25 dark:text-brand-300" : "text-slate-600 hover:bg-slate-500/10 dark:text-slate-300",
                )}
              >
                <Icon className="size-[18px]" aria-hidden />
                {t.nav[key]}
              </Link>
            );
          })}
        </nav>
        <div className="mt-4 rounded-xl bg-slate-500/5 p-3 text-xs text-slate-500 dark:text-slate-400">
          <p className="font-semibold text-slate-700 dark:text-slate-200">{user.name}</p>
          <p>{user.role}</p>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200/70 bg-white/70 px-4 py-3 backdrop-blur-xl sm:px-6 dark:border-white/[0.06] dark:bg-slate-950/60">
          <div className="flex items-center gap-3">
            <Link href="/" className="lg:hidden">
              <Logo className="size-8" />
            </Link>
            {sites.length > 1 ? (
              <select className="input w-auto py-1.5 text-sm" value={site?.id} onChange={(e) => setSiteId(e.target.value)} aria-label={t.common.site}>
                {sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {lang === "ur" ? (s.name_ur ?? s.name) : s.name}
                  </option>
                ))}
              </select>
            ) : (
              <span className={cx("text-sm font-semibold text-slate-700 dark:text-slate-200", lang === "ur" && "urdu-h")}>{site ? (lang === "ur" ? (site.name_ur ?? site.name) : site.name) : ""}</span>
            )}
            <ConnectionDot />
          </div>
          <div className="flex items-center gap-2">
            <button className="btn-ghost px-2.5" onClick={toggle} title="Language">
              <Languages className="size-4" aria-hidden />
              <span className="text-xs">{t.common.language}</span>
            </button>
            <button className="btn-ghost px-2.5" onClick={theme.toggle} aria-label={t.common.theme}>
              {theme.dark ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </button>
            <button
              className="btn-ghost px-2.5"
              onClick={async () => {
                await logout();
                router.replace("/login/");
              }}
              aria-label={t.common.logout}
            >
              <LogOut className="size-4" />
            </button>
          </div>
          <nav className="flex w-full gap-1 overflow-x-auto pb-1 lg:hidden" aria-label="mobile">
            {NAV.filter((n) => n.perm === null || can(n.perm)).map(({ href, key, icon: Icon }) => (
              <Link key={href} href={href} className={cx("flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium", (href === "/" ? path === "/" : path.startsWith(href)) ? "bg-brand-500/15 text-brand-700 dark:text-brand-300" : "text-slate-600 dark:text-slate-300")}>
                <Icon className="size-4" aria-hidden />
                {t.nav[key]}
              </Link>
            ))}
          </nav>
        </header>
        <main className={cx("mx-auto px-4 py-6 sm:px-6 lg:py-8", wide ? "max-w-[1600px]" : "max-w-7xl")}>{children}</main>
      </div>
      <NewAlertToast />
    </div>
  );
}
