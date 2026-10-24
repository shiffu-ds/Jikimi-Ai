"use client";

import { Bell, Cctv, Footprints, Gauge, MessageSquare, Percent, Timer } from "lucide-react";
import Link from "next/link";

import { AlertCard } from "@/components/alerts";
import { AppShell } from "@/components/AppShell";
import { ModeBadge } from "@/components/EventModes";
import { DayBars, TypeBars } from "@/components/charts";
import { Card, Chip, Empty, ErrorBox, PageHeader, Spinner, Stat, cx } from "@/components/ui";
import { qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AlertPage, CalendarOut, HealthOverview, Hotspots, StatsOut } from "@/lib/contracts.gen";
import { ago, duration, pct } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveEvent } from "@/lib/live";

function Overview() {
  const { site, can } = useAuth();
  const { t, lang } = useI18n();
  const sid = site?.id;
  const alerts = useApi<AlertPage>(sid ? `/v1/alerts${qs({ site_id: sid, limit: 8 })}` : null);
  const stats = useApi<StatsOut>(sid && can("stats:read") ? `/v1/stats${qs({ site_id: sid, days: 7 })}` : null, 30000);
  const health = useApi<HealthOverview>(can("health:read") ? "/v1/health/overview" : null, 15000);
  const calendar = useApi<CalendarOut>(sid ? `/v1/sites/${encodeURIComponent(sid)}/calendar` : null);
  const hot = useApi<Hotspots>(sid && can("stats:read") ? `/v1/sites/${encodeURIComponent(sid)}/hotspots` : null, 300000);
  useLiveEvent(["alert.created", "alert.updated"], () => {
    alerts.reload();
    stats.reload();
  });
  useLiveEvent(["health.updated", "snapshot.updated"], () => health.reload());

  const s = stats.data;
  const active = alerts.data?.items.filter((a) => a.status === "open" || a.status === "escalated" || a.status === "verifying") ?? [];
  const cams = health.data?.cameras ?? site?.cameras ?? [];

  return (
    <>
      <PageHeader
        title={t.overview.title}
        subtitle={new Date().toLocaleDateString(lang === "ur" ? "ur-PK" : "en-GB", { timeZone: "Asia/Karachi", weekday: "long", day: "numeric", month: "long" })}
        actions={calendar.data ? <ModeBadge mode={calendar.data.current_mode} /> : undefined}
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6">
        <Stat label={t.overview.openAlerts} value={s?.open_alerts ?? "—"} icon={Bell} tone={s && s.open_alerts > 0 ? "red" : "brand"} />
        <Stat label={t.overview.alertsToday} value={s?.alerts_today ?? "—"} icon={Gauge} tone="amber" />
        <Stat label={t.overview.mtta} value={duration(s?.mtta_median_s)} hint={s?.mtta_p95_s ? `p95 ${duration(s.mtta_p95_s)}` : undefined} icon={Timer} tone="sky" />
        <Stat label={t.overview.falseAlarm} value={pct(s?.false_alarm_rate)} hint={s ? `${s.false_alarms}/${s.reviewed}` : undefined} icon={Percent} tone="violet" />
        <Stat label={t.overview.cameras} value={s ? `${s.cameras_online}/${s.cameras_total}` : "—"} icon={Cctv} tone="brand" />
        <Stat label={t.overview.smsFallback} value={s?.sms_fallbacks ?? "—"} icon={MessageSquare} tone="amber" />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Card
          title={t.overview.latest}
          actions={
            <Link href="/alerts/" className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-400">
              {t.common.viewAll}
            </Link>
          }
        >
          <div className="space-y-3 p-3 sm:p-4">
            {alerts.error && <ErrorBox error={alerts.error} onRetry={alerts.reload} />}
            {!alerts.data && !alerts.error && <Spinner label={t.common.loading} />}
            {alerts.data && alerts.data.items.length === 0 && <Empty title={t.overview.allClear} />}
            {active.length === 0 && alerts.data && alerts.data.items.length > 0 && (
              <p className="rounded-xl bg-emerald-500/10 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300">{t.overview.allClear}</p>
            )}
            {alerts.data?.items.map((a) => <AlertCard key={a.id} a={a} onChange={alerts.reload} compact />)}
          </div>
        </Card>

        <div className="space-y-6">
          <Card title={t.nav.live} actions={<Link href="/live/" className="text-xs font-medium text-brand-600 hover:underline dark:text-brand-400">{t.common.viewAll}</Link>}>
            <div className="grid gap-3 p-3">
              {cams.map((c) => (
                <Link key={c.id} href="/live/" className="group relative overflow-hidden rounded-xl bg-slate-900">
                  {c.snapshot_url ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={`${c.snapshot_url}?t=${c.last_seen ?? ""}`} alt={c.name} className="aspect-video w-full object-cover opacity-95 transition group-hover:opacity-100" />
                  ) : (
                    <div className="grid aspect-video place-items-center text-sm text-slate-400">{t.live.noSnapshot}</div>
                  )}
                  <div className="absolute inset-x-0 bottom-0 flex items-center justify-between bg-gradient-to-t from-black/80 to-transparent px-3 py-2 text-xs text-white">
                    <span className={cx(lang === "ur" && "font-naskh")}>{lang === "ur" ? (c.name_ur ?? c.name) : c.name}</span>
                    <span className="inline-flex items-center gap-1.5">
                      <span className={cx("size-2 rounded-full", c.status === "online" ? "bg-emerald-400" : "bg-red-500")} />
                      <span className="ltr-num">{c.fps ? `${c.fps.toFixed(1)} fps` : c.status}</span>
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </Card>
          {health.data && (
            <Card title={t.overview.devices}>
              <ul className="divide-y divide-slate-200/70 dark:divide-white/[0.06]">
                {health.data.devices.map((d) => (
                  <li key={d.id} className="flex items-center justify-between gap-2 px-4 py-3 text-sm">
                    <span className="flex items-center gap-2">
                      <span className={cx("size-2.5 rounded-full", d.online ? "bg-emerald-500" : "bg-red-500")} />
                      <span className="font-medium">{d.name}</span>
                    </span>
                    <span className="flex flex-wrap items-center justify-end gap-1.5 text-xs text-slate-500">
                      <Chip>{d.power_source === "battery" ? `${t.health.battery} ${d.battery_pct ?? "?"}%` : t.health.ac}</Chip>
                      <Chip tone={d.outbox_backlog > 0 ? "amber" : "slate"}>
                        {t.health.backlog}: <span className="ltr-num">{d.outbox_backlog}</span>
                      </Chip>
                      <span className="ltr-num">{ago(d.last_seen, lang)}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {hot.data && (
            <Card title={t.overview.hotspots}>
              <div className="space-y-4 p-4">
                <p className="text-xs text-slate-500">{t.overview.hotspotsNote}</p>
                {hot.data.events_used === 0 ? (
                  <p className="text-sm text-slate-500">{t.overview.fewIncidents}</p>
                ) : (
                  <>
                    <ul className="space-y-2">
                      {hot.data.zones.slice(0, 5).map((z) => {
                        const top = hot.data?.zones[0]?.expected_events || 1;
                        return (
                          <li key={z.zone_key} className="text-sm">
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-medium">{lang === "ur" ? (z.name_ur ?? z.name) : z.name}</span>
                              <span className="ltr-num text-xs text-slate-500">
                                {z.events_90d} {t.overview.events90}
                              </span>
                            </div>
                            <div className="mt-1 h-2 rounded-full bg-slate-200/70 dark:bg-white/10">
                              <div className="h-2 rounded-full bg-amber-500" style={{ width: `${Math.max(4, (100 * z.expected_events) / top)}%` }} />
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                    {hot.data.patrol.length > 0 && (
                      <div>
                        <p className="label mb-1.5 flex items-center gap-1.5">
                          <Footprints className="size-3.5" /> {t.overview.patrol}
                        </p>
                        <ol className="flex flex-wrap items-center gap-1.5 text-xs">
                          {hot.data.patrol.map((p, i) => (
                            <li key={p.zone_key}>
                              <Chip tone={i === 0 ? "amber" : "slate"}>
                                {i + 1}. {lang === "ur" ? (p.name_ur ?? p.name) : p.name} · <span className="ltr-num">{p.arrive_min}</span> {t.overview.minutes}
                              </Chip>
                            </li>
                          ))}
                        </ol>
                      </div>
                    )}
                  </>
                )}
              </div>
            </Card>
          )}
          {s && (
            <Card title={t.overview.week}>
              <div className="space-y-5 p-4">
                <DayBars data={s.by_day} />
                <TypeBars data={s.by_type} label={(k) => t.type[k] ?? k} />
              </div>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

export default function Page() {
  return (
    <AppShell wide>
      <Overview />
    </AppShell>
  );
}
