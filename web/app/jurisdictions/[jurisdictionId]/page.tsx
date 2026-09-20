// web/app/jurisdictions/[jurisdictionId]/page.tsx
// A jurisdiction (v0): name and type, its courts (linked), the available
// years and the data completeness from /coverage — the source rows named
// by the jurisdiction's provenance (plus every synthetic source when one
// of its courts is synthetic; lib/jurisdictions.ts), their declared
// coverage windows giving the years, "no case data" when none declares one
// (an FJC-only jurisdiction) —, and the
// jurisdiction-level compare table of the default metric (`?metric=`,
// `?window=`) from /metrics/compare, linking to /compare. Trends and metric
// distributions over time arrive with the first real state-court pipeline.
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CourtTypeBadge, SyntheticBadge } from "@/components/badges";
import { WindowSelector } from "@/components/cohort-selector";
import { CompareTable } from "@/components/compare-table";
import { ProvenancePanel } from "@/components/provenance-panel";
import { QuerySelect } from "@/components/query-select";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
  getCoverage,
  getJurisdiction,
  getRegistry,
  listCourts,
} from "@/lib/api/client";
import { formatDate, formatDateTime, formatInteger, isUuid, titleCase } from "@/lib/format";
import { availableYears, jurisdictionSources } from "@/lib/jurisdictions";
import { sourceLinks } from "@/lib/links";
import {
  ASSOCIATION_STATEMENT,
  COMPARED_KINDS,
  DEFAULT_COMPARE_METRIC,
  compareHref,
  defaultSort,
  definitionsFor,
  formatPeriod,
  isWindowed,
  resolveWindow,
  windowsFromRegistry,
} from "@/lib/metrics";

export const dynamic = "force-dynamic";

const COMPARE_ROWS = 100;
const COURT_LIMIT = 100;

type Params = Promise<{ jurisdictionId: string }>;
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstValue(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { jurisdictionId } = await params;
  if (!isUuid(jurisdictionId)) return { title: "Jurisdiction" };
  const result = await getJurisdiction(jurisdictionId);
  return { title: result.ok ? result.data.name : "Jurisdiction" };
}

export default async function JurisdictionPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const { jurisdictionId } = await params;
  if (!isUuid(jurisdictionId)) notFound();
  const query = await searchParams;

  const [jurisdiction, courts, coverage, registry] = await Promise.all([
    getJurisdiction(jurisdictionId),
    listCourts({ jurisdiction_id: jurisdictionId, limit: COURT_LIMIT }),
    getCoverage(),
    getRegistry(),
  ]);
  if (!jurisdiction.ok) {
    if (jurisdiction.error.status === 404) notFound();
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Jurisdiction</h1>
        <ErrorState what="this jurisdiction" error={jurisdiction.error} />
      </div>
    );
  }

  const judgeDefinitions = registry.ok
    ? definitionsFor(registry.data, "judge").filter((d) => COMPARED_KINDS.has(d.kind))
    : [];
  const requestedMetric = firstValue(query.metric) || DEFAULT_COMPARE_METRIC;
  const compared = judgeDefinitions.find((d) => d.slug === requestedMetric) ?? judgeDefinitions[0] ?? null;
  const windows = registry.ok ? windowsFromRegistry(registry.data) : [];
  const window = resolveWindow(firstValue(query.window), windows);
  const compareWindow = compared && isWindowed(compared) && window !== null ? window : null;
  const compareSort = compared ? defaultSort(compared) : "rate";
  const comparison = compared
    ? await compareMetrics({
        metric: compared.slug,
        window: compareWindow ?? undefined,
        jurisdiction_id: jurisdictionId,
        sort: compareSort,
        order: "desc",
        limit: COMPARE_ROWS,
      })
    : null;

  const j = jurisdiction.data;
  const courtList = courts.ok ? [...courts.data.items].sort((a, b) => a.canonical_name.localeCompare(b.canonical_name)) : [];
  const sources = coverage.ok ? jurisdictionSources(j, courtList, coverage.data.sources) : [];
  const years = availableYears(sources);
  const pagePath = `/jurisdictions/${jurisdictionId}`;
  const keep = { metric: compared?.slug, window: window === null ? undefined : String(window) };
  const synthetic = j.provenance.some((entry) => entry.synthetic);
  const fullCompare = compared
    ? compareHref({ metric: compared.slug, window: compareWindow, jurisdiction_id: jurisdictionId, sort: compareSort })
    : "/compare";

  return (
    <article className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight" data-testid="jurisdiction-name">
            {j.name}
          </h1>
          <span className="rounded-md border px-2 py-0.5 text-xs" data-testid="jurisdiction-type">
            {titleCase(j.type)}
          </span>
          {synthetic ? <SyntheticBadge /> : null}
        </div>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted-foreground">
          {j.state_code ? (
            <div className="flex gap-1.5">
              <dt>State:</dt>
              <dd className="text-foreground">{j.state_code}</dd>
            </div>
          ) : null}
          {j.fips_code ? (
            <div className="flex gap-1.5">
              <dt>FIPS:</dt>
              <dd className="font-mono text-foreground">{j.fips_code}</dd>
            </div>
          ) : null}
          <div className="flex gap-1.5">
            <dt>Courts:</dt>
            <dd className="text-foreground" data-testid="court-count">
              {courts.ok ? formatInteger(courts.data.total) : "—"}
            </dd>
          </div>
          <div className="flex gap-1.5">
            <dt>Available years:</dt>
            <dd className="text-foreground" data-testid="available-years">
              {!coverage.ok ? "unavailable" : years ?? "no case data"}
            </dd>
          </div>
        </dl>
      </header>

      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-labelledby="courts-heading" className="flex flex-col gap-3">
          <h2 id="courts-heading" className="text-lg font-semibold">
            Courts
          </h2>
          {!courts.ok ? (
            <ErrorState what="the courts of this jurisdiction" error={courts.error} />
          ) : courtList.length === 0 ? (
            <EmptyState title="No court of this jurisdiction is on file." />
          ) : (
            <div className="overflow-x-auto rounded-xl border">
              <Table data-testid="jurisdiction-courts">
                <caption className="sr-only">Courts of {j.name}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead scope="col">Court</TableHead>
                    <TableHead scope="col">Type</TableHead>
                    <TableHead scope="col">State</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {courtList.map((court) => (
                    <TableRow key={court.id} data-testid="jurisdiction-court-row">
                      <TableCell>
                        <Link href={`/courts/${court.id}`} className="font-medium text-primary hover:underline">
                          {court.canonical_name}
                        </Link>
                        {court.synthetic ? <SyntheticBadge className="ml-2" /> : null}
                      </TableCell>
                      <TableCell>
                        <CourtTypeBadge type={court.court_type} />
                      </TableCell>
                      <TableCell>{court.state_code ?? "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {courts.data.total > COURT_LIMIT ? (
                <p className="p-2 text-xs text-muted-foreground">
                  Showing the first {COURT_LIMIT} of {courts.data.total} courts.
                </p>
              ) : null}
            </div>
          )}
        </section>

        <section aria-labelledby="completeness-heading" className="flex flex-col gap-3">
          <h2 id="completeness-heading" className="text-lg font-semibold">
            Data completeness
          </h2>
          {!coverage.ok ? (
            <ErrorState what="the coverage summary" error={coverage.error} />
          ) : sources.length === 0 ? (
            <EmptyState title="No ingested source is attached to this jurisdiction." />
          ) : (
            <div className="flex flex-col gap-3" data-testid="completeness">
              {sources.map((source) => (
                <Card key={source.source} size="sm" data-testid="completeness-source" data-source={source.source}>
                  <CardHeader>
                    <CardTitle>
                      <h3 className="flex flex-wrap items-center gap-2 text-sm">
                        <span className="font-mono">{source.source}</span>
                        {source.synthetic ? <SyntheticBadge /> : null}
                      </h3>
                    </CardTitle>
                    <CardDescription>{sourceLinks(source.source).name}</CardDescription>
                  </CardHeader>
                  <CardContent>
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                      <dt className="text-muted-foreground">Courts / judges</dt>
                      <dd className="tabular-nums">
                        {formatInteger(source.courts)} / {formatInteger(source.judges)}
                      </dd>
                      <dt className="text-muted-foreground">Cases / persons</dt>
                      <dd className="tabular-nums">
                        {formatInteger(source.cases)} / {formatInteger(source.persons)} (pseudonymous)
                      </dd>
                      <dt className="text-muted-foreground">Filing dates</dt>
                      <dd>
                        {source.earliest_filed
                          ? `${formatDate(source.earliest_filed)} – ${formatDate(source.latest_filed)}`
                          : "no case data"}
                      </dd>
                      <dt className="text-muted-foreground">Coverage window</dt>
                      <dd data-testid="completeness-window">
                        {source.coverage_start || source.coverage_end
                          ? formatPeriod(source.coverage_start, source.coverage_end)
                          : "none declared: no metric is computed for this source"}
                      </dd>
                      <dt className="text-muted-foreground">Observable outcomes</dt>
                      <dd>
                        {source.observable_outcomes.length > 0
                          ? source.observable_outcomes.map(titleCase).join(", ")
                          : "none: this source documents no subsequent event"}
                      </dd>
                      <dt className="text-muted-foreground">Last run</dt>
                      <dd>
                        {source.last_ingest
                          ? `${formatDateTime(source.last_ingest.completed_at)} (${source.last_ingest.status})`
                          : "no completed run"}
                      </dd>
                    </dl>
                  </CardContent>
                </Card>
              ))}
              <p className="text-xs text-muted-foreground">
                Completeness is described by what each source contributes and covers; per-jurisdiction
                completeness estimates against an external census arrive with the first real
                state-court pipeline (Phase 5). See the{" "}
                <Link href="/coverage" className="text-primary hover:underline">
                  coverage page
                </Link>
                .
              </p>
            </div>
          )}
        </section>
      </div>

      <section aria-labelledby="compare-heading" className="flex flex-col gap-3 scroll-mt-20" id="compare">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="compare-heading" className="text-lg font-semibold">
            Judges across the jurisdiction
          </h2>
          <Button asChild variant="outline" size="sm">
            <Link href={fullCompare} data-testid="open-compare">
              Open in Compare
            </Link>
          </Button>
        </div>
        <p className="text-sm text-muted-foreground" data-testid="association-statement">
          {ASSOCIATION_STATEMENT} The judges with a service record at a court of this jurisdiction
          and a current observation of one metric over the same source period, one metric at a
          time; a row below the suppression threshold is marked and never ranked by its withheld
          figure.
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
                action={`${pagePath}#compare`}
                keep={keep}
                label="Metric"
                testId="metric-selector"
                options={judgeDefinitions.map((d) => ({ value: d.slug, label: d.name }))}
              />
              {isWindowed(compared) && window !== null ? (
                <WindowSelector value={window} windows={windows} action={`${pagePath}#compare`} keep={keep} />
              ) : null}
            </div>
            {!comparison ? null : !comparison.ok ? (
              <ErrorState what="the jurisdiction compare table" error={comparison.error} />
            ) : comparison.data.items.length === 0 ? (
              <EmptyState title="No judge in this jurisdiction has a current observation of this metric.">
                The Federal Judicial Center directory carries service records only, so an
                FJC-only jurisdiction has no published metric.
              </EmptyState>
            ) : (
              <>
                <p className="text-sm text-muted-foreground" data-testid="compare-summary">
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
                    compareHref({
                      metric: compared.slug,
                      window: compareWindow,
                      jurisdiction_id: jurisdictionId,
                      sort,
                      order,
                    })
                  }
                />
              </>
            )}
          </>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]" id="sources">
        <section aria-labelledby="trends-heading" className="flex flex-col gap-3">
          <h2 id="trends-heading" className="text-lg font-semibold">
            Trends and distributions
          </h2>
          <p className="rounded-xl border border-dashed px-6 py-6 text-sm text-muted-foreground">
            Jurisdiction-level trends over time and metric distributions across courts arrive with
            the first real state-court pipeline (Phase 5); until then the compare table above is the
            jurisdiction&apos;s distribution of one metric across its judges.
          </p>
        </section>
        <ProvenancePanel entries={j.provenance} issueTitle={`${j.name} (jurisdiction ${j.id})`} />
      </div>
    </article>
  );
}
