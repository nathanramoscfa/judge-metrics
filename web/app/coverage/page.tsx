// web/app/coverage/page.tsx
// Coverage v1: a "Snapshot" card (the registry and methodology versions the
// API serves and the newest snapshot behind any current observation), then
// one card per ingested source with its row counts, filing window, the
// coverage window its connector declares, the outcomes it can and cannot
// document (the not-observable ones named from the registry's outcomes),
// the latest snapshot hash and time, the methodology version, and its last
// run — read from /api/v1/coverage and /api/v1/metrics on every request.
import type { Metadata } from "next";

import { CopyHashButton } from "@/components/provenance-panel";
import { SyntheticBadge } from "@/components/badges";
import { EmptyState, ErrorState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { getCoverage, getRegistry, type Coverage, type CoverageSource, type Registry } from "@/lib/api/client";
import { formatDate, formatDateTime, formatInteger, titleCase, truncateHash } from "@/lib/format";
import { DATA_SOURCES_URL, sourceLinks } from "@/lib/links";
import { formatPeriod } from "@/lib/metrics";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Coverage" };

/** Every outcome a registry metric counts, sorted: the universe a source can or cannot observe. */
function registryOutcomes(registry: Registry | null): string[] {
  if (!registry) return [];
  const outcomes = new Set<string>();
  for (const definition of registry.definitions) {
    if (definition.outcome) outcomes.add(definition.outcome);
  }
  return [...outcomes].sort();
}

function Hash({ hash }: { hash: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <Tooltip>
        <TooltipTrigger asChild>
          <code tabIndex={0} className="font-mono" data-testid="snapshot-hash" aria-label={`snapshot ${hash}`}>
            {truncateHash(hash)}
          </code>
        </TooltipTrigger>
        <TooltipContent className="max-w-none font-mono">{hash}</TooltipContent>
      </Tooltip>
      <CopyHashButton hash={hash} />
    </span>
  );
}

function SnapshotCard({ coverage, registry }: { coverage: Coverage; registry: Registry | null }) {
  const snapshots = coverage.sources
    .filter((source) => source.latest_snapshot !== null)
    .sort((a, b) => (b.latest_snapshot?.exported_at ?? "").localeCompare(a.latest_snapshot?.exported_at ?? ""));
  const latest = snapshots[0]?.latest_snapshot ?? null;
  return (
    <Card size="sm" data-testid="snapshot-card">
      <CardHeader>
        <CardTitle>
          <h2>Snapshot</h2>
        </CardTitle>
        <CardDescription>
          Every published number is computed from a hashed export of the canonical tables and
          records the registry and methodology versions it followed;{" "}
          <code className="font-mono">judgemetrics metrics verify</code> reproduces it from that
          snapshot.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Registry version</dt>
          <dd data-testid="registry-version">{coverage.registry_version}</dd>
          <dt className="text-muted-foreground">Methodology version</dt>
          <dd data-testid="methodology-version">{coverage.methodology_version}</dd>
          <dt className="text-muted-foreground">Metrics defined</dt>
          <dd>{registry ? registry.definitions.length : "—"}</dd>
          <dt className="text-muted-foreground">Latest snapshot</dt>
          <dd data-testid="latest-snapshot">
            {latest ? (
              <>
                <Hash hash={latest.content_hash} /> exported{" "}
                <time dateTime={latest.exported_at}>{formatDateTime(latest.exported_at)}</time>
              </>
            ) : (
              "none yet: no metric has been computed"
            )}
          </dd>
          <dt className="text-muted-foreground">Generated</dt>
          <dd>
            <time dateTime={coverage.generated_at}>{formatDateTime(coverage.generated_at)}</time>
          </dd>
        </dl>
      </CardContent>
    </Card>
  );
}

function SourceCard({ source, outcomes }: { source: CoverageSource; outcomes: string[] }) {
  const links = sourceLinks(source.source);
  const rows: [string, string][] = [
    ["Jurisdictions", formatInteger(source.jurisdictions)],
    ["Courts", formatInteger(source.courts)],
    ["Judges", formatInteger(source.judges)],
    ["Cases", formatInteger(source.cases)],
    ["Persons (pseudonymous)", formatInteger(source.persons)],
  ];
  const observable = new Set(source.observable_outcomes);
  const notObservable = outcomes.filter((outcome) => !observable.has(outcome));
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
          <dt className="text-muted-foreground">Coverage window</dt>
          <dd data-testid="coverage-declared">
            {source.coverage_start || source.coverage_end
              ? `${formatPeriod(source.coverage_start, source.coverage_end)} — follow-up is censored the day after the end`
              : "none declared: no metric is computed for this source"}
          </dd>
          <dt className="text-muted-foreground">Observable outcomes</dt>
          <dd data-testid="observable-outcomes">
            {source.observable_outcomes.length > 0
              ? source.observable_outcomes.map(titleCase).join(", ")
              : "none: this source documents no subsequent event"}
          </dd>
          <dt className="text-muted-foreground">Not observable</dt>
          <dd data-testid="not-observable-outcomes">
            {outcomes.length === 0 || !(source.coverage_start || source.coverage_end)
              ? "not applicable: no coverage window, so no metric is computed"
              : notObservable.length > 0
                ? `${notObservable.map(titleCase).join(", ")} — no number is published for these, never a zero`
                : "none: every registry outcome is documented"}
          </dd>
          <dt className="text-muted-foreground">Latest snapshot</dt>
          <dd data-testid="source-snapshot">
            {source.latest_snapshot ? (
              <>
                <Hash hash={source.latest_snapshot.content_hash} />{" "}
                <time dateTime={source.latest_snapshot.exported_at}>
                  {formatDateTime(source.latest_snapshot.exported_at)}
                </time>
              </>
            ) : (
              "none: no current observation"
            )}
          </dd>
          <dt className="text-muted-foreground">Methodology</dt>
          <dd data-testid="source-methodology">
            {source.methodology_version ? `version ${source.methodology_version}` : "—"}
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
  const [coverage, registry] = await Promise.all([getCoverage(), getRegistry()]);
  const outcomes = registryOutcomes(registry.ok ? registry.data : null);
  return (
    <article className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">Coverage</h1>
        <p className="max-w-3xl text-muted-foreground">
          What each ingested source contributes to the canonical tables, the span of dates it
          covers, which subsequent events it can document, and the snapshot its numbers were
          computed from. Every row traces to a raw artifact in the immutable lake.
        </p>
      </header>

      {!coverage.ok ? (
        <ErrorState what="the coverage summary" error={coverage.error} />
      ) : (
        <>
          <SnapshotCard coverage={coverage.data} registry={registry.ok ? registry.data : null} />
          {!registry.ok ? <ErrorState what="the metric registry" error={registry.error} /> : null}
          {coverage.data.sources.length === 0 ? (
            <EmptyState title="No source has been ingested yet." />
          ) : (
            <div className="grid gap-4 md:grid-cols-2" data-testid="coverage-sources">
              {coverage.data.sources.map((source) => (
                <SourceCard key={source.source} source={source} outcomes={outcomes} />
              ))}
            </div>
          )}
        </>
      )}

      <p className="rounded-xl border border-dashed px-6 py-6 text-sm text-muted-foreground" data-testid="coverage-note">
        A source without a declared coverage window has no metric; a metric whose outcome the
        source cannot observe is never published for it. Completeness estimates per
        jurisdiction and the known-gaps register arrive with the first real state-court
        pipeline (Phase 5). Until then the only case-level source is the synthetic demo
        dataset, labelled as such on every surface and refused by the ingest runner in
        production.
      </p>
      <p className="text-sm">
        <a href={DATA_SOURCES_URL} className="text-primary hover:underline">
          Read the data-source register
        </a>
      </p>
    </article>
  );
}
