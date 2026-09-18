// web/app/judges/[judgeId]/cases/page.tsx
// A judge's cases: the four API filters as a plain GET form (filed from and
// to, status, case type), a paginated table newest filing first, each row
// linking to the case page. A malformed query value is dropped before the
// API is called; an inverted date range is left to the API, whose 422
// becomes the error state.
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { SyntheticBadge } from "@/components/badges";
import { EmptyState, ErrorState } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getJudge, getJudgeCases, type ListJudgeCasesParams } from "@/lib/api/client";
import { formatDate, formatInteger, isIsoDate, isUuid, titleCase } from "@/lib/format";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 25;
const STATUSES = ["open", "closed"] as const;
const CASE_TYPES = ["felony", "misdemeanor"] as const;
const VOCABULARY_VALUE = /^[a-z][a-z0-9_]*$/;

type Params = Promise<{ judgeId: string }>;
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstValue(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { judgeId } = await params;
  if (!isUuid(judgeId)) return { title: "Cases" };
  const result = await getJudge(judgeId);
  return { title: result.ok ? `Cases · ${result.data.canonical_name}` : "Cases" };
}

/** The filters the query string carries, with malformed values dropped. */
function readFilters(query: Record<string, string | string[] | undefined>): ListJudgeCasesParams {
  const filedFrom = firstValue(query.filed_from);
  const filedTo = firstValue(query.filed_to);
  const status = firstValue(query.status);
  const caseType = firstValue(query.case_type);
  const requestedOffset = Number.parseInt(firstValue(query.offset), 10);
  return {
    filed_from: isIsoDate(filedFrom) ? filedFrom : undefined,
    filed_to: isIsoDate(filedTo) ? filedTo : undefined,
    status: VOCABULARY_VALUE.test(status) ? status : undefined,
    case_type: VOCABULARY_VALUE.test(caseType) ? caseType : undefined,
    offset: Number.isFinite(requestedOffset) && requestedOffset > 0 ? requestedOffset : 0,
    limit: PAGE_SIZE,
  };
}

function pageHref(judgeId: string, filters: ListJudgeCasesParams, offset: number): string {
  const params = new URLSearchParams();
  if (filters.filed_from) params.set("filed_from", filters.filed_from);
  if (filters.filed_to) params.set("filed_to", filters.filed_to);
  if (filters.status) params.set("status", filters.status);
  if (filters.case_type) params.set("case_type", filters.case_type);
  if (offset > 0) params.set("offset", String(offset));
  const query = params.toString();
  return `/judges/${judgeId}/cases${query ? `?${query}` : ""}#cases-heading`;
}

export default async function JudgeCasesPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const { judgeId } = await params;
  if (!isUuid(judgeId)) notFound();
  const filters = readFilters(await searchParams);
  const offset = filters.offset ?? 0;

  const [judge, cases] = await Promise.all([getJudge(judgeId), getJudgeCases(judgeId, filters)]);
  if (!judge.ok) {
    if (judge.error.status === 404) notFound();
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Cases</h1>
        <ErrorState what="this judge" error={judge.error} />
      </div>
    );
  }

  return (
    <article className="flex flex-col gap-6">
      <header className="flex flex-col gap-2">
        <p className="text-sm text-muted-foreground">
          <Link href={`/judges/${judgeId}`} className="text-primary hover:underline" data-testid="judge-link">
            {judge.data.canonical_name}
          </Link>
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <h1 id="cases-heading" className="text-3xl font-semibold tracking-tight">
            Cases
          </h1>
          {judge.data.synthetic ? <SyntheticBadge /> : null}
        </div>
        <p className="text-sm text-muted-foreground">
          Every case with an assignment to this judge in the ingested sources, newest filing
          first. Persons are pseudonymous throughout.
        </p>
      </header>

      <form method="get" action={`/judges/${judgeId}/cases`} className="flex flex-wrap items-end gap-3" data-testid="case-filters">
        <div className="flex flex-col gap-1">
          <label htmlFor="filed_from" className="text-sm text-muted-foreground">
            Filed from
          </label>
          <Input id="filed_from" name="filed_from" type="date" defaultValue={filters.filed_from ?? ""} className="w-44" />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="filed_to" className="text-sm text-muted-foreground">
            Filed to
          </label>
          <Input id="filed_to" name="filed_to" type="date" defaultValue={filters.filed_to ?? ""} className="w-44" />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="status" className="text-sm text-muted-foreground">
            Status
          </label>
          <select
            id="status"
            name="status"
            defaultValue={filters.status ?? ""}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">Any</option>
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {titleCase(status)}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="case_type" className="text-sm text-muted-foreground">
            Case type
          </label>
          <select
            id="case_type"
            name="case_type"
            defaultValue={filters.case_type ?? ""}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            <option value="">Any</option>
            {CASE_TYPES.map((type) => (
              <option key={type} value={type}>
                {titleCase(type)}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" variant="secondary">
          Apply filters
        </Button>
      </form>

      <section aria-labelledby="cases-heading" className="flex flex-col gap-3">
        {!cases.ok ? (
          <ErrorState what="the case list" error={cases.error} />
        ) : cases.data.items.length === 0 ? (
          <EmptyState title="No case matches these filters.">
            Filters apply to the filing date, the status, and the case type.
          </EmptyState>
        ) : (
          <>
            <p className="text-sm text-muted-foreground" data-testid="cases-summary">
              {formatInteger(cases.data.total)} case{cases.data.total === 1 ? "" : "s"}
              {cases.data.total > PAGE_SIZE
                ? `, showing ${offset + 1}–${Math.min(offset + PAGE_SIZE, cases.data.total)}`
                : ""}
              .
            </p>
            <div className="overflow-x-auto rounded-xl border">
              <Table data-testid="cases-table">
                <caption className="sr-only">Cases assigned to {judge.data.canonical_name}</caption>
                <TableHeader>
                  <TableRow>
                    <TableHead scope="col">Case number</TableHead>
                    <TableHead scope="col">Court</TableHead>
                    <TableHead scope="col">Type</TableHead>
                    <TableHead scope="col">Status</TableHead>
                    <TableHead scope="col">Filed</TableHead>
                    <TableHead scope="col">Closed</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {cases.data.items.map((item) => (
                    <TableRow key={item.id} data-testid="case-row">
                      <TableCell>
                        <Link href={`/cases/${item.id}`} className="font-mono font-medium text-primary hover:underline">
                          {item.case_number}
                        </Link>
                        {item.synthetic ? <SyntheticBadge className="ml-2" /> : null}
                      </TableCell>
                      <TableCell>
                        <Link href={`/courts/${item.court.id}`} className="text-primary hover:underline">
                          {item.court.canonical_name}
                        </Link>
                      </TableCell>
                      <TableCell>{titleCase(item.case_type)}</TableCell>
                      <TableCell>{titleCase(item.status)}</TableCell>
                      <TableCell>
                        {item.filed_date ? <time dateTime={item.filed_date}>{formatDate(item.filed_date)}</time> : "—"}
                      </TableCell>
                      <TableCell>
                        {item.closed_date ? <time dateTime={item.closed_date}>{formatDate(item.closed_date)}</time> : "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {cases.data.total > PAGE_SIZE ? (
              <nav aria-label="Cases pagination" className="flex gap-2">
                {offset > 0 ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(judgeId, filters, Math.max(0, offset - PAGE_SIZE))}>Previous</Link>
                  </Button>
                ) : null}
                {cases.data.next_offset !== null ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(judgeId, filters, cases.data.next_offset)}>Next</Link>
                  </Button>
                ) : null}
              </nav>
            ) : null}
          </>
        )}
      </section>
    </article>
  );
}
