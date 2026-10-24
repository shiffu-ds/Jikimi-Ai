"use client";

import { Languages, Lock, ShieldCheck } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { HangulMark } from "@/components/HangulMark";
import { Logo } from "@/components/Logo";
import { cx } from "@/components/ui";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useI18n } from "@/lib/i18n";

function LoginForm() {
  const { login, user, ready } = useAuth();
  const { t, lang, toggle } = useI18n();
  const router = useRouter();
  const params = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const next = params.get("next") || "/";

  useEffect(() => {
    if (ready && user) router.replace(user.role === "guard" ? "/guard/" : next);
  }, [ready, user, router, next]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim().toLowerCase(), password);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? t.login.failed : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative grid min-h-screen place-items-center overflow-hidden px-4">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(60rem_40rem_at_70%_-10%,rgb(20_184_166/0.22),transparent),radial-gradient(40rem_30rem_at_-10%_110%,rgb(14_116_144/0.25),transparent)]" />
      <div className="scanlines pointer-events-none absolute inset-0 opacity-40" />
      <div className="relative w-full max-w-md">
        <div className="mb-8 flex flex-col items-center text-center">
          <Logo className="size-20 drop-shadow-[0_10px_30px_rgb(20_184_166/0.45)]" />
          <h1 className={cx("mt-4 text-3xl font-bold text-slate-900 dark:text-white", lang === "ur" && "urdu-h font-normal")}>{t.appName}</h1>
          <p className="mt-2 flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
            <HangulMark className="h-3.5 w-auto text-brand-500" /> · {t.tagline}
          </p>
        </div>
        <form onSubmit={submit} className="card space-y-4 p-6 backdrop-blur">
          <div>
            <h2 className="text-lg font-semibold">{t.login.title}</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">{t.login.subtitle}</p>
          </div>
          <label className="block space-y-1.5">
            <span className="label">{t.login.username}</span>
            <input className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required dir="ltr" />
          </label>
          <label className="block space-y-1.5">
            <span className="label">{t.login.password}</span>
            <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required dir="ltr" />
          </label>
          {error && (
            <p className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-300" role="alert">
              {error}
            </p>
          )}
          <button className="btn-primary w-full py-2.5" disabled={busy}>
            <Lock className="size-4" />
            {t.login.submit}
          </button>
          <div className="flex items-center justify-between pt-1 text-xs text-slate-500 dark:text-slate-400">
            <span className="inline-flex items-center gap-1.5">
              <ShieldCheck className="size-3.5 text-brand-500" />
              {t.login.privacy}
            </span>
            <button type="button" onClick={toggle} className="inline-flex items-center gap-1 hover:text-brand-500">
              <Languages className="size-3.5" />
              {t.common.language}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
