// web/lib/metrics.ts
// Helpers for the metric surfaces: grouping a subject's observations by
// slug → window → dimension, choosing a window, the formatting every
// presentation field uses (rates as percentages, medians as days, counts as
// integers, periods and coverage as date ranges), suppression, the cohort
// labels, and the methodology anchor. Every formatter is null-safe so a
// suppressed or not-observable row formats as a dash, never as "NaN%". The
// follow-up windows are read from the registry response (`windows_days`),
// never hard-coded here. Phase 4 Step 5 adds the adjusted kind
// (`observed_expected`): its ratio and bootstrap-interval formatters, the
// pooling-weight sentence, the suppression reasons in words, the adjusted
// panel of the judge page, and the descriptive rate each ratio adjusts.
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
  bootstrap: "95% bootstrap interval",
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

/** Each registry kind in words, for the methodology page's definition sections. */
export const KIND_TEXT: Record<MetricDefinition["kind"], string> = {
  count: "count",
  share: "share (numerator over denominator, Wilson interval)",
  windowed_rate: "fixed-window rate per observation window (Wilson interval)",
  survival: "Kaplan–Meier cumulative incidence per observation window",
  distribution: "distribution of counts by dimension value",
  median: "median",
  observed_expected:
    "observed-to-expected ratio, partially pooled toward 1 (95% bootstrap interval; see Adjusted statistics)",
};

/** The registry kind of an observed-to-expected ratio. */
export const ADJUSTED_KIND = "observed_expected";

export function isAdjusted(item: Pick<MetricDefinition, "kind">): boolean {
  return item.kind === ADJUSTED_KIND;
}

/** "1.10" for an observed-to-expected ratio (two decimals); a dash for null. */
export function formatRatio(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toFixed(2);
}

/** "[0.99–1.21]": the bounds alone, where the method is stated once (a table header); null-safe. */
export function formatRatioBounds(
  lower: number | null | undefined,
  upper: number | null | undefined,
): string {
  if (lower === null || lower === undefined || upper === null || upper === undefined) return "—";
  return `[${formatRatio(lower)}–${formatRatio(upper)}]`;
}

/** "0.99–1.21 (95% bootstrap interval)"; a dash when either bound is null. */
export function formatRatioInterval(
  lower: number | null | undefined,
  upper: number | null | undefined,
): string {
  if (lower === null || lower === undefined || upper === null || upper === undefined) return "—";
  return `${formatRatio(lower)}–${formatRatio(upper)} (${INTERVAL_METHOD_LABEL.bootstrap})`;
}

/** "276.4" for a model-expected count (one decimal: a sum of probabilities); a dash for null. */
export function formatExpected(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

/** The pooling weight as a sentence; a dash for null. */
export function poolingSentence(weight: number | null | undefined): string {
  if (weight === null || weight === undefined || !Number.isFinite(weight)) return "—";
  return `estimate pooled toward 1.0; this judge's own data carries weight ${weight.toFixed(2)}`;
}

export type SuppressionReason = NonNullable<Observation["suppression_reason"]>;

/**
 * Why an adjusted ratio is withheld, in words: too few members in the ratio,
 * too few expected events, or no fitted model. The threshold and the minimum
 * expected count come from the registry, never from a literal here.
 */
export function adjustedSuppressionText(
  reason: Observation["suppression_reason"],
  threshold: number,
  minimumExpected: number | null | undefined,
): string {
  switch (reason) {
    case "expected_below_minimum":
      return `Suppressed: fewer than ${minimumExpected ?? "the minimum"} expected events in the ratio; a ratio over so few predicted events is withheld as unstable.`;
    case "model_unavailable":
      return "Suppressed: the expected-outcome model could not be fitted for this window, so no expected count exists and no ratio is published.";
    default:
      return `Suppressed: fewer than ${threshold} followed members in the ratio; the ratio is withheld to protect a small cohort.`;
  }
}

/**
 * The descriptive rate each adjusted ratio adjusts: its observed rate is
 * shown beside the ratio so a reader sees the raw number the model
 * conditions. Keyed by the adjusted metric's slug.
 */
export const ADJUSTS: Readonly<Record<string, string>> = {
  pretrial_release_observed_expected: "pretrial_release_share",
  new_case_observed_expected: "new_case_rate",
  failure_to_appear_observed_expected: "failure_to_appear_rate",
};

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
 * for a median; an integer for a count; the pooled ratio for an adjusted
 * metric. A dash when the figure is withheld.
 */
export function primaryFigure(
  observation: Pick<Observation, "kind" | "numerator" | "denominator" | "rate" | "value" | "ratio">,
): string {
  switch (observation.kind) {
    case "observed_expected":
      return formatRatio(observation.ratio);
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
export const COMPARE_SORTS = ["rate", "numerator", "denominator", "value", "ratio", "name"] as const;
export type CompareSort = (typeof COMPARE_SORTS)[number];
export const COMPARE_ORDERS = ["asc", "desc"] as const;
export type CompareOrder = (typeof COMPARE_ORDERS)[number];

/**
 * The sort a metric's figure lives under: medians by value, counts and
 * distributions by numerator, an adjusted metric by its pooled ratio,
 * everything else by rate.
 */
export function defaultSort(definition: Pick<MetricDefinition, "kind">): CompareSort {
  if (definition.kind === "median") return "value";
  if (definition.kind === ADJUSTED_KIND) return "ratio";
  if (definition.kind === "count" || definition.kind === "distribution") return "numerator";
  return "rate";
}

/** The comparable figure of a compare row: the pooled ratio, the rate, or the median's value. */
export function compareFigure(row: Pick<CompareRow, "rate" | "value" | "ratio">): number | null {
  return row.ratio ?? row.rate ?? row.value ?? null;
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
  id: "cases" | "pretrial" | "outcomes" | "adjusted" | "disposition" | "sentencing";
  title: string;
  /** A panel that collects every definition of one kind (the adjusted panel), in registry order. */
  kind?: MetricDefinition["kind"];
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
 * panel without a change here; the adjusted ratios are collected by kind
 * into "Risk-adjusted comparison" and no other panel; a judge metric no
 * panel names is listed under "Other metrics" rather than dropped.
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
    id: "adjusted",
    title: "Risk-adjusted comparison",
    slugs: [],
    indexEvent: null,
    casesFilter: null,
    kind: ADJUSTED_KIND,
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

export interface CourtPanelSpec {
  id: "cases" | "pretrial" | "outcomes" | "disposition" | "sentencing";
  title: string;
  slugs: readonly string[];
  indexEvent: IndexEvent | null;
}

/**
 * The court page's panels: the judge panels' slugs plus the court-only
 * counts the registry publishes for a court subject (`statutory_release_count`,
 * `unknown_actor_pretrial_count`: the pretrial rows no judge's metric may
 * count). Windowed metrics are placed by `index_event` as on the judge page.
 * The adjusted ratios are judge-only, so the court has no adjusted panel:
 * its panel ids are a subset of the judge page's.
 */
export const COURT_PANELS: readonly CourtPanelSpec[] = [
  { id: "cases", title: "Cases", slugs: ["eligible_cases", "eligible_defendants"], indexEvent: null },
  {
    id: "pretrial",
    title: "Pretrial",
    slugs: [
      "pretrial_decisions",
      "pretrial_released",
      "pretrial_detained",
      "pretrial_release_share",
      "statutory_release_count",
      "unknown_actor_pretrial_count",
    ],
    indexEvent: null,
  },
  { id: "outcomes", title: "Outcomes after qualifying release", slugs: [], indexEvent: "pretrial_release" },
  {
    id: "disposition",
    title: "Disposition",
    slugs: ["disposition_distribution", "judicial_dismissal_rate", "median_days_to_disposition"],
    indexEvent: "disposition",
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
  },
];

/** The kinds a cohort comparison (`/metrics/compare`) is fetched for on the judge page. */
export const COMPARED_KINDS: ReadonlySet<MetricDefinition["kind"]> = new Set([
  "share",
  "windowed_rate",
  "survival",
  "median",
  ADJUSTED_KIND,
]);

/** The metric the court and jurisdiction compare tables open on. */
export const DEFAULT_COMPARE_METRIC = "pretrial_release_share";

/**
 * The id of the first observation a panel shows, in slug order (any window
 * or dimension): the target of the panel's "Report a data error" link.
 */
export function firstObservationId(grouped: GroupedObservations, slugs: readonly string[]): string | null {
  for (const slug of slugs) {
    for (const window of Object.values(grouped[slug] ?? {})) {
      for (const rows of Object.values(window)) {
        if (rows[0]) return rows[0].id;
      }
    }
  }
  return null;
}

/**
 * The definitions a panel shows: the named slugs in order, then the windowed
 * metrics of the panel's index event grouped by outcome in registry order of
 * first appearance (a fixed-window rate beside the Kaplan–Meier estimate of
 * the same outcome). A panel with a `kind` collects exactly the definitions
 * of that kind, in registry order; an adjusted ratio is never placed by its
 * index event, so it appears in no other panel.
 */
export function panelDefinitions(
  spec: { slugs: readonly string[]; indexEvent: IndexEvent | null; kind?: MetricDefinition["kind"] },
  definitions: MetricDefinition[],
): { named: MetricDefinition[]; windowed: MetricDefinition[] } {
  if (spec.kind) return { named: definitions.filter((d) => d.kind === spec.kind), windowed: [] };
  const descriptive = definitions.filter((d) => !isAdjusted(d));
  const bySlug = new Map(descriptive.map((d) => [d.slug, d]));
  const outcomeOrder = [...new Set(descriptive.map((d) => d.outcome ?? ""))];
  const named = spec.slugs.map((slug) => bySlug.get(slug)).filter((d): d is MetricDefinition => !!d);
  const windowed = spec.indexEvent
    ? descriptive
        .filter((d) => d.index_event === spec.indexEvent)
        .sort((a, b) => outcomeOrder.indexOf(a.outcome ?? "") - outcomeOrder.indexOf(b.outcome ?? ""))
    : [];
  return { named, windowed };
}

/**
 * The judge metrics no panel shows: not a named slug, not windowed (a
 * windowed metric is placed by its index event), and not adjusted (the
 * adjusted panel collects those by kind).
 */
export function uncoveredDefinitions(definitions: MetricDefinition[]): MetricDefinition[] {
  const covered = new Set<string>(JUDGE_PANELS.flatMap((spec) => [...spec.slugs]));
  return definitions.filter((d) => !covered.has(d.slug) && !isWindowed(d) && !isAdjusted(d));
}

/** The model card page of a model an adjusted figure cites. */
export function modelHref(modelId: string): string {
  return `/models/${encodeURIComponent(modelId)}`;
}

/** A feature name of the model specification in words: "lead_severity" → "lead severity". */
export function featureLabel(name: string): string {
  return name.replace(/_/g, " ");
}

/**
 * The cohort definition under an adjusted ratio: the model, the
 * specification, what it was fitted on (when the model card is known), the
 * features it adjusts for, and the cohort the ratio is compared within.
 */
export function adjustedCohortDefinition(params: {
  modelVersion: string;
  specVersion: number;
  indexEvents: number | null;
  source: string;
  coverage: ObservationCoverage;
  features: string[];
  cohort: string;
}): string {
  const fitted =
    params.indexEvents === null
      ? `fitted on the index events of ${params.source}`
      : `fitted on ${formatCount(params.indexEvents)} events of ${params.source}`;
  const window = formatPeriod(params.coverage.coverage_start, params.coverage.coverage_end);
  const features = params.features.length > 0 ? params.features.map(featureLabel).join(", ") : "no feature";
  return `Expected counts from model ${params.modelVersion}, specification ${params.specVersion}, ${fitted} (${window}), adjusting for ${features}; compared within ${params.cohort}.`;
}

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
