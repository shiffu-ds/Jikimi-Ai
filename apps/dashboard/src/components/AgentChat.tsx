"use client";

import { Bot, Loader2, Send, User, Wrench } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { AgentContext, AgentReply } from "@/lib/contracts.gen";
import { dateTime } from "@/lib/format";
import { useI18n } from "@/lib/i18n";

import { Chip, TypeIcon, cx } from "./ui";

type Msg = { who: "you"; text: string } | { who: "agent"; reply: AgentReply };

/** F1 Tier 2: multi-turn investigation. Read-only tools; every answer cites this site's clips. */
export function AgentChat() {
  const { site } = useAuth();
  const { t, lang } = useI18n();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [ctx, setCtx] = useState<AgentContext | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function ask(message: string) {
    if (!site || !message.trim() || busy) return;
    setMsgs((m) => [...m, { who: "you", text: message }]);
    setText("");
    setBusy(true);
    setErr(null);
    try {
      const reply = await api<AgentReply>("/v1/agent", {
        body: { site_id: site.id, message, context: ctx },
      });
      setCtx(reply.context);
      setMsgs((m) => [...m, { who: "agent", reply }]);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">{t.analyst.readOnly}</p>
      <div className="space-y-4">
        {msgs.map((m, i) =>
          m.who === "you" ? (
            <div key={i} className="flex justify-end">
              <p
                className="flex max-w-[85%] items-start gap-2 rounded-2xl bg-brand-500/15 px-4 py-2.5 text-sm"
                dir="auto"
              >
                <User className="mt-0.5 size-4 shrink-0" /> {m.text}
              </p>
            </div>
          ) : (
            <div key={i} className="card space-y-3 p-4">
              <p
                className={cx(
                  "flex items-start gap-2",
                  lang === "ur" ? "urdu text-base" : "text-sm",
                )}
              >
                <Bot className="mt-1 size-4 shrink-0 text-brand-500" />
                {lang === "ur" ? m.reply.answer_ur : m.reply.answer_en}
              </p>
              {m.reply.citations.length > 0 && (
                <div>
                  <p className="label mb-1.5">{t.analyst.cited}</p>
                  <div className="flex gap-2 overflow-x-auto pb-1">
                    {m.reply.citations.map((c) => {
                      const card = (
                        <div className="w-40 shrink-0 overflow-hidden rounded-xl bg-slate-500/10 text-xs">
                          <div className="grid aspect-video place-items-center bg-slate-900">
                            {c.thumbnail_url ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={c.thumbnail_url}
                                alt=""
                                className="size-full object-contain"
                                loading="lazy"
                              />
                            ) : (
                              <TypeIcon
                                type={c.alert_type ?? "loitering"}
                                className="size-6 text-slate-500"
                              />
                            )}
                          </div>
                          <p className="truncate px-2 pt-1 font-medium">
                            {c.camera_name ?? c.camera_id}
                          </p>
                          <p className="ltr-num px-2 pb-1.5 text-slate-500">
                            {dateTime(c.ts_start)}
                          </p>
                        </div>
                      );
                      return c.alert_id ? (
                        <Link
                          key={c.clip_id}
                          href={`/alerts/view/?id=${c.alert_id}`}
                          title={c.clip_id}
                        >
                          {card}
                        </Link>
                      ) : (
                        <div key={c.clip_id} title={c.clip_id}>
                          {card}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
              {m.reply.draft_report && (
                <details className="rounded-xl bg-amber-500/10 p-3 text-xs">
                  <summary className="cursor-pointer font-semibold">
                    {t.analyst.draft}
                  </summary>
                  <pre className="mt-2 whitespace-pre-wrap font-mono" dir="ltr">
                    {m.reply.draft_report}
                  </pre>
                </details>
              )}
              <p className="flex flex-wrap items-center gap-1.5 text-[11px] text-slate-500">
                <Wrench className="size-3" /> {t.analyst.tools}:
                {m.reply.tools.map((tc, j) => (
                  <Chip key={j}>
                    {tc.name} · <span className="ltr-num">{tc.results}</span>
                  </Chip>
                ))}
              </p>
            </div>
          ),
        )}
        {busy && <Loader2 className="size-5 animate-spin text-brand-500" />}
        {err && <p className="text-sm text-red-500">{err}</p>}
      </div>
      {ctx && ctx.clip_ids.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {t.analyst.followups.map((f) => (
            <button
              key={f}
              onClick={() => ask(f)}
              className="rounded-full bg-slate-500/10 px-3 py-1 text-xs hover:bg-brand-500/15"
              dir="auto"
            >
              {f}
            </button>
          ))}
        </div>
      )}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void ask(text);
        }}
        className="card flex items-center gap-2 p-2"
      >
        <input
          className="min-w-0 flex-1 bg-transparent px-3 py-2.5 outline-none placeholder:text-slate-400"
          placeholder={t.analyst.placeholder}
          value={text}
          onChange={(e) => setText(e.target.value)}
          dir="auto"
          aria-label={t.analyst.ask}
        />
        <button
          className="btn-primary px-4 py-2.5"
          disabled={busy || !text.trim()}
        >
          <Send className="size-4" /> {t.analyst.ask}
        </button>
      </form>
    </div>
  );
}
