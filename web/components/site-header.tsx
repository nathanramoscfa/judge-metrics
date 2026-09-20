// web/components/site-header.tsx
// The header landmark: wordmark, primary navigation, and the theme toggle.
// The skip link that precedes it lives in app/layout.tsx.
import Link from "next/link";

import { ThemeToggle } from "@/components/theme-toggle";

const NAV = [
  { href: "/search", label: "Search" },
  { href: "/compare", label: "Compare" },
  { href: "/coverage", label: "Coverage" },
  { href: "/methodology", label: "Methodology" },
  { href: "/about", label: "About" },
] as const;

export function SiteHeader() {
  return (
    <header className="border-b bg-background/95">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4">
        <Link
          href="/"
          className="font-heading text-base font-semibold tracking-tight"
          aria-label="JudgeMetrics home"
        >
          JudgeMetrics
        </Link>
        <nav aria-label="Primary" className="flex items-center gap-1">
          <ul className="flex items-center gap-1">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
