import "@fontsource-variable/inter";
import "@fontsource/noto-nastaliq-urdu/400.css";
import "@fontsource/noto-nastaliq-urdu/700.css";
import "@fontsource/noto-naskh-arabic/400.css";
import "@fontsource/noto-naskh-arabic/600.css";
import "./globals.css";

import type { Metadata, Viewport } from "next";

import { Providers, ThemeScript } from "@/components/Providers";

export const metadata: Metadata = {
  title: "Jikimi AI · جکیمی",
  description: "Edge-first AI guard for existing CCTV: early warning, Roman Urdu search, offline SMS alerts and tamper-evident evidence.",
  icons: { icon: "/favicon.svg" },
};

export const viewport: Viewport = {
  themeColor: "#0f766e",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ur" dir="rtl" className="dark" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
