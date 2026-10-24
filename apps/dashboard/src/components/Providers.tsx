"use client";

import { useEffect, useState } from "react";

import { AuthProvider, useAuth } from "@/lib/auth";
import { I18nProvider } from "@/lib/i18n";
import { LiveProvider } from "@/lib/live";

function LiveGate({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  return <LiveProvider enabled={Boolean(user)}>{children}</LiveProvider>;
}

export function ThemeScript() {
  // runs before paint: dark by default (night shift), light if the user chose it
  const code = `try{var t=localStorage.getItem('jikimi.theme');document.documentElement.classList.toggle('dark',t!=='light');var l=localStorage.getItem('jikimi.lang');if(l==='en'){document.documentElement.dir='ltr';document.documentElement.lang='en'}}catch(e){document.documentElement.classList.add('dark')}`;
  return <script dangerouslySetInnerHTML={{ __html: code }} />;
}

export function useTheme(): { dark: boolean; toggle: () => void } {
  const [dark, setDark] = useState(true);
  useEffect(() => setDark(document.documentElement.classList.contains("dark")), []);
  return {
    dark,
    toggle: () => {
      const next = !document.documentElement.classList.contains("dark");
      document.documentElement.classList.toggle("dark", next);
      setDark(next);
      try {
        localStorage.setItem("jikimi.theme", next ? "dark" : "light");
      } catch {
        /* ignore */
      }
    },
  };
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <I18nProvider>
      <AuthProvider>
        <LiveGate>{children}</LiveGate>
      </AuthProvider>
    </I18nProvider>
  );
}
