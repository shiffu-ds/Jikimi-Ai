"use client";

import {
  AlertTriangle,
  Bike,
  CameraOff,
  CheckCircle2,
  CircleDot,
  Clock,
  Hand,
  Loader2,
  type LucideIcon,
  MessageSquareWarning,
  Network,
  Ruler,
  ShieldAlert,
  Siren,
  Volume2,
  XCircle,
} from "lucide-react";

import { useI18n } from "@/lib/i18n";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export const TYPE_ICON: Record<string, LucideIcon> = {
  snatch: Hand,
  loitering: Bike,
  camera_tamper: CameraOff,
  rule: Ruler,
  sos: Siren,
  audio_event: Volume2,
  network_match: Network,
};

const SEV: Record<string, string> = {
  high: "bg-red-500/15 text-red-600 ring-red-500/30 dark:text-red-300",
  medium: "bg-amber-500/15 text-amber-700 ring-amber-500/30 dark:text-amber-300",
  low: "bg-slate-500/15 text-slate-600 ring-slate-500/25 dark:text-slate-300",
};
const SEV_ICON: Record<string, LucideIcon> = { high: ShieldAlert, medium: AlertTriangle, low: CircleDot };

export function SeverityBadge({ severity }: { severity: string }) {
  const { t } = useI18n();
  const Icon = SEV_ICON[severity] ?? CircleDot;
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1", SEV[severity] ?? SEV.low)}>
      <Icon className="size-3.5" aria-hidden />
      {t.severity[severity] ?? severity}
    </span>
  );
}

const STATUS: Record<string, string> = {
  open: "bg-red-500 text-white",
  escalated: "bg-orange-500 text-white",
  verifying: "bg-violet-500/90 text-white",
  acked: "bg-sky-500/90 text-white",
  resolved: "bg-emerald-600/90 text-white",
  false_alarm: "bg-slate-500/80 text-white",
  unclear: "bg-zinc-500/80 text-white",
  logged_only: "bg-slate-400/40 text-slate-800 dark:text-slate-200",
};
const STATUS_ICON: Record<string, LucideIcon> = {
  open: Siren,
  escalated: MessageSquareWarning,
  verifying: Loader2,
  acked: CheckCircle2,
  resolved: CheckCircle2,
  false_alarm: XCircle,
  unclear: CircleDot,
  logged_only: Clock,
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useI18n();
  const Icon = STATUS_ICON[status] ?? CircleDot;
  return (
    <span className={cx("inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold", STATUS[status] ?? STATUS.logged_only)}>
      <Icon className={cx("size-3.5", status === "verifying" && "animate-spin")} aria-hidden />
      {t.status[status] ?? status}
    </span>
  );
}

export function TypeIcon({ type, className }: { type: string; className?: string }) {
  const Icon = TYPE_ICON[type] ?? AlertTriangle;
  return <Icon className={className} aria-hidden />;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400" role="status">
      <Loader2 className="size-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function ErrorBox({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const { t } = useI18n();
  return (
    <div className="card flex items-center justify-between gap-3 border-red-500/30 p-4 text-sm text-red-600 dark:text-red-300" role="alert">
      <span>
        {t.common.error}: {error.message}
      </span>
      {onRetry && (
        <button className="btn-ghost" onClick={onRetry}>
          {t.common.retry}
        </button>
      )}
    </div>
  );
}

export function Empty({ icon: Icon = CheckCircle2, title, hint }: { icon?: LucideIcon; title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center text-slate-500 dark:text-slate-400">
      <Icon className="size-10 text-brand-500/70" aria-hidden />
      <p className="text-base font-medium text-slate-700 dark:text-slate-200">{title}</p>
      {hint && <p className="max-w-md text-sm">{hint}</p>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  const { lang } = useI18n();
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className={cx("text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl dark:text-white", lang === "ur" && "urdu-h font-normal")}>{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, icon: Icon, tone = "brand" }: { label: string; value: React.ReactNode; hint?: React.ReactNode; icon: LucideIcon; tone?: "brand" | "red" | "amber" | "sky" | "violet" }) {
  const tones = {
    brand: "from-brand-500/20 text-brand-600 dark:text-brand-300",
    red: "from-red-500/20 text-red-600 dark:text-red-300",
    amber: "from-amber-500/20 text-amber-600 dark:text-amber-300",
    sky: "from-sky-500/20 text-sky-600 dark:text-sky-300",
    violet: "from-violet-500/20 text-violet-600 dark:text-violet-300",
  };
  return (
    <div className="card relative overflow-hidden p-4">
      <div className={cx("pointer-events-none absolute -end-6 -top-6 size-24 rounded-full bg-gradient-to-br to-transparent blur-xl", tones[tone])} />
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm leading-snug text-slate-500 dark:text-slate-400">{label}</p>
          <p className="ltr-num mt-1 text-3xl font-bold text-slate-900 dark:text-white">{value}</p>
          {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
        </div>
        <div className={cx("rounded-xl bg-current/10 p-2.5", tones[tone])}>
          <Icon className="size-5" aria-hidden />
        </div>
      </div>
    </div>
  );
}

export function Chip({ children, tone = "slate", title }: { children: React.ReactNode; tone?: "slate" | "brand" | "amber" | "red" | "sky"; title?: string }) {
  const tones = {
    slate: "bg-slate-500/10 text-slate-700 ring-slate-500/20 dark:text-slate-300",
    brand: "bg-brand-500/10 text-brand-700 ring-brand-500/25 dark:text-brand-300",
    amber: "bg-amber-500/10 text-amber-700 ring-amber-500/25 dark:text-amber-300",
    red: "bg-red-500/10 text-red-700 ring-red-500/25 dark:text-red-300",
    sky: "bg-sky-500/10 text-sky-700 ring-sky-500/25 dark:text-sky-300",
  };
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded-lg px-2 py-0.5 text-xs font-medium ring-1", tones[tone])}>
      {children}
    </span>
  );
}

export function Card({ title, actions, children, className }: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={cx("card", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-200/70 px-4 py-3 dark:border-white/[0.06]">
          <h2 className="text-sm font-semibold text-slate-700 dark:text-slate-200">{title}</h2>
          {actions}
        </header>
      )}
      <div>{children}</div>
    </section>
  );
}
