"use client";

import { Check, Fingerprint, MessageSquare, Timer } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { api } from "@/lib/api";
import type { AlertEventOut, AlertSummary } from "@/lib/contracts.gen";
import { ago, clock, dateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

import { Chip, SeverityBadge, StatusBadge, TypeIcon, cx } from "./ui";

const TYPE_TONE: Record<string, string> = {
  snatch: "bg-red-500/15 text-red-600 dark:text-red-300",
  loitering: "bg-amber-500/15 text-amber-600 dark:text-amber-300",
  camera_tamper: "bg-violet-500/15 text-violet-600 dark:text-violet-300",
  sos: "bg-red-600 text-white",
  rule: "bg-sky-500/15 text-sky-600 dark:text-sky-300",
  person_in_danger: "bg-red-600 text-white",
  vehicle_theft: "bg-amber-500/15 text-amber-600 dark:text-amber-300",
  crowd_panic: "bg-red-500/15 text-red-600 dark:text-red-300",
};

export function AlertCard({ a, onChange, compact = false }: { a: AlertSummary; onChange?: () => void; compact?: boolean }) {
  const { t, lang } = useI18n();
  const [busy, setBusy] = useState(false);
  const active = a.status === "open" || a.status === "escalated";
  const text = lang === "ur" ? a.explanation_ur : a.explanation_en;

  async function ack(e: React.MouseEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await api(`/v1/alerts/${a.id}/ack`, { body: {} });
      onChange?.();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Link
      href={`/alerts/view/?id=${a.id}`}
      className={cx(
        "card card-hover group relative flex gap-4 overflow-hidden p-3 sm:p-4",
        active && a.severity === "high" && "ring-1 ring-red-500/40",
      )}
    >
      {active && a.severity === "high" && <span className="absolute inset-y-0 start-0 w-1 bg-red-500" aria-hidden />}
      <div className="relative hidden shrink-0 overflow-hidden rounded-xl bg-slate-900 sm:block" style={{ width: compact ? 120 : 160, aspectRatio: "16/9" }}>
        {a.thumbnail_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={a.thumbnail_url} alt="" className="size-full object-cover" loading="lazy" />
        ) : (
          <div className={cx("grid size-full place-items-center", TYPE_TONE[a.type] ?? "bg-slate-500/20")}>
            <TypeIcon type={a.type} className="size-8" />
          </div>
        )}
        <span className="ltr-num absolute bottom-1 end-1 rounded bg-black/70 px-1.5 py-0.5 font-mono text-[10px] text-white">{clock(a.ts_end)}</span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={cx("inline-flex items-center gap-1.5 rounded-lg px-2 py-0.5 text-xs font-bold", TYPE_TONE[a.type] ?? "bg-slate-500/15")}>
            <TypeIcon type={a.type} className="size-3.5" />
            {t.type[a.type] ?? a.type}
          </span>
          <SeverityBadge severity={a.severity} />
          <StatusBadge status={a.status} />
          {a.sms_sent && (
            <Chip tone="amber">
              <MessageSquare className="size-3" /> {t.alerts.sms}
            </Chip>
          )}
          {a.escalation_step > 0 && (a.status === "escalated" || a.status === "acked") && (
            <Chip tone="red">
              {t.alerts.escalation} {a.escalation_step}
            </Chip>
          )}
          <span className="ms-auto font-mono text-[11px] text-slate-400">#{a.short_code}</span>
        </div>
        <p className={cx("mt-2 text-slate-800 dark:text-slate-100", lang === "ur" ? "urdu text-[15px]" : "text-sm", compact && "line-clamp-2")}>{text}</p>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
          <span>{lang === "ur" ? (a.camera_name_ur ?? a.camera_name) : a.camera_name}</span>
          <span className="ltr-num">{ago(a.created_at, lang)}</span>
          {a.p_value !== null && <span className="ltr-num">p = {a.p_value.toFixed(4)}</span>}
          {a.acked_by && (
            <span className="inline-flex items-center gap-1">
              <Check className="size-3" /> {a.acked_by}
            </span>
          )}
        </div>
      </div>
      {active && onChange && (
        <div className="hidden shrink-0 items-center sm:flex">
          <button className="btn-primary" onClick={ack} disabled={busy}>
            <Check className="size-4" />
            {t.alerts.ack}
          </button>
        </div>
      )}
    </Link>
  );
}

const EVENT_LABEL: Record<string, { ur: string; en: string }> = {
  ingested: { ur: "ایج سے موصول", en: "Received from edge" },
  sms_sent: { ur: "انٹرنیٹ بند — SMS بھیجا گیا", en: "Internet down — SMS sent" },
  opened: { ur: "الرٹ کھلا", en: "Alert opened" },
  notified: { ur: "گارڈ کو اطلاع", en: "Guard notified" },
  escalated: { ur: "اگلے مرحلے پر", en: "Escalated" },
  acked: { ur: "دیکھ لیا گیا", en: "Acknowledged" },
  reviewed: { ur: "فیصلہ", en: "Reviewed" },
  verify_skipped: { ur: "VLM دستیاب نہیں — غیر تصدیق شدہ", en: "No VLM — opened unverified" },
  verify_requested: { ur: "VLM تصدیق کی درخواست", en: "VLM verification requested" },
  verify_timeout: { ur: "VLM نے وقت پر جواب نہیں دیا", en: "VLM timed out" },
  verified: { ur: "VLM نتیجہ", en: "VLM verdict" },
  clip_received: { ur: "کلپ موصول (دستخط شدہ)", en: "Clip received (signed)" },
  superseded: { ur: "نئے الرٹ میں ضم", en: "Superseded by newer alert" },
  need_help: { ur: "گارڈ نے مدد مانگی", en: "Guard asked for help" },
  sos: { ur: "SOS دبایا گیا", en: "SOS pressed" },
};

export function Timeline({ events, start }: { events: AlertEventOut[]; start: string }) {
  const { lang } = useI18n();
  const t0 = new Date(start).getTime();
  const grouped: AlertEventOut[] = [];
  for (const e of events) {
    const prev = grouped[grouped.length - 1];
    if (prev && prev.kind === e.kind && prev.at === e.at) {
      prev.channel = [prev.channel, e.channel].filter(Boolean).join(", ");
      continue;
    }
    grouped.push({ ...e });
  }
  return (
    <ol className="relative space-y-4 border-s border-slate-200 ps-5 dark:border-white/10">
      {grouped.map((e, i) => {
        const label = EVENT_LABEL[e.kind]?.[lang] ?? e.kind;
        const dt = Math.max(0, (new Date(e.at).getTime() - t0) / 1000);
        const tone = e.kind === "escalated" || e.kind === "sms_sent" ? "bg-amber-500" : e.kind === "acked" || e.kind === "reviewed" ? "bg-emerald-500" : e.kind === "opened" || e.kind === "sos" ? "bg-red-500" : "bg-brand-500";
        const payload = e.payload as Record<string, unknown>;
        return (
          <li key={i} className="relative">
            <span className={cx("absolute -start-[1.6rem] top-1 size-3 rounded-full ring-4 ring-white dark:ring-slate-950", tone)} />
            <div className="flex flex-wrap items-baseline gap-x-3">
              <span className="font-medium text-slate-800 dark:text-slate-100">{label}</span>
              <span className="ltr-num font-mono text-xs text-slate-500">{clock(e.at, true)}</span>
              <span className="ltr-num text-xs text-slate-400">+{dt.toFixed(1)}s</span>
            </div>
            <div className="mt-0.5 flex flex-wrap gap-2 text-xs text-slate-500 dark:text-slate-400">
              {e.actor && e.actor !== "system" && <span>{e.actor}</span>}
              {e.channel && <Chip>{e.channel}</Chip>}
              {payload?.roles ? <Chip tone="sky">{(payload.roles as string[]).join(", ")}</Chip> : null}
              {payload?.latency_s !== undefined && <Chip tone="brand">edge→server {String(payload.latency_s)}s</Chip>}
              {payload?.mtta_s !== undefined && payload?.mtta_s !== null && (
                <Chip tone="brand">
                  <Timer className="size-3" /> MTTA {String(payload.mtta_s)}s
                </Chip>
              )}
              {payload?.verdict ? <Chip>{String(payload.verdict)}</Chip> : null}
              {payload?.note ? <span className="italic">{String(payload.note)}</span> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function SignatureLine({ valid, keyId }: { valid: boolean; keyId: string | null }) {
  const { t } = useI18n();
  return (
    <span className={cx("inline-flex items-center gap-1.5 text-xs", valid ? "text-emerald-600 dark:text-emerald-400" : "text-red-500")}>
      <Fingerprint className="size-3.5" /> {valid ? t.alerts.signature : "signature?"} <span className="font-mono opacity-70">{keyId}</span>
    </span>
  );
}

export function when(iso: string): string {
  return dateTime(iso);
}
