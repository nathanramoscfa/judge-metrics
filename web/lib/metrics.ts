// web/lib/metrics.ts
// Helpers for the metric surfaces: grouping a subject's observations by
// slug → window → dimension, choosing a window, the formatting every
// presentation field uses (rates as percentages, medians as days, counts as
// integers, periods and coverage as date ranges), suppression, the cohort
// labels, and the methodology anchor. Every formatter is null-safe so a
// suppressed or not-observable row formats as a dash, never as "NaN%". The
// follow-up windows are read from the registry response (`windows_days`),
// never hard-coded here.
import type {
  CompareRow,
  MetricDefinition,
  Observation,
  Registry,
  Schemas,
} from "@/lib/api/client";
import { formatDate, formatInteger, titleCase } from "@/lib/format";

export type ObservationCoverage = Schemas["ObservationCoverage"];

/**
 * The brief's statement, word for word, above every metric panel and on the
 * methodology page (`data-testid="association-statement"` on both).
 */
export const ASSOCIATION_STATEMENT =
  "These statistics describe associations in available records. They do not prove that a judicial decision caused a later event.";

/** The window key of an unwindowed metric. */
export const NO_WINDOW = "all";
/** The dimension key of an undimensioned observation. */
export const NO_DIMENSION = "";
/** The window the judge page and the compare page open on. */
export const DEFAULT_WINDOW_DAYS = 365;

/** Dimension key → the observations of that dimension, one per source, in API order. */
export type DimensionGroup = Record<string, Observation[]>;
/** Window key → dimension group. */
export type WindowGroup = Record<string, DimensionGroup>;
/** Metric slug → window group. */
export type GroupedObservations = Record<string, WindowGroup>;

export function windowKey(days: number | null | undefined): string {
  return days === null || days === undefined ? NO_WINDOW : String(days);
}

export function dimensionKey(value: string | null | undefined): string {
  return value ?? NO_DIMENSION;
}

/**
 * `SubjectMetrics.observations` (a map keyed by slug, each list ordered by
 * window, dimension value, and source) grouped by slug → window → dimension.
 */
export function groupObservations(
  observations: Record<string, Observation[]>,
): GroupedObservations {
  const grouped: GroupedObservations = {};
  for (const [slug, rows] of Object.entries(observations)) {
    const windows: WindowGroup = {};
    for (const row of rows) {
      const window = (windows[windowKey(row.window_days)] ??= {});
      (window[dimensionKey(row.dimension_value)] ??= []).push(row);
    }
    grouped[slug] = windows;
  }
  return grouped;
}

/** The dimension group of one window of a slug's group; `null` days is the unwindowed entry. */
export function pickWindow(
  group: WindowGroup | undefined,
  days: number | null,
): DimensionGroup | undefined {
  return group?.[windowKey(days)];
}

/** The first observation (the first source) of a slug at a window and dimension. */
export function pickObservation(
  grouped: GroupedObservations,
  slug: string,
  options: { window?: number | null; dimension?: string | null } = {},
): Observation | undefined {
  return pickWindow(grouped[slug], options.window ?? null)?.[dimensionKey(options.dimension)]?.[0];
}

/** The dimension values present for a slug at a window, in API order. */
export function dimensionValues(
  grouped: GroupedObservations,
  slug: string,
  window: number | null = null,
): string[] {
  return Object.keys(pickWindow(grouped[slug], window) ?? {}).filter((key) => key !== NO_DIMENSION);
}

/** The follow-up windows the registry declares, ascending; never a literal here. */
export function windowsFromRegistry(registry: Pick<Registry, "windows_days" | "definitions">): number[] {
  const declared = new Set<number>(registry.windows_days);
  for (const definition of registry.definitions) {
    for (const days of definition.windows_days ?? []) declared.add(days);
  }
  return [...declared].sort((a, b) => a - b);
}

/**
 * The window a page shows: the query value when it is one of the registry's
 * windows, else the default (365) when the registry has it, else the largest
 * window. `null` when the registry declares no window at all.
 */
export function resolveWindow(raw: string | undefined, windows: number[]): number | null {
  if (windows.length === 0) return null;
  const requested = Number.parseInt(raw ?? "", 10);
  if (Number.isFinite(requested) && windows.includes(requested)) return requested;
  if (windows.includes(DEFAULT_WINDOW_DAYS)) return DEFAULT_WINDOW_DAYS;
  return windows[windows.length - 1];
}

export function isSuppressed(observation: Pick<Observation, "suppressed">): boolean {
  return observation.suppressed;
}

/** "22.1%" for 0.220641; a dash for null (suppressed or absent). */
export function formatRate(rate: number | null | undefined, digits = 1): string {
  if (rate === null || rate === undefined || !Number.isFinite(rate)) return "—";
  return `${(rate * 100).toFixed(digits)}%`;
}

const INTERVAL_METHOD_LABEL: Record<string, string> = {
  wilson: "95% Wilson interval",
  greenwood: "95% Greenwood interval",
};

/** "17.6%–27.3% (95% Wilson interval)"; a dash when either bound is null. */
export function formatInterval(
  lower: number | null | undefined,
  upper: number | null | undefined,
  method: string | null | undefined,
): string {
  if (lower === null || lower === undefined || upper === null || upper === undefined) return "—";
  const label = method ? INTERVAL_METHOD_LABEL[method] ?? `95% ${titleCase(method)} interval` : "95% interval";
  return `${formatRate(lower)}–${formatRate(upper)} (${label})`;
}

/** "150.5 days" for a median; whole numbers without a decimal; a dash for null. */
export function formatDays(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  const rounded = Number.isInteger(value) ? String(value) : value.toFixed(1);
  return `${rounded} day${value === 1 ? "" : "s"}`;
}

/** "1,234" for a count; a dash for null. */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return formatInteger(value);
}

/** "Jan 1, 2016 – Dec 31, 2023"; either end may be null. */
export function formatPeriod(start: string | null | undefined, end: string | null | undefined): string {
  if (!start && !end) return "—";
  return `${formatDate(start)} – ${formatDate(end)}`;
}

/** "synthetic · Jan 1, 2016 – Dec 31, 2023 · outcome observable". */
export function formatCoverage(coverage: ObservationCoverage, source: string): string {
  const window = formatPeriod(coverage.coverage_start, coverage.coverage_end);
  const observable = coverage.observable ? "outcome observable" : "outcome not observable";
  return `${source} · ${window} · ${observable}`;
}

/** "n / d" with both formatted; a dash when either is withheld. */
export function formatFraction(
  numerator: number | null | undefined,
  denominator: number | null | undefined,
): string {
  if (numerator === null || numerator === undefined || denominator === null || denominator === undefined) {
    return "—";
  }
  return `${formatCount(numerator)} / ${formatCount(denominator)}`;
}

/**
 * The primary figure of an observation by kind: a percentage for a share,
 * fixed-window rate, survival estimate, or one value of a distribution; days
 * for a median; an integer for a count. A dash when the figure is withheld.
 */
export function primaryFigure(
  observation: Pick<Observation, "kind" | "numerator" | "denominator" | "rate" | "value">,
): string {
  switch (observation.kind) {
    case "count":
      return formatCount(observation.numerator);
    case "median":
      return formatDays(observation.value);
    case "distribution":
      return observation.numerator !== null && observation.denominator
        ? formatRate(observation.numerator / observation.denominator)
        : "—";
    default:
      return formatRate(observation.rate);
  }
}

/** "released" for a slug like "pretrial_released"; a dimension value in words. */
export function dimensionLabel(value: string | null | undefined): string {
  return value ? titleCase(value) : "";
}

export const COHORTS = {
  court: "Same court, same period",
  jurisdiction: "Jurisdiction, same period",
} as const;

export type CohortKind = keyof typeof COHORTS;

export function isCohortKind(value: string): value is CohortKind {
  return value in COHORTS;
}

/** The cohort query value, defaulting to the court. */
export function parseCohort(raw: string | undefined): CohortKind {
  return raw && isCohortKind(raw) ? raw : "court";
}

/** "Same court, same period (Jan 1, 2016 – Dec 31, 2023)". */
export function cohortLabel(
  observation: Pick<Observation, "period_start" | "period_end">,
  kind: CohortKind = "court",
): string {
  return `${COHORTS[kind]} (${formatPeriod(observation.period_start, observation.period_end)})`;
}

/**
 * The methodology page anchored at the metric's slug. The API already sends
 * `methodology_url` in this shape; pages pass it through when present and
 * fall back to this for a definition without one. The version is carried
 * in the link title, not the path: one page serves the current registry.
 */
export function methodologyHref(slug: string, version?: string, base = "/methodology"): string {
  void version;
  return `${base}#${encodeURIComponent(slug)}`;
}

/** The definitions a subject type can carry, in registry order. */
export function definitionsFor(
  registry: Pick<Registry, "definitions">,
  subject: "judge" | "court",
): MetricDefinition[] {
  return registry.definitions.filter((definition) => definition.subject_types.includes(subject));
}

/** True for a fixed-window rate or a survival estimate. */
export function isWindowed(definition: Pick<MetricDefinition, "windows_days">): boolean {
  return (definition.windows_days?.length ?? 0) > 0;
}

/** The compare sort keys the API accepts. */
export const COMPARE_SORTS = ["rate", "numerator", "denominator", "value", "name"] as const;
export type CompareSort = (typeof COMPARE_SORTS)[number];
export const COMPARE_ORDERS = ["asc", "desc"] as const;
export type CompareOrder = (typeof COMPARE_ORDERS)[number];

/** The sort a metric's figure lives under: medians sort by value, everything else by rate. */
export function defaultSort(definition: Pick<MetricDefinition, "kind">): CompareSort {
  if (definition.kind === "median") return "value";
  if (definition.kind === "count" || definition.kind === "distribution") return "numerator";
  return "rate";
}

/** The comparable figure of a compare row: the rate, or the median's value. */
export function compareFigure(row: Pick<CompareRow, "rate" | "value">): number | null {
  return row.rate ?? row.value ?? null;
}

export interface CohortPosition {
  /** Judges in the cohort (the page total, suppressed rows included). */
  judges: number;
  /** Judges whose figure is published (unsuppressed) on the page. */
  published: number;
  /** The median of the published figures; null when none is published. */
  median: number | null;
  /** The judge's 1-based rank among the published figures, descending; null when unranked. */
  rank: number | null;
}

/**
 * Where a judge falls in a cohort's distribution of one metric, from the
 * compare rows of the same window and dimension: the number of judges, the
 * cohort's median figure, and the judge's rank by figure (highest first).
 */
export function cohortPosition(
  rows: CompareRow[],
  judgeId: string,
  total: number,
  dimension: string | null = null,
): CohortPosition {
  const cohort = rows.filter((row) => dimensionKey(row.dimension_value) === dimensionKey(dimension));
  const published = cohort
    .map((row) => ({ id: row.subject_id, figure: compareFigure(row) }))
    .filter((row): row is { id: string; figure: number } => row.figure !== null)
    .sort((a, b) => b.figure - a.figure);
  const figures = published.map((row) => row.figure);
  const mid = Math.floor(figures.length / 2);
  const median =
    figures.length === 0
      ? null
      : figures.length % 2 === 1
        ? figures[mid]
        : (figures[mid - 1] + figures[mid]) / 2;
  const index = published.findIndex((row) => row.id === judgeId);
  return {
    judges: dimension === null ? total : cohort.length,
    published: published.length,
    median,
    rank: index === -1 ? null : index + 1,
  };
}

export type IndexEvent = "pretrial_release" | "disposition" | "sentence";

export interface JudgePanelSpec {
  /** The section anchor. */
  id: "cases" | "pretrial" | "outcomes" | "disposition" | "sentencing";
  title: string;
  /** Unwindowed metrics shown in this order (registry names are the labels). */
  slugs: readonly string[];
  /** The index event whose windowed metrics (rates and survival estimates) the panel also shows. */
  indexEvent: IndexEvent | null;
  /** The cases-route filter the "View eligible cases" link carries, when one applies. */
  casesFilter: Record<string, string> | null;
}

/**
 * The judge page's panels. Windowed metrics are placed by the registry's
 * `index_event`, not by slug, so a new outcome metric lands in the right
 * panel without a change here; a judge metric no panel names is listed
 * under "Other metrics" rather than dropped.
 */
export const JUDGE_PANELS: readonly JudgePanelSpec[] = [
  {
    id: "cases",
    title: "Cases",
    slugs: ["eligible_cases", "eligible_defendants"],
    indexEvent: null,
    casesFilter: null,
  },
  {
    id: "pretrial",
    title: "Pretrial",
    slugs: ["pretrial_decisions", "pretrial_released", "pretrial_detained", "pretrial_release_share"],
    indexEvent: null,
    casesFilter: null,
  },
  {
    id: "outcomes",
    title: "Outcomes after qualifying release",
    slugs: [],
    indexEvent: "pretrial_release",
    casesFilter: null,
  },
  {
    id: "disposition",
    title: "Disposition",
    slugs: ["disposition_distribution", "judicial_dismissal_rate", "median_days_to_disposition"],
    indexEvent: "disposition",
    casesFilter: { status: "closed" },
  },
  {
    id: "sentencing",
    title: "Sentencing",
    slugs: [
      "sentence_count",
      "incarceration_days_median",
      "probation_days_median",
      "incarceration_days_median_by_offense_category",
    ],
    indexEvent: "sentence",
    casesFilter: { status: "closed" },
  },
];

/** The kinds a cohort comparison (`/metrics/compare`) is fetched for on the judge page. */
export const COMPARED_KINDS: ReadonlySet<MetricDefinition["kind"]> = new Set([
  "share",
  "windowed_rate",
  "survival",
  "median",
]);

/** The judge's case list with a panel's filter, when the cases route supports one. */
export function eligibleCasesHref(judgeId: string, filter: Record<string, string> | null): string {
  const query = filter ? new URLSearchParams(filter).toString() : "";
  return `/judges/${judgeId}/cases${query ? `?${query}` : ""}`;
}

/** The compare page for one metric, window, and cohort. */
export function compareHref(params: {
  metric: string;
  window?: number | null;
  court_id?: string;
  jurisdiction_id?: string;
  sort?: CompareSort;
  order?: CompareOrder;
  offset?: number;
}): string {
  const query = new URLSearchParams();
  query.set("metric", params.metric);
  if (params.window !== null && params.window !== undefined) query.set("window", String(params.window));
  if (params.court_id) query.set("court_id", params.court_id);
  else if (params.jurisdiction_id) query.set("jurisdiction_id", params.jurisdiction_id);
  if (params.sort) query.set("sort", params.sort);
  if (params.order) query.set("order", params.order);
  if (params.offset) query.set("offset", String(params.offset));
  return `/compare?${query.toString()}`;
}
