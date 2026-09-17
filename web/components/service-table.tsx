// web/components/service-table.tsx
// A judge's current and historical service as a sortable TanStack table.
// Sorting is client-side over the rows the page already holds; the header
// buttons expose the sort state through aria-sort.
"use client";

import {
  createColumnHelper,
  createSortedRowModel,
  rowSortingFeature,
  sortFn_text,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { EmptyState } from "@/components/states";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ServiceRecord } from "@/lib/api/client";
import { formatDate, titleCase } from "@/lib/format";

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
});

const helper = createColumnHelper<typeof features, ServiceRecord>();

function metadataString(record: ServiceRecord, key: string): string {
  const value = record.metadata[key];
  return typeof value === "string" ? value : "";
}

const columns = helper.columns([
  helper.accessor((row) => row.court.canonical_name, {
    id: "court",
    header: "Court",
    sortFn: sortFn_text,
    cell: ({ row }) => (
      <Link href={`/courts/${row.original.court.id}`} className="text-primary hover:underline">
        {row.original.court.canonical_name}
      </Link>
    ),
  }),
  helper.accessor((row) => row.court.court_type, {
    id: "court_type",
    header: "Type",
    sortFn: sortFn_text,
    cell: ({ getValue }) => titleCase(getValue()),
  }),
  helper.accessor("position_type", {
    header: "Position",
    sortFn: sortFn_text,
  }),
  helper.accessor("start_date", {
    header: "Start",
    sortFn: sortFn_text,
    sortUndefined: "last",
    cell: ({ getValue }) => <time dateTime={getValue() ?? undefined}>{formatDate(getValue())}</time>,
  }),
  helper.accessor("end_date", {
    header: "End",
    sortFn: sortFn_text,
    sortUndefined: "last",
    cell: ({ getValue, row }) => {
      const value = getValue();
      if (value) return <time dateTime={value}>{formatDate(value)}</time>;
      const termination = metadataString(row.original, "termination");
      return <span className="text-muted-foreground">{termination ? "—" : "Current"}</span>;
    },
  }),
  helper.accessor((row) => metadataString(row, "termination"), {
    id: "termination",
    header: "Termination",
    sortFn: sortFn_text,
    cell: ({ getValue }) => getValue() || <span className="text-muted-foreground">—</span>,
  }),
]);

export function ServiceTable({ records }: { records: ServiceRecord[] }) {
  const data = useMemo(() => records, [records]);
  const table = useTable(
    {
      features,
      columns,
      data,
      initialState: { sorting: [{ id: "start_date", desc: false }] },
    },
    (state) => ({ sorting: state.sorting }),
  );

  if (records.length === 0) {
    return (
      <EmptyState title="No service records">
        The source has no appointment on file for this judge.
      </EmptyState>
    );
  }

  return (
    <div className="overflow-x-auto rounded-xl border">
      <Table data-testid="service-table">
        <caption className="sr-only">
          Service records, sortable by column; {records.length} rows.
        </caption>
        <TableHeader>
          {table.getHeaderGroups().map((group) => (
            <TableRow key={group.id}>
              {group.headers.map((header) => {
                const sorted = header.column.getIsSorted();
                const ariaSort =
                  sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : "none";
                return (
                  <TableHead key={header.id} scope="col" aria-sort={ariaSort}>
                    {header.isPlaceholder ? null : (
                      <button
                        type="button"
                        onClick={header.column.getToggleSortingHandler()}
                        className="inline-flex items-center gap-1 rounded font-medium hover:text-foreground"
                      >
                        <table.FlexRender header={header} />
                        {sorted === "asc" ? (
                          <ArrowUp aria-hidden="true" className="size-3.5" />
                        ) : sorted === "desc" ? (
                          <ArrowDown aria-hidden="true" className="size-3.5" />
                        ) : (
                          <ArrowUpDown aria-hidden="true" className="size-3.5 opacity-50" />
                        )}
                      </button>
                    )}
                  </TableHead>
                );
              })}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id} data-testid="service-row">
              {row.getAllCells().map((cell) => (
                <TableCell key={cell.id}>
                  <table.FlexRender cell={cell} />
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
