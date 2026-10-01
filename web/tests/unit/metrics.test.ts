// web/tests/unit/metrics.test.ts
// lib/metrics.ts: grouping by slug → window → dimension, window selection
// from the registry, every formatter including its null-safe path (a
// suppressed or not-observable row formats as a dash, never NaN), the
// cohort labels, the methodology anchor, and the cohort position; and
// (Phase 4 Step 5) the adjusted kind: the ratio formatters, the
// suppression reasons in words, the adjusted panel, and the cohort
// definition.
import { describe, expect, it } from "vitest";

import {
  ADJUSTS,
  COHORTS,
  COMPARED_KINDS,
  COMPARE_SORTS,
  COURT_PANELS,
  DEFAULT_COMPARE_METRIC,
  DEFAULT_WINDOW_DAYS,
  JUDGE_PANELS,
  adjustedCohortDefinition,
  adjustedSuppressionText,
  cohortLabel,
  cohortPosition,
  compareHref,
  defaultSort,
  definitionsFor,
  dimensionValues,
  eligibleCasesHref,
  featureLabel,
  firstObservationId,
  formatCount,
  formatCoverage,
  formatDays,
  formatExpected,
  formatFraction,
  formatInterval,
  formatPeriod,
  formatRate,
  formatRatio,
  formatRatioBounds,
  formatRatioInterval,
  groupObservations,
  isAdjusted,
  isSuppressed,
  isWindowed,
  methodologyHref,
  modelHref,
  panelDefinitions,
  poolingSentence,
  parseCohort,
  pickObservation,
  pickWindow,
  primaryFigure,
  resolveWindow,
  uncoveredDefinitions,
  windowsFromRegistry,
} from "@/lib/metrics";

import {
  ADJUSTED,
  COUNT,
  DEFINITIONS,
  DISTRIBUTION,
  JUDGE_ID,
  MEDIAN,
  RATE,
  REGISTRY,
  SHARE,
  SUPPRESSED,
  adjustedRow,
  compareRow,
  suppressedAdjusted,
} from "./fixtures/observations";

describe("groupObservations", () => {
  const grouped = groupObservations({
    new_case_rate: [{ ...RATE, window_days: 90 }, RATE, { ...RATE, source: "other" }],
    disposition_distribution: [DISTRIBUTION, { ...DISTRIBUTION, dimension_value: "acquitted", numerator: 21 }],
    pretrial_release_share: [SHARE],
  });

  it("groups by slug, then window, then dimension, keeping one entry per source", () => {
    expect(Object.keys(grouped)).toEqual(["new_case_rate", "disposition_distribution", "pretrial_release_share"]);
    expect(Object.keys(grouped.new_case_rate)).toEqual(["90", "365"]);
    expect(pickWindow(grouped.new_case_rate, 365)?.[""]).toHaveLength(2);
    expect(pickWindow(grouped.new_case_rate, 30)).toBeUndefined();
    expect(Object.keys(pickWindow(grouped.disposition_distribution, null) ?? {})).toEqual(["dismissed", "acquitted"]);
    expect(dimensionValues(grouped, "disposition_distribution")).toEqual(["dismissed", "acquitted"]);
    expect(dimensionValues(grouped, "pretrial_release_share")).toEqual([]);
  });

  it("picks the first source's observation at a window and dimension", () => {
    expect(pickObservation(grouped, "new_case_rate", { window: 365 })?.source).toBe("synthetic");
    expect(pickObservation(grouped, "disposition_distribution", { dimension: "acquitted" })?.numerator).toBe(21);
    expect(pickObservation(grouped, "pretrial_release_share")).toBe(SHARE);
    expect(pickObservation(grouped, "missing")).toBeUndefined();
  });
});

describe("windows", () => {
  it("reads the windows from the registry response, ascending", () => {
    expect(windowsFromRegistry(REGISTRY)).toEqual([30, 90, 180, 365, 730, 1095]);
    expect(windowsFromRegistry({ windows_days: [], definitions: [{ ...REGISTRY.definitions[2], windows_days: [90, 30] }] })).toEqual([30, 90]);
  });

  it("resolves the query window against the registry, defaulting to 365", () => {
    const windows = windowsFromRegistry(REGISTRY);
    expect(DEFAULT_WINDOW_DAYS).toBe(365);
    expect(resolveWindow(undefined, windows)).toBe(365);
    expect(resolveWindow("90", windows)).toBe(90);
    expect(resolveWindow("91", windows)).toBe(365);
    expect(resolveWindow("abc", windows)).toBe(365);
    expect(resolveWindow("30", [30, 90])).toBe(30);
    expect(resolveWindow(undefined, [30, 90])).toBe(90);
    expect(resolveWindow("30", [])).toBeNull();
  });

  it("knows which definitions are windowed", () => {
    expect(isWindowed(REGISTRY.definitions[2])).toBe(true);
    expect(isWindowed(REGISTRY.definitions[0])).toBe(false);
  });
});

describe("formatting", () => {
  it("formats rates as percentages, null-safe", () => {
    expect(formatRate(0.220641)).toBe("22.1%");
    expect(formatRate(0)).toBe("0.0%");
    expect(formatRate(1, 0)).toBe("100%");
    expect(formatRate(null)).toBe("—");
    expect(formatRate(undefined)).toBe("—");
    expect(formatRate(Number.NaN)).toBe("—");
  });

  it("formats intervals with the method, null-safe", () => {
    expect(formatInterval(0.176104, 0.272712, "wilson")).toBe("17.6%–27.3% (95% Wilson interval)");
    expect(formatInterval(0.2, 0.3, "greenwood")).toBe("20.0%–30.0% (95% Greenwood interval)");
    expect(formatInterval(0.2, 0.3, null)).toBe("20.0%–30.0% (95% interval)");
    expect(formatInterval(null, 0.3, "wilson")).toBe("—");
    expect(formatInterval(0.2, null, "wilson")).toBe("—");
  });

  it("formats days, counts, fractions, periods, and coverage", () => {
    expect(formatDays(150.5)).toBe("150.5 days");
    expect(formatDays(304)).toBe("304 days");
    expect(formatDays(1)).toBe("1 day");
    expect(formatDays(null)).toBe("—");
    expect(formatCount(1234)).toBe("1,234");
    expect(formatCount(null)).toBe("—");
    expect(formatFraction(62, 281)).toBe("62 / 281");
    expect(formatFraction(null, 281)).toBe("—");
    expect(formatPeriod("2016-01-01", "2023-12-31")).toBe("Jan 1, 2016 – Dec 31, 2023");
    expect(formatPeriod(null, null)).toBe("—");
    expect(formatPeriod("2016-01-01", null)).toBe("Jan 1, 2016 – —");
    expect(formatCoverage(RATE.coverage, "synthetic")).toBe(
      "synthetic · Jan 1, 2016 – Dec 31, 2023 · outcome observable",
    );
    expect(formatCoverage({ coverage_start: null, coverage_end: null, observable: false }, "fjc")).toBe(
      "fjc · — · outcome not observable",
    );
  });

  it("chooses the primary figure by kind and dashes a suppressed row", () => {
    expect(primaryFigure(RATE)).toBe("22.1%");
    expect(primaryFigure(SHARE)).toBe("67.8%");
    expect(primaryFigure(MEDIAN)).toBe("150.5 days");
    expect(primaryFigure(COUNT)).toBe("697");
    expect(primaryFigure(DISTRIBUTION)).toBe("22.4%");
    expect(primaryFigure(SUPPRESSED)).toBe("—");
    expect(primaryFigure({ ...MEDIAN, value: null })).toBe("—");
    expect(primaryFigure({ ...COUNT, numerator: null })).toBe("—");
  });

  it("reports suppression from the flag alone", () => {
    expect(isSuppressed(RATE)).toBe(false);
    expect(isSuppressed(SUPPRESSED)).toBe(true);
  });
});

describe("cohorts and links", () => {
  it("labels the cohort with the period", () => {
    expect(COHORTS.court).toBe("Same court, same period");
    expect(COHORTS.jurisdiction).toBe("Jurisdiction, same period");
    expect(cohortLabel(RATE)).toBe("Same court, same period (Jan 1, 2016 – Dec 31, 2023)");
    expect(cohortLabel(RATE, "jurisdiction")).toBe("Jurisdiction, same period (Jan 1, 2016 – Dec 31, 2023)");
    expect(parseCohort(undefined)).toBe("court");
    expect(parseCohort("jurisdiction")).toBe("jurisdiction");
    expect(parseCohort("nonsense")).toBe("court");
  });

  it("anchors the methodology page at the slug", () => {
    expect(methodologyHref("new_case_rate", "1")).toBe("/methodology#new_case_rate");
    expect(methodologyHref("a b")).toBe("/methodology#a%20b");
  });

  it("builds the case and compare links", () => {
    expect(eligibleCasesHref(JUDGE_ID, null)).toBe(`/judges/${JUDGE_ID}/cases`);
    expect(eligibleCasesHref(JUDGE_ID, { status: "closed" })).toBe(`/judges/${JUDGE_ID}/cases?status=closed`);
    expect(compareHref({ metric: "new_case_rate", window: 365, court_id: "c", sort: "rate" })).toBe(
      "/compare?metric=new_case_rate&window=365&court_id=c&sort=rate",
    );
    expect(compareHref({ metric: "x", court_id: "c", jurisdiction_id: "j" })).toBe("/compare?metric=x&court_id=c");
    expect(compareHref({ metric: "x", jurisdiction_id: "j", offset: 50 })).toBe("/compare?metric=x&jurisdiction_id=j&offset=50");
  });

  it("filters definitions by subject and picks the sort of a kind", () => {
    expect(definitionsFor(REGISTRY, "judge").map((d) => d.slug)).not.toContain("statutory_release_count");
    expect(definitionsFor(REGISTRY, "court").map((d) => d.slug)).toContain("statutory_release_count");
    expect(defaultSort({ kind: "median" })).toBe("value");
    expect(defaultSort({ kind: "count" })).toBe("numerator");
    expect(defaultSort({ kind: "share" })).toBe("rate");
  });
});

describe("cohortPosition", () => {
  const rows = [
    compareRow({ subject_id: "a", rate: 0.3 }),
    compareRow({ subject_id: JUDGE_ID, rate: 0.22 }),
    compareRow({ subject_id: "c", rate: 0.1 }),
    compareRow({ subject_id: "d", rate: null, suppressed: true, numerator: null, denominator: null }),
  ];

  it("ranks the judge among the published figures and takes the median", () => {
    const position = cohortPosition(rows, JUDGE_ID, 4);
    expect(position).toEqual({ judges: 4, published: 3, median: 0.22, rank: 2 });
  });

  it("takes the mean of the middle pair for an even count and leaves an absent judge unranked", () => {
    const position = cohortPosition(rows.slice(0, 2), "zzz", 2);
    expect(position.median).toBeCloseTo(0.26);
    expect(position.rank).toBeNull();
  });

  it("uses the median's value and filters by dimension", () => {
    const medians = [
      compareRow({ subject_id: JUDGE_ID, rate: null, value: 300, dimension_value: "drug" }),
      compareRow({ subject_id: "b", rate: null, value: 100, dimension_value: "drug" }),
      compareRow({ subject_id: JUDGE_ID, rate: null, value: 50, dimension_value: "traffic" }),
    ];
    expect(cohortPosition(medians, JUDGE_ID, 3, "drug")).toEqual({ judges: 2, published: 2, median: 200, rank: 1 });
    expect(cohortPosition([], JUDGE_ID, 0)).toEqual({ judges: 0, published: 0, median: null, rank: null });
  });
});

describe("the adjusted kind (Phase 4 Step 5)", () => {
  const adjusted = DEFINITIONS.filter(isAdjusted);

  it("formats ratios, their bootstrap interval, expected counts, and the pooling weight, null-safe", () => {
    expect(formatRatio(1.0974)).toBe("1.10");
    expect(formatRatio(0)).toBe("0.00");
    expect(formatRatio(null)).toBe("—");
    expect(formatRatio(Number.NaN)).toBe("—");
    expect(formatRatioInterval(0.9912, 1.2087)).toBe("0.99–1.21 (95% bootstrap interval)");
    expect(formatRatioInterval(null, 1.2)).toBe("—");
    expect(formatRatioBounds(0.9912, 1.2087)).toBe("[0.99–1.21]");
    expect(formatRatioBounds(0.9, null)).toBe("—");
    expect(formatInterval(0.9, 1.1, "bootstrap")).toContain("95% bootstrap interval");
    expect(formatExpected(276.4182)).toBe("276.4");
    expect(formatExpected(1234)).toBe("1,234.0");
    expect(formatExpected(undefined)).toBe("—");
    expect(poolingSentence(0.6213)).toBe(
      "estimate pooled toward 1.0; this judge's own data carries weight 0.62",
    );
    expect(poolingSentence(null)).toBe("—");
  });

  it("chooses the ratio as the primary figure, sorts by it, and compares the kind", () => {
    expect(primaryFigure(ADJUSTED)).toBe("1.10");
    expect(primaryFigure(suppressedAdjusted("below_threshold"))).toBe("—");
    expect(defaultSort({ kind: "observed_expected" })).toBe("ratio");
    expect(COMPARE_SORTS).toContain("ratio");
    expect(COMPARED_KINDS.has("observed_expected")).toBe(true);
    // The cohort position ranks the published pooled ratios.
    const rows = [
      adjustedRow({ subject_id: "a", ratio: 1.3 }),
      adjustedRow({ subject_id: JUDGE_ID, ratio: 1.0974 }),
      adjustedRow({ subject_id: "c", ratio: 0.9 }),
      adjustedRow({ subject_id: "d", ratio: null, rate: null, suppressed: true, suppression_reason: "below_threshold" }),
    ];
    expect(cohortPosition(rows, JUDGE_ID, 4)).toEqual({ judges: 4, published: 3, median: 1.0974, rank: 2 });
  });

  it("states each suppression reason in words with the registry's numbers", () => {
    expect(adjustedSuppressionText("below_threshold", 30, 5)).toBe(
      "Suppressed: fewer than 30 followed members in the ratio; the ratio is withheld to protect a small cohort.",
    );
    expect(adjustedSuppressionText("expected_below_minimum", 30, 5)).toContain("fewer than 5 expected events");
    expect(adjustedSuppressionText("model_unavailable", 30, 5)).toContain(
      "the expected-outcome model could not be fitted for this window",
    );
    expect(adjustedSuppressionText(null, 30, null)).toContain("fewer than 30 followed members");
  });

  it("collects exactly the adjusted definitions in the adjusted panel and in no other", () => {
    const spec = JUDGE_PANELS.find((panel) => panel.id === "adjusted");
    expect(spec?.title).toBe("Risk-adjusted comparison");
    expect(JUDGE_PANELS.map((panel) => panel.id)).toEqual([
      "cases",
      "pretrial",
      "outcomes",
      "adjusted",
      "disposition",
      "sentencing",
    ]);
    const panel = panelDefinitions(spec!, DEFINITIONS);
    expect(panel.named.map((d) => d.slug)).toEqual(adjusted.map((d) => d.slug));
    expect(panel.named.map((d) => d.slug)).toEqual(["pretrial_release_observed_expected", "new_case_observed_expected"]);
    expect(panel.windowed).toEqual([]);
    for (const other of JUDGE_PANELS.filter((panel) => panel.id !== "adjusted")) {
      const shown = panelDefinitions(other, DEFINITIONS);
      expect([...shown.named, ...shown.windowed].some(isAdjusted), other.id).toBe(false);
    }
    // The new-case ratio shares the outcomes panel's index event and still lands only in its own panel.
    const outcomes = panelDefinitions(JUDGE_PANELS.find((panel) => panel.id === "outcomes")!, DEFINITIONS);
    expect(outcomes.windowed.map((d) => d.slug)).toEqual(["new_case_rate", "rearrest_rate"]);
    // "Other metrics" never lists an adjusted metric.
    expect(uncoveredDefinitions(DEFINITIONS).some(isAdjusted)).toBe(false);
    expect(uncoveredDefinitions([...DEFINITIONS, { ...DEFINITIONS[0], slug: "loose_count" }]).map((d) => d.slug)).toEqual([
      "statutory_release_count",
      "loose_count",
    ]);
  });

  it("names the raw rate each ratio adjusts and links the model card", () => {
    expect(ADJUSTS).toEqual({
      pretrial_release_observed_expected: "pretrial_release_share",
      new_case_observed_expected: "new_case_rate",
      failure_to_appear_observed_expected: "failure_to_appear_rate",
    });
    expect(modelHref("abc")).toBe("/models/abc");
    expect(featureLabel("prior_failures_to_appear")).toBe("prior failures to appear");
  });

  it("writes the cohort definition from the model, its training, and the cohort", () => {
    expect(
      adjustedCohortDefinition({
        modelVersion: "expected-logit-v1",
        specVersion: 1,
        indexEvents: 4534,
        source: "synthetic",
        coverage: ADJUSTED.coverage,
        features: ["lead_severity", "prior_cases"],
        cohort: cohortLabel(ADJUSTED),
      }),
    ).toBe(
      "Expected counts from model expected-logit-v1, specification 1, fitted on 4,534 events of synthetic (Jan 1, 2016 – Dec 31, 2023), adjusting for lead severity, prior cases; compared within Same court, same period (Jan 1, 2016 – Dec 31, 2023).",
    );
    expect(
      adjustedCohortDefinition({
        modelVersion: "m",
        specVersion: 2,
        indexEvents: null,
        source: "synthetic",
        coverage: ADJUSTED.coverage,
        features: [],
        cohort: "x",
      }),
    ).toContain("fitted on the index events of synthetic");
  });
});

describe("panels (Phase 3 Step 5)", () => {
  it("names the court-only counts on the court's Pretrial panel; court panel ids are a subset of judge panel ids", () => {
    const pretrial = COURT_PANELS.find((spec) => spec.id === "pretrial");
    expect(pretrial?.slugs).toEqual(expect.arrayContaining(["statutory_release_count", "unknown_actor_pretrial_count"]));
    const judgeIds = JUDGE_PANELS.map((spec) => spec.id as string);
    for (const spec of COURT_PANELS) expect(judgeIds).toContain(spec.id);
    // The adjusted ratios are judge-only: the court has no adjusted panel.
    expect(COURT_PANELS.map((spec) => spec.id as string)).not.toContain("adjusted");
    expect(DEFAULT_COMPARE_METRIC).toBe("pretrial_release_share");
  });

  it("places named slugs in order and windowed metrics by index event, grouped by outcome", () => {
    const { named, windowed } = panelDefinitions(
      { slugs: ["pretrial_release_share", "not_in_registry", "eligible_cases"], indexEvent: "pretrial_release" },
      DEFINITIONS,
    );
    expect(named.map((d) => d.slug)).toEqual(["pretrial_release_share", "eligible_cases"]);
    expect(windowed.length).toBeGreaterThan(0);
    expect(windowed.every((d) => d.index_event === "pretrial_release")).toBe(true);
    const outcomes = windowed.map((d) => d.outcome);
    // Every metric of one outcome is adjacent to the others of that outcome.
    for (let i = 1; i < outcomes.length; i += 1) {
      if (outcomes[i] !== outcomes[i - 1]) expect(outcomes.slice(i)).not.toContain(outcomes[i - 1]);
    }
    expect(panelDefinitions({ slugs: [], indexEvent: null }, DEFINITIONS)).toEqual({ named: [], windowed: [] });
  });

  it("finds the first observation of a panel in slug order, at any window or dimension", () => {
    const grouped = groupObservations({
      new_case_rate: [RATE],
      pretrial_release_share: [SHARE],
      disposition_distribution: [DISTRIBUTION],
    });
    expect(firstObservationId(grouped, ["pretrial_release_share", "new_case_rate"])).toBe(SHARE.id);
    expect(firstObservationId(grouped, ["missing", "new_case_rate"])).toBe(RATE.id);
    expect(firstObservationId(grouped, ["disposition_distribution"])).toBe(DISTRIBUTION.id);
    expect(firstObservationId(grouped, ["missing"])).toBeNull();
    expect(firstObservationId({}, ["new_case_rate"])).toBeNull();
  });
});
