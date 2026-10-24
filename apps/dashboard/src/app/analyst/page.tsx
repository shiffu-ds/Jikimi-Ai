"use client";

import { Clock, Loader2, MapPin, Search, Sparkles, Tag } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AgentChat } from "@/components/AgentChat";
import { AppShell } from "@/components/AppShell";
import {
  Card,
  Chip,
  Empty,
  ErrorBox,
  PageHeader,
  TypeIcon,
  cx,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { SearchResponse } from "@/lib/contracts.gen";
import { clock, dateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";

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

function Analyst() {
  const { site } = useAuth();
  const { t, lang } = useI18n();
  const [q, setQ] = useState("");
  const [res, setRes] = useState<SearchResponse | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const examples = useApi<{ examples: string[] }>("/v1/search/examples");
  const [mode, setMode] = useState<"search" | "chat">("search");

  async function run(query: string) {
    if (!site || !query.trim()) return;
    setQ(query);
    setBusy(true);
    setErr(null);
    try {
      setRes(
        await api<SearchResponse>("/v1/search", {
          body: { site_id: site.id, query, limit: 24 },
        }),
      );
    } catch (e) {
      setErr(e as Error);
    } finally {
      setBusy(false);
    }
  }

  const p = res?.parsed;
  return (
    <>
      <PageHeader title={t.analyst.title} subtitle={t.analyst.subtitle} />
      <div className="mb-4 inline-flex rounded-xl bg-slate-500/10 p-1 text-sm">
        {(["search", "chat"] as const).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={cx(
              "rounded-lg px-4 py-1.5 font-medium",
              mode === m
                ? "bg-white shadow-sm dark:bg-slate-800"
                : "text-slate-500",
            )}
          >
            {m === "search" ? t.analyst.modeSearch : t.analyst.modeChat}
          </button>
        ))}
      </div>
      {mode === "chat" ? (
        <AgentChat />
      ) : (
        <>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(q);
            }}
            className="card relative flex items-center gap-2 p-2 ring-brand-500/20 focus-within:ring-2"
          >
            <Search
              className="ms-2 size-5 shrink-0 text-slate-400"
              aria-hidden
            />
            <input
              className="min-w-0 flex-1 bg-transparent px-2 py-3 text-lg outline-none placeholder:text-slate-400"
              placeholder={t.analyst.placeholder}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              dir="auto"
              aria-label={t.analyst.search}
            />
            <button
              className="btn-primary px-5 py-3"
              disabled={busy || !q.trim()}
            >
              {busy ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Sparkles className="size-4" />
              )}
              {t.analyst.search}
            </button>
          </form>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-500">
              {t.analyst.examples}:
            </span>
            {examples.data?.examples.map((ex) => (
              <button
                key={ex}
                onClick={() => run(ex)}
                className="rounded-full bg-slate-500/10 px-3 py-1 text-xs text-slate-700 transition hover:bg-brand-500/15 hover:text-brand-700 dark:text-slate-300 dark:hover:text-brand-300"
                dir="auto"
              >
                {ex}
              </button>
            ))}
          </div>

          {err && (
            <div className="mt-6">
              <ErrorBox error={err} />
            </div>
          )}

          {p && res && (
            <div className="mt-6 space-y-6">
              <Card title={t.analyst.understood}>
                <div className="flex flex-wrap items-center gap-2 p-4 text-sm">
                  {p.time_range && (
                    <Chip tone="sky">
                      <Clock className="size-3" />
                      <span className="ltr-num">
                        {dateTime(p.time_range.from)} →{" "}
                        {dateTime(p.time_range.to).slice(0, 10) ===
                        dateTime(p.time_range.from).slice(0, 10)
                          ? clock(p.time_range.to)
                          : dateTime(p.time_range.to)}
                      </span>
                      {p.default_time_range && (
                        <span>({t.analyst.defaultRange})</span>
                      )}
                    </Chip>
                  )}
                  {p.objects.map((o, i) => (
                    <Chip key={i} tone="brand">
                      <Tag className="size-3" />
                      {o.color && (
                        <span
                          className="inline-block size-2.5 rounded-full ring-1 ring-black/20"
                          style={{ background: COLOR_DOT[o.color] }}
                        />
                      )}
                      {[
                        o.color,
                        o.type,
                        o.riders ? `${o.riders} riders` : null,
                        o.helmet === false
                          ? "no helmet"
                          : o.helmet
                            ? "helmet"
                            : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </Chip>
                  ))}
                  {p.zones.map((z) => (
                    <Chip key={z} tone="amber">
                      <MapPin className="size-3" />
                      {z}
                    </Chip>
                  ))}
                  {p.alert_types.map((a) => (
                    <Chip key={a} tone="red">
                      <TypeIcon type={a} className="size-3" /> {t.type[a] ?? a}
                    </Chip>
                  ))}
                  <span className="ms-auto flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <Chip>{p.parser_path}</Chip>
                    <span className="ltr-num">
                      {t.analyst.coverage} {Math.round(p.coverage * 100)}% ·{" "}
                      {t.analyst.took} {res.took_ms} ms
                    </span>
                  </span>
                  {p.unknown_tokens.length > 0 && (
                    <p className="w-full text-xs text-amber-600 dark:text-amber-400">
                      {t.analyst.unknown}: {p.unknown_tokens.join(", ")}
                    </p>
                  )}
                  {p.notes
                    .filter((n) => n.startsWith("privacy"))
                    .map((n) => (
                      <p key={n} className="w-full text-xs text-slate-500">
                        🔒 {n}
                      </p>
                    ))}
                  <p
                    className="w-full font-mono text-xs text-slate-500"
                    dir="ltr"
                  >
                    ≈ {p.text_en}
                  </p>
                </div>
              </Card>

              <div>
                <h2 className="mb-3 text-sm font-semibold text-slate-600 dark:text-slate-300">
                  {t.analyst.results}{" "}
                  <span className="ltr-num">({res.results.length})</span>
                </h2>
                {res.results.length === 0 ? (
                  <div className="card">
                    <Empty icon={Search} title={t.analyst.none} />
                  </div>
                ) : (
                  <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                    {res.results.map((r) => {
                      const body = (
                        <>
                          <div className="relative aspect-video overflow-hidden rounded-t-2xl bg-slate-900">
                            {r.thumbnail_url ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={r.thumbnail_url}
                                alt=""
                                className="size-full object-contain"
                                loading="lazy"
                              />
                            ) : (
                              <div className="grid size-full place-items-center text-slate-500">
                                <TypeIcon
                                  type={r.alert_type ?? "loitering"}
                                  className="size-10"
                                />
                              </div>
                            )}
                            <span className="absolute start-2 top-2 rounded-md bg-black/70 px-2 py-0.5 text-[11px] font-semibold text-white">
                              {r.kind === "alert"
                                ? (t.type[r.alert_type ?? ""] ?? "alert")
                                : "track"}
                            </span>
                            <span className="ltr-num absolute bottom-2 end-2 rounded-md bg-black/70 px-2 py-0.5 font-mono text-[11px] text-white">
                              {Math.round(r.score * 100)}%
                            </span>
                          </div>
                          <div className="space-y-2 p-3">
                            <div className="flex items-center justify-between text-xs text-slate-500">
                              <span>{r.camera_name ?? r.camera_id}</span>
                              <span className="ltr-num">
                                {dateTime(r.ts_start)}
                              </span>
                            </div>
                            <div className="flex flex-wrap gap-1">
                              {r.matched.map((m) => (
                                <Chip
                                  key={m}
                                  tone={m.includes("~") ? "amber" : "brand"}
                                >
                                  {m}
                                </Chip>
                              ))}
                            </div>
                          </div>
                        </>
                      );
                      return r.alert_id ? (
                        <Link
                          key={r.clip_id}
                          href={`/alerts/view/?id=${r.alert_id}`}
                          className="card card-hover overflow-hidden"
                        >
                          {body}
                        </Link>
                      ) : (
                        <div key={r.clip_id} className="card overflow-hidden">
                          {body}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
          {!res && !busy && (
            <div className={cx("card mt-6", lang === "ur" && "urdu")}>
              <Empty
                icon={Sparkles}
                title={t.analyst.subtitle}
                hint="kal raat · aaj subah · pichle 2 ghante · kaali / laal / safaid · bike / gaari / rickshaw · 2 sawar · helmet nahi · gate"
              />
            </div>
          )}
        </>
      )}
    </>
  );
}

export default function Page() {
  return (
    <AppShell wide>
      <Analyst />
    </AppShell>
  );
}
