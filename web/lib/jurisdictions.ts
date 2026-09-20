// web/lib/jurisdictions.ts
// Helpers for the jurisdiction page: which /coverage source rows belong to
// a jurisdiction (the sources in its own provenance, plus every synthetic
// source when one of its courts is synthetic — a court summary carries the
// flag, not its provenance), and the years those sources' declared coverage
// windows span ("no case data" when none declares one, as for an FJC-only
// jurisdiction).
import type { CourtSummary, CoverageSource, JurisdictionDetail } from "@/lib/api/client";

export function jurisdictionSources(
  jurisdiction: Pick<JurisdictionDetail, "provenance">,
  courts: Pick<CourtSummary, "synthetic">[],
  sources: CoverageSource[],
): CoverageSource[] {
  const keys = new Set<string>(jurisdiction.provenance.map((entry) => entry.source));
  const syntheticCourt = courts.some((court) => court.synthetic);
  return sources.filter((source) => keys.has(source.source) || (syntheticCourt && source.synthetic));
}

/** "2016–2023" from the declared coverage windows; null when no source declares one. */
export function availableYears(
  sources: Pick<CoverageSource, "coverage_start" | "coverage_end">[],
): string | null {
  const years = sources
    .flatMap((source) => [source.coverage_start, source.coverage_end])
    .filter((value): value is string => !!value)
    .map((value) => Number.parseInt(value.slice(0, 4), 10))
    .filter((year) => Number.isFinite(year));
  if (years.length === 0) return null;
  const first = Math.min(...years);
  const last = Math.max(...years);
  return first === last ? String(first) : `${first}–${last}`;
}
