"use client";

import { Bell } from "lucide-react";
import { useState } from "react";

import { AlertCard } from "@/components/alerts";
import { AppShell } from "@/components/AppShell";
import { Empty, ErrorBox, PageHeader, Spinner, TypeIcon, cx } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AlertPage, AlertSummary } from "@/lib/contracts.gen";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveEvent } from "@/lib/live";

const TABS = {
  active: ["open", "escalated", "verifying", "acked"],
  all: [] as string[],
  logged: ["logged_only"],
} as const;
const TYPES = ["snatch", "loitering", "camera_tamper", "sos", "rule"];

function Alerts() {
  const { site } = useAuth();
  const { t } = useI18n();
  const [tab, setTab] = useState<keyof typeof TABS>("active");
  const [types, setTypes] = useState<string[]>([]);
  const [more, setMore] = useState<AlertSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const path = site ? `/v1/alerts${qs({ site_id: site.id, status: [...TABS[tab]], type: types, limit: 30 })}` : null;
  const page = useApi<AlertPage>(path);
  useLiveEvent(["alert.created", "alert.updated"], () => page.reload());

  const items = [...(page.data?.items ?? []), ...more];
  const next = cursor ?? page.data?.next_cursor ?? null;

  async function loadMore() {
    if (!path || !next) return;
    const res = await api<AlertPage>(`${path}&cursor=${encodeURIComponent(next)}`);
    setMore((m) => [...m, ...res.items]);
    setCursor(res.next_cursor ?? null);
  }

  return (
    <>
      <PageHeader title={t.alerts.title} />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-xl bg-slate-500/10 p-1">
          {(Object.keys(TABS) as Array<keyof typeof TABS>).map((k) => (
            <button
              key={k}
              onClick={() => {
                setTab(k);
                setMore([]);
                setCursor(null);
              }}
              className={cx("rounded-lg px-3 py-1.5 text-sm font-medium", tab === k ? "bg-white text-slate-900 shadow dark:bg-slate-800 dark:text-white" : "text-slate-500")}
            >
              {t.alerts[k]}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {TYPES.map((ty) => {
            const on = types.includes(ty);
            return (
              <button
                key={ty}
                onClick={() => setTypes((xs) => (on ? xs.filter((x) => x !== ty) : [...xs, ty]))}
                className={cx("inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium ring-1", on ? "bg-brand-500/15 text-brand-700 ring-brand-500/30 dark:text-brand-300" : "text-slate-500 ring-slate-500/20")}
              >
                <TypeIcon type={ty} className="size-3.5" />
                {t.type[ty]}
              </button>
            );
          })}
        </div>
      </div>
      {page.error && <ErrorBox error={page.error} onRetry={page.reload} />}
      {!page.data && !page.error && <Spinner label={t.common.loading} />}
      {page.data && items.length === 0 && <Empty icon={Bell} title={t.overview.allClear} />}
      <div className="space-y-3">
        {items.map((a) => (
          <AlertCard key={a.id} a={a} onChange={page.reload} />
        ))}
      </div>
      {next && (
        <div className="mt-6 text-center">
          <button className="btn-ghost" onClick={loadMore}>
            {t.common.viewAll} …
          </button>
        </div>
      )}
    </>
  );
}

export default function Page() {
  return (
    <AppShell>
      <Alerts />
    </AppShell>
  );
}
