"use client";

import { Download, FileCheck2, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/components/AppShell";
import { Chip, Empty, ErrorBox, PageHeader, Spinner } from "@/components/ui";
import { qs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { EvidenceSummary } from "@/lib/contracts.gen";
import { dateTime, short } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useLiveEvent } from "@/lib/live";

function EvidenceList() {
  const { site } = useAuth();
  const { t } = useI18n();
  const list = useApi<EvidenceSummary[]>(site ? `/v1/evidence${qs({ site_id: site.id })}` : null);
  useLiveEvent(["evidence.created"], () => list.reload());
  return (
    <>
      <PageHeader title={t.evidence.title} subtitle={t.evidence.subtitle} />
      {list.error && <ErrorBox error={list.error} onRetry={list.reload} />}
      {!list.data && !list.error && <Spinner label={t.common.loading} />}
      {list.data?.length === 0 && (
        <div className="card">
          <Empty icon={FileCheck2} title={t.evidence.none} />
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {list.data?.map((e) => (
          <div key={e.id} className="card card-hover p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <Link href={`/evidence/view/?id=${e.id}`} className="font-mono text-lg font-semibold text-brand-700 hover:underline dark:text-brand-300">
                  {e.id}
                </Link>
                <p className="ltr-num mt-0.5 text-xs text-slate-500">
                  {dateTime(e.created_at)} · {e.created_by}
                </p>
              </div>
              <ShieldCheck className="size-7 text-brand-500" />
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {e.case_reference && <Chip tone="amber">{e.case_reference}</Chip>}
              <Chip>
                {e.alert_count} alert · {e.clip_count} clip
              </Chip>
              <Chip tone={e.merkle_status === "included" ? "brand" : "slate"}>
                {t.evidence.merkle}: {e.merkle_status}
              </Chip>
              <Chip tone={e.ots_status === "confirmed" ? "brand" : "slate"}>
                {t.evidence.ots}: {e.ots_status}
              </Chip>
            </div>
            <p className="mt-3 font-mono text-[11px] text-slate-500" dir="ltr">
              sha256 {short(e.manifest_sha256, 14)}
            </p>
            <div className="mt-3 flex gap-2">
              {e.pdf_url && (
                <a className="btn-ghost" href={e.pdf_url}>
                  <Download className="size-4" /> {t.evidence.pdf}
                </a>
              )}
              <Link className="btn-ghost" href={`/verify/?id=${e.id}`}>
                <ShieldCheck className="size-4" /> {t.evidence.verify}
              </Link>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}

export default function Page() {
  return (
    <AppShell>
      <EvidenceList />
    </AppShell>
  );
}
