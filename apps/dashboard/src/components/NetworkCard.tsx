"use client";

import { Network, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { NetworkSettings, NetworkStatus } from "@/lib/contracts.gen";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";

import { Card, Chip, ErrorBox, Spinner } from "./ui";

/** F21 mohalla network: admins opt in (with the signed agreement and the site's location). */
export function NetworkCard() {
  const { site, can } = useAuth();
  const { t } = useI18n();
  const url =
    site && can("admin")
      ? `/v1/sites/${encodeURIComponent(site.id)}/network`
      : null;
  const st = useApi<NetworkStatus>(url);
  const [form, setForm] = useState<NetworkSettings | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (st.data) setForm(st.data.settings);
  }, [st.data]);
  if (!url) return null;
  if (st.error) return <ErrorBox error={st.error} onRetry={st.reload} />;
  if (!st.data || !form) return <Spinner label={t.common.loading} />;

  async function save(next: NetworkSettings) {
    setBusy(true);
    setErr(null);
    try {
      await api<NetworkStatus>(url as string, { method: "PUT", body: next });
      st.reload();
    } catch (e) {
      setErr(e as Error);
    }
    setBusy(false);
  }
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  return (
    <Card
      title={
        <span className="inline-flex items-center gap-2">
          <Network className="size-4" /> {t.network.title}
        </span>
      }
      actions={
        <Chip tone={st.data.settings.opted_in ? "brand" : "slate"}>
          {st.data.settings.opted_in ? t.network.on : t.network.off}
        </Chip>
      }
    >
      <div className="space-y-4 p-4 text-sm">
        <p className="text-slate-500">{t.network.explain}</p>
        <ul className="flex flex-wrap gap-2 text-xs">
          <Chip>
            {t.network.neighbors}:{" "}
            <span className="ltr-num">{st.data.neighbors}</span>
          </Chip>
          <Chip>
            {t.network.sent}:{" "}
            <span className="ltr-num">{st.data.shares_sent_24h}</span>
          </Chip>
          <Chip>
            {t.network.received}:{" "}
            <span className="ltr-num">{st.data.shares_received_active}</span>
          </Chip>
        </ul>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="block">
            <span className="label">{t.network.radius}</span>
            <select
              className="input mt-1"
              value={form.radius_km}
              onChange={(e) =>
                setForm({ ...form, radius_km: Number(e.target.value) })
              }
            >
              {[1, 1.5, 2].map((r) => (
                <option key={r} value={r}>
                  {r} km
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="label">{t.network.lat}</span>
            <input
              className="input ltr-num mt-1"
              dir="ltr"
              value={form.lat ?? ""}
              onChange={(e) => setForm({ ...form, lat: num(e.target.value) })}
            />
          </label>
          <label className="block">
            <span className="label">{t.network.lon}</span>
            <input
              className="input ltr-num mt-1"
              dir="ltr"
              value={form.lon ?? ""}
              onChange={(e) => setForm({ ...form, lon: num(e.target.value) })}
            />
          </label>
        </div>
        <label className="block">
          <span className="label">{t.network.agreement}</span>
          <input
            className="input mt-1"
            value={form.agreement ?? ""}
            placeholder={t.network.agreementHint}
            onChange={(e) =>
              setForm({ ...form, agreement: e.target.value || null })
            }
          />
        </label>
        <p className="flex items-start gap-1.5 text-xs text-slate-500">
          <ShieldCheck className="mt-0.5 size-3.5 shrink-0" /> {t.network.rules}
        </p>
        {err && <p className="text-sm text-red-500">{err.message}</p>}
        <div className="flex flex-wrap gap-2">
          {st.data.settings.opted_in ? (
            <>
              <button
                className="btn-primary"
                disabled={busy}
                onClick={() => save({ ...form, opted_in: true })}
              >
                {t.network.save}
              </button>
              <button
                className="btn-ghost"
                disabled={busy}
                onClick={() => save({ ...form, opted_in: false })}
              >
                {t.network.leave}
              </button>
            </>
          ) : (
            <button
              className="btn-primary"
              disabled={
                busy || !form.agreement || form.lat == null || form.lon == null
              }
              onClick={() => save({ ...form, opted_in: true })}
            >
              {t.network.join}
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}
