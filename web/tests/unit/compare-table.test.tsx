// web/tests/unit/compare-table.test.tsx
// The compare table of an adjusted metric (Phase 4 Step 5): the columns
// Judge, Court, Observed / expected, O/E (pooled) with its bootstrap
// interval, Pooling weight, Sample size, and Coverage; the `ratio` sort on
// the O/E header; and a suppressed adjusted row that spans the figure
// columns with its reason in words and no figure. The descriptive table is
// covered in metric-stat.test.tsx.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CompareTable } from "@/components/compare-table";
import { TooltipProvider } from "@/components/ui/tooltip";

import { ADJUSTED_DEFINITION, JUDGE_ID, adjustedRow } from "./fixtures/observations";

const ROWS = [
  adjustedRow(),
  adjustedRow({ subject_id: "b", name: "Moonstone Pistachio", observation_id: "o2", ratio: 0.8812, ratio_lower: 0.7, ratio_upper: 1.05, pooling_weight: 0.41 }),
  adjustedRow({
    subject_id: "c",
    name: "Small Cohort",
    observation_id: "o3",
    numerator: null,
    denominator: null,
    rate: null,
    expected: null,
    expected_rate: null,
    ratio: null,
    ratio_lower: null,
    ratio_upper: null,
    pooling_weight: null,
    suppressed: true,
    suppression_reason: "expected_below_minimum",
    eligible_count: 41,
  }),
];

function renderTable(sort: "ratio" | "name" = "ratio", order: "asc" | "desc" = "desc") {
  render(
    <TooltipProvider>
      <CompareTable
        rows={ROWS}
        definition={ADJUSTED_DEFINITION}
        sort={sort}
        order={order}
        hrefFor={(s, o) => `/compare?sort=${s}&order=${o}`}
        highlightJudgeId={JUDGE_ID}
      />
    </TooltipProvider>,
  );
  return screen.getByTestId("compare-table");
}

describe("CompareTable (adjusted)", () => {
  it("shows the adjusted columns in order", () => {
    const table = renderTable();
    expect(table).toHaveAttribute("data-kind", "observed_expected");
    const headers = within(table).getAllByRole("columnheader").map((cell) => cell.textContent?.trim());
    expect(headers).toEqual([
      "Judge",
      "Court",
      "Observed / expected",
      "O/E (pooled)[95% bootstrap interval]",
      "Pooling weight",
      "Sample size",
      "Coverage",
    ]);
  });

  it("renders observed over expected, the pooled ratio with its interval, the weight, and the sample size", () => {
    const table = renderTable();
    const rows = within(table).getAllByTestId("compare-row");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("(this judge)");
    expect(within(rows[0]).getByTestId("compare-observed-expected")).toHaveTextContent("304 / 276.4");
    expect(within(rows[0]).getByTestId("compare-figure")).toHaveTextContent("1.10");
    expect(within(rows[0]).getByTestId("compare-interval")).toHaveTextContent("[0.99–1.21]");
    expect(within(rows[0]).getByTestId("compare-interval")).toHaveAttribute(
      "title",
      "0.99–1.21 (95% bootstrap interval)",
    );
    expect(within(rows[0]).getByTestId("compare-pooling")).toHaveTextContent("0.62");
    expect(within(rows[0]).getByTestId("compare-sample")).toHaveTextContent("2,391");
    expect(within(rows[0]).getByTestId("compare-sample")).toHaveTextContent("2,140 in the ratio");
    expect(within(rows[1]).getByTestId("compare-figure")).toHaveTextContent("0.88");
    expect(within(rows[0]).getByTestId("compare-period")).toHaveTextContent("Jan 1, 2016 – Dec 31, 2023");
  });

  it("sorts by ratio on the O/E header and flips the order of the active column", () => {
    const table = renderTable("ratio", "desc");
    expect(within(table).getByTestId("sort-ratio").closest("th")).toHaveAttribute("aria-sort", "descending");
    expect(within(table).getByTestId("sort-ratio")).toHaveAttribute("href", "/compare?sort=ratio&order=asc");
    expect(within(table).getByTestId("sort-numerator").closest("th")).toHaveAttribute("aria-sort", "none");
    expect(within(table).queryByTestId("sort-rate")).toBeNull();
  });

  it("spans the figure columns of a suppressed adjusted row with its reason and no figure", () => {
    const table = renderTable("name", "asc");
    const suppressed = within(table).getAllByTestId("compare-row")[2];
    expect(suppressed).toHaveAttribute("data-suppressed", "true");
    expect(suppressed).toHaveAttribute("data-reason", "expected_below_minimum");
    const cell = within(suppressed).getByTestId("compare-suppressed");
    expect(cell).toHaveAttribute("colspan", "3");
    expect(cell).toHaveTextContent("fewer than 5 expected events");
    for (const id of ["compare-observed-expected", "compare-figure", "compare-interval", "compare-pooling"]) {
      expect(within(suppressed).queryByTestId(id)).toBeNull();
    }
    expect(within(suppressed).getByTestId("compare-sample")).toHaveTextContent(/^41$/);
  });
});
