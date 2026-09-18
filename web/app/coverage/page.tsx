// web/app/coverage/page.tsx
// Coverage v0: one table per ingested source with its row counts, filing
// window, and last completed run, read from /api/v1/coverage on every
// request. Completeness estimates and known gaps arrive with the metrics
// engine in Phase 3; the page says so.
import type { Metadata } from "next";

import { SyntheticBadge } from "@/components/badges";
import { EmptyState, ErrorState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { getCoverage, type CoverageSource } from "@/lib/api/client";
import { formatDate, formatDateTime, formatInteger, titleCase } from "@/lib/format";
import { DATA_SOURCES_URL, sourceLinks } from "@/lib/links";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Coverage" };

function SourceCard({ source }: { source: CoverageSource }) {
  const links = sourceLinks(source.source);
  const rows: [string, string][] = [
    ["Jurisdictions", formatInteger(source.jurisdictions)],
    ["Courts", formatInteger(source.courts)],
    ["Judges", formatInteger(source.judges)],
    ["Cases", formatInteger(source.cases)],
    ["Persons (pseudonymous)", formatInteger(source.persons)],
  ];
  return (
    <Card size="sm" data-testid="coverage-source" data-source={source.source}>
      <CardHeader>
        <CardTitle>
          <h2 className="flex flex-wrap items-center gap-2">
            <span className="font-mono">{source.source}</span>
            {source.synthetic ? <SyntheticBadge /> : null}
          </h2>
        </CardTitle>
        <CardDescription>
          {links.name} · {titleCase(source.source_type)}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <table className="w-full text-sm">
          <caption className="sr-only">Rows derived from {source.source}</caption>
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th scope="col" className="py-1 font-medium">
                Table
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                Rows
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, value]) => (
              <tr key={label} className="border-t">
                <th scope="row" className="py-1 text-left font-normal">
                  {label}
                </th>
                <td className="py-1 text-right font-mono tabular-nums">{value}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
          <dt className="text-muted-foreground">Filing dates</dt>
          <dd data-testid="coverage-window">
            {source.earliest_filed ? (
              <>
                <time dateTime={source.earliest_filed}>{formatDate(source.earliest_filed)}</time>
                {" – "}
                <time dateTime={source.latest_filed ?? undefined}>{formatDate(source.latest_filed)}</time>
              </>
            ) : (
              "no case data"
            )}
          </dd>
          <dt className="text-muted-foreground">Last run</dt>
          <dd data-testid="coverage-last-run">
            {source.last_ingest ? (
              <>
                <time dateTime={source.last_ingest.completed_at ?? undefined}>
                  {formatDateTime(source.last_ingest.completed_at)}
                </time>{" "}
                ({source.last_ingest.status}){" "}
                <span className="font-mono text-muted-foreground">{source.last_ingest.run_id}</span>
              </>
            ) : (
              "no completed run"
            )}
          </dd>
        </dl>
        <p className="text-xs">
          <a href={links.exportUrl} className="text-primary hover:underline">
            Source documentation
          </a>
        </p>
      </CardContent>
    </Card>
  );
}

export default async function CoveragePage() {
  const coverage = await getCoverage();
  return (
    <article className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">Coverage</h1>
        <p className="max-w-3xl text-muted-foreground">
          What each ingested source contributes to the canonical tables, the span of filing
          dates it covers, and its most recent ingest run. Every row traces to a raw artifact
          in the immutable lake.
        </p>
      </header>

      {!coverage.ok ? (
        <ErrorState what="the coverage summary" error={coverage.error} />
      ) : coverage.data.sources.length === 0 ? (
        <EmptyState title="No source has been ingested yet." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2" data-testid="coverage-sources">
          {coverage.data.sources.map((source) => (
            <SourceCard key={source.source} source={source} />
          ))}
        </div>
      )}

      <p className="rounded-xl border border-dashed px-6 py-6 text-sm text-muted-foreground" data-testid="coverage-note">
        Completeness estimates per jurisdiction and the known-gaps register arrive with the
        metrics engine in Phase 3; the interactive coverage map with the first real state-court
        pipeline. Until then the only case-level source is the synthetic demo dataset, labelled
        as such on every surface and refused by the ingest runner in production.
      </p>
      <p className="text-sm">
        <a href={DATA_SOURCES_URL} className="text-primary hover:underline">
          Read the data-source register
        </a>
      </p>
    </article>
  );
}
