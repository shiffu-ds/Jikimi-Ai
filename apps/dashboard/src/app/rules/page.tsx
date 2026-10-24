"use client";

import { BellRing, CheckCircle2, CircleSlash, Clock, Cpu, FlaskConical, HelpCircle, ListChecks, Loader2, MapPin, PenLine, Send, ShieldCheck, Tag, Timer, Users } from "lucide-react";
import { useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EventModes } from "@/components/EventModes";
import { NetworkCard } from "@/components/NetworkCard";
import { Card, Chip, Empty, ErrorBox, PageHeader, SeverityBadge, Spinner, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { RuleBacktest, RuleDraft, RuleOut } from "@/lib/contracts.gen";
import { ago, dateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveEvent } from "@/lib/live";

const EXAMPLES = [
  "raat 11 ke baad gate 2 par koi 5 min se zyada ruke to batao",
  "gate 2 par raat ko kaali bike 2 minute se zyada ruke foran batao",
  "bazaar mein 3 se zyada bikes khari hon to supervisor ko batao",
  "subah 9 se shaam 5 tak bazaar mein 10 se zyada log hon",
];

const COLOR_DOT: Record<string, string> = {
  black: "#111827",
  white: "#f8fafc",
  red: "#dc2626",
  blue: "#2563eb",
  green: "#16a34a",
  yellow: "#eab308",
  gray: "#6b7280",
  silver: "#cbd5e1",
  brown: "#92400e",
  orange: "#f97316",
};

interface Understood {
  schedule?: { days: string[]; from: string; to: string } | null;
  zone?: string | null;
  zone_label?: string | null;
  camera_ids?: string[];
  object?: string | null;
  color?: string | null;
  dwell_s?: number | null;
  count_gt?: number | null;
  severity?: string;
  notify?: string[];
}

const STATUS_TONE: Record<string, string> = {
  pending: "bg-amber-500/15 text-amber-700 ring-amber-500/30 dark:text-amber-300",
  active: "bg-emerald-500/15 text-emerald-700 ring-emerald-500/30 dark:text-emerald-300",
  disabled: "bg-slate-500/10 text-slate-500 ring-slate-500/20",
};

function useDur() {
  const { t } = useI18n();
  return (s: number) => (s % 3600 === 0 ? `${s / 3600} ${t.rules.unit.h}` : s % 60 === 0 ? `${s / 60} ${t.rules.unit.min}` : `${s} ${t.rules.unit.s}`);
}

function UnderstoodChips({ u }: { u: Understood }) {
  const { t } = useI18n();
  const dur = useDur();
  const sched = u.schedule;
  const days = sched && sched.days.length < 7 ? ` · ${sched.days.map((d) => t.rules.days[d] ?? d).join("، ")}` : "";
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <Chip tone="sky" title={t.rules.when}>
        <Clock className="size-3" />
        {sched ? <span className="ltr-num">{`${sched.from} → ${sched.to}`}</span> : t.rules.anyTime}
        {days}
      </Chip>
      {(u.zone_label || (u.camera_ids && u.camera_ids.length > 0)) && (
        <Chip tone="amber" title={t.rules.where}>
          <MapPin className="size-3" />
          {u.zone_label ?? u.camera_ids?.join(", ")}
        </Chip>
      )}
      {u.object && (
        <Chip tone="brand" title={t.rules.what}>
          <Tag className="size-3" />
          {u.color && <span className="inline-block size-2.5 rounded-full ring-1 ring-black/20" style={{ background: COLOR_DOT[u.color] }} />}
          {[u.color, u.object].filter(Boolean).join(" ")}
        </Chip>
      )}
      {u.count_gt !== null && u.count_gt !== undefined && (
        <Chip tone="red" title={t.rules.condition}>
          <Users className="size-3" />
          <span className="ltr-num">&gt; {u.count_gt}</span> {t.rules.moreThan}
        </Chip>
      )}
      {u.dwell_s ? (
        <Chip tone="red" title={t.rules.condition}>
          <Timer className="size-3" />
          {t.rules.staysOver} <span className="ltr-num">{dur(u.dwell_s)}</span>
        </Chip>
      ) : null}
      {u.severity && <SeverityBadge severity={u.severity} />}
      {u.notify?.map((n) => (
        <Chip key={n} title={t.rules.notify}>
          <BellRing className="size-3" />
          {t.rules.who[n] ?? n}
        </Chip>
      ))}
    </div>
  );
}

function Backtest({ bt }: { bt: RuleBacktest }) {
  const { t, lang } = useI18n();
  const noisy = bt.per_day > 3;
  return (
    <div className={cx("rounded-xl p-4 ring-1", noisy ? "bg-amber-500/10 ring-amber-500/30" : "bg-slate-500/5 ring-slate-500/15")}>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="flex items-center gap-1.5 text-sm font-semibold">
          <FlaskConical className="size-4 text-brand-600 dark:text-brand-400" /> {t.rules.backtest}
        </span>
        <span className="text-sm">
          {t.rules.wouldFire}: <b className="ltr-num text-lg">{bt.matches}</b>
          <span className="ltr-num text-slate-500"> ({bt.per_day} {t.rules.perDay})</span>
        </span>
        <span className="ltr-num text-xs text-slate-500">
          {bt.tracks_checked} {t.rules.checked}
        </span>
      </div>
      <p className={cx("mt-2 text-sm", noisy ? "text-amber-700 dark:text-amber-300" : "text-slate-600 dark:text-slate-300")}>{noisy ? t.rules.noisy : bt.matches === 0 ? t.rules.quiet : t.rules.estimate}</p>
      {bt.last_matches.length > 0 && (
        <p className="mt-1 text-xs text-slate-500">
          {t.rules.lastMatches}: <span className="ltr-num">{bt.last_matches.map((m) => `${dateTime(m)} (${ago(m, lang)})`).join(" · ")}</span>
        </p>
      )}
    </div>
  );
}

function Rules() {
  const { site, can } = useAuth();
  const { t, lang } = useI18n();
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<RuleDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<Error | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const list = useApi<RuleOut[]>(site ? `/v1/rules?site_id=${encodeURIComponent(site.id)}` : null);
  useLiveEvent(["rules.updated", "health.updated"], () => list.reload()); // heartbeats carry the edge's bundle version

  async function understand(value: string) {
    if (!site || !value.trim()) return;
    setText(value);
    setBusy(true);
    setErr(null);
    setSent(null);
    try {
      setDraft(await api<RuleDraft>("/v1/rules/draft", { body: { site_id: site.id, text: value } }));
    } catch (e) {
      setErr(e as Error);
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      list.reload();
    } catch (e) {
      setErr(e as Error);
    }
  }

  return (
    <>
      <PageHeader title={t.rules.title} subtitle={t.rules.subtitle} />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void understand(text);
        }}
        className="card relative flex items-center gap-2 p-2 ring-brand-500/20 focus-within:ring-2"
      >
        <PenLine className="ms-2 size-5 shrink-0 text-slate-400" aria-hidden />
        <input className="min-w-0 flex-1 bg-transparent px-2 py-3 text-lg outline-none placeholder:text-slate-400" placeholder={t.rules.placeholder} value={text} onChange={(e) => setText(e.target.value)} dir="auto" maxLength={300} aria-label={t.rules.title} />
        <button className="btn-primary px-5 py-3" disabled={busy || !text.trim()}>
          {busy ? <Loader2 className="size-4 animate-spin" /> : <HelpCircle className="size-4" />}
          {t.rules.understand}
        </button>
      </form>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-500">{t.rules.examples}:</span>
        {EXAMPLES.map((ex) => (
          <button key={ex} onClick={() => understand(ex)} className="rounded-full bg-slate-500/10 px-3 py-1 text-xs text-slate-700 transition hover:bg-brand-500/15 hover:text-brand-700 dark:text-slate-300 dark:hover:text-brand-300" dir="auto">
            {ex}
          </button>
        ))}
      </div>

      {err && (
        <div className="mt-6">
          <ErrorBox error={err} />
        </div>
      )}

      {draft && (
        <div className="mt-6 space-y-4">
          {!draft.valid && (
            <div className={cx("rounded-2xl p-4 ring-1", draft.errors.length ? "bg-red-500/10 ring-red-500/30" : "bg-amber-500/10 ring-amber-500/30")}>
              <p className="flex items-center gap-2 font-semibold">
                <HelpCircle className="size-4" /> {draft.errors.length ? t.rules.problems : t.rules.questions}
              </p>
              <ul className="mt-2 list-disc space-y-1 ps-6 text-sm" dir="auto">
                {[...draft.errors, ...draft.questions].map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-slate-600 dark:text-slate-400">{t.rules.questionsHint}</p>
            </div>
          )}
          <Card title={t.rules.understood}>
            <div className="space-y-4 p-4">
              {draft.rule && (
                <p className={cx("text-xl font-semibold leading-relaxed", lang === "ur" && "urdu")} dir={lang === "ur" ? "rtl" : "ltr"}>
                  {lang === "ur" ? draft.rule.name_ur : (draft.rule.name_en ?? draft.rule.name_ur)}
                </p>
              )}
              <UnderstoodChips u={draft.understood as Understood} />
              {draft.rule && (
                <p className="font-mono text-xs text-slate-500" dir="ltr">
                  {draft.rule.rule_id}
                </p>
              )}
              {draft.backtest && <Backtest bt={draft.backtest} />}
              {draft.rule && can("rules:propose") && (
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    className="btn-primary"
                    disabled={sent === draft.rule.rule_id}
                    onClick={() =>
                      act(async () => {
                        await api<RuleOut>("/v1/rules", { body: { rule: draft.rule } });
                        setSent(draft.rule?.rule_id ?? null);
                      })
                    }
                  >
                    {sent === draft.rule.rule_id ? <CheckCircle2 className="size-4" /> : <Send className="size-4" />}
                    {sent === draft.rule.rule_id ? t.rules.proposed : t.rules.propose}
                  </button>
                  <span className="flex items-center gap-1.5 text-xs text-slate-500">
                    <ShieldCheck className="size-3.5" /> {t.rules.signedNote}
                  </span>
                </div>
              )}
            </div>
          </Card>
        </div>
      )}

      <div className="mt-8 grid gap-6">
        <Card title={t.rules.list}>
          {list.loading && !list.data ? (
            <Spinner />
          ) : list.error ? (
            <div className="p-4">
              <ErrorBox error={list.error} onRetry={list.reload} />
            </div>
          ) : !list.data?.length ? (
            <Empty icon={ListChecks} title={t.rules.none} />
          ) : (
            <ul className="divide-y divide-slate-200/70 dark:divide-white/5">
              {list.data.map((r) => (
                <li key={r.rule_id} className="flex flex-wrap items-start gap-4 p-4">
                  <div className="min-w-0 flex-1 space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={cx("rounded-md px-2 py-0.5 text-xs font-semibold ring-1", STATUS_TONE[r.status])}>{t.rules.status[r.status] ?? r.status}</span>
                      {r.on_edge === true && (
                        <Chip tone="brand">
                          <Cpu className="size-3" /> {t.rules.onEdge}
                        </Chip>
                      )}
                      {r.on_edge === false && (
                        <Chip tone="amber">
                          <Loader2 className="size-3 animate-spin" /> {t.rules.toEdge}
                        </Chip>
                      )}
                      <span className={cx("font-medium", lang === "ur" && "urdu")}>{lang === "ur" ? r.rule.name_ur : (r.rule.name_en ?? r.rule.name_ur)}</span>
                    </div>
                    {r.rule.source_text && (
                      <p className="text-sm text-slate-500" dir="auto">
                        “{r.rule.source_text}”
                      </p>
                    )}
                    <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
                      <span>
                        {t.rules.by}: {r.created_by}
                      </span>
                      {r.approved_by && (
                        <span>
                          {t.rules.approvedBy}: {r.approved_by}
                        </span>
                      )}
                      <span className="ltr-num">
                        {t.rules.version} {r.version} · {ago(r.created_at, lang)}
                      </span>
                      {r.backtest && (
                        <span className="ltr-num">
                          <FlaskConical className="inline size-3" /> {r.backtest.matches} / 7d
                        </span>
                      )}
                    </p>
                  </div>
                  {can("rules:manage") && r.status !== "disabled" && (
                    <div className="flex gap-2">
                      {r.status === "pending" && (
                        <button className="btn-primary" onClick={() => act(() => api(`/v1/rules/${r.rule_id}/approve`, { method: "POST" }))}>
                          <CheckCircle2 className="size-4" /> {t.rules.approve}
                        </button>
                      )}
                      <button className="btn-ghost" onClick={() => act(() => api(`/v1/rules/${r.rule_id}/disable`, { method: "POST" }))}>
                        <CircleSlash className="size-4" /> {t.rules.disable}
                      </button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
        <EventModes />
        <NetworkCard />
      </div>
    </>
  );
}

export default function Page() {
  return (
    <AppShell wide>
      <Rules />
    </AppShell>
  );
}
