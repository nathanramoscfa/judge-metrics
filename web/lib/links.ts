// web/lib/links.ts
// External links the pages cite. Every URL here is a verified source
// (docs/DATA_SOURCES.md) or this repository; nothing is guessed.
export const REPOSITORY_URL = "https://github.com/nathanramoscfa/judge-metrics";

export const DATA_SOURCES_URL = `${REPOSITORY_URL}/blob/main/docs/DATA_SOURCES.md`;

export const ROADMAP_URL = `${REPOSITORY_URL}/blob/main/ROADMAP.md`;

export const SYNTHETIC_DATA_URL = `${REPOSITORY_URL}/blob/main/docs/SYNTHETIC_DATA.md`;

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
