// web/app/courts/[courtId]/page.tsx
// A court: name, type, jurisdiction (linked), the court's own metric panels
// (Cases, Pretrial — with the court-only statutory-release and
// unknown-actor counts —, Outcomes after qualifying release with the
// window selector, Disposition, Sentencing) rendered through MetricStat
// from /courts/{id}/metrics; "Comparable judges", the compare table of the
// court's judges for one metric (`?metric=`, default pretrial_release_share)
// and window (`?window=`) from /metrics/compare, linking to /compare; then
// the judges whose service interval covers a chosen date (`?active_on=`, a
// plain GET form so it works without JavaScript), paginated through
// `?offset=`; and the provenance panel. Every fetch degrades to an
// ErrorState or EmptyState in its own region.
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import type { ReactNode } from "react";

import { CourtTypeBadge, StatusBadge, SyntheticBadge } from "@/components/badges";
import { WindowSelector } from "@/components/cohort-selector";
import { CompareTable } from "@/components/compare-table";
import { MetricPanel } from "@/components/metric-panel";
import { MetricNotObservable, MetricStat } from "@/components/metric-stat";
import { ProvenancePanel } from "@/components/provenance-panel";
import { QuerySelect } from "@/components/query-select";
import { ReportErrorLink } from "@/components/report-error-link";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  compareMetrics,
  getCourt,
  getCourtMetrics,
  getJurisdiction,
  getRegistry,
  listJudges,
  type MetricDefinition,
} from "@/lib/api/client";
import { formatDate, formatInteger, isIsoDate, isUuid, todayIsoDate } from "@/lib/format";
import {
  ASSOCIATION_STATEMENT,
  COMPARED_KINDS,
  COURT_PANELS,
  DEFAULT_COMPARE_METRIC,
  type CourtPanelSpec,
  type GroupedObservations,
  compareHref,
  defaultSort,
  definitionsFor,
  dimensionValues,
  firstObservationId,
  groupObservations,
  isWindowed,
  panelDefinitions,
  pickObservation,
  resolveWindow,
  windowsFromRegistry,
} from "@/lib/metrics";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;
const COMPARE_ROWS = 100;

type Params = Promise<{ courtId: string }>;
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstValue(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { courtId } = await params;
  if (!isUuid(courtId)) return { title: "Court" };
  const result = await getCourt(courtId);
  return { title: result.ok ? result.data.canonical_name : "Court" };
}

/** The rows of one court definition: one MetricStat per dimension value, else one. */
function courtRows(
  definition: MetricDefinition,
  grouped: GroupedObservations,
  window: number | null,
  source: string,
): ReactNode {
  const days = isWindowed(definition) ? window : null;
  const label = isWindowed(definition) && days !== null ? `${definition.name}, ${days} days` : definition.name;
  if (!(definition.slug in grouped)) {
    if (definition.outcome) {
      return (
        <MetricNotObservable
          key={definition.slug}
          label={label}
          slug={definition.slug}
          source={source}
          methodologyUrl={definition.methodology_url}
          version={definition.version}
        />
      );
    }
    return (
      <p key={definition.slug} className="text-xs text-muted-foreground" data-testid="metric-absent" data-slug={definition.slug}>
        {definition.name}: no observation is published for this court yet.
      </p>
    );
  }
  const dimensions = definition.dimension ? dimensionValues(grouped, definition.slug, days) : [null];
  return dimensions.map((dimension) => {
    const observation = pickObservation(grouped, definition.slug, { window: days, dimension });
    if (!observation) {
      return (
        <p key={`${definition.slug}:${dimension ?? ""}`} className="text-xs text-muted-foreground" data-testid="metric-absent" data-slug={definition.slug}>
          {label}: no observation at this window.
        </p>
      );
    }
    return <MetricStat key={`${definition.slug}:${dimension ?? ""}`} observation={observation} label={label} />;
  });
}

function CourtPanel({
  spec,
  definitions,
  grouped,
  window,
  source,
  controls,
}: {
  spec: CourtPanelSpec;
  definitions: MetricDefinition[];
  grouped: GroupedObservations;
  window: number | null;
  source: string;
  controls?: ReactNode;
}) {
  const { named, windowed } = panelDefinitions(spec, definitions);
  const shown = [...named, ...windowed];
  return (
    <MetricPanel
      id={spec.id}
      title={spec.title}
      description={
        spec.id === "outcomes"
          ? "Fixed-window rates and Kaplan–Meier cumulative incidence after an attributed pretrial release at this court, pooled over its judges, at the selected window."
          : spec.id === "pretrial"
            ? "Pooled over the court's judges. The statutory-release and unknown-actor counts are court-level only: those rows enter no judge's metric."
            : undefined
      }
      controls={controls}
      reportObservationId={firstObservationId(grouped, shown.map((d) => d.slug))}
    >
      {shown.length === 0 ? (
        <EmptyState title="No metric of this kind is defined in the registry." />
      ) : (
        <div className="flex flex-col gap-2">
          <div className="grid gap-2 md:grid-cols-2">
            {named.map((definition) => courtRows(definition, grouped, window, source))}
          </div>
          {spec.indexEvent && windowed.length > 0 ? (
            <div className="flex flex-col gap-2" data-testid={`${spec.id}-windowed`}>
              {spec.id !== "outcomes" ? (
                <h3 className="pt-2 text-sm font-medium">
                  Outcomes after {spec.indexEvent === "disposition" ? "disposition" : "sentence"}
                  {window !== null ? `, ${window} days` : ""}
                </h3>
              ) : null}
              <div className="grid gap-2 md:grid-cols-2">
                {windowed.map((definition) => courtRows(definition, grouped, window, source))}
              </div>
            </div>
          ) : null}
        </div>
      )}
    </MetricPanel>
  );
}

export default async function CourtPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const { courtId } = await params;
  if (!isUuid(courtId)) notFound();

  const query = await searchParams;
  const requestedDate = firstValue(query.active_on);
  const activeOn = isIsoDate(requestedDate) ? requestedDate : todayIsoDate();
  const requestedOffset = Number.parseInt(firstValue(query.offset), 10);
  const offset = Number.isFinite(requestedOffset) && requestedOffset > 0 ? requestedOffset : 0;

  const [court, registry, metrics] = await Promise.all([
    getCourt(courtId),
    getRegistry(),
    getCourtMetrics(courtId),
  ]);
  if (!court.ok) {
    if (court.error.status === 404) notFound();
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Court</h1>
        <ErrorState what="this court" error={court.error} />
      </div>
    );
  }

  // The compare metric: a compared judge-level definition, default pretrial_release_share.
  const judgeDefinitions = registry.ok
    ? definitionsFor(registry.data, "judge").filter((d) => COMPARED_KINDS.has(d.kind))
    : [];
  const requestedMetric = firstValue(query.metric) || DEFAULT_COMPARE_METRIC;
  const compared = judgeDefinitions.find((d) => d.slug === requestedMetric) ?? judgeDefinitions[0] ?? null;
  const windows = registry.ok ? windowsFromRegistry(registry.data) : [];
  const window = resolveWindow(firstValue(query.window), windows);
  const compareWindow = compared && isWindowed(compared) && window !== null ? window : null;
  const compareSort = compared ? defaultSort(compared) : "rate";

  const [jurisdiction, judges, comparison] = await Promise.all([
    getJurisdiction(court.data.jurisdiction_id),
    listJudges({ court_id: courtId, active_on: activeOn, limit: PAGE_SIZE, offset }),
    compared
      ? compareMetrics({
          metric: compared.slug,
          window: compareWindow ?? undefined,
          court_id: courtId,
          sort: compareSort,
          order: "desc",
          limit: COMPARE_ROWS,
        })
      : Promise.resolve(null),
  ]);

  const pagePath = `/courts/${courtId}`;
  const keep = {
    metric: compared?.slug,
    window: window === null ? undefined : String(window),
    active_on: requestedDate && isIsoDate(requestedDate) ? requestedDate : undefined,
  };
  const pageHref = (nextOffset: number) =>
    `${pagePath}?active_on=${activeOn}${nextOffset > 0 ? `&offset=${nextOffset}` : ""}#judges-heading`;
  const grouped = metrics.ok ? groupObservations(metrics.data.observations) : null;
  const source = metrics.ok
    ? (Object.values(metrics.data.observations)[0]?.[0]?.source ?? "the ingested")
    : "the ingested";
  const courtDefinitions = registry.ok ? definitionsFor(registry.data, "court") : [];
  const fullCompare = compared
    ? compareHref({ metric: compared.slug, window: compareWindow, court_id: courtId, sort: compareSort })
    : "/compare";

  return (
    <article className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight" data-testid="court-name">
            {court.data.canonical_name}
          </h1>
          <CourtTypeBadge type={court.data.court_type} />
          {court.data.synthetic ? <SyntheticBadge /> : null}
          <ReportErrorLink targetType="court" targetId={court.data.id} label={court.data.canonical_name} className="ml-auto" />
        </div>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted-foreground">
          <div className="flex gap-1.5">
            <dt>Jurisdiction:</dt>
            <dd className="text-foreground">
              {jurisdiction.ok ? (
                <Link
                  href={`/jurisdictions/${jurisdiction.data.id}`}
                  className="text-primary hover:underline"
                  data-testid="jurisdiction-link"
                >
                  {jurisdiction.data.name}
                </Link>
              ) : (
                <Link
                  href={`/jurisdictions/${court.data.jurisdiction_id}`}
                  className="text-primary hover:underline"
                  data-testid="jurisdiction-link"
                >
                  Jurisdiction (name unavailable)
                </Link>
              )}
            </dd>
          </div>
          {court.data.state_code ? (
            <div className="flex gap-1.5">
              <dt>State:</dt>
              <dd className="text-foreground">{court.data.state_code}</dd>
            </div>
          ) : null}
          {court.data.active_from || court.data.active_to ? (
            <div className="flex gap-1.5">
              <dt>Active:</dt>
              <dd className="text-foreground">
                {formatDate(court.data.active_from)} – {court.data.active_to ? formatDate(court.data.active_to) : "present"}
              </dd>
            </div>
          ) : null}
        </dl>
        <nav aria-label="Sections" className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
          {COURT_PANELS.map((spec) => (
            <a key={spec.id} href={`#${spec.id}`} className="text-primary hover:underline">
              {spec.title}
            </a>
          ))}
          <a href="#comparable-heading" className="text-primary hover:underline">
            Comparable judges
          </a>
          <a href="#judges-heading" className="text-primary hover:underline">
            Judges serving
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
          Court-level numbers pool every attributed row of the court&apos;s judges over the
          source period; each shows its numerator, denominator, date range, coverage, sample
          size, and interval, and links to the{" "}
          <Link href="/methodology" className="text-primary hover:underline">
            methodology
          </Link>
          . Cohorts below the suppression threshold are withheld.
        </p>
      </section>

      <div className="flex flex-col gap-6" data-testid="metric-panels">
        {!registry.ok ? (
          <ErrorState what="the metric registry" error={registry.error} />
        ) : !metrics.ok ? (
          <ErrorState what="this court's metrics" error={metrics.error} />
        ) : metrics.data.total === 0 || !grouped ? (
          <EmptyState title="No metric is published for this court.">
            The ingested sources hold no case-level data for this court, so no observation
            exists; the Federal Judicial Center directory carries service records only.
          </EmptyState>
        ) : (
          COURT_PANELS.map((spec) => (
            <CourtPanel
              key={spec.id}
              spec={spec}
              definitions={courtDefinitions}
              grouped={grouped}
              window={window}
              source={source}
              controls={
                spec.id === "outcomes" && window !== null ? (
                  <WindowSelector value={window} windows={windows} action={`${pagePath}#outcomes`} keep={keep} />
                ) : undefined
              }
            />
          ))
        )}
      </div>

      <section aria-labelledby="comparable-heading" className="flex flex-col gap-3 scroll-mt-20" id="comparable">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="comparable-heading" className="text-lg font-semibold">
            Comparable judges
          </h2>
          <Button asChild variant="outline" size="sm">
            <Link href={fullCompare} data-testid="open-compare">
              Open in Compare
            </Link>
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          The judges with a service record at this court and a current observation of one
          metric over the same source period — one metric at a time, the API&apos;s order, with
          every row&apos;s numerator, denominator, interval, and sample size. A row below the
          suppression threshold is marked and never ranked by its withheld figure.
        </p>
        {!registry.ok ? (
          <ErrorState what="the metric registry" error={registry.error} />
        ) : !compared ? (
          <EmptyState title="The registry defines no comparable judge-level metric." />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-4">
              <QuerySelect
                name="metric"
                value={compared.slug}
                action={`${pagePath}#comparable`}
                keep={keep}
                label="Metric"
                testId="metric-selector"
                options={judgeDefinitions.map((d) => ({ value: d.slug, label: d.name }))}
              />
              {isWindowed(compared) && window !== null ? (
                <WindowSelector value={window} windows={windows} action={`${pagePath}#comparable`} keep={keep} />
              ) : null}
            </div>
            {!comparison ? null : !comparison.ok ? (
              <ErrorState what="the comparable-judge table" error={comparison.error} />
            ) : comparison.data.items.length === 0 ? (
              <EmptyState title="No judge of this court has a current observation of this metric.">
                A metric the source cannot observe is never published, and a judge with no
                attributed rows has no observation.
              </EmptyState>
            ) : (
              <>
                <p className="text-sm text-muted-foreground" data-testid="comparable-summary">
                  {compared.name}
                  {compareWindow !== null ? `, ${compareWindow} days` : ""}: {comparison.data.total} judge
                  {comparison.data.total === 1 ? "" : "s"} in the cohort
                  {comparison.data.total > COMPARE_ROWS ? `, showing the first ${COMPARE_ROWS}` : ""}.
                </p>
                <CompareTable
                  rows={comparison.data.items}
                  definition={compared}
                  sort={compareSort}
                  order="desc"
                  hrefFor={(sort, order) =>
                    compareHref({ metric: compared.slug, window: compareWindow, court_id: courtId, sort, order })
                  }
                />
              </>
            )}
          </>
        )}
      </section>

      <section aria-labelledby="judges-heading" className="flex flex-col gap-3 scroll-mt-20">
        <h2 id="judges-heading" className="text-lg font-semibold">
          Judges serving on a date
        </h2>
        <form method="get" action={pagePath} className="flex flex-wrap items-end gap-2">
          {compared && compared.slug !== DEFAULT_COMPARE_METRIC ? (
            <input type="hidden" name="metric" value={compared.slug} />
          ) : null}
          <div className="flex flex-col gap-1">
            <label htmlFor="active_on" className="text-sm text-muted-foreground">
              Active on
            </label>
            <Input
              id="active_on"
              name="active_on"
              type="date"
              defaultValue={activeOn}
              required
              className="w-44"
              data-testid="active-on"
            />
          </div>
          <Button type="submit" variant="secondary">
            Show judges
          </Button>
          <p className="basis-full text-xs text-muted-foreground">
            A service interval runs from the source&apos;s commission date to its
            termination date; senior status does not end it.
          </p>
        </form>
        {!judges.ok ? (
          <ErrorState what="the judges serving on this date" error={judges.error} />
        ) : judges.data.items.length === 0 ? (
          <EmptyState title={`No judge on file was serving here on ${formatDate(activeOn)}`}>
            Service intervals follow the source&apos;s commission and termination dates.
          </EmptyState>
        ) : (
          <>
            <p className="text-sm text-muted-foreground" data-testid="judges-summary">
              {formatInteger(judges.data.total)} judge{judges.data.total === 1 ? "" : "s"} serving on{" "}
              <time dateTime={activeOn}>{formatDate(activeOn)}</time>
              {judges.data.total > PAGE_SIZE
                ? `, showing ${offset + 1}–${Math.min(offset + PAGE_SIZE, judges.data.total)}`
                : ""}
              .
            </p>
            <div className="overflow-x-auto rounded-xl border">
              <Table data-testid="court-judges">
                <caption className="sr-only">
                  Judges serving at {court.data.canonical_name} on {activeOn}
                </caption>
                <TableHeader>
                  <TableRow>
                    <TableHead scope="col">Judge</TableHead>
                    <TableHead scope="col">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {judges.data.items.map((judge) => (
                    <TableRow key={judge.id} data-testid="court-judge-row">
                      <TableCell>
                        <Link href={`/judges/${judge.id}`} className="font-medium text-primary hover:underline">
                          {judge.canonical_name}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <span className="flex flex-wrap items-center gap-2">
                          <StatusBadge status={judge.status} />
                          {judge.synthetic ? <SyntheticBadge /> : null}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {judges.data.total > PAGE_SIZE ? (
              <nav aria-label="Judges pagination" className="flex gap-2">
                {offset > 0 ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(Math.max(0, offset - PAGE_SIZE))}>Previous</Link>
                  </Button>
                ) : null}
                {judges.data.next_offset !== null ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(judges.data.next_offset)}>Next</Link>
                  </Button>
                ) : null}
              </nav>
            ) : null}
          </>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]" id="sources">
        <section aria-labelledby="about-heading" className="flex flex-col gap-3">
          <h2 id="about-heading" className="text-lg font-semibold">
            About these numbers
          </h2>
          <p className="text-sm text-muted-foreground">
            A court&apos;s metrics pool the attributed rows of every judge with a service record
            here; they are the &ldquo;court, pooled&rdquo; values shown beside each judge&apos;s
            own on the judge pages. Case volume trends and outcome distributions over time
            arrive with the first real state-court pipeline (Phase 5).
          </p>
        </section>
        <ProvenancePanel
          entries={court.data.provenance}
          issueTitle={`${court.data.canonical_name} (court ${court.data.id})`}
        />
      </div>
    </article>
  );
}
