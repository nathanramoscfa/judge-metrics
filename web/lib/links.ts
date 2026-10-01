// web/lib/links.ts
// External links the pages cite. Every URL here is a verified source
// (docs/DATA_SOURCES.md) or this repository; nothing is guessed.
export const REPOSITORY_URL = "https://github.com/nathanramoscfa/judge-metrics";

export const DATA_SOURCES_URL = `${REPOSITORY_URL}/blob/main/docs/DATA_SOURCES.md`;

export const ROADMAP_URL = `${REPOSITORY_URL}/blob/main/docs/roadmap/ROADMAP.md`;

export const SYNTHETIC_DATA_URL = `${REPOSITORY_URL}/blob/main/docs/SYNTHETIC_DATA.md`;

/** The Markdown render of the metric registry, versioned with the code. */
export const METHODOLOGY_DOC_URL = `${REPOSITORY_URL}/blob/main/docs/METHODOLOGY.md`;

/** The model validation report (methodology 1.0), rendered from the latest snapshot's models. */
export const VALIDATION_DOC_URL = `${REPOSITORY_URL}/blob/main/docs/VALIDATION.md`;

/**
 * The validation report's calibration section of one model: GitHub's anchor
 * for the heading "synthetic: new_case, 365 days" (lowercased, punctuation
 * dropped, spaces as hyphens; the first heading of that text is the
 * calibration section's).
 */
export function validationSectionUrl(source: string, target: string, windowDays: number | null): string {
  const heading = `${source}: ${target}${windowDays === null ? "" : `, ${windowDays} days`}`;
  const anchor = heading
    .toLowerCase()
    .replace(/[^a-z0-9_ -]/g, "")
    .replace(/ /g, "-");
  return `${VALIDATION_DOC_URL}#${anchor}`;
}

/** The GitHub issue form for a wrong, changed, or misread data source. */
export function dataIssueUrl(title: string): string {
  const params = new URLSearchParams({
    template: "data_source_issue.md",
    title: `data: ${title}`,
    labels: "data-source",
  });
  return `${REPOSITORY_URL}/issues/new?${params.toString()}`;
}

export interface SourceLinks {
  name: string;
  /** The page the artifacts are exported from. */
  exportUrl: string;
  /** The public page for one record at the source, when the source has one. */
  recordUrl?: (externalId: string) => string;
}

/** Source register entries, keyed like `Provenance.source`. */
export const SOURCES: Record<string, SourceLinks> = {
  fjc: {
    name: "Federal Judicial Center, Biographical Directory of Article III Federal Judges",
    exportUrl:
      "https://www.fjc.gov/history/judges/biographical-directory-article-iii-federal-judges-export",
    // The directory serves each judge's biography at /node/<nid>.
    recordUrl: (nid: string) => `https://www.fjc.gov/node/${encodeURIComponent(nid)}`,
  },
  synthetic: {
    name: "Synthetic dataset (JudgeMetrics generator, demo data)",
    // The generator and its known-truth files are documented in the repository.
    exportUrl: SYNTHETIC_DATA_URL,
  },
};

export function sourceLinks(sourceId: string): SourceLinks {
  return SOURCES[sourceId] ?? { name: sourceId, exportUrl: DATA_SOURCES_URL };
}
