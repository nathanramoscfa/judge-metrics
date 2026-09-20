// web/components/synthetic-banner.tsx
// The site-wide demo-data notice: a server component that reads
// /api/v1/coverage through the sixty-second in-process cache
// (lib/coverage-cache.ts) and renders a persistent, non-dismissable banner
// whenever any synthetic source has rows. When the call fails the banner is
// simply absent (ApiResult never throws; a failure is not cached) — the
// pages show their own error states.
import { FlaskConical } from "lucide-react";
import Link from "next/link";

import { coverageCache } from "@/lib/coverage-cache";

export const SYNTHETIC_BANNER_TEXT =
  "Demo data: this site currently includes a synthetic dataset; synthetic records are labelled";

export function SyntheticBannerView({ present }: { present: boolean }) {
  if (!present) return null;
  return (
    <div
      role="note"
      aria-label="Demo data notice"
      data-testid="synthetic-banner"
      className="border-b border-amber-300 bg-amber-50 text-amber-950 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-100"
    >
      <p className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-2 text-sm">
        <FlaskConical aria-hidden="true" className="size-4 shrink-0" />
        <span>
          {SYNTHETIC_BANNER_TEXT}{" "}
          <Link href="/coverage" className="font-medium underline underline-offset-2">
            (see coverage)
          </Link>
          .
        </span>
      </p>
    </div>
  );
}

export async function SyntheticBanner() {
  const coverage = await coverageCache.get();
  return <SyntheticBannerView present={coverage.ok && coverage.data.synthetic_present} />;
}
