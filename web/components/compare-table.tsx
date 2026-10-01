// web/components/compare-table.tsx
// The compare table: one row per judge (per dimension value for a
// dimensioned metric) of one metric, window, and cohort, as
// /metrics/compare sorts it. Sorting is the API's — the column headers are
// links that change `sort` and `order` in the query, so the order never
// depends on a withheld number (the API sorts a suppressed row as null).
// Every figure cell is the observation's numerator over denominator, the
// figure, the interval, and the sample size; a suppressed row shows the
// notice and no figure; a coverage warning names why the row is not
// strictly comparable. An adjusted metric (`observed_expected`) has its own
// columns — observed over expected events, the pooled O/E with its 95%
// bootstrap interval, the pooling weight — and a suppressed adjusted row
// spans them with its reason in words. Reused on the court and jurisdiction
// pages.
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import Link from "next/link";

import { adjustedSuppressionNotice } from "@/components/adjusted-stat";
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
  formatExpected,
  formatFraction,
  formatInterval,
  formatPeriod,
  formatRate,
  formatRatio,
  formatRatioBounds,
  formatRatioInterval,
  isAdjusted,
} from "@/lib/metrics";

interface SortableColumn {
  key: CompareSort;
  label: string;
  /** A second, smaller header line (the adjusted ratio's interval method). */
  note?: string;
  align?: "right";
}

const COLUMNS: SortableColumn[] = [
  { key: "name", label: "Judge" },
  { key: "numerator", label: "Numerator / denominator", align: "right" },
  { key: "rate", label: "Figure", align: "right" },
];

const ADJUSTED_COLUMNS: SortableColumn[] = [
  { key: "name", label: "Judge" },
  { key: "numerator", label: "Observed / expected", align: "right" },
  { key: "ratio", label: "O/E (pooled)", note: "[95% bootstrap interval]", align: "right" },
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
  const adjusted = isAdjusted(definition);
  const columns = adjusted ? ADJUSTED_COLUMNS : COLUMNS;
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
        {column.note ? (
          <span className="block text-xs font-normal text-muted-foreground">{column.note}</span>
        ) : null}
      </TableHead>
    );
  }

  function figureCells(row: CompareRow) {
    if (adjusted) {
      if (row.suppressed) {
        return (
          <TableCell colSpan={3} className="whitespace-normal text-xs text-muted-foreground" data-testid="compare-suppressed">
            {adjustedSuppressionNotice(row, definition.adjustment?.minimum_expected)}
          </TableCell>
        );
      }
      return (
        <>
          <TableCell className="text-right font-mono tabular-nums" data-testid="compare-observed-expected">
            {formatCount(row.numerator)} / {formatExpected(row.expected)}
          </TableCell>
          <TableCell className="text-right tabular-nums" data-testid="compare-ratio">
            <span className="font-semibold" data-testid="compare-figure">
              {formatRatio(row.ratio)}
            </span>
            <span
              className="block text-xs text-muted-foreground"
              data-testid="compare-interval"
              title={formatRatioInterval(row.ratio_lower, row.ratio_upper)}
            >
              {formatRatioBounds(row.ratio_lower, row.ratio_upper)}
            </span>
          </TableCell>
          <TableCell className="text-right font-mono tabular-nums" data-testid="compare-pooling">
            {row.pooling_weight === null ? "—" : row.pooling_weight.toFixed(2)}
          </TableCell>
        </>
      );
    }
    if (row.suppressed) {
      return (
        <TableCell colSpan={3} className="whitespace-normal text-xs text-muted-foreground" data-testid="compare-suppressed">
          {suppressionNotice(row)}
        </TableCell>
      );
    }
    return (
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
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border">
      <Table data-testid="compare-table" data-kind={definition.kind}>
        <caption className="sr-only">
          {definition.name} by judge, sorted by {sort} {order}; {rows.length} rows on this page.
        </caption>
        <TableHeader>
          <TableRow>
            {header(columns[0])}
            <TableHead scope="col">Court</TableHead>
            {definition.dimension ? <TableHead scope="col">{dimensionLabel(definition.dimension)}</TableHead> : null}
            {header(columns[1])}
            {header(columns[2])}
            {adjusted ? (
              <TableHead scope="col" className="text-right">
                Pooling weight
              </TableHead>
            ) : (
              <TableHead scope="col">Interval</TableHead>
            )}
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
                data-reason={row.suppression_reason ?? undefined}
                className={highlighted ? "bg-primary/5" : undefined}
              >
                <TableCell>
                  <Link href={`/judges/${row.subject_id}`} className="font-medium text-primary hover:underline">
                    {row.name}
                  </Link>
                  {row.synthetic ? <SyntheticBadge className="ml-2" /> : null}
                  {highlighted ? <span className="ml-2 text-xs text-muted-foreground">(this judge)</span> : null}
                </TableCell>
                <TableCell className="min-w-48 whitespace-normal">
                  <Link href={`/courts/${row.court.id}`} className="text-primary hover:underline">
                    {row.court.canonical_name}
                  </Link>
                </TableCell>
                {definition.dimension ? <TableCell>{dimensionLabel(row.dimension_value)}</TableCell> : null}
                {figureCells(row)}
                <TableCell className="text-right tabular-nums" data-testid="compare-sample">
                  {formatCount(row.eligible_count)}
                  {adjusted && !row.suppressed ? (
                    <span className="block text-xs text-muted-foreground">
                      {formatCount(row.denominator)} in the ratio
                    </span>
                  ) : null}
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
