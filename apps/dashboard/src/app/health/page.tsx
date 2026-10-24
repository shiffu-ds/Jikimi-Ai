"use client";

import { Battery, BatteryCharging, Cctv, Check, MessageSquare, ScanEye, Server } from "lucide-react";
import { useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Card, Chip, ErrorBox, PageHeader, Spinner, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { CameraInfo, EdgeCommand, HealthOverview } from "@/lib/contracts.gen";
import { ago, dateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveEvent } from "@/lib/live";

const CHECK_TONE: Record<string, "brand" | "amber" | "red"> = { ok: "brand", warn: "amber", alarm: "red" };
const CHECKS = ["offline", "covered", "blur", "moved", "frozen", "moving"] as const;

/** A camera turned on purpose keeps alarming "moved": an admin accepts its new view (signed edge command). */
function AcceptView({ camera }: { camera: CameraInfo }) {
  const { t } = useI18n();
  const [state, setState] = useState<"idle" | "busy" | "sent" | Error>("idle");
  if (state === "sent")
    return (
      <span className="inline-flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400" title={t.health.acceptViewSent}>
        <Check className="size-3.5" /> {t.health.acceptViewSent}
      </span>
    );
  return (
    <button
      className="btn-ghost px-2 py-1 text-xs"
      disabled={state === "busy"}
      title={state instanceof Error ? state.message : t.health.acceptViewHint}
      onClick={async () => {
        setState("busy");
        try {
          await api<EdgeCommand>(`/v1/sites/${camera.site_id}/cameras/${camera.id}/accept-view`, { method: "POST" });
          setState("sent");
        } catch (e) {
          setState(e as Error);
        }
      }}
    >
      <ScanEye className="size-3.5" /> {t.health.acceptView}
    </button>
  );
}

function Health() {
  const { t, lang } = useI18n();
  const { can } = useAuth();
  const h = useApi<HealthOverview>("/v1/health/overview", 10000);
  useLiveEvent(["health.updated"], () => h.reload());
  if (h.error) return <ErrorBox error={h.error} onRetry={h.reload} />;
  if (!h.data) return <Spinner label={t.common.loading} />;
  return (
    <>
      <PageHeader title={t.health.title} subtitle={`server ${dateTime(h.data.server_time)}`} />
      <div className="grid gap-5 lg:grid-cols-2">
        {h.data.devices.map((d) => (
          <Card
            key={d.id}
            title={
              <span className="inline-flex items-center gap-2">
                <Server className="size-4" /> {d.name}
              </span>
            }
            actions={<Chip tone={d.online ? "brand" : "red"}>{d.online ? t.health.online : t.health.offline}</Chip>}
          >
            <dl className="grid grid-cols-2 gap-4 p-4 text-sm">
              <div>
                <dt className="label">{t.health.power}</dt>
                <dd className="mt-1 flex items-center gap-1.5 font-semibold">
                  {d.power_source === "battery" ? <Battery className="size-4 text-amber-500" /> : <BatteryCharging className="size-4 text-emerald-500" />}
                  {d.power_source === "battery" ? `${t.health.battery} ${d.battery_pct ?? "?"}%` : t.health.ac}
                  <Chip>{d.power_profile}</Chip>
                </dd>
              </div>
              <div>
                <dt className="label">{t.health.backlog}</dt>
                <dd className={cx("ltr-num mt-1 text-lg font-bold", d.outbox_backlog > 0 && "text-amber-500")}>
                  {d.outbox_backlog}
                  {d.outbox_dead > 0 && <span className="ms-2 text-sm text-red-500">dead {d.outbox_dead}</span>}
                </dd>
              </div>
              <div>
                <dt className="label">{t.health.sms}</dt>
                <dd className="mt-1 flex items-center gap-1.5 font-semibold">
                  <MessageSquare className="size-4" /> {d.sms_gateway}
                </dd>
              </div>
              <div>
                <dt className="label">{t.live.lastSeen}</dt>
                <dd className="ltr-num mt-1 font-semibold">{ago(d.last_seen, lang)}</dd>
              </div>
              <div className="col-span-2">
                <dt className="label">{t.health.versions}</dt>
                <dd className="mt-1 flex flex-wrap gap-1">
                  {Object.entries(d.versions).map(([k, v]) => (
                    <Chip key={k}>
                      {k} {v}
                    </Chip>
                  ))}
                  {Object.entries(d.drift).map(([k, v]) => (
                    <Chip key={k} tone={v ? "red" : "brand"}>
                      {t.health.drift} {k}: {v ? "yes" : "no"}
                    </Chip>
                  ))}
                </dd>
              </div>
            </dl>
          </Card>
        ))}
        <Card
          title={
            <span className="inline-flex items-center gap-2">
              <Cctv className="size-4" /> {t.health.checks}
            </span>
          }
          className="lg:col-span-2"
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-start text-xs text-slate-500">
                <tr>
                  <th className="px-4 py-2 text-start">{t.common.camera}</th>
                  <th className="px-4 py-2 text-start">status</th>
                  <th className="px-4 py-2 text-start">fps</th>
                  {CHECKS.map((c) => (
                    <th key={c} className="px-4 py-2 text-start">
                      {t.health.check[c]}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200/70 dark:divide-white/[0.06]">
                {h.data.cameras.map((c) => (
                  <tr key={c.id}>
                    <td className="px-4 py-2.5 font-medium">{lang === "ur" ? (c.name_ur ?? c.name) : c.name}</td>
                    <td className="px-4 py-2.5">
                      <Chip tone={c.status === "online" ? "brand" : "red"}>{c.status}</Chip>
                    </td>
                    <td className="ltr-num px-4 py-2.5">{c.fps.toFixed(1)}</td>
                    {CHECKS.map((k) => (
                      <td key={k} className="px-4 py-2.5">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Chip tone={CHECK_TONE[c.health[k] ?? "ok"] ?? "brand"}>{c.health[k] ?? "ok"}</Chip>
                          {k === "moved" && c.health.moved && c.health.moved !== "ok" && can("admin") && <AcceptView camera={c} />}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  );
}

export default function Page() {
  return (
    <AppShell wide>
      <Health />
    </AppShell>
  );
}
