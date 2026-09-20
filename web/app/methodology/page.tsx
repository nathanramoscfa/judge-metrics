// web/app/methodology/page.tsx
// Methodology, rendered from GET /api/v1/metrics on every request: the
// association-is-not-causation statement, the ten product principles, how
// to read a number, the index-event and censoring semantics, attribution,
// one anchored section per metric definition (name, version, subjects,
// formula, eligibility, attribution rule, windows, threshold, unit),
// suppression, the eight known limitations verbatim, and the changelog —
// all as React text nodes, never HTML. The definitions are the same
// registry `docs/METHODOLOGY.md` is rendered from, not a second copy.
import type { Metadata } from "next";

import { ErrorState } from "@/components/states";
import { getRegistry, type MetricDefinition, type Registry } from "@/lib/api/client";
import { DATA_SOURCES_URL, METHODOLOGY_DOC_URL, ROADMAP_URL } from "@/lib/links";
import { ASSOCIATION_STATEMENT } from "@/lib/metrics";

export const dynamic = "force-dynamic";

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

const KIND_TEXT: Record<MetricDefinition["kind"], string> = {
  count: "count",
  share: "share (numerator over denominator, Wilson interval)",
  windowed_rate: "fixed-window rate per observation window (Wilson interval)",
  survival: "Kaplan–Meier cumulative incidence per observation window",
  distribution: "distribution of counts by dimension value",
  median: "median",
};

function attributionText(definition: MetricDefinition, gates: Record<string, string>): string {
  const rule = definition.attribution;
  const parts: string[] = [];
  if (rule.decision_type) parts.push(`decision type ${rule.decision_type}`);
  if (rule.actor_types) parts.push(`actor ${rule.actor_types.join(" or ")}`);
  if (rule.discretion) parts.push(`discretion ${rule.discretion.join(" or ")}`);
  parts.push(`gate: ${gates[rule.assignment_gate] ?? rule.assignment_gate}`);
  return `${parts.join("; ")}.`;
}

function Definition({ definition, gates }: { definition: MetricDefinition; gates: Record<string, string> }) {
  const threshold =
    definition.suppression_threshold === 0
      ? "0 (never suppressed: a count)"
      : `${definition.suppression_threshold} (suppressed below this denominator)`;
  return (
    <section
      id={definition.slug}
      aria-labelledby={`${definition.slug}-heading`}
      data-testid="metric-definition"
      data-slug={definition.slug}
      className="scroll-mt-20 flex flex-col gap-2 border-t pt-4"
    >
      <h3 id={`${definition.slug}-heading`} className="text-base font-semibold">
        {definition.name}
      </h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Slug</dt>
        <dd>
          <code className="font-mono">{definition.slug}</code> (version {definition.version})
        </dd>
        <dt className="text-muted-foreground">Kind</dt>
        <dd>
          {KIND_TEXT[definition.kind]}; unit: {definition.unit}; subjects: {definition.subject_types.join(", ")}
        </dd>
        <dt className="text-muted-foreground">What it says</dt>
        <dd>{definition.description}</dd>
        <dt className="text-muted-foreground">Formula</dt>
        <dd data-testid="definition-formula">
          <span className="font-medium">Numerator:</span> {definition.numerator}{" "}
          <span className="font-medium">Denominator:</span> {definition.denominator}
        </dd>
        <dt className="text-muted-foreground">Eligibility</dt>
        <dd>{definition.eligibility}</dd>
        <dt className="text-muted-foreground">Attribution</dt>
        <dd>{attributionText(definition, gates)}</dd>
        {definition.windows_days ? (
          <>
            <dt className="text-muted-foreground">Windows</dt>
            <dd>
              index event {definition.index_event}; outcome {definition.outcome}; windows{" "}
              {definition.windows_days.join(", ")} days
            </dd>
          </>
        ) : null}
        {definition.dimension ? (
          <>
            <dt className="text-muted-foreground">Dimension</dt>
            <dd>one observation per {definition.dimension} value</dd>
          </>
        ) : null}
        <dt className="text-muted-foreground">Suppression threshold</dt>
        <dd>{threshold}</dd>
      </dl>
    </section>
  );
}

function Rendered({ registry }: { registry: Registry }) {
  return (
    <>
      <section aria-labelledby="read-heading" className="flex flex-col gap-3">
        <h2 id="read-heading" className="text-lg font-semibold">
          How to read a number
        </h2>
        <p className="text-sm text-muted-foreground">
          Registry version {registry.registry_version}; methodology version {registry.methodology_version};{" "}
          {registry.definitions.length} metrics.
        </p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm" data-testid="how-to-read">
          {registry.how_to_read.map((item) => (
            <div key={item.term} className="contents">
              <dt className="font-medium">{item.term}</dt>
              <dd>{item.text}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section aria-labelledby="semantics-heading" className="flex flex-col gap-3">
        <h2 id="semantics-heading" className="text-lg font-semibold">
          Index events, exposure, and censoring
        </h2>
        <div className="flex flex-col gap-2 text-sm" data-testid="semantics">
          {registry.semantics.map((item) => (
            <p key={item.term}>
              <strong>{item.term}.</strong> {item.text}
            </p>
          ))}
        </div>
      </section>

      <section aria-labelledby="attribution-heading" className="flex flex-col gap-3">
        <h2 id="attribution-heading" className="text-lg font-semibold">
          Attribution
        </h2>
        <div className="flex flex-col gap-2 text-sm" data-testid="attribution-notes">
          {registry.attribution_notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      </section>

      <section aria-labelledby="metrics-heading" className="flex flex-col gap-4">
        <h2 id="metrics-heading" className="text-lg font-semibold">
          Metrics
        </h2>
        <p className="text-sm">
          One section per metric, in registry order. A metric&apos;s formula is its numerator over
          its denominator; its eligibility states which rows enter; its attribution rule states
          how a row is tied to the subject. Every number on this site links here at its metric.
        </p>
        <nav aria-label="Metric definitions" className="flex flex-wrap gap-x-3 gap-y-1 text-sm" data-testid="definition-index">
          {registry.definitions.map((definition) => (
            <a key={definition.slug} href={`#${definition.slug}`} className="text-primary hover:underline">
              {definition.name}
            </a>
          ))}
        </nav>
        {registry.definitions.map((definition) => (
          <Definition key={definition.slug} definition={definition} gates={registry.gate_descriptions} />
        ))}
      </section>

      <section aria-labelledby="suppression-heading" className="flex flex-col gap-3" id="suppression">
        <h2 id="suppression-heading" className="text-lg font-semibold">
          Suppression
        </h2>
        <p className="text-sm">Default threshold: {registry.suppression.default_threshold}.</p>
        <p className="text-sm" data-testid="suppression-rule">
          {registry.suppression.rule}
        </p>
        <p className="text-sm">{registry.suppression.rationale}</p>
      </section>

      <section aria-labelledby="limitations-heading" className="flex flex-col gap-3" id="known-limitations">
        <h2 id="limitations-heading" className="text-lg font-semibold">
          Known limitations
        </h2>
        <p className="text-sm">
          The brief&apos;s statistical warnings, published verbatim and never softened for
          presentation:
        </p>
        <ol className="list-decimal space-y-1.5 pl-6 text-sm" data-testid="known-limitations">
          {registry.known_limitations.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="changelog-heading" className="flex flex-col gap-3" id="changelog">
        <h2 id="changelog-heading" className="text-lg font-semibold">
          Methodology changelog
        </h2>
        <ul className="list-disc space-y-1 pl-6 text-sm" data-testid="changelog">
          {registry.changelog.map((entry) => (
            <li key={entry.version}>
              <span className="font-medium">{entry.version}</span> — {entry.text}
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}

export default async function MethodologyPage() {
  const registry = await getRegistry();
  return (
    <article className="prose-sm flex max-w-3xl flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">Methodology</h1>
        <p className="text-muted-foreground">
          How JudgeMetrics turns public court records into statistics, and what those
          statistics can and cannot say. Rendered from the versioned metric registry the API
          serves, the same contract every published number is computed against.
        </p>
      </header>

      <section aria-labelledby="statement-heading" className="rounded-xl border bg-muted/40 p-5">
        <h2 id="statement-heading" className="text-lg font-semibold">
          What the numbers mean
        </h2>
        <p className="mt-2 text-base" data-testid="association-statement">
          {ASSOCIATION_STATEMENT}
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

      {registry.ok ? <Rendered registry={registry.data} /> : <ErrorState what="the metric registry" error={registry.error} />}

      <section aria-labelledby="links-heading" className="flex flex-col gap-3">
        <h2 id="links-heading" className="text-lg font-semibold">
          Further reading
        </h2>
        <ul className="list-disc space-y-1 pl-6 text-sm">
          <li>
            <a href={METHODOLOGY_DOC_URL} className="text-primary hover:underline">
              docs/METHODOLOGY.md
            </a>{" "}
            — the same registry rendered as Markdown in the repository, versioned with the code.
          </li>
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
