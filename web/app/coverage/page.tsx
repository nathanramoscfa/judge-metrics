// web/app/coverage/page.tsx
// Coverage: jurisdictions, dates, sources, completeness, and known gaps
// arrive in Phase 2; this stub says so and links the source register.
import type { Metadata } from "next";

import { DATA_SOURCES_URL } from "@/lib/links";

export const metadata: Metadata = { title: "Coverage" };

export default function CoveragePage() {
  return (
    <article className="flex max-w-3xl flex-col gap-4">
      <h1 className="text-3xl font-semibold tracking-tight">Coverage</h1>
      <p className="rounded-xl border border-dashed px-6 py-8 text-muted-foreground" data-testid="coverage-note">
        The coverage map, dates covered, completeness estimates, and known gaps are coming
        in Phase 2. Today the only ingested source is the Federal Judicial Center&apos;s
        biographical directory: Article III judges, their courts, and their service
        records.
      </p>
      <p className="text-sm">
        <a href={DATA_SOURCES_URL} className="text-primary hover:underline">
          Read the data-source register
        </a>
      </p>
    </article>
  );
}
