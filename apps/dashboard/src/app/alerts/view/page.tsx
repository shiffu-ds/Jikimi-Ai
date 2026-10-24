"use client";

import { ArrowLeft, Check, FileCheck2, HelpCircle, ShieldCheck, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { SignatureLine, Timeline } from "@/components/alerts";
import { AppShell } from "@/components/AppShell";
import { Card, Chip, ErrorBox, SeverityBadge, Spinner, StatusBadge, TypeIcon, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AlertDetail, EvidenceSummary } from "@/lib/contracts.gen";
import { dateTime, short } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveEvent } from "@/lib/live";

const FEATURE_LABEL: Record<string, { ur: string; en: string }> = {
  passes: { ur: "چکر", en: "Passes" },
  window_min: { ur: "وقت کی کھڑکی (منٹ)", en: "Window (min)" },
  riders: { ur: "سوار", en: "Riders" },
  slowdowns_near_ped: { ur: "پیدل کے پاس آہستہ", en: "Slow-downs near pedestrian" },
  dwell_s: { ur: "رکنے کا وقت (s)", en: "Dwell (s)" },
  color: { ur: "رنگ", en: "Colour" },
  vehicle: { ur: "سواری", en: "Vehicle" },
  contact: { ur: "ہاتھ کا رابطہ", en: "Hand contact" },
  depart_accel: { ur: "تیزی سے روانگی", en: "Fast departure" },
  ped_jerk: { ur: "پیدل کو جھٹکا", en: "Pedestrian jerk" },
  slow_approach: { ur: "آہستہ قریب آنا", en: "Slow approach" },
  min_hand_dist: { ur: "کم ترین ہاتھ فاصلہ", en: "Min hand distance" },
  close_duration_s: { ur: "قریب رہنے کا وقت", en: "Time close (s)" },
  check: { ur: "جانچ", en: "Check" },
  held_s: { ur: "برقرار (s)", en: "Held (s)" },
  calibrated: { ur: "کیلیبریٹڈ", en: "Calibrated" },
};
const HIDDEN = new Set(["dedupe_key", "rule_severity", "notify"]);

function Detail() {
  const params = useSearchParams();
  const id = params.get("id");
  const { t, lang } = useI18n();
  const { can } = useAuth();
  const router = useRouter();
  const res = useApi<AlertDetail>(id ? `/v1/alerts/${id}` : null);
  const [busy, setBusy] = useState(false);
  const [frame, setFrame] = useState(0);
  useLiveEvent(["alert.updated"], (m) => {
    const a = m.data.alert as { id?: string } | undefined;
    if (a?.id === id) res.reload();
  });

  if (res.error) return <ErrorBox error={res.error} onRetry={res.reload} />;
  if (!res.data) return <Spinner label={t.common.loading} />;
  const a = res.data;
  const active = ["open", "escalated", "verifying"].includes(a.status);

  async function act(path: string, body: unknown) {
    setBusy(true);
    try {
      await api(path, { body });
      res.reload();
    } finally {
      setBusy(false);
    }
  }

  async function makeEvidence() {
    setBusy(true);
    try {
      const ev = await api<EvidenceSummary>("/v1/evidence", { body: { alert_ids: [a.id] } });
      router.push(`/evidence/view/?id=${ev.id}`);
    } finally {
      setBusy(false);
    }
  }

  const features = Object.entries(a.features).filter(([k, v]) => !HIDDEN.has(k) && v !== null && v !== undefined && typeof v !== "object");

  return (
    <>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Link href="/alerts/" className="btn-ghost px-2.5" aria-label={t.common.back}>
            <ArrowLeft className="size-4 rtl:rotate-180" />
          </Link>
          <span className="inline-flex items-center gap-2 text-xl font-bold">
            <TypeIcon type={a.type} className="size-6 text-brand-500" />
            <span className={cx(lang === "ur" && "urdu-h font-normal")}>{t.type[a.type] ?? a.type}</span>
          </span>
          <SeverityBadge severity={a.severity} />
          <StatusBadge status={a.status} />
          <Chip>
            {t.alerts.code} <span className="font-mono">{a.short_code}</span>
          </Chip>
          {a.sms_sent && <Chip tone="amber">{t.alerts.sms}</Chip>}
          {a.verified === true && <Chip tone="brand">{t.alerts.verified}</Chip>}
          {a.verified === null && a.route === "VERIFY" && <Chip tone="amber">{t.alerts.unverified}</Chip>}
          {a.vlm_verdict && a.verified === null && (
            <Chip tone={a.vlm_verdict === a.type ? "amber" : "brand"}>
              {t.alerts.vlmOpinion}: {a.vlm_verdict === a.type ? t.alerts.vlmYes : a.vlm_verdict === "normal" ? t.alerts.vlmNo : t.alerts.vlmUnclear}
              {a.vlm_confidence != null && <span className="ltr-num ms-1 opacity-70">{Math.round(a.vlm_confidence * 100)}%</span>}
            </Chip>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {active && can("alerts:ack") && (
            <button className="btn-primary" disabled={busy} onClick={() => act(`/v1/alerts/${a.id}/ack`, {})}>
              <Check className="size-4" /> {t.alerts.ack}
            </button>
          )}
          {can("evidence:create") && (
            <button className="btn-ghost" disabled={busy} onClick={makeEvidence}>
              <FileCheck2 className="size-4" /> {t.alerts.makeEvidence}
            </button>
          )}
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="space-y-6">
          <Card title={t.alerts.clip}>
            <div className="p-3">
              {a.clip_url ? (
                <video key={a.clip_url} src={a.clip_url} controls autoPlay muted loop playsInline className="aspect-video w-full rounded-xl bg-black" />
              ) : a.keyframe_urls.length ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={a.keyframe_urls[frame]} alt="" className="aspect-video w-full rounded-xl bg-black object-contain" />
              ) : (
                <div className="grid aspect-video place-items-center rounded-xl bg-slate-900 text-sm text-slate-400">
                  <Spinner label={t.alerts.noClip} />
                </div>
              )}
              {a.keyframe_urls.length > 0 && (
                <div className="mt-3 grid grid-cols-4 gap-2 sm:grid-cols-8">
                  {a.keyframe_urls.map((u, i) => (
                    <button key={u} onClick={() => setFrame(i)} className={cx("overflow-hidden rounded-lg ring-2", i === frame ? "ring-brand-500" : "ring-transparent")}>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={u} alt="" className="aspect-video w-full object-cover" loading="lazy" />
                    </button>
                  ))}
                </div>
              )}
              <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                <span className="ltr-num">
                  {dateTime(a.ts_start)} → {dateTime(a.ts_end)}
                </span>
                <SignatureLine valid={a.signature_valid} keyId={a.device_key_id} />
              </div>
            </div>
          </Card>

          <Card title={t.alerts.timeline}>
            <div className="p-5">
              <Timeline events={a.events} start={a.ts_end} />
            </div>
          </Card>
        </div>

        <div className="space-y-6">
          <Card title={<span className="inline-flex items-center gap-2"><Sparkles className="size-4 text-brand-500" /> {t.alerts.why}</span>}>
            <div className="space-y-4 p-4">
              <p className="urdu text-lg text-slate-900 dark:text-white">{a.explanation_ur}</p>
              <p className="text-sm text-slate-600 dark:text-slate-300" dir="ltr">
                {a.explanation_en}
              </p>
              {a.explanation_roman && (
                <p className="rounded-lg bg-slate-500/10 px-3 py-2 font-mono text-xs text-slate-600 dark:text-slate-300" dir="ltr">
                  SMS: {a.explanation_roman}
                </p>
              )}
              {(a.p_value_text_ur || a.p_value_text_en) && (
                <div className="rounded-xl border border-brand-500/25 bg-brand-500/5 p-3">
                  <p className={cx("text-sm font-medium text-brand-800 dark:text-brand-200", lang === "ur" && "urdu")}>{lang === "ur" ? a.p_value_text_ur : a.p_value_text_en}</p>
                  <p className="ltr-num mt-1 text-xs text-slate-500">
                    conformal p = {a.p_value?.toFixed(4)} · score {a.raw_score?.toFixed(3)} · route {a.route}
                  </p>
                </div>
              )}
            </div>
          </Card>

          <Card title={t.alerts.features}>
            <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-b-2xl bg-slate-200/60 text-sm dark:bg-white/[0.05]">
              {features.map(([k, v]) => (
                <div key={k} className="bg-white px-4 py-2.5 dark:bg-slate-950/60">
                  <dt className="text-xs text-slate-500">{FEATURE_LABEL[k]?.[lang] ?? k}</dt>
                  <dd className="ltr-num font-semibold">{typeof v === "number" ? Math.round(v * 1000) / 1000 : String(v)}</dd>
                </div>
              ))}
            </dl>
            <div className="flex flex-wrap gap-1.5 p-4">
              {Object.entries(a.model_versions).map(([k, v]) => (
                <Chip key={k}>
                  {k}: <span className="font-mono">{v}</span>
                </Chip>
              ))}
              {a.clip_sha256 && (
                <Chip tone="brand" title={a.clip_sha256}>
                  <ShieldCheck className="size-3" /> clip {short(a.clip_sha256, 6)}
                </Chip>
              )}
            </div>
          </Card>

          {can("alerts:review") && (
            <Card title={t.alerts.review}>
              <div className="space-y-3 p-4">
                <div className="grid grid-cols-3 gap-2">
                  <button className="btn-ghost flex-col py-3" disabled={busy} onClick={() => act(`/v1/alerts/${a.id}/review`, { verdict: "true" })}>
                    <ThumbsUp className="size-5 text-emerald-500" />
                    {t.alerts.trueAlarm}
                  </button>
                  <button className="btn-ghost flex-col py-3" disabled={busy} onClick={() => act(`/v1/alerts/${a.id}/review`, { verdict: "false" })}>
                    <ThumbsDown className="size-5 text-red-500" />
                    {t.alerts.falseAlarm}
                  </button>
                  <button className="btn-ghost flex-col py-3" disabled={busy} onClick={() => act(`/v1/alerts/${a.id}/review`, { verdict: "unclear" })}>
                    <HelpCircle className="size-5 text-slate-400" />
                    {t.alerts.unclear}
                  </button>
                </div>
                <p className="text-xs text-slate-500">{t.alerts.reviewHint}</p>
                {a.reviews.map((r, i) => (
                  <p key={i} className="text-xs text-slate-500">
                    {r.reviewer}: <b>{r.verdict}</b> · <span className="ltr-num">{dateTime(r.at)}</span>
                  </p>
                ))}
              </div>
            </Card>
          )}

          {a.evidence_ids.length > 0 && (
            <Card title={t.nav.evidence}>
              <ul className="p-4 text-sm">
                {a.evidence_ids.map((e) => (
                  <li key={e}>
                    <Link className="font-mono text-brand-600 hover:underline dark:text-brand-400" href={`/evidence/view/?id=${e}`}>
                      {e}
                    </Link>
                  </li>
                ))}
              </ul>
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
      <Suspense>
        <Detail />
      </Suspense>
    </AppShell>
  );
}
