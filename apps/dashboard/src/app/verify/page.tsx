"use client";

import { Languages, ShieldCheck } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Logo } from "@/components/Logo";
import { VerifyReportView } from "@/components/VerifyReport";
import { ErrorBox, Spinner, cx } from "@/components/ui";
import type { VerificationReport } from "@/lib/contracts.gen";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";

// Public portal (no login): QR codes on evidence PDFs land here.
function VerifyPortal() {
  const params = useSearchParams();
  const router = useRouter();
  const { t, lang, toggle } = useI18n();
  const id = params.get("id");
  const [input, setInput] = useState(id ?? "");
  const report = useApi<VerificationReport>(id ? `/v1/verify/${encodeURIComponent(id)}` : null);

  return (
    <div className="min-h-screen">
      <header className="border-b border-slate-200/70 bg-white/70 backdrop-blur dark:border-white/[0.06] dark:bg-slate-950/60">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4">
          <div className="flex items-center gap-3">
            <Logo className="size-9" />
            <div>
              <p className={cx("font-bold", lang === "ur" && "urdu-h font-normal")}>{t.verify.title}</p>
              <p className="text-xs text-slate-500">{t.verify.subtitle}</p>
            </div>
          </div>
          <button className="btn-ghost px-2.5" onClick={toggle}>
            <Languages className="size-4" /> <span className="text-xs">{t.common.language}</span>
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-3xl space-y-6 px-4 py-8">
        <form
          className="card flex gap-2 p-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (input.trim()) router.replace(`/verify/?id=${encodeURIComponent(input.trim())}`);
          }}
        >
          <input className="min-w-0 flex-1 bg-transparent px-3 py-2 font-mono outline-none" placeholder="EV-2026-10-22-0007" value={input} onChange={(e) => setInput(e.target.value)} dir="ltr" aria-label={t.verify.enterId} />
          <button className="btn-primary">
            <ShieldCheck className="size-4" /> {t.verify.check}
          </button>
        </form>
        {id && report.loading && !report.data && <Spinner label={t.common.loading} />}
        {report.error && <ErrorBox error={report.error} />}
        {report.data && <VerifyReportView report={report.data} />}
        <p className="text-center text-xs text-slate-500">Jikimi AI · Ed25519 · RFC 6962 Merkle · OpenTimestamps · SHA-256</p>
      </main>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <VerifyPortal />
    </Suspense>
  );
}
