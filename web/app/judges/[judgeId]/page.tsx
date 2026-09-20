// web/app/judges/[judgeId]/page.tsx
// A judge: identity and status; the association statement; the metric
// panels (Cases, Pretrial, Outcomes after qualifying release, Disposition,
// Sentencing) rendered through MetricStat from /judges/{id}/metrics with the
// court's pooled value from /courts/{id}/metrics and the judge's position in
// the comparison cohort from /metrics/compare (one call per compared metric,
// batched); then the service table, the cases panel, and the source
// coverage panel. The cohort (`?cohort=court|jurisdiction`) and the
// follow-up window (`?window=`) are query parameters; the panels degrade
// one at a time: a failed registry, metrics, or compare call renders an
// ErrorState in its place and the rest of the page still renders.
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { StatusBadge, SyntheticBadge } from "@/components/badges";
import { CasesPanel } from "@/components/cases-panel";
import { CohortSelector, WindowSelector } from "@/components/cohort-selector";
import { CohortPositionLine, MetricPanel, MetricRow } from "@/components/metric-panel";
import { MetricNotObservable } from "@/components/metric-stat";
import { ProvenancePanel } from "@/components/provenance-panel";
import { ReportErrorLink } from "@/components/report-error-link";
import { ServiceTable } from "@/components/service-table";
import { EmptyState, ErrorState } from "@/components/states";
import {
  compareMetrics,
  getCourt,
  getCourtMetrics,
  getJudge,
  getJudgeMetrics,
  getRegistry,
  type ApiError,
  type ApiResult,
  type ComparePage,
  type JudgeDetail,
  type MetricDefinition,
} from "@/lib/api/client";
import { isUuid } from "@/lib/format";
import { sourceLinks } from "@/lib/links";
import {
  ASSOCIATION_STATEMENT,
  COMPARED_KINDS,
  COHORTS,
  JUDGE_PANELS,
  type CohortKind,
  type GroupedObservations,
  type JudgePanelSpec,
  cohortPosition,
  compareHref,
  defaultSort,
  definitionsFor,
  dimensionValues,
  eligibleCasesHref,
  firstObservationId,
  groupObservations,
  isWindowed,
  panelDefinitions,
  parseCohort,
  pickObservation,
  resolveWindow,
  windowsFromRegistry,
} from "@/lib/metrics";

export const dynamic = "force-dynamic";

type Params = Promise<{ judgeId: string }>;
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstValue(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { judgeId } = await params;
  if (!isUuid(judgeId)) return { title: "Judge" };
  const result = await getJudge(judgeId);
  return { title: result.ok ? result.data.canonical_name : "Judge" };
}

function fjcNid(judge: JudgeDetail): string | null {
  const nid = judge.external_ids.fjc_nid;
  return typeof nid === "string" && /^\d+$/.test(nid) ? nid : null;
}

function birthYear(judge: JudgeDetail): string | null {
  const year = judge.metadata.birth_year;
  return typeof year === "number" ? String(year) : null;
}

/** The judge's court for pooling and cohorts: the current appointment, else the latest. */
function primaryCourtId(judge: JudgeDetail): string | null {
  const current = judge.service.find((record) => record.end_date === null);
  if (current) return current.court.id;
  const latest = [...judge.service].sort((a, b) =>
    (b.start_date ?? "").localeCompare(a.start_date ?? ""),
  )[0];
  return latest?.court.id ?? null;
}

type CohortTarget = { court_id: string } | { jurisdiction_id: string };

/** One compare call per compared definition, keyed by slug, batched. */
async function fetchComparisons(
  definitions: MetricDefinition[],
  window: number | null,
  target: CohortTarget,
): Promise<Record<string, ApiResult<ComparePage>>> {
  const compared = definitions.filter((d) => COMPARED_KINDS.has(d.kind));
  const results = await Promise.all(
    compared.map((definition) =>
      compareMetrics({
        metric: definition.slug,
        window: isWindowed(definition) && window !== null ? window : undefined,
        ...target,
        sort: defaultSort(definition),
        order: "desc",
        limit: 100,
      }),
    ),
  );
  return Object.fromEntries(compared.map((definition, index) => [definition.slug, results[index]]));
}

interface PanelData {
  judgeId: string;
  judge: GroupedObservations;
  court: GroupedObservations | null;
  comparisons: Record<string, ApiResult<ComparePage>>;
  cohort: CohortKind;
  target: CohortTarget | null;
  window: number | null;
  source: string;
}

function outcomeLabel(definition: MetricDefinition, window: number | null): string {
  return isWindowed(definition) && window !== null ? `${definition.name}, ${window} days` : definition.name;
}

/** The rows of one definition: per dimension value when dimensioned, else one. */
function definitionRows(definition: MetricDefinition, data: PanelData): ReactNode {
  const window = isWindowed(definition) ? data.window : null;
  const dimensions = definition.dimension ? dimensionValues(data.judge, definition.slug, window) : [null];
  const label = outcomeLabel(definition, window);
  const observedAtAll = definition.slug in data.judge;
  if (!observedAtAll) {
    if (definition.outcome) {
      return (
        <MetricNotObservable
          key={definition.slug}
          label={label}
          slug={definition.slug}
          source={data.source}
          methodologyUrl={definition.methodology_url}
          version={definition.version}
        />
      );
    }
    return (
      <p key={definition.slug} className="text-xs text-muted-foreground" data-testid="metric-absent" data-slug={definition.slug}>
        {definition.name}: no observation is published for this judge yet.
      </p>
    );
  }
  return dimensions.map((dimension) => {
    const judge = pickObservation(data.judge, definition.slug, { window, dimension });
    if (!judge) {
      return (
        <p key={`${definition.slug}:${dimension ?? ""}`} className="text-xs text-muted-foreground" data-testid="metric-absent" data-slug={definition.slug}>
          {label}: no observation at this window.
        </p>
      );
    }
    const court = data.court
      ? pickObservation(data.court, definition.slug, { window, dimension }) ?? null
      : null;
    const comparison = data.comparisons[definition.slug];
    const compareLink = data.target
      ? compareHref({ metric: definition.slug, window, ...data.target, sort: defaultSort(definition) })
      : null;
    const position =
      comparison?.ok && compareLink && !definition.dimension
        ? (
            <CohortPositionLine
              position={cohortPosition(comparison.data.items, data.judgeId, comparison.data.total, dimension)}
              cohort={data.cohort}
              kind={definition.kind}
              compareHref={compareLink}
            />
          )
        : null;
    return (
      <MetricRow
        key={`${definition.slug}:${dimension ?? ""}`}
        label={label}
        judge={judge}
        court={court}
        comparison={position}
      />
    );
  });
}

function comparisonErrors(slugs: string[], data: PanelData): ApiError | null {
  for (const slug of slugs) {
    const result = data.comparisons[slug];
    if (result && !result.ok) return result.error;
  }
  return null;
}

function Panel({
  spec,
  definitions,
  data,
  controls,
}: {
  spec: JudgePanelSpec;
  definitions: MetricDefinition[];
  data: PanelData;
  controls?: ReactNode;
}) {
  // Windowed metrics grouped by outcome, in registry order of first appearance,
  // so a fixed-window rate sits beside the Kaplan–Meier estimate of the same outcome.
  const { named, windowed } = panelDefinitions(spec, definitions);
  const shown = [...named, ...windowed];
  const error = comparisonErrors(shown.map((d) => d.slug), data);
  return (
    <MetricPanel
      id={spec.id}
      title={spec.title}
      reportObservationId={firstObservationId(data.judge, shown.map((d) => d.slug))}
      description={
        spec.id === "outcomes"
          ? `Fixed-window rates and Kaplan–Meier cumulative incidence after an attributed pretrial release, at the selected window. ${COHORTS[data.cohort]}: the court's pooled value beside the judge's, and where the judge falls among the cohort's judges.`
          : undefined
      }
      controls={controls}
      casesHref={eligibleCasesHref(data.judgeId, spec.casesFilter)}
      casesLabel={spec.casesFilter ? "View eligible cases (closed)" : "View eligible cases"}
    >
      {error ? <ErrorState what="the cohort comparison" error={error} /> : null}
      {shown.length === 0 ? (
        <EmptyState title="No metric of this kind is defined in the registry." />
      ) : (
        <div className="flex flex-col gap-2">
          {named.map((definition) => definitionRows(definition, data))}
          {spec.indexEvent && windowed.length > 0 ? (
            <div className="flex flex-col gap-2" data-testid={`${spec.id}-windowed`}>
              {spec.id !== "outcomes" ? (
                <h3 className="pt-2 text-sm font-medium">
                  Outcomes after {spec.indexEvent === "disposition" ? "disposition" : "sentence"}
                  {data.window !== null ? `, ${data.window} days` : ""}
                </h3>
              ) : null}
              {windowed.map((definition) => definitionRows(definition, data))}
            </div>
          ) : null}
        </div>
      )}
    </MetricPanel>
  );
}

export default async function JudgePage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const { judgeId } = await params;
  if (!isUuid(judgeId)) notFound();
  const query = await searchParams;
  const cohort = parseCohort(firstValue(query.cohort));

  const [result, metrics, registry] = await Promise.all([
    getJudge(judgeId),
    getJudgeMetrics(judgeId),
    getRegistry(),
  ]);
  if (!result.ok) {
    if (result.error.status === 404) notFound();
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Judge</h1>
        <ErrorState what="this judge" error={result.error} />
      </div>
    );
  }

  const judge = result.data;
  const nid = fjcNid(judge);
  const born = birthYear(judge);
  const fjc = sourceLinks("fjc");
  const current = judge.service.filter((record) => record.end_date === null);
  const courtId = primaryCourtId(judge);

  const windows = registry.ok ? windowsFromRegistry(registry.data) : [];
  const window = resolveWindow(firstValue(query.window), windows);
  const keep = { cohort, window: window === null ? undefined : String(window) };
  const pagePath = `/judges/${judgeId}`;

  // The cohort target and the pooled court metrics, only once the judge is known.
  let target: CohortTarget | null = null;
  let courtMetrics: Awaited<ReturnType<typeof getCourtMetrics>> | null = null;
  let cohortError: ApiError | null = null;
  if (courtId) {
    if (cohort === "jurisdiction") {
      const court = await getCourt(courtId);
      if (court.ok) target = { jurisdiction_id: court.data.jurisdiction_id };
      else cohortError = court.error;
    } else {
      target = { court_id: courtId };
    }
  }
  const definitions = registry.ok ? definitionsFor(registry.data, "judge") : [];
  const [comparisons, pooled] = await Promise.all([
    target && registry.ok ? fetchComparisons(definitions, window, target) : Promise.resolve({}),
    courtId ? getCourtMetrics(courtId) : Promise.resolve(null),
  ]);
  courtMetrics = pooled;

  const source = metrics.ok
    ? (Object.values(metrics.data.observations)[0]?.[0]?.source ?? "the ingested")
    : "the ingested";
  const data: PanelData | null =
    registry.ok && metrics.ok
      ? {
          judgeId,
          judge: groupObservations(metrics.data.observations),
          court: courtMetrics?.ok ? groupObservations(courtMetrics.data.observations) : null,
          comparisons,
          cohort,
          target,
          window,
          source,
        }
      : null;
  const covered = new Set<string>(JUDGE_PANELS.flatMap((spec) => [...spec.slugs]));
  const uncovered = definitions.filter(
    (d) => !covered.has(d.slug) && !isWindowed(d),
  );

  const selectors = (
    <>
      {window !== null ? (
        <WindowSelector value={window} windows={windows} action={`${pagePath}#outcomes`} keep={keep} />
      ) : null}
      <CohortSelector value={cohort} action={`${pagePath}#outcomes`} keep={keep} />
    </>
  );

  return (
    <article className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight" data-testid="judge-name">
            {judge.canonical_name}
          </h1>
          <StatusBadge status={judge.status} />
          {judge.synthetic ? <SyntheticBadge /> : null}
          <ReportErrorLink targetType="judge" targetId={judge.id} label={judge.canonical_name} className="ml-auto" />
        </div>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted-foreground">
          {current.length > 0 ? (
            <div className="flex gap-1.5">
              <dt>Current:</dt>
              <dd className="text-foreground">
                {current.map((record) => `${record.position_type}, ${record.court.canonical_name}`).join("; ")}
              </dd>
            </div>
          ) : null}
          {born ? (
            <div className="flex gap-1.5">
              <dt>Born:</dt>
              <dd className="text-foreground">{born}</dd>
            </div>
          ) : null}
          {nid && fjc.recordUrl ? (
            <div className="flex gap-1.5">
              <dt>FJC biography:</dt>
              <dd>
                <a href={fjc.recordUrl(nid)} className="font-mono text-primary hover:underline">
                  nid {nid}
                </a>
              </dd>
            </div>
          ) : null}
        </dl>
        <nav aria-label="Sections" className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
          {JUDGE_PANELS.map((spec) => (
            <a key={spec.id} href={`#${spec.id}`} className="text-primary hover:underline">
              {spec.title}
            </a>
          ))}
          <a href="#service-heading" className="text-primary hover:underline">
            Service
          </a>
          <a href="#sources" className="text-primary hover:underline">
            Sources
          </a>
        </nav>
      </header>

      <section aria-labelledby="statement-heading" className="rounded-xl border bg-muted/40 p-4">
        <h2 id="statement-heading" className="text-sm font-semibold">
          What the numbers mean
        </h2>
        <p className="mt-1 text-sm" data-testid="association-statement">
          {ASSOCIATION_STATEMENT}
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Every number below shows its numerator, denominator, date range, coverage, sample size,
          and — for rates — a 95% interval, and links to the{" "}
          <Link href="/methodology" className="text-primary hover:underline">
            methodology
          </Link>
          . Cohorts below the suppression threshold are withheld. Raw rates depend on case mix;
          see the known limitations.
        </p>
      </section>

      <div className="flex flex-col gap-6" data-testid="metric-panels">
        {!registry.ok ? (
          <ErrorState what="the metric registry" error={registry.error} />
        ) : !metrics.ok ? (
          <ErrorState what="this judge's metrics" error={metrics.error} />
        ) : metrics.data.total === 0 ? (
          <EmptyState title="No metric is published for this judge.">
            The ingested sources hold no case-level data for this judge, so no observation exists;
            the Federal Judicial Center directory carries service records only.
          </EmptyState>
        ) : data ? (
          <>
            {cohortError ? <ErrorState what="the comparison cohort" error={cohortError} /> : null}
            {courtMetrics && !courtMetrics.ok ? (
              <ErrorState what="the court's pooled metrics" error={courtMetrics.error} />
            ) : null}
            {JUDGE_PANELS.map((spec) => (
              <Panel
                key={spec.id}
                spec={spec}
                definitions={definitions}
                data={data}
                controls={spec.id === "outcomes" ? selectors : undefined}
              />
            ))}
            {uncovered.length > 0 ? (
              <MetricPanel
                id="other"
                title="Other metrics"
                casesHref={eligibleCasesHref(judgeId, null)}
                reportObservationId={firstObservationId(data.judge, uncovered.map((d) => d.slug))}
              >
                <div className="flex flex-col gap-2">
                  {uncovered.map((definition) => definitionRows(definition, data))}
                </div>
              </MetricPanel>
            ) : null}
          </>
        ) : null}
      </div>

      <section aria-labelledby="service-heading" className="flex flex-col gap-3 scroll-mt-20" id="service">
        <h2 id="service-heading" className="text-lg font-semibold">
          Service
        </h2>
        <p className="text-sm text-muted-foreground">
          Every appointment on file, oldest first. Senior status does not end an
          appointment; a judge on senior status is still serving.
        </p>
        <ServiceTable records={judge.service} />
      </section>

      <div className="grid gap-6 lg:grid-cols-2" id="sources">
        <section aria-labelledby="cases-heading">
          <CasesPanel judge={judge} />
        </section>
        <ProvenancePanel
          entries={judge.provenance}
          issueTitle={`${judge.canonical_name} (judge ${judge.id})`}
        />
      </div>
    </article>
  );
}
