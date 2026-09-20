// web/app/compare/page.tsx
// Compare one objective metric across the judges of one court or one
// jurisdiction. The whole page state lives in the query string (`metric`,
// `window`, `court_id`, `jurisdiction_id`, `sort`, `order`, `offset`, and an
// optional `judge` to highlight), read by this server page, validated
// against the registry before any fetch (an unknown metric, a window the
// metric does not have, a malformed id, or an unknown sort renders an
// ErrorState, never a crash), and validated again by the API. The controls
// are a plain GET form; the table is /metrics/compare's order, so a
// suppressed row never reveals its figure through its position.
import type { Metadata } from "next";
import Link from "next/link";

import { SyntheticBadge } from "@/components/badges";
import { CompareTable } from "@/components/compare-table";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  compareMetrics,
  getRegistry,
  listCourts,
  listJurisdictions,
  type ApiError,
  type ComparePage,
  type CourtSummary,
  type JurisdictionSummary,
  type MetricDefinition,
} from "@/lib/api/client";
import { isUuid } from "@/lib/format";
import {
  ASSOCIATION_STATEMENT,
  COMPARE_ORDERS,
  COMPARE_SORTS,
  type CompareOrder,
  type CompareSort,
  DEFAULT_WINDOW_DAYS,
  compareHref,
  defaultSort,
  definitionsFor,
  formatPeriod,
  isWindowed,
  methodologyHref,
  windowsFromRegistry,
} from "@/lib/metrics";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Compare" };

const PAGE_SIZE = 50;
const DEFAULT_METRIC = "pretrial_release_share";
// /courts pages at 100; two pages cover every court ingested today (159 FJC
// plus the synthetic ones). A larger registry needs a court search (Phase 5).
const COURT_PAGES = 2;

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstValue(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

function invalid(parameter: string, message: string): ApiError {
  return {
    status: 422,
    code: "validation_error",
    message: `${parameter}: ${message}`,
    requestId: null,
    retryAfterSeconds: null,
  };
}

interface CompareState {
  definition: MetricDefinition;
  window: number | null;
  court_id?: string;
  jurisdiction_id?: string;
  sort: CompareSort;
  order: CompareOrder;
  offset: number;
  judge?: string;
}

/** The validated page state, or the first invalid parameter. */
function readState(
  query: Record<string, string | string[] | undefined>,
  definitions: MetricDefinition[],
): { ok: true; state: CompareState } | { ok: false; error: ApiError } {
  const slug = firstValue(query.metric) || DEFAULT_METRIC;
  const definition = definitions.find((d) => d.slug === slug);
  if (!definition) return { ok: false, error: invalid("metric", `"${slug}" is not a judge-level metric of the registry`) };

  let window: number | null = null;
  const rawWindow = firstValue(query.window);
  if (isWindowed(definition)) {
    const windows = definition.windows_days ?? [];
    if (rawWindow) {
      const requested = Number.parseInt(rawWindow, 10);
      if (!windows.includes(requested)) {
        return { ok: false, error: invalid("window", `must be one of ${windows.join(", ")} days for ${definition.name}`) };
      }
      window = requested;
    } else {
      window = windows.includes(DEFAULT_WINDOW_DAYS) ? DEFAULT_WINDOW_DAYS : windows[windows.length - 1];
    }
  }

  const courtId = firstValue(query.court_id);
  const jurisdictionId = firstValue(query.jurisdiction_id);
  if (courtId && !isUuid(courtId)) return { ok: false, error: invalid("court_id", "must be a UUID") };
  if (jurisdictionId && !isUuid(jurisdictionId)) {
    return { ok: false, error: invalid("jurisdiction_id", "must be a UUID") };
  }

  const rawSort = firstValue(query.sort);
  const sort = rawSort || defaultSort(definition);
  if (!(COMPARE_SORTS as readonly string[]).includes(sort)) {
    return { ok: false, error: invalid("sort", `must be one of ${COMPARE_SORTS.join(", ")}`) };
  }
  const rawOrder = firstValue(query.order);
  const order = rawOrder || "desc";
  if (!(COMPARE_ORDERS as readonly string[]).includes(order)) {
    return { ok: false, error: invalid("order", "must be asc or desc") };
  }
  const rawOffset = firstValue(query.offset);
  const offset = rawOffset ? Number.parseInt(rawOffset, 10) : 0;
  if (!Number.isInteger(offset) || offset < 0) return { ok: false, error: invalid("offset", "must be a non-negative integer") };
  const judge = firstValue(query.judge);
  if (judge && !isUuid(judge)) return { ok: false, error: invalid("judge", "must be a UUID") };

  // A court narrows more than a jurisdiction: when both are given the court wins.
  return {
    ok: true,
    state: {
      definition,
      window,
      court_id: courtId || undefined,
      jurisdiction_id: courtId ? undefined : jurisdictionId || undefined,
      sort: sort as CompareSort,
      order: order as CompareOrder,
      offset,
      judge: judge || undefined,
    },
  };
}

function pageHref(state: CompareState, overrides: Partial<CompareState> = {}): string {
  const next = { ...state, ...overrides };
  const base = compareHref({
    metric: next.definition.slug,
    window: next.window,
    court_id: next.court_id,
    jurisdiction_id: next.jurisdiction_id,
    sort: next.sort,
    order: next.order,
    offset: next.offset,
  });
  return next.judge ? `${base}&judge=${next.judge}` : base;
}

async function allCourts(): Promise<CourtSummary[] | ApiError> {
  const pages = await Promise.all(
    Array.from({ length: COURT_PAGES }, (_, index) => listCourts({ limit: 100, offset: index * 100 })),
  );
  const items: CourtSummary[] = [];
  for (const page of pages) {
    if (!page.ok) return page.error;
    items.push(...page.data.items);
  }
  return items.sort((a, b) => a.canonical_name.localeCompare(b.canonical_name));
}

function Controls({
  definitions,
  windows,
  state,
  courts,
  jurisdictions,
}: {
  definitions: MetricDefinition[];
  /** Every window the registry declares; ignored for an unwindowed metric. */
  windows: number[];
  state: CompareState | null;
  courts: CourtSummary[];
  jurisdictions: JurisdictionSummary[];
}) {
  const definition = state?.definition ?? definitions[0];
  const selectClass = "h-9 rounded-md border border-input bg-background px-3 text-sm";
  return (
    <form method="get" action="/compare" className="flex flex-wrap items-end gap-3" data-testid="compare-controls">
      <div className="flex flex-col gap-1">
        <label htmlFor="metric" className="text-sm text-muted-foreground">
          Metric
        </label>
        <select id="metric" name="metric" defaultValue={definition?.slug ?? ""} className={selectClass}>
          {definitions.map((item) => (
            <option key={item.slug} value={item.slug}>
              {item.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="window" className="text-sm text-muted-foreground">
          Window
        </label>
        <select
          id="window"
          name="window"
          defaultValue={state?.window === null || state?.window === undefined ? "" : String(state.window)}
          className={selectClass}
        >
          <option value="">Not windowed (ignored for an unwindowed metric)</option>
          {windows.map((days) => (
            <option key={days} value={String(days)}>
              {days} days
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="court_id" className="text-sm text-muted-foreground">
          Court
        </label>
        <select id="court_id" name="court_id" defaultValue={state?.court_id ?? ""} className={selectClass}>
          <option value="">Any (use the jurisdiction)</option>
          {courts.map((court) => (
            <option key={court.id} value={court.id}>
              {court.canonical_name}
              {court.synthetic ? " (synthetic)" : ""}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="jurisdiction_id" className="text-sm text-muted-foreground">
          Jurisdiction
        </label>
        <select
          id="jurisdiction_id"
          name="jurisdiction_id"
          defaultValue={state?.jurisdiction_id ?? ""}
          className={selectClass}
        >
          <option value="">Any</option>
          {jurisdictions.map((jurisdiction) => (
            <option key={jurisdiction.id} value={jurisdiction.id}>
              {jurisdiction.name}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="sort" className="text-sm text-muted-foreground">
          Sort
        </label>
        <select id="sort" name="sort" defaultValue={state?.sort ?? "rate"} className={selectClass}>
          {COMPARE_SORTS.map((key) => (
            <option key={key} value={key}>
              {key}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="order" className="text-sm text-muted-foreground">
          Order
        </label>
        <select id="order" name="order" defaultValue={state?.order ?? "desc"} className={selectClass}>
          {COMPARE_ORDERS.map((key) => (
            <option key={key} value={key}>
              {key === "desc" ? "Descending" : "Ascending"}
            </option>
          ))}
        </select>
      </div>
      {state?.judge ? <input type="hidden" name="judge" value={state.judge} /> : null}
      <Button type="submit" variant="secondary">
        Compare
      </Button>
      <p className="basis-full text-xs text-muted-foreground">
        One metric at a time; a court narrows more than a jurisdiction, so when both are chosen
        the court is compared. A windowed metric needs a window.
      </p>
    </form>
  );
}

function Results({ state, page }: { state: CompareState; page: ComparePage }) {
  const { definition } = state;
  return (
    <>
      <section aria-labelledby="table-heading" className="flex flex-col gap-3">
        <h2 id="table-heading" className="flex flex-wrap items-center gap-2 text-lg font-semibold">
          {definition.name}
          {state.window !== null ? <span className="text-muted-foreground">· {state.window} days</span> : null}
          <span className="text-muted-foreground">· {page.cohort.name}</span>
          {page.items.some((row) => row.synthetic) ? <SyntheticBadge /> : null}
        </h2>
        {page.items.length === 0 ? (
          <EmptyState title="No judge in this cohort has a current observation of this metric.">
            A metric the source cannot observe is never published, and a judge with no
            attributed rows has no observation.
          </EmptyState>
        ) : (
          <>
            <p className="text-sm text-muted-foreground" data-testid="compare-summary">
              {page.total} judge{page.total === 1 ? "" : "s"} in the cohort
              {page.total > PAGE_SIZE
                ? `, showing ${state.offset + 1}–${Math.min(state.offset + PAGE_SIZE, page.total)}`
                : ""}
              .
            </p>
            <CompareTable
              rows={page.items}
              definition={definition}
              sort={state.sort}
              order={state.order}
              hrefFor={(sort, order) => pageHref(state, { sort, order, offset: 0 })}
              highlightJudgeId={state.judge}
            />
            {page.total > PAGE_SIZE ? (
              <nav aria-label="Compare pagination" className="flex gap-2">
                {state.offset > 0 ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(state, { offset: Math.max(0, state.offset - PAGE_SIZE) })}>Previous</Link>
                  </Button>
                ) : null}
                {page.next_offset !== null ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(state, { offset: page.next_offset })}>Next</Link>
                  </Button>
                ) : null}
              </nav>
            ) : null}
          </>
        )}
      </section>

      <Card size="sm" data-testid="comparison-notes">
        <CardHeader>
          <CardTitle>
            <h2>Comparison notes</h2>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Cohort</dt>
            <dd>
              {state.court_id
                ? "Judges with a service record at this court"
                : "Judges with a service record at a court of this jurisdiction"}
              {" — "}
              {page.cohort.name}
              {" — "}with a current observation of {definition.name} (definition version{" "}
              {page.cohort.version}).
            </dd>
            <dt className="text-muted-foreground">Period</dt>
            <dd data-testid="cohort-period">
              {formatPeriod(page.cohort.period_start, page.cohort.period_end)} — the source period
              most rows share; a row over a different period carries a coverage warning.
            </dd>
            <dt className="text-muted-foreground">Formula</dt>
            <dd>
              <span className="font-medium">Numerator:</span> {definition.numerator}{" "}
              <span className="font-medium">Denominator:</span> {definition.denominator}
            </dd>
            <dt className="text-muted-foreground">Methodology</dt>
            <dd>
              <Link
                href={definition.methodology_url || methodologyHref(definition.slug)}
                className="text-primary hover:underline"
                data-testid="methodology-link"
              >
                {definition.name} — methodology version {page.methodology_version}
              </Link>
            </dd>
            <dt className="text-muted-foreground">Reading</dt>
            <dd data-testid="association-statement">
              {ASSOCIATION_STATEMENT} Rates depend on case mix: a judge who handles a higher-risk
              docket may show a higher raw rate with no causal effect, and small samples produce
              extreme but unstable rates. No composite or ranking across metrics is published.
            </dd>
          </dl>
        </CardContent>
      </Card>
    </>
  );
}

export default async function ComparePageView({ searchParams }: { searchParams: SearchParams }) {
  const query = await searchParams;
  const [registry, courts, jurisdictions] = await Promise.all([
    getRegistry(),
    allCourts(),
    listJurisdictions({ limit: 100 }),
  ]);

  const header = (
    <header className="flex flex-col gap-2">
      <h1 className="text-3xl font-semibold tracking-tight">Compare</h1>
      <p className="max-w-3xl text-muted-foreground">
        One objective metric across the judges of a court or a jurisdiction over the same source
        period, with every row&apos;s numerator, denominator, interval, sample size, and coverage
        warning. Cohorts below the suppression threshold are marked suppressed and never ranked
        by a withheld number.
      </p>
    </header>
  );

  if (!registry.ok) {
    return (
      <article className="flex flex-col gap-6">
        {header}
        <ErrorState what="the metric registry" error={registry.error} />
      </article>
    );
  }
  const definitions = definitionsFor(registry.data, "judge");
  const courtList = Array.isArray(courts) ? courts : [];
  const jurisdictionList = jurisdictions.ok ? jurisdictions.data.items : [];
  const read = readState(query, definitions);
  const state = read.ok ? read.state : null;

  const compared =
    state && (state.court_id || state.jurisdiction_id)
      ? await compareMetrics({
          metric: state.definition.slug,
          window: state.window ?? undefined,
          court_id: state.court_id,
          jurisdiction_id: state.jurisdiction_id,
          sort: state.sort,
          order: state.order,
          limit: PAGE_SIZE,
          offset: state.offset,
        })
      : null;

  return (
    <article className="flex flex-col gap-6">
      {header}
      {!Array.isArray(courts) ? <ErrorState what="the court list" error={courts} /> : null}
      {!jurisdictions.ok ? <ErrorState what="the jurisdiction list" error={jurisdictions.error} /> : null}
      <Controls
        definitions={definitions}
        windows={windowsFromRegistry(registry.data)}
        state={state}
        courts={courtList}
        jurisdictions={jurisdictionList}
      />

      {!read.ok ? (
        <ErrorState what="the comparison" error={read.error} />
      ) : !compared ? (
        <EmptyState title="Choose a court or a jurisdiction to compare.">
          The cohort is the judges with a service record at the court, or at a court of the
          jurisdiction, with a current observation of the metric.
        </EmptyState>
      ) : !compared.ok ? (
        <ErrorState what="the comparison" error={compared.error} />
      ) : (
        <Results state={read.state} page={compared.data} />
      )}
    </article>
  );
}
