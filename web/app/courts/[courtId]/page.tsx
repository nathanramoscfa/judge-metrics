// web/app/courts/[courtId]/page.tsx
// A court: name, type, jurisdiction, and the judges whose service interval
// covers a chosen date (`?active_on=`, a plain GET form so it works without
// JavaScript), paginated through `?offset=`.
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { CourtTypeBadge, StatusBadge, SyntheticBadge } from "@/components/badges";
import { ProvenancePanel } from "@/components/provenance-panel";
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
import { getCourt, getJurisdiction, listJudges } from "@/lib/api/client";
import { formatDate, formatInteger, isIsoDate, isUuid, todayIsoDate } from "@/lib/format";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

type Params = Promise<{ courtId: string }>;
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function firstValue(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

export async function generateMetadata({ params }: { params: Params }): Promise<Metadata> {
  const { courtId } = await params;
  if (!isUuid(courtId)) return { title: "Court" };
  const result = await getCourt(courtId);
  return { title: result.ok ? result.data.canonical_name : "Court" };
}

export default async function CourtPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const { courtId } = await params;
  if (!isUuid(courtId)) notFound();

  const query = await searchParams;
  const requestedDate = firstValue(query.active_on);
  const activeOn = isIsoDate(requestedDate) ? requestedDate : todayIsoDate();
  const requestedOffset = Number.parseInt(firstValue(query.offset), 10);
  const offset = Number.isFinite(requestedOffset) && requestedOffset > 0 ? requestedOffset : 0;

  const court = await getCourt(courtId);
  if (!court.ok) {
    if (court.error.status === 404) notFound();
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-semibold tracking-tight">Court</h1>
        <ErrorState what="this court" error={court.error} />
      </div>
    );
  }

  const [jurisdiction, judges] = await Promise.all([
    getJurisdiction(court.data.jurisdiction_id),
    listJudges({ court_id: courtId, active_on: activeOn, limit: PAGE_SIZE, offset }),
  ]);

  const pageHref = (nextOffset: number) =>
    `/courts/${courtId}?active_on=${activeOn}${nextOffset > 0 ? `&offset=${nextOffset}` : ""}#judges-heading`;

  return (
    <article className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight" data-testid="court-name">
            {court.data.canonical_name}
          </h1>
          <CourtTypeBadge type={court.data.court_type} />
          {court.data.synthetic ? <SyntheticBadge /> : null}
        </div>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted-foreground">
          <div className="flex gap-1.5">
            <dt>Jurisdiction:</dt>
            <dd className="text-foreground">
              {jurisdiction.ok ? jurisdiction.data.name : "Unavailable"}
            </dd>
          </div>
          {court.data.state_code ? (
            <div className="flex gap-1.5">
              <dt>State:</dt>
              <dd className="text-foreground">{court.data.state_code}</dd>
            </div>
          ) : null}
          {court.data.active_from || court.data.active_to ? (
            <div className="flex gap-1.5">
              <dt>Active:</dt>
              <dd className="text-foreground">
                {formatDate(court.data.active_from)} – {court.data.active_to ? formatDate(court.data.active_to) : "present"}
              </dd>
            </div>
          ) : null}
        </dl>
      </header>

      <section aria-labelledby="judges-heading" className="flex flex-col gap-3">
        <h2 id="judges-heading" className="text-lg font-semibold">
          Judges serving on a date
        </h2>
        <form method="get" action={`/courts/${courtId}`} className="flex flex-wrap items-end gap-2">
          <div className="flex flex-col gap-1">
            <label htmlFor="active_on" className="text-sm text-muted-foreground">
              Active on
            </label>
            <Input
              id="active_on"
              name="active_on"
              type="date"
              defaultValue={activeOn}
              required
              className="w-44"
              data-testid="active-on"
            />
          </div>
          <Button type="submit" variant="secondary">
            Show judges
          </Button>
          <p className="basis-full text-xs text-muted-foreground">
            A service interval runs from the source&apos;s commission date to its
            termination date; senior status does not end it.
          </p>
        </form>
        {!judges.ok ? (
          <ErrorState what="the judges serving on this date" error={judges.error} />
        ) : judges.data.items.length === 0 ? (
          <EmptyState title={`No judge on file was serving here on ${formatDate(activeOn)}`}>
            Service intervals follow the source&apos;s commission and termination dates.
          </EmptyState>
        ) : (
          <>
            <p className="text-sm text-muted-foreground" data-testid="judges-summary">
              {formatInteger(judges.data.total)} judge{judges.data.total === 1 ? "" : "s"} serving on{" "}
              <time dateTime={activeOn}>{formatDate(activeOn)}</time>
              {judges.data.total > PAGE_SIZE
                ? `, showing ${offset + 1}–${Math.min(offset + PAGE_SIZE, judges.data.total)}`
                : ""}
              .
            </p>
            <div className="overflow-x-auto rounded-xl border">
              <Table data-testid="court-judges">
                <caption className="sr-only">
                  Judges serving at {court.data.canonical_name} on {activeOn}
                </caption>
                <TableHeader>
                  <TableRow>
                    <TableHead scope="col">Judge</TableHead>
                    <TableHead scope="col">Status</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {judges.data.items.map((judge) => (
                    <TableRow key={judge.id} data-testid="court-judge-row">
                      <TableCell>
                        <Link href={`/judges/${judge.id}`} className="font-medium text-primary hover:underline">
                          {judge.canonical_name}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <span className="flex flex-wrap items-center gap-2">
                          <StatusBadge status={judge.status} />
                          {judge.synthetic ? <SyntheticBadge /> : null}
                        </span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {judges.data.total > PAGE_SIZE ? (
              <nav aria-label="Judges pagination" className="flex gap-2">
                {offset > 0 ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(Math.max(0, offset - PAGE_SIZE))}>Previous</Link>
                  </Button>
                ) : null}
                {judges.data.next_offset !== null ? (
                  <Button asChild variant="outline" size="sm">
                    <Link href={pageHref(judges.data.next_offset)}>Next</Link>
                  </Button>
                ) : null}
              </nav>
            ) : null}
          </>
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <section aria-labelledby="court-stats-heading" className="flex flex-col gap-3">
          <h2 id="court-stats-heading" className="text-lg font-semibold">
            Court statistics
          </h2>
          <div className="rounded-xl border border-dashed px-6 py-8 text-sm text-muted-foreground">
            Case volume, outcome distributions, and the comparable-judge table arrive
            with the metrics engine in Phase 3.
          </div>
        </section>
        <ProvenancePanel
          entries={court.data.provenance}
          issueTitle={`${court.data.canonical_name} (court ${court.data.id})`}
        />
      </div>
    </article>
  );
}
