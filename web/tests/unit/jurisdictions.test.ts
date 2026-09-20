// web/tests/unit/jurisdictions.test.ts
// The jurisdiction page's helpers: which coverage sources belong to a
// jurisdiction (its provenance, plus the synthetic sources when a court is
// synthetic) and the available years from their declared windows ("no case
// data", i.e. null, for an FJC-only jurisdiction).
import { describe, expect, it } from "vitest";

import type { CoverageSource } from "@/lib/api/client";
import { availableYears, jurisdictionSources } from "@/lib/jurisdictions";

function source(overrides: Partial<CoverageSource>): CoverageSource {
  return {
    source: "fjc",
    source_type: "public_dataset",
    synthetic: false,
    jurisdictions: 1,
    courts: 159,
    judges: 4076,
    cases: 0,
    persons: 0,
    earliest_filed: null,
    latest_filed: null,
    last_ingest: null,
    coverage_start: null,
    coverage_end: null,
    observable_outcomes: [],
    latest_snapshot: null,
    methodology_version: null,
    ...overrides,
  };
}

const FJC = source({});
const SYNTHETIC = source({
  source: "synthetic",
  source_type: "synthetic",
  synthetic: true,
  cases: 5200,
  coverage_start: "2016-01-01",
  coverage_end: "2023-12-31",
  observable_outcomes: ["new_case", "reconviction"],
});

const provenance = (name: string) => ({
  source: name,
  external_record_id: null,
  retrieved_at: "2026-09-16T00:00:00Z",
  raw_sha256: "a".repeat(64),
  parser_version: "1",
  ingest_run_id: "0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e",
  synthetic: name === "synthetic",
});

describe("jurisdictionSources", () => {
  it("keeps the sources named by the jurisdiction's provenance", () => {
    const sources = jurisdictionSources({ provenance: [provenance("fjc")] }, [{ synthetic: false }], [FJC, SYNTHETIC]);
    expect(sources.map((s) => s.source)).toEqual(["fjc"]);
  });

  it("adds every synthetic source when one of the courts is synthetic", () => {
    const sources = jurisdictionSources({ provenance: [provenance("synthetic")] }, [{ synthetic: true }], [FJC, SYNTHETIC]);
    expect(sources.map((s) => s.source)).toEqual(["synthetic"]);
    const viaCourt = jurisdictionSources({ provenance: [] }, [{ synthetic: false }, { synthetic: true }], [FJC, SYNTHETIC]);
    expect(viaCourt.map((s) => s.source)).toEqual(["synthetic"]);
  });
});

describe("availableYears", () => {
  it("spans the declared coverage windows", () => {
    expect(availableYears([SYNTHETIC])).toBe("2016–2023");
    expect(availableYears([SYNTHETIC, source({ coverage_start: "2024-01-01", coverage_end: "2024-06-30" })])).toBe(
      "2016–2024",
    );
    expect(availableYears([source({ coverage_start: "2020-03-01", coverage_end: "2020-11-30" })])).toBe("2020");
  });

  it("is null when no source declares a window (an FJC-only jurisdiction)", () => {
    expect(availableYears([FJC])).toBeNull();
    expect(availableYears([])).toBeNull();
  });
});
