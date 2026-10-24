"use client";

import { CheckCircle2, CircleDashed, FileUp, Loader2, ShieldCheck, ShieldX, XCircle } from "lucide-react";
import { useState } from "react";

import { api } from "@/lib/api";
import type { FileMatch, VerificationReport } from "@/lib/contracts.gen";
import { dateTime, short } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { sha256File } from "@/lib/sha256";

import { cx } from "./ui";

const ICON = { pass: CheckCircle2, fail: XCircle, pending: CircleDashed, skipped: CircleDashed } as const;
const TONE = {
  pass: "text-emerald-500",
  fail: "text-red-500",
  pending: "text-amber-500",
  skipped: "text-slate-400",
} as const;

export function VerifyReportView({ report }: { report: VerificationReport }) {
  const { t, lang } = useI18n();
  const [drag, setDrag] = useState(false);
  const [result, setResult] = useState<(FileMatch & { file: string }) | null>(null);
  const [hashing, setHashing] = useState(false);

  async function check(file: File) {
    setHashing(true);
    setResult(null);
    try {
      const sha = await sha256File(file);
      const m = await api<FileMatch>(`/v1/verify/${report.evidence_id}/match?sha256=${sha}`);
      setResult({ ...m, file: file.name });
    } finally {
      setHashing(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className={cx("card flex flex-wrap items-center gap-5 p-6", report.verified ? "border-emerald-500/40" : "border-red-500/50")}>
        <div className={cx("grid size-16 place-items-center rounded-2xl", report.verified ? "bg-emerald-500/15 text-emerald-500" : "bg-red-500/15 text-red-500")}>
          {report.verified ? <ShieldCheck className="size-9" /> : <ShieldX className="size-9" />}
        </div>
        <div className="min-w-0 flex-1">
          <p className={cx("text-2xl font-bold", report.verified ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400", lang === "ur" && "urdu-h font-normal")}>
            {lang === "ur" ? report.summary_ur : report.summary_en}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            <span className="font-mono">{report.evidence_id}</span> · {report.site_name} · <span className="ltr-num">{dateTime(report.created_at)}</span> · {report.alert_count} alert / {report.clip_count} clip
          </p>
        </div>
      </div>

      <div className="card divide-y divide-slate-200/70 dark:divide-white/[0.06]">
        {report.checks.map((c) => {
          const Icon = ICON[c.status as keyof typeof ICON] ?? CircleDashed;
          return (
            <div key={c.name} className="flex items-start gap-3 px-5 py-3.5">
              <Icon className={cx("mt-0.5 size-5 shrink-0", TONE[c.status as keyof typeof TONE])} />
              <div className="min-w-0 flex-1">
                <p className={cx("font-medium", lang === "ur" && "urdu text-base")}>{lang === "ur" ? c.detail_ur : c.detail_en}</p>
                <p className="font-mono text-xs text-slate-500">
                  {c.name} · {t.check[c.status] ?? c.status}
                  {typeof c.data?.root === "string" && <> · root {short(c.data.root as string, 8)}</>}
                </p>
              </div>
            </div>
          );
        })}
      </div>

      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          const f = e.dataTransfer.files?.[0];
          if (f) void check(f);
        }}
        className={cx("card flex cursor-pointer flex-col items-center gap-2 border-2 border-dashed p-8 text-center transition", drag ? "border-brand-500 bg-brand-500/5" : "border-slate-300 dark:border-white/15")}
      >
        {hashing ? <Loader2 className="size-8 animate-spin text-brand-500" /> : <FileUp className="size-8 text-brand-500" />}
        <span className={cx("font-medium", lang === "ur" && "urdu")}>{hashing ? t.verify.hashing : t.verify.drop}</span>
        <span className="text-xs text-slate-500">{t.verify.privacy}</span>
        <input type="file" className="hidden" onChange={(e) => e.target.files?.[0] && check(e.target.files[0])} />
      </label>
      {result && (
        <div className={cx("card flex items-center gap-3 p-4", result.matched ? "border-emerald-500/40" : "border-red-500/50")} role="status">
          {result.matched ? <CheckCircle2 className="size-6 text-emerald-500" /> : <XCircle className="size-6 text-red-500" />}
          <div className="min-w-0">
            <p className={cx("font-semibold", lang === "ur" && "urdu")}>{result.matched ? t.verify.match : t.verify.noMatch}</p>
            <p className="truncate font-mono text-xs text-slate-500" dir="ltr">
              {result.file} · {result.kind ?? "?"} · sha256 {short(result.sha256, 12)}
            </p>
          </div>
        </div>
      )}

      <details className="card p-4 text-sm">
        <summary className="cursor-pointer font-medium">{t.verify.artifacts}</summary>
        <ul className="mt-3 space-y-1 font-mono text-xs" dir="ltr">
          <li>manifest {report.manifest_sha256}</li>
          {report.artifacts.map((a) => (
            <li key={a.name}>
              {a.kind} {a.name} {a.sha256}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
