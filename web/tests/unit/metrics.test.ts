// web/tests/unit/metrics.test.ts
// lib/metrics.ts: grouping by slug → window → dimension, window selection
// from the registry, every formatter including its null-safe path (a
// suppressed or not-observable row formats as a dash, never NaN), the
// cohort labels, the methodology anchor, and the cohort position.
import { describe, expect, it } from "vitest";

import {
  COHORTS,
  DEFAULT_WINDOW_DAYS,
  cohortLabel,
  cohortPosition,
  compareHref,
  defaultSort,
  definitionsFor,
  dimensionValues,
  eligibleCasesHref,
  formatCount,
  formatCoverage,
  formatDays,
  formatFraction,
  formatInterval,
  formatPeriod,
  formatRate,
  groupObservations,
  isSuppressed,
  isWindowed,
  methodologyHref,
  parseCohort,
  pickObservation,
  pickWindow,
  primaryFigure,
  resolveWindow,
  windowsFromRegistry,
} from "@/lib/metrics";

import {
  COUNT,
  DISTRIBUTION,
  JUDGE_ID,
  MEDIAN,
  RATE,
  REGISTRY,
  SHARE,
  SUPPRESSED,
  compareRow,
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
