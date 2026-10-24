"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { en, ur, type Messages } from "./messages";

export type Lang = "ur" | "en";

interface I18n {
  lang: Lang;
  dir: "rtl" | "ltr";
  t: Messages;
  setLang: (l: Lang) => void;
  toggle: () => void;
}

const Ctx = createContext<I18n | null>(null);

function stored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("ur");

  useEffect(() => {
    const saved = stored("jikimi.lang");
    if (saved === "en" || saved === "ur") setLangState(saved);
  }, []);

  useEffect(() => {
    const html = document.documentElement;
    html.lang = lang === "ur" ? "ur" : "en";
    html.dir = lang === "ur" ? "rtl" : "ltr";
  }, [lang]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      window.localStorage.setItem("jikimi.lang", l);
    } catch {
      /* private mode */
    }
  }, []);

  const value = useMemo<I18n>(
    () => ({
      lang,
      dir: lang === "ur" ? "rtl" : "ltr",
      t: lang === "ur" ? ur : en,
      setLang,
      toggle: () => setLang(lang === "ur" ? "en" : "ur"),
    }),
    [lang, setLang],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useI18n(): I18n {
  const v = useContext(Ctx);
  if (!v) throw new Error("useI18n outside I18nProvider");
  return v;
}
