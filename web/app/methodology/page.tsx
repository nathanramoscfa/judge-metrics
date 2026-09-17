// web/app/methodology/page.tsx
// Methodology: the ten product principles, the association-is-not-causation
// statement, and where the metric definitions will appear (Phase 3). This
// page is static; it reads nothing from the API.
import type { Metadata } from "next";

import { DATA_SOURCES_URL, ROADMAP_URL } from "@/lib/links";

export const metadata: Metadata = { title: "Methodology" };

const PRINCIPLES = [
  "Source every material claim.",
  "Preserve raw source records immutably.",
  "Separate facts from derived statistics.",
  "Separate observed outcomes from causal claims.",
  "Separate judicial actions from prosecutor, legislature, jury, clerk, and law-enforcement actions.",
  "Show uncertainty, sample size, and missing-data limitations.",
  "Make methodology inspectable and reproducible.",
  "Prefer APIs and bulk public data over brittle scraping.",
  "Minimize public exposure of personally identifying defendant information.",
  "Treat data lineage as a first-class feature.",
] as const;

export default function MethodologyPage() {
  return (
    <article className="prose-sm flex max-w-3xl flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">Methodology</h1>
        <p className="text-muted-foreground">
          How JudgeMetrics turns public court records into statistics, and what those
          statistics can and cannot say.
        </p>
      </header>

      <section aria-labelledby="statement-heading" className="rounded-xl border bg-muted/40 p-5">
        <h2 id="statement-heading" className="text-lg font-semibold">
          What the numbers mean
        </h2>
        <p className="mt-2 text-base" data-testid="association-statement">
          These statistics describe associations in available records. They do not
          prove that a judicial decision caused a later event.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          An arrest never proves a crime. Arrest, charge, conviction, dismissal,
          acquittal, release, sentence, and later events are separate facts and are kept
          as separate records. A prosecutor&apos;s dismissal is not a judicial dismissal,
          and a statutory release is not a discretionary decision; every judge-level
          metric uses only events whose attribution satisfies its documented inclusion
          rules. There is no composite, ideological, partisan, or &ldquo;best judge&rdquo;
          score, and there never will be.
        </p>
      </section>

      <section aria-labelledby="principles-heading" className="flex flex-col gap-3">
        <h2 id="principles-heading" className="text-lg font-semibold">
          Principles
        </h2>
        <ol className="list-decimal space-y-1.5 pl-6" data-testid="principles">
          {PRINCIPLES.map((principle) => (
            <li key={principle}>{principle}</li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="published-heading" className="flex flex-col gap-3">
        <h2 id="published-heading" className="text-lg font-semibold">
          What every published number shows
        </h2>
        <p>
          The numerator, the denominator, the date range, the coverage of the records
          behind it, the sample size, and — for adjusted statistics — an interval and a
          methodology version. Small cohorts are suppressed. Every number traces to the
          raw artifacts it was derived from, identified by the sha256 of the stored bytes
          (the &ldquo;Source coverage&rdquo; panel on each judge and court page).
        </p>
      </section>

      <section aria-labelledby="status-heading" className="flex flex-col gap-3">
        <h2 id="status-heading" className="text-lg font-semibold">
          Status
        </h2>
        <p data-testid="metrics-note">
          Metric definitions, formulas, the risk-adjustment model, exclusions, sample
          thresholds, known limitations, and the methodology changelog arrive in Phase 3
          with the metrics engine. Until then this site publishes judicial identity and
          service records only, with their provenance.
        </p>
        <ul className="list-disc space-y-1 pl-6 text-sm">
          <li>
            <a href={DATA_SOURCES_URL} className="text-primary hover:underline">
              Data-source register
            </a>{" "}
            — every source, its terms, and its verification status.
          </li>
          <li>
            <a href={ROADMAP_URL} className="text-primary hover:underline">
              Project roadmap
            </a>{" "}
            — the phases, including when each metric family is published.
          </li>
        </ul>
      </section>
    </article>
  );
}
