// Times are shown in the site timezone (Asia/Karachi) with Western digits (plan Section 12.1).
const TZ = "Asia/Karachi";

export function clock(iso: string | null | undefined, withSeconds = false): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit", second: withSeconds ? "2-digit" : undefined, hour12: false });
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const date = d.toLocaleDateString("en-CA", { timeZone: TZ });
  return `${date} ${clock(iso, true)}`;
}

export function ago(iso: string | null | undefined, lang: "ur" | "en", now = Date.now()): string {
  if (!iso) return "—";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (lang === "ur") {
    if (s < 60) return `${s} سیکنڈ پہلے`;
    if (s < 3600) return `${Math.round(s / 60)} منٹ پہلے`;
    if (s < 86400) return `${Math.round(s / 3600)} گھنٹے پہلے`;
    return `${Math.round(s / 86400)} دن پہلے`;
  }
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s.toString().padStart(2, "0")}s`;
}

export function pct(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return `${Math.round(x * 1000) / 10}%`;
}

export function short(hash: string | null | undefined, n = 10): string {
  if (!hash) return "—";
  return hash.length > 2 * n ? `${hash.slice(0, n)}…${hash.slice(-6)}` : hash;
}
