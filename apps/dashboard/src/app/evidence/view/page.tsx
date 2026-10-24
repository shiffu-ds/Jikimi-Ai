"use client";

import { ArrowLeft, Download, ExternalLink, History } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { AppShell } from "@/components/AppShell";
import { VerifyReportView } from "@/components/VerifyReport";
import { Card, Chip, ErrorBox, PageHeader, Spinner } from "@/components/ui";
import type { EvidenceDetail, VerificationReport } from "@/lib/contracts.gen";
import { dateTime, short } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";

function Detail() {
  const id = useSearchParams().get("id");
  const { t } = useI18n();
  const ev = useApi<EvidenceDetail>(id ? `/v1/evidence/${id}` : null);
  const report = useApi<VerificationReport>(id ? `/v1/verify/${id}` : null);
  if (ev.error) return <ErrorBox error={ev.error} onRetry={ev.reload} />;
  if (!ev.data) return <Spinner label={t.common.loading} />;
  const e = ev.data;
  const manifest = e.manifest as { alerts?: Array<{ alert_id: string; type: string; ts_end: string; explanation_ur?: string }>; clips?: Array<{ clip_id: string; sha256: string }> };
  return (
    <>
      <PageHeader
        title={e.id}
        subtitle={`${dateTime(e.created_at)} · ${e.created_by}${e.case_reference ? ` · ${e.case_reference}` : ""}`}
        actions={
          <>
            <Link href="/evidence/" className="btn-ghost px-2.5">
              <ArrowLeft className="size-4 rtl:rotate-180" />
            </Link>
            {e.pdf_url && (
              <a className="btn-primary" href={e.pdf_url}>
                <Download className="size-4" /> {t.evidence.pdf}
              </a>
            )}
            <a className="btn-ghost" href={e.verify_url} target="_blank" rel="noreferrer">
              <ExternalLink className="size-4" /> {t.evidence.verify}
            </a>
          </>
        }
      />
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div>{report.data ? <VerifyReportView report={report.data} /> : <Spinner label={t.common.loading} />}</div>
        <div className="space-y-6">
          <Card title={t.nav.alerts}>
            <ul className="divide-y divide-slate-200/70 dark:divide-white/[0.06]">
              {manifest.alerts?.map((a) => (
                <li key={a.alert_id} className="px-4 py-3">
                  <Link href={`/alerts/view/?id=${a.alert_id}`} className="text-sm font-medium text-brand-700 hover:underline dark:text-brand-300">
                    {t.type[a.type] ?? a.type} · <span className="ltr-num">{dateTime(a.ts_end)}</span>
                  </Link>
                  {a.explanation_ur && <p className="urdu text-sm text-slate-600 dark:text-slate-300">{a.explanation_ur}</p>}
                </li>
              ))}
            </ul>
          </Card>
          <Card title={t.evidence.hashes}>
            <div className="space-y-2 p-4 font-mono text-xs" dir="ltr">
              <p>manifest {short(e.manifest_sha256, 16)}</p>
              {e.pdf_sha256 && <p>pdf {short(e.pdf_sha256, 16)}</p>}
              {manifest.clips?.map((c) => (
                <p key={c.clip_id}>
                  {c.clip_id} {short(c.sha256, 10)}
                </p>
              ))}
              <div className="flex gap-2 pt-1">
                <Chip>{t.evidence.merkle}: {e.merkle_status}</Chip>
                <Chip>{t.evidence.ots}: {e.ots_status}</Chip>
              </div>
            </div>
          </Card>
          <Card title={<span className="inline-flex items-center gap-2"><History className="size-4" /> {t.evidence.custody}</span>}>
            <ol className="space-y-2 p-4 text-xs">
              {e.custody.map((c, i) => (
                <li key={i} className="flex justify-between gap-2">
                  <span>
                    <b>{c.actor}</b> · {c.action}
                  </span>
                  <span className="ltr-num text-slate-500">{dateTime(c.at)}</span>
                </li>
              ))}
            </ol>
          </Card>
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
