"use client";

import { CalendarCheck2, CalendarClock, CalendarPlus, Moon, Trash2 } from "lucide-react";
import { useState } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { CalendarOut, ModeWindow, ModeWindowCreate } from "@/lib/contracts.gen";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveEvent } from "@/lib/live";

import { Card, ErrorBox, Spinner, cx } from "./ui";

type Mode = ModeWindowCreate["mode"];
const MODES: Mode[] = ["ramadan", "chand_raat", "eid", "muharram", "independence_day", "bazaar_day"];

const MODE_TONE: Record<string, string> = {
  normal: "bg-slate-500/10 text-slate-600 ring-slate-500/20 dark:text-slate-300",
  ramadan: "bg-violet-500/15 text-violet-700 ring-violet-500/30 dark:text-violet-300",
  chand_raat: "bg-amber-500/15 text-amber-700 ring-amber-500/30 dark:text-amber-300",
  eid: "bg-emerald-500/15 text-emerald-700 ring-emerald-500/30 dark:text-emerald-300",
  muharram: "bg-slate-700/15 text-slate-800 ring-slate-700/30 dark:text-slate-200",
  independence_day: "bg-green-600/15 text-green-700 ring-green-600/30 dark:text-green-300",
  bazaar_day: "bg-sky-500/15 text-sky-700 ring-sky-500/30 dark:text-sky-300",
};

export function ModeBadge({ mode }: { mode: string }) {
  const { t } = useI18n();
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1", MODE_TONE[mode] ?? MODE_TONE.normal)}>
      <Moon className="size-3" aria-hidden />
      {t.modes.label[mode] ?? mode}
    </span>
  );
}

function Dates({ w }: { w: Pick<ModeWindow, "starts" | "ends"> }) {
  return <span className="ltr-num font-mono text-xs text-slate-500">{w.starts === w.ends ? w.starts : `${w.starts} → ${w.ends}`}</span>;
}

function EstimateRow({ w, onConfirm, canConfirm }: { w: ModeWindow; onConfirm: (body: ModeWindowCreate) => void; canConfirm: boolean }) {
  const { t } = useI18n();
  const [starts, setStarts] = useState(w.starts);
  const [ends, setEnds] = useState(w.ends);
  return (
    <li className="flex flex-wrap items-center gap-3 py-2.5">
      <ModeBadge mode={w.mode} />
      <span className="min-w-36 font-medium" dir="ltr">
        {w.name}
      </span>
      {canConfirm ? (
        <span className="flex items-center gap-1.5">
          <input type="date" className="input ltr-num w-40 py-1 text-xs" value={starts} onChange={(e) => setStarts(e.target.value)} aria-label="starts" />
          <span className="text-slate-400">→</span>
          <input type="date" className="input ltr-num w-40 py-1 text-xs" value={ends} onChange={(e) => setEnds(e.target.value)} aria-label="ends" />
        </span>
      ) : (
        <Dates w={w} />
      )}
      {canConfirm && (
        <button className="btn-ghost ms-auto py-1 text-xs" onClick={() => onConfirm({ name: w.name, mode: w.mode, starts, ends })}>
          <CalendarCheck2 className="size-3.5" /> {t.modes.confirm}
        </button>
      )}
    </li>
  );
}

export function EventModes() {
  const { site, can } = useAuth();
  const { t } = useI18n();
  const cal = useApi<CalendarOut>(site ? `/v1/sites/${encodeURIComponent(site.id)}/calendar` : null);
  useLiveEvent(["calendar.updated", "health.updated"], () => cal.reload());
  const [err, setErr] = useState<Error | null>(null);
  const [draft, setDraft] = useState<ModeWindowCreate>({ name: "", mode: "bazaar_day", starts: "", ends: "" });
  const admin = can("admin");
  const base = site ? `/v1/sites/${encodeURIComponent(site.id)}/calendar` : "";

  async function act(fn: () => Promise<unknown>) {
    setErr(null);
    try {
      await fn();
      cal.reload();
    } catch (e) {
      setErr(e as Error);
    }
  }

  const c = cal.data;
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <CalendarClock className="size-4" /> {t.modes.title}
          {c && (
            <span className="ms-2 flex items-center gap-1.5 text-xs font-normal text-slate-500">
              {t.modes.today}: <ModeBadge mode={c.current_mode} />
              {c.edge_synced === true && <span className="text-emerald-600 dark:text-emerald-400">✓ {t.modes.synced}</span>}
              {c.edge_synced === false && <span className="text-amber-600 dark:text-amber-400">{t.modes.syncing}</span>}
            </span>
          )}
        </span>
      }
    >
      <div className="space-y-5 p-4">
        <p className="text-sm text-slate-600 dark:text-slate-300">{t.modes.hint}</p>
        {c && c.current_mode === "normal" && (c.rush_ratio ?? 0) >= 2 && (
          <p className="rounded-xl bg-amber-500/10 p-3 text-sm text-amber-800 ring-1 ring-amber-500/30 dark:text-amber-200">
            {t.modes.rush.replace("{x}", (c.rush_ratio ?? 0).toFixed(1))}
          </p>
        )}
        {err && <ErrorBox error={err} />}
        {cal.loading && !c ? (
          <Spinner />
        ) : cal.error ? (
          <ErrorBox error={cal.error} onRetry={cal.reload} />
        ) : c ? (
          <>
            <section>
              <h3 className="mb-1 text-sm font-semibold">{t.modes.confirmed}</h3>
              {c.windows.length === 0 ? (
                <p className="text-sm text-slate-500">{t.modes.none}</p>
              ) : (
                <ul className="divide-y divide-slate-200/70 dark:divide-white/5">
                  {c.windows.map((w) => (
                    <li key={w.id} className="flex flex-wrap items-center gap-3 py-2.5">
                      <ModeBadge mode={w.mode} />
                      <span className="font-medium" dir="ltr">
                        {w.name}
                      </span>
                      <Dates w={w} />
                      <span className="text-xs text-slate-500">
                        {t.modes.by}: {w.confirmed_by}
                      </span>
                      {admin && (
                        <button className="btn-ghost ms-auto py-1 text-xs" onClick={() => act(() => api(`${base}/${w.id}`, { method: "DELETE" }))}>
                          <Trash2 className="size-3.5" /> {t.modes.remove}
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section>
              <h3 className="text-sm font-semibold">{t.modes.estimates}</h3>
              <p className="mb-1 text-xs text-slate-500">{t.modes.estimateHint}</p>
              <ul className="divide-y divide-slate-200/70 dark:divide-white/5">
                {c.estimates.slice(0, 8).map((w) => (
                  <EstimateRow key={`${w.name}-${w.starts}`} w={w} canConfirm={admin} onConfirm={(body) => act(() => api<ModeWindow>(base, { body }))} />
                ))}
              </ul>
            </section>
            {admin && (
              <form
                className="flex flex-wrap items-end gap-2 rounded-xl bg-slate-500/5 p-3"
                onSubmit={(e) => {
                  e.preventDefault();
                  void act(async () => {
                    await api<ModeWindow>(base, { body: { ...draft, ends: draft.ends || draft.starts } });
                    setDraft({ ...draft, name: "", starts: "", ends: "" });
                  });
                }}
              >
                <span className="flex w-full items-center gap-1.5 text-xs font-semibold text-slate-600 dark:text-slate-300">
                  <CalendarPlus className="size-3.5" /> {t.modes.add}
                </span>
                <input className="input w-44 py-1 text-sm" placeholder={t.modes.name} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} required maxLength={80} dir="auto" />
                <select className="input w-36 py-1 text-sm" value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value as Mode })} aria-label="mode">
                  {MODES.map((m) => (
                    <option key={m} value={m}>
                      {t.modes.label[m]}
                    </option>
                  ))}
                </select>
                <input type="date" className="input ltr-num w-40 py-1 text-xs" value={draft.starts} onChange={(e) => setDraft({ ...draft, starts: e.target.value })} required aria-label="starts" />
                <input type="date" className="input ltr-num w-40 py-1 text-xs" value={draft.ends} onChange={(e) => setDraft({ ...draft, ends: e.target.value })} aria-label="ends" />
                <button className="btn-primary py-1.5 text-sm">
                  <CalendarCheck2 className="size-4" /> {t.modes.confirm}
                </button>
              </form>
            )}
          </>
        ) : null}
      </div>
    </Card>
  );
}
