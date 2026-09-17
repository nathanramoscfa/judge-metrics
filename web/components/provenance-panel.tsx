// web/components/provenance-panel.tsx
// The "Source coverage" panel: one entry per raw artifact behind an entity,
// with the source name, when it was retrieved, the sha256 of the stored
// bytes (truncated, with the full digest one click away), the parser
// version, and links to the source's export page and the data-issue form.
"use client";

import { Check, Copy, ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Provenance } from "@/lib/api/client";
import { formatDateTime, truncateHash } from "@/lib/format";
import { dataIssueUrl, sourceLinks } from "@/lib/links";

export function CopyHashButton({ hash }: { hash: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(hash);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-xs"
      onClick={copy}
      aria-label={copied ? "Copied the full sha256" : "Copy the full sha256"}
      title="Copy the full sha256"
      data-testid="copy-hash"
    >
      {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
      <span className="sr-only" aria-live="polite">
        {copied ? "Copied" : ""}
      </span>
    </Button>
  );
}

export function ProvenancePanel({
  entries,
  issueTitle,
}: {
  entries: Provenance[];
  issueTitle: string;
}) {
  return (
    <Card data-testid="provenance-panel" size="sm">
      <CardHeader>
        <CardTitle>
          <h2>Source coverage</h2>
        </CardTitle>
        <CardDescription>
          The raw artifacts these values were derived from. Each sha256 names
          the exact bytes kept in the immutable raw lake.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {entries.length === 0 ? (
          <EmptyState title="No source record is attached to this entity." />
        ) : (
          <ul className="flex flex-col gap-3">
            {entries.map((entry) => {
              const source = sourceLinks(entry.source);
              return (
                <li
                  key={`${entry.ingest_run_id}:${entry.raw_sha256}`}
                  data-testid="provenance-entry"
                  className="rounded-lg border p-3"
                >
                  <p className="font-medium">{source.name}</p>
                  <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                    <dt className="text-muted-foreground">artifact</dt>
                    <dd className="font-mono">{entry.external_record_id ?? "—"}</dd>
                    <dt className="text-muted-foreground">retrieved</dt>
                    <dd>
                      <time dateTime={entry.retrieved_at}>{formatDateTime(entry.retrieved_at)}</time>
                    </dd>
                    <dt className="text-muted-foreground">sha256</dt>
                    <dd className="flex items-center gap-1">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <code
                            tabIndex={0}
                            className="font-mono"
                            data-testid="hash-truncated"
                            aria-label={`sha256 ${entry.raw_sha256}`}
                          >
                            {truncateHash(entry.raw_sha256)}
                          </code>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-none font-mono">
                          {entry.raw_sha256}
                        </TooltipContent>
                      </Tooltip>
                      <CopyHashButton hash={entry.raw_sha256} />
                    </dd>
                    <dt className="text-muted-foreground">parser</dt>
                    <dd className="font-mono">{entry.parser_version}</dd>
                    <dt className="text-muted-foreground">ingest run</dt>
                    <dd className="font-mono">{entry.ingest_run_id}</dd>
                  </dl>
                  <p className="mt-2 text-xs">
                    <a
                      href={source.exportUrl}
                      className="inline-flex items-center gap-1 text-primary hover:underline"
                    >
                      Source export page
                      <ExternalLink aria-hidden="true" className="size-3" />
                    </a>
                  </p>
                </li>
              );
            })}
          </ul>
        )}
        <p className="text-xs">
          <a
            href={dataIssueUrl(issueTitle)}
            className="inline-flex items-center gap-1 text-primary hover:underline"
            data-testid="report-data-issue"
          >
            Report a data issue
            <ExternalLink aria-hidden="true" className="size-3" />
          </a>
        </p>
      </CardContent>
    </Card>
  );
}
