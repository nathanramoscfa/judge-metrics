// web/components/compare-table.tsx
// The compare table: one row per judge (per dimension value for a
// dimensioned metric) of one metric, window, and cohort, as
// /metrics/compare sorts it. Sorting is the API's — the column headers are
// links that change `sort` and `order` in the query, so the order never
// depends on a withheld number (the API sorts a suppressed row as null).
// Every figure cell is the observation's numerator over denominator, the
// figure, the interval, and the sample size; a suppressed row shows the
// notice and no figure; a coverage warning names why the row is not
// strictly comparable. Step 5 reuses this on the court and jurisdiction
// pages.
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import Link from "next/link";

import { SyntheticBadge } from "@/components/badges";
import { suppressionNotice } from "@/components/metric-stat";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { CompareRow, MetricDefinition } from "@/lib/api/client";
import {
  type CompareOrder,
  type CompareSort,
  dimensionLabel,
  formatCount,
  formatDays,
  formatFraction,
  formatInterval,
  formatPeriod,
  formatRate,
} from "@/lib/metrics";

interface SortableColumn {
  key: CompareSort;
  label: string;
  align?: "right";
}

const COLUMNS: SortableColumn[] = [
  { key: "name", label: "Judge" },
  { key: "numerator", label: "Numerator / denominator", align: "right" },
  { key: "rate", label: "Figure", align: "right" },
];

export function CompareTable({
  rows,
  definition,
  sort,
  order,
  hrefFor,
  highlightJudgeId,
}: {
  rows: CompareRow[];
  definition: MetricDefinition;
  sort: CompareSort;
  order: CompareOrder;
  /** The page URL with a different sort and order (the other parameters kept). */
  hrefFor: (sort: CompareSort, order: CompareOrder) => string;
  /** A judge to mark in the table (the judge page's compare link). */
  highlightJudgeId?: string;
}) {
  const figureSort: CompareSort = definition.kind === "median" ? "value" : "rate";
  const figure = (row: CompareRow) =>
    definition.kind === "median"
      ? formatDays(row.value)
      : definition.kind === "count"
        ? formatCount(row.numerator)
        : definition.kind === "distribution"
          ? row.numerator !== null && row.denominator
            ? formatRate(row.numerator / row.denominator)
            : "—"
          : formatRate(row.rate);

  function header(column: SortableColumn) {
    const key = column.key === "rate" ? figureSort : column.key;
    const active = sort === key;
    const nextOrder: CompareOrder = active && order === "desc" ? "asc" : "desc";
    const Icon = active ? (order === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
    return (
      <TableHead
        key={column.key}
        scope="col"
        aria-sort={active ? (order === "asc" ? "ascending" : "descending") : "none"}
        className={column.align === "right" ? "text-right" : undefined}
      >
        <Link
          href={hrefFor(key, nextOrder)}
          className="inline-flex items-center gap-1 hover:underline"
          data-testid={`sort-${key}`}
        >
          {column.label}
          <Icon aria-hidden="true" className="size-3.5" />
        </Link>
      </TableHead>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border">
      <Table data-testid="compare-table">
        <caption className="sr-only">
          {definition.name} by judge, sorted by {sort} {order}; {rows.length} rows on this page.
        </caption>
        <TableHeader>
          <TableRow>
            {header(COLUMNS[0])}
            <TableHead scope="col">Court</TableHead>
            {definition.dimension ? <TableHead scope="col">{dimensionLabel(definition.dimension)}</TableHead> : null}
            {header(COLUMNS[1])}
            {header(COLUMNS[2])}
            <TableHead scope="col">Interval</TableHead>
            <TableHead scope="col" className="text-right">
              Sample size
            </TableHead>
            <TableHead scope="col">Coverage</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const highlighted = row.subject_id === highlightJudgeId;
            return (
              <TableRow
                key={row.observation_id}
                data-testid="compare-row"
                data-judge={row.subject_id}
                data-suppressed={row.suppressed ? "true" : "false"}
                className={highlighted ? "bg-primary/5" : undefined}
              >
                <TableCell>
                  <Link href={`/judges/${row.subject_id}`} className="font-medium text-primary hover:underline">
                    {row.name}
                  </Link>
                  {row.synthetic ? <SyntheticBadge className="ml-2" /> : null}
                  {highlighted ? <span className="ml-2 text-xs text-muted-foreground">(this judge)</span> : null}
                </TableCell>
                <TableCell>
                  <Link href={`/courts/${row.court.id}`} className="text-primary hover:underline">
                    {row.court.canonical_name}
                  </Link>
                </TableCell>
                {definition.dimension ? <TableCell>{dimensionLabel(row.dimension_value)}</TableCell> : null}
                {row.suppressed ? (
                  <TableCell colSpan={3} className="text-xs text-muted-foreground" data-testid="compare-suppressed">
                    {suppressionNotice(row)}
                  </TableCell>
                ) : (
                  <>
                    <TableCell className="text-right font-mono tabular-nums" data-testid="compare-fraction">
                      {formatFraction(row.numerator, row.denominator)}
                    </TableCell>
                    <TableCell className="text-right font-semibold tabular-nums" data-testid="compare-figure">
                      {figure(row)}
                    </TableCell>
                    <TableCell className="text-xs tabular-nums" data-testid="compare-interval">
                      {formatInterval(row.lower, row.upper, row.interval_method)}
                    </TableCell>
                  </>
                )}
                <TableCell className="text-right tabular-nums" data-testid="compare-sample">
                  {formatCount(row.eligible_count)}
                </TableCell>
                <TableCell className="text-xs">
                  <span data-testid="compare-period">{formatPeriod(row.period_start, row.period_end)}</span>
                  {row.coverage_warning ? (
                    <span className="mt-0.5 block text-destructive" data-testid="compare-warning">
                      {row.coverage_warning}
                    </span>
                  ) : null}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
