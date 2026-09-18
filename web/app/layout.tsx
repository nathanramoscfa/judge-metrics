// web/app/layout.tsx
// The root layout: skip link, the demo-data banner, header, main landmark,
// footer, and the theme provider. `suppressHydrationWarning` on <html> is
// for next-themes, which writes data-theme before React hydrates. The
// banner asks the API whether a synthetic source is present on every
// request, so the whole site renders dynamically: nothing is prerendered at
// build time (the build still needs no API — a failed call shows no banner).
import type { Metadata } from "next";
import type { ReactNode } from "react";

import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";
import { SyntheticBanner } from "@/components/synthetic-banner";
import { ThemeProvider } from "@/components/theme-provider";
import { TooltipProvider } from "@/components/ui/tooltip";

import "./globals.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: {
    default: "JudgeMetrics",
    template: "%s · JudgeMetrics",
  },
  description:
    "Judicial outcomes, measured from public court records, with every statistic traceable to its source.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <ThemeProvider>
          <TooltipProvider>
            <a href="#main" className="skip-link">
              Skip to main content
            </a>
            <SyntheticBanner />
            <SiteHeader />
            <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
              {children}
            </main>
            <SiteFooter />
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
