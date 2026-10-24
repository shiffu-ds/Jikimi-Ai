"use client";

import { Layers } from "lucide-react";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { Chip, PageHeader, cx } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { CameraInfo, HealthOverview } from "@/lib/contracts.gen";
import { ago } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveEvent } from "@/lib/live";

function CameraTile({ cam, showZones, bust }: { cam: CameraInfo; showZones: boolean; bust: number }) {
  const { t, lang } = useI18n();
  const checks = Object.entries(cam.health ?? {}).filter(([, v]) => v !== "ok");
  return (
    <div className="card overflow-hidden">
      <div className="relative aspect-video bg-slate-950">
        {cam.snapshot_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={`${cam.snapshot_url}?b=${bust}`} alt={cam.name} className="size-full object-cover" />
        ) : (
          <div className="grid size-full place-items-center text-sm text-slate-500">{t.live.noSnapshot}</div>
        )}
        {showZones && (
          <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 size-full">
            {cam.zones.map((z) => (
              <polygon key={z.id} points={z.polygon.map(([x, y]) => `${x},${y}`).join(" ")} className="fill-brand-400/15 stroke-brand-300" strokeWidth={0.004} />
            ))}
          </svg>
        )}
        <div className="scanlines pointer-events-none absolute inset-0" />
        <span className="absolute start-3 top-3 inline-flex items-center gap-1.5 rounded-md bg-black/60 px-2 py-1 text-xs font-semibold text-white">
          <span className={cx("size-2 rounded-full", cam.status === "online" ? "animate-pulse bg-red-500" : "bg-slate-400")} />
          {cam.status === "online" ? "REC" : cam.status}
        </span>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 p-3">
        <div>
          <p className={cx("font-semibold", lang === "ur" && "font-naskh")}>{lang === "ur" ? (cam.name_ur ?? cam.name) : cam.name}</p>
          <p className="ltr-num text-xs text-slate-500">
            {cam.fps.toFixed(1)} {t.live.fps} · {t.live.lastSeen} {ago(cam.last_seen, lang)}
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {cam.zones.map((z) => (
            <Chip key={z.id} tone="brand">
              {lang === "ur" ? (z.name_ur ?? z.name ?? z.id) : (z.name ?? z.id)}
            </Chip>
          ))}
          {checks.map(([k, v]) => (
            <Chip key={k} tone={v === "alarm" ? "red" : "amber"}>
              {k}: {v}
            </Chip>
          ))}
        </div>
      </div>
    </div>
  );
}

function Live() {
  const { t } = useI18n();
  const { site } = useAuth();
  const [zones, setZones] = useState(true);
  const [bust, setBust] = useState(0);
  const health = useApi<HealthOverview>("/v1/health/overview", 10000);
  useLiveEvent(["snapshot.updated", "health.updated"], () => setBust(Date.now()));
  useEffect(() => {
    const h = setInterval(() => setBust(Date.now()), 3000);
    return () => clearInterval(h);
  }, []);
  const cams = (health.data?.cameras ?? site?.cameras ?? []).filter((c) => !site || c.site_id === site.id);
  return (
    <>
      <PageHeader
        title={t.live.title}
        subtitle={t.live.subtitle}
        actions={
          <button className={cx("btn-ghost", zones && "ring-1 ring-brand-500/40")} onClick={() => setZones((z) => !z)}>
            <Layers className="size-4" /> {t.live.zones}
          </button>
        }
      />
      <div className="grid gap-5 lg:grid-cols-2">
        {cams.map((c) => (
          <CameraTile key={c.id} cam={c} showZones={zones} bust={bust} />
        ))}
      </div>
    </>
  );
}

export default function Page() {
  return (
    <AppShell wide>
      <Live />
    </AppShell>
  );
}
