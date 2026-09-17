// web/components/theme-provider.tsx
// next-themes keyed on `data-theme` (see app/globals.css): the resolved
// theme is written to <html data-theme="light|dark"> before paint, and the
// preference lives in localStorage — no cookie is set.
"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ReactNode } from "react";

export function ThemeProvider({ children }: { children: ReactNode }) {
  return (
    <NextThemesProvider
      attribute="data-theme"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
    >
      {children}
    </NextThemesProvider>
  );
}
