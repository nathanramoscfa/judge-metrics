// web/app/search/page.tsx
// Search: `?q=` → GET /api/v1/search, rendered as a table with an entity
// type badge per row. The rate-limited API answers 429 under a burst; that
// becomes the error state with the wait time, never a blank page.
import type { Metadata } from "next";
import Link from "next/link";

import { EntityTypeBadge } from "@/components/badges";
import { SearchForm } from "@/components/search-form";
import { EmptyState, ErrorState } from "@/components/states";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { search, type SearchResult } from "@/lib/api/client";

export const dynamic = "force-dynamic";

export const metadata: Metadata = { title: "Search" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstValue(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

function resultHref(result: SearchResult): string {
  return result.entity_type === "judge" ? `/judges/${result.id}` : `/courts/${result.id}`;
}

export default async function SearchPage({ searchParams }: { searchParams: SearchParams }) {
  const q = firstValue((await searchParams).q).trim().slice(0, 200);
  const result = q ? await search(q) : null;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Search</h1>
        <p className="text-sm text-muted-foreground">
          Judges and courts by name similarity. A close spelling still matches.
        </p>
        <SearchForm defaultValue={q} autoFocus={!q} className="max-w-2xl" />
      </header>

      <section aria-labelledby="results-heading" aria-live="polite">
        <h2 id="results-heading" className="sr-only">
          Results
        </h2>
        {result === null ? (
          <EmptyState title="Type a name to search">
            For example a judge&apos;s surname, or a court such as &ldquo;Southern
            District of New York&rdquo;.
          </EmptyState>
        ) : !result.ok ? (
          <ErrorState what="search results" error={result.error} />
        ) : result.data.items.length === 0 ? (
          <EmptyState title={`No judge or court matches “${q}”`}>
            Only names in the ingested sources can match. Try a different spelling or a
            shorter query.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto rounded-xl border">
            <Table data-testid="search-results">
              <caption className="sr-only">
                {result.data.items.length} results for {q}
              </caption>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">Name</TableHead>
                  <TableHead scope="col">Type</TableHead>
                  <TableHead scope="col" className="text-right">
                    Similarity
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {result.data.items.map((item) => (
                  <TableRow key={`${item.entity_type}:${item.id}`} data-testid="search-result">
                    <TableCell>
                      <Link href={resultHref(item)} className="font-medium text-primary hover:underline">
                        {item.name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <EntityTypeBadge type={item.entity_type} />
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs tabular-nums">
                      {item.score.toFixed(2)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
    </div>
  );
}
