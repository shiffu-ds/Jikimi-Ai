"use client";

// Small dependency-free SVG charts (bars by day, horizontal bars by type).
import type { CountByKey } from "@/lib/contracts.gen";

export function DayBars({ data, height = 120 }: { data: CountByKey[]; height?: number }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  const w = 100 / Math.max(1, data.length);
  return (
    <div className="ltr-num" dir="ltr">
      <svg viewBox={`0 0 100 ${height / 3}`} className="w-full" style={{ height }} preserveAspectRatio="none" role="img" aria-label="alerts per day">
        {data.map((d, i) => {
          const h = (d.count / max) * (height / 3 - 6);
          return (
            <g key={d.key}>
              <rect x={i * w + w * 0.18} y={height / 3 - h} width={w * 0.64} height={Math.max(h, 0.6)} rx={1.2} className="fill-brand-500/80" />
            </g>
          );
        })}
      </svg>
      <div className="mt-1 grid text-center text-[10px] text-slate-500" style={{ gridTemplateColumns: `repeat(${data.length}, minmax(0, 1fr))` }}>
        {data.map((d) => (
          <span key={d.key}>
            <span className="block font-semibold text-slate-700 dark:text-slate-300">{d.count}</span>
            {d.key.slice(5)}
          </span>
        ))}
      </div>
    </div>
  );
}

export function TypeBars({ data, label }: { data: CountByKey[]; label: (k: string) => string }) {
  const max = Math.max(1, ...data.map((d) => d.count));
  if (!data.length) return <p className="text-sm text-slate-500">—</p>;
  return (
    <ul className="space-y-2">
      {data.map((d) => (
        <li key={d.key}>
          <div className="mb-1 flex justify-between text-xs text-slate-600 dark:text-slate-300">
            <span>{label(d.key)}</span>
            <span className="ltr-num font-semibold">{d.count}</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-500/10">
            <div className="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-300" style={{ width: `${(d.count / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}
