"use client";

import { BellRing, Check, HelpCircle, Loader2, LogOut, Mic, Siren, Volume2, WifiOff, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Logo } from "@/components/Logo";
import { TypeIcon, cx } from "@/components/ui";
import { ApiError, api, qs, upload } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AlertPage, AlertSummary, VoiceReply as Heard } from "@/lib/contracts.gen";
import { ago, clock } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useI18n } from "@/lib/i18n";
import { useLive, useLiveEvent } from "@/lib/live";

// Guard PWA (plan Section 12.2): big buttons, little text, voice-first, works on a cheap phone,
// queues actions while offline and plays a loud alarm (sound + vibration + flash).

type Queued = { path: string; body: unknown; at: number };
type Kind = "ack" | "false" | "help";
const KIND_OF: Record<NonNullable<Heard["intent"]>, Kind> = { ack: "ack", false_alarm: "false", need_help: "help" };
const QUEUE_KEY = "jikimi.guard.queue";

function readQueue(): Queued[] {
  try {
    return JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]") as Queued[];
  } catch {
    return [];
  }
}
function writeQueue(q: Queued[]) {
  try {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(q));
  } catch {
    /* ignore */
  }
}

function useAlarm() {
  const ctx = useRef<AudioContext | null>(null);
  const [enabled, setEnabled] = useState(false);
  const enable = () => {
    ctx.current = ctx.current ?? new AudioContext();
    void ctx.current.resume();
    setEnabled(true);
  };
  const ring = useCallback(() => {
    navigator.vibrate?.([400, 150, 400, 150, 800]);
    const ac = ctx.current;
    if (!ac) return;
    const now = ac.currentTime;
    for (let i = 0; i < 6; i++) {
      const o = ac.createOscillator();
      const g = ac.createGain();
      o.type = "square";
      o.frequency.value = i % 2 ? 880 : 1320;
      g.gain.setValueAtTime(0.0001, now + i * 0.28);
      g.gain.exponentialRampToValueAtTime(0.25, now + i * 0.28 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, now + i * 0.28 + 0.25);
      o.connect(g).connect(ac.destination);
      o.start(now + i * 0.28);
      o.stop(now + i * 0.28 + 0.26);
    }
  }, []);
  return { enabled, enable, ring };
}

/** Read an alert aloud. Many phones have a Hindi voice and no Urdu one; spoken Urdu and Hindi are
 * one language, so the Urdu text in Devanagari (``explanation_hi``) goes to the Hindi voice. */
function speak(a: Pick<AlertSummary, "explanation_ur" | "explanation_en" | "explanation_hi">, lang: "ur" | "en") {
  if (!("speechSynthesis" in window)) return;
  const voices = window.speechSynthesis.getVoices();
  const find = (code: string) => voices.find((x) => x.lang.toLowerCase().startsWith(code));
  let text = a.explanation_en ?? "";
  let voice = find("en");
  let tag = "en-GB";
  if (lang === "ur" && find("ur")) [text, voice, tag] = [a.explanation_ur ?? "", find("ur"), "ur-PK"];
  else if (lang === "ur" && find("hi") && a.explanation_hi) [text, voice, tag] = [a.explanation_hi, find("hi"), "hi-IN"];
  else if (lang === "ur") [text, tag] = [a.explanation_ur ?? "", "ur-PK"];
  const u = new SpeechSynthesisUtterance(text);
  if (voice) u.voice = voice;
  u.lang = tag;
  u.rate = 0.95;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
}

/** F12: the guard says "haan dekh liya" / "ghalat alarm hai" / "madad chahiye"; the server writes it
 * down and reads the intent, and nothing is sent until the guard taps what was understood. */
function VoiceReply({ onConfirm }: { onConfirm: (kind: Kind, note: string) => void }) {
  const { t, lang } = useI18n();
  const [state, setState] = useState<"idle" | "recording" | "sending">("idle");
  const [heard, setHeard] = useState<Heard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [supported, setSupported] = useState(false);
  const rec = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const label: Record<Kind, string> = { ack: t.guard.seen, false: t.guard.falseAlarm, help: t.guard.needHelp };
  // the microphone needs HTTPS (or localhost) and MediaRecorder; without them the buttons remain
  useEffect(() => setSupported(Boolean(navigator.mediaDevices?.getUserMedia) && typeof MediaRecorder !== "undefined"), []);

  function stop() {
    clearTimeout(timer.current);
    if (rec.current?.state === "recording") rec.current.stop();
  }
  async function start() {
    setErr(null);
    setHeard(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setErr(t.guard.micDenied);
      return;
    }
    const mime = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find((m) => MediaRecorder.isTypeSupported(m));
    const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
    const parts: Blob[] = [];
    r.ondataavailable = (e) => {
      if (e.data.size) parts.push(e.data);
    };
    r.onstop = async () => {
      stream.getTracks().forEach((tr) => tr.stop());
      setState("sending");
      try {
        setHeard(await upload<Heard>(`/v1/voice/reply${qs({ lang })}`, new Blob(parts, { type: r.mimeType })));
      } catch (e) {
        setErr(e instanceof ApiError && e.status === 503 ? t.guard.voiceOff : (e as Error).message);
      }
      setState("idle");
    };
    rec.current = r;
    r.start();
    setState("recording");
    timer.current = setTimeout(stop, 8000); // replies are short; the server cuts at 15 s anyway
  }

  const kind = heard?.intent ? KIND_OF[heard.intent] : null;
  if (!supported) return null;
  return (
    <div className="mt-3 space-y-2">
      <button
        onClick={state === "recording" ? stop : start}
        disabled={state === "sending"}
        className={cx(
          "flex w-full items-center justify-center gap-2 rounded-2xl py-3 text-base font-semibold active:scale-[0.98]",
          state === "recording" ? "animate-pulse bg-red-500 text-white" : "bg-white/10",
        )}
      >
        {state === "sending" ? <Loader2 className="size-5 animate-spin" /> : <Mic className="size-5" />}
        {state === "recording" ? t.guard.voiceListening : state === "sending" ? t.guard.voiceSending : t.guard.voice}
      </button>
      {err && <p className="text-sm text-amber-300">{err}</p>}
      {heard && (
        <div className="rounded-2xl bg-white/5 p-3">
          <p className="text-xs text-slate-400">{t.guard.voiceHeard}</p>
          <p dir="auto" className={cx("mt-1 text-white", /[\u0600-\u06ff]/.test(heard.text) ? "urdu text-lg" : "text-base")}>
            «{heard.text || "…"}»
          </p>
          {kind ? (
            <div className="mt-3 grid grid-cols-[2fr_1fr] gap-2">
              <button
                onClick={() => {
                  onConfirm(kind, `voice: ${heard.text}`.slice(0, 250));
                  setHeard(null);
                }}
                className={cx(
                  "flex items-center justify-center gap-2 rounded-xl py-3 font-bold text-slate-950 active:scale-[0.98]",
                  kind === "help" ? "bg-orange-500" : kind === "false" ? "bg-slate-200" : "bg-emerald-500",
                )}
              >
                <Check className="size-5" /> {t.guard.voiceSend}: {label[kind]}
              </button>
              <button onClick={start} className="rounded-xl bg-white/10 py-3 font-semibold">
                {t.guard.voiceRetry}
              </button>
            </div>
          ) : (
            <p className="mt-2 text-sm text-amber-300">{t.guard.voiceUnclear}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function GuardPage() {
  const { user, ready, site, logout } = useAuth();
  const { t, lang, toggle } = useI18n();
  const { status } = useLive();
  const router = useRouter();
  const alarm = useAlarm();
  const [flash, setFlash] = useState(false);
  const [online, setOnline] = useState(true);
  const [queued, setQueued] = useState(0);
  const [sosState, setSosState] = useState<"idle" | "holding" | "sent">("idle");
  const holdTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const page = useApi<AlertPage>(site ? `/v1/alerts${qs({ site_id: site.id, limit: 10 })}` : null, 20000);

  useEffect(() => {
    if (ready && !user) router.replace("/login/?next=/guard/");
  }, [ready, user, router]);

  useEffect(() => {
    if ("serviceWorker" in navigator) void navigator.serviceWorker.register("/guard/sw.js", { scope: "/guard/" }).catch(() => undefined);
    const up = () => setOnline(navigator.onLine);
    up();
    window.addEventListener("online", up);
    window.addEventListener("offline", up);
    setQueued(readQueue().length);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", up);
    };
  }, []);

  const send = useCallback(async (path: string, body: unknown) => {
    try {
      await api(path, { body });
      return true;
    } catch (e) {
      if (!navigator.onLine || (e instanceof TypeError)) {
        const q = [...readQueue(), { path, body, at: Date.now() }];
        writeQueue(q);
        setQueued(q.length);
        return false;
      }
      throw e;
    }
  }, []);

  // flush the offline queue when we are back online
  useEffect(() => {
    if (!online) return;
    const q = readQueue();
    if (!q.length) return;
    void (async () => {
      const left: Queued[] = [];
      for (const item of q) {
        try {
          await api(item.path, { body: item.body });
        } catch {
          left.push(item);
        }
      }
      writeQueue(left);
      setQueued(left.length);
      page.reload();
    })();
  }, [online, page]);

  useLiveEvent(["alert.notify"], (m) => {
    const a = m.data.alert as AlertSummary | undefined;
    alarm.ring();
    setFlash(true);
    setTimeout(() => setFlash(false), 2500);
    if (a) speak(a, lang);
    page.reload();
  });
  useLiveEvent(["alert.created", "alert.updated"], () => page.reload());

  const items = page.data?.items ?? [];
  const current = items.find((a) => a.status === "open" || a.status === "escalated");

  async function act(a: AlertSummary, kind: Kind, note?: string) {
    if (kind === "ack") await send(`/v1/alerts/${a.id}/ack`, { note: note ?? "guard app" });
    if (kind === "false") await send(`/v1/alerts/${a.id}/review`, { verdict: "false", notes: note });
    if (kind === "help") await send(`/v1/sos`, { site_id: a.site_id, camera_id: a.camera_id, note: `madad: ${a.short_code}${note ? ` (${note})` : ""}` });
    page.reload();
  }

  function holdStart() {
    if (!site) return;
    setSosState("holding");
    holdTimer.current = setTimeout(async () => {
      await send("/v1/sos", { site_id: site.id, note: "guard SOS" });
      setSosState("sent");
      navigator.vibrate?.(300);
      setTimeout(() => setSosState("idle"), 4000);
    }, 2000);
  }
  function holdEnd() {
    clearTimeout(holdTimer.current);
    if (sosState === "holding") setSosState("idle");
  }

  if (!ready || !user) return null;

  return (
    <div className={cx("min-h-screen bg-slate-950 text-white transition-colors", flash && "bg-red-900")}>
      <link rel="manifest" href="/guard/manifest.webmanifest" />
      <header className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <Logo className="size-8" />
          <div className="leading-tight">
            <p className={cx("font-bold", lang === "ur" && "urdu-h font-normal")}>{t.guard.title} · {user.name.split(" ")[0]}</p>
            <p className="flex items-center gap-1.5 text-xs text-slate-400">
              <span className={cx("size-2 rounded-full", status === "open" && online ? "bg-emerald-400" : "bg-red-500")} />
              {status === "open" && online ? t.common.live : t.common.offline}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={toggle} className="rounded-xl bg-white/10 px-3 py-2 text-xs font-semibold">
            {t.common.language}
          </button>
          <button onClick={async () => { await logout(); router.replace("/login/"); }} className="rounded-xl bg-white/10 p-2" aria-label={t.common.logout}>
            <LogOut className="size-4" />
          </button>
        </div>
      </header>

      {!alarm.enabled && (
        <button onClick={alarm.enable} className="mx-4 mb-3 flex w-[calc(100%-2rem)] items-center justify-center gap-2 rounded-2xl bg-amber-500 py-3 text-base font-bold text-slate-950">
          <Volume2 className="size-5" /> {t.guard.sound}
        </button>
      )}
      {(!online || queued > 0) && (
        <p className="mx-4 mb-3 flex items-center gap-2 rounded-xl bg-amber-500/15 px-3 py-2 text-sm text-amber-300">
          <WifiOff className="size-4" /> {t.guard.queued} ({queued})
        </p>
      )}

      <main className="space-y-4 px-4 pb-40">
        {current ? (
          <section className={cx("animate-pulse-ring rounded-3xl border-2 border-red-500 bg-red-500/10 p-5")}>
            <div className="flex items-center justify-between">
              <span className="inline-flex items-center gap-2 text-lg font-bold text-red-300">
                <TypeIcon type={current.type} className="size-6" />
                <span className={cx(lang === "ur" && "urdu-h font-normal")}>{t.type[current.type]}</span>
              </span>
              <span className="ltr-num font-mono text-sm text-red-200">
                #{current.short_code} · {clock(current.ts_end)}
              </span>
            </div>
            {current.thumbnail_url && (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={current.thumbnail_url} alt="" className="mt-3 aspect-video w-full rounded-2xl object-cover" />
            )}
            <p className={cx("mt-3 text-white", lang === "ur" ? "urdu text-xl" : "text-lg")}>{lang === "ur" ? current.explanation_ur : current.explanation_en}</p>
            <button onClick={() => speak(current, lang)} className="mt-2 inline-flex items-center gap-1.5 text-sm text-red-200">
              <Volume2 className="size-4" /> {t.guard.speak}
            </button>
            {online && <VoiceReply onConfirm={(kind, note) => act(current, kind, note)} />}
            <div className="mt-4 grid grid-cols-1 gap-3">
              <button onClick={() => act(current, "ack")} className="flex items-center justify-center gap-3 rounded-2xl bg-emerald-500 py-5 text-2xl font-bold text-slate-950 active:scale-[0.98]">
                <Check className="size-7" /> {t.guard.seen}
              </button>
              <div className="grid grid-cols-2 gap-3">
                <button onClick={() => act(current, "false")} className="flex items-center justify-center gap-2 rounded-2xl bg-white/10 py-4 text-lg font-semibold active:scale-[0.98]">
                  <X className="size-5" /> {t.guard.falseAlarm}
                </button>
                <button onClick={() => act(current, "help")} className="flex items-center justify-center gap-2 rounded-2xl bg-orange-500 py-4 text-lg font-semibold text-slate-950 active:scale-[0.98]">
                  <HelpCircle className="size-5" /> {t.guard.needHelp}
                </button>
              </div>
            </div>
          </section>
        ) : (
          <section className="rounded-3xl border border-emerald-500/30 bg-emerald-500/10 p-8 text-center">
            <BellRing className="mx-auto size-12 text-emerald-400" />
            <p className={cx("mt-3 text-3xl font-bold text-emerald-300", lang === "ur" && "urdu-h font-normal")}>{t.guard.allClear}</p>
            <p className="mt-1 text-slate-300">{t.guard.allClearSub}</p>
          </section>
        )}

        <section>
          <h2 className="mb-2 text-sm font-semibold text-slate-400">{t.guard.recent}</h2>
          <ul className="space-y-2">
            {items
              .filter((a) => a !== current)
              .slice(0, 6)
              .map((a) => (
                <li key={a.id} className="flex items-center gap-3 rounded-2xl bg-white/5 p-3">
                  <TypeIcon type={a.type} className="size-5 shrink-0 text-slate-300" />
                  <div className="min-w-0 flex-1">
                    <p className={cx("truncate text-sm", lang === "ur" && "font-naskh")}>{t.type[a.type]}</p>
                    <p className="ltr-num text-xs text-slate-400">{ago(a.created_at, lang)}</p>
                  </div>
                  <span className="rounded-md bg-white/10 px-2 py-0.5 text-xs">{t.status[a.status]}</span>
                </li>
              ))}
          </ul>
        </section>
      </main>

      <div className="fixed inset-x-0 bottom-0 bg-gradient-to-t from-slate-950 via-slate-950/95 to-transparent px-4 pb-6 pt-10">
        <button
          onPointerDown={holdStart}
          onPointerUp={holdEnd}
          onPointerLeave={holdEnd}
          onContextMenu={(e) => e.preventDefault()}
          className={cx(
            "relative flex w-full select-none items-center justify-center gap-3 overflow-hidden rounded-3xl py-6 text-3xl font-black tracking-wider text-white shadow-2xl shadow-red-900/50 transition",
            sosState === "sent" ? "bg-emerald-600" : "bg-red-600 active:scale-[0.99]",
          )}
          aria-label={t.guard.sos}
        >
          {sosState === "holding" && <span className="absolute inset-y-0 start-0 animate-[grow_2s_linear_forwards] bg-red-400/40" />}
          <Siren className="relative size-8" />
          <span className="relative">{sosState === "sent" ? t.guard.sosSent : t.guard.sos}</span>
        </button>
        <p className="mt-2 text-center text-xs text-slate-400">{t.guard.sosHold}</p>
      </div>
    </div>
  );
}
