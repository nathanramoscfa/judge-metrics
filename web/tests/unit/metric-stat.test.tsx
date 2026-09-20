// web/tests/unit/metric-stat.test.tsx
// The presentation-rule component: every field the brief requires is
// present for a rate, a share, a survival estimate, a median, a count, and
// a distribution value; a suppressed observation renders the notice and
// no digit in its figure region; a not-observable metric renders its
// notice; the methodology link anchors at the slug; the synthetic badge
// follows the flag. Also the panel, the row, and the compare table.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CompareTable } from "@/components/compare-table";
import { CohortPositionLine, MetricPanel, MetricRow } from "@/components/metric-panel";
import { MetricNotObservable, MetricStat } from "@/components/metric-stat";
import { TooltipProvider } from "@/components/ui/tooltip";

import {
  COUNT,
  DEFINITIONS,
  DISTRIBUTION,
  JUDGE_ID,
  MEDIAN,
  RATE,
  SHARE,
  SUPPRESSED,
  SURVIVAL,
  compareRow,
} from "./fixtures/observations";

function stat(testId: string) {
  return within(screen.getByTestId("metric-stat")).getByTestId(testId);
}

describe("MetricStat", () => {
  it("renders every presentation field for a fixed-window rate", () => {
    render(<MetricStat observation={RATE} label="New-case rate, 365 days" />);
    const root = screen.getByTestId("metric-stat");
    expect(root).toHaveAttribute("data-slug", "new_case_rate");
    expect(root).toHaveAttribute("data-window", "365");
    expect(root).toHaveAttribute("data-suppressed", "false");
    expect(stat("metric-label")).toHaveTextContent("New-case rate, 365 days");
    expect(stat("metric-figure")).toHaveTextContent("22.1%");
    expect(stat("metric-fraction")).toHaveTextContent("62 / 281");
    expect(stat("metric-eligible")).toHaveTextContent("353");
    expect(stat("metric-interval")).toHaveTextContent("17.6%–27.3% (95% Wilson interval)");
    expect(stat("metric-sample")).toHaveTextContent("353 eligible, 281 in the denominator");
    expect(stat("metric-period")).toHaveTextContent("Jan 1, 2016 – Dec 31, 2023");
    expect(stat("metric-coverage")).toHaveTextContent("synthetic · Jan 1, 2016 – Dec 31, 2023 · outcome observable");
    expect(stat("methodology-link")).toHaveAttribute("href", "/methodology#new_case_rate");
    expect(stat("synthetic-badge")).toBeInTheDocument();
  });

  it("omits the eligible line when it equals the denominator and shows the Greenwood method", () => {
    render(<MetricStat observation={SURVIVAL} label="New-case cumulative incidence" />);
    expect(stat("metric-figure")).toHaveTextContent("25.1%");
    expect(within(screen.getByTestId("metric-stat")).queryByTestId("metric-eligible")).toBeNull();
    expect(stat("metric-interval")).toHaveTextContent("95% Greenwood interval");
    expect(stat("metric-sample")).toHaveTextContent("353 eligible, 353 in the denominator");
  });

  it("renders a share with its fraction and interval", () => {
    render(<MetricStat observation={SHARE} label="Pretrial release share" />);
    expect(stat("metric-figure")).toHaveTextContent("67.8%");
    expect(stat("metric-fraction")).toHaveTextContent("353 / 521");
    expect(stat("metric-interval")).toHaveTextContent("63.6%–71.6%");
    expect(screen.getByTestId("metric-stat")).toHaveAttribute("data-window", "all");
  });

  it("renders a median as days without an interval", () => {
    render(<MetricStat observation={MEDIAN} label="Median days to disposition" />);
    expect(stat("metric-figure")).toHaveTextContent("150.5 days");
    expect(stat("metric-fraction")).toHaveTextContent("406 / 406");
    expect(within(screen.getByTestId("metric-stat")).queryByTestId("metric-interval")).toBeNull();
    expect(stat("metric-period")).toHaveTextContent("Jan 1, 2016 – Dec 31, 2023");
    expect(stat("methodology-link")).toHaveAttribute("href", "/methodology#median_days_to_disposition");
  });

  it("renders a count as an integer with its sample size and no fraction", () => {
    render(<MetricStat observation={COUNT} label="Eligible cases" />);
    expect(stat("metric-figure")).toHaveTextContent("697");
    expect(within(screen.getByTestId("metric-stat")).queryByTestId("metric-fraction")).toBeNull();
    expect(stat("metric-sample")).toHaveTextContent("697 eligible");
    expect(stat("metric-coverage")).toHaveTextContent("synthetic");
  });

  it("renders one distribution value as its share with the dimension in the label", () => {
    render(<MetricStat observation={DISTRIBUTION} label="Disposition distribution" />);
    expect(stat("metric-label")).toHaveTextContent("Disposition distribution · Dismissed");
    expect(stat("metric-figure")).toHaveTextContent("22.4%");
    expect(stat("metric-fraction")).toHaveTextContent("144 / 644");
    expect(screen.getByTestId("metric-stat")).toHaveAttribute("data-dimension", "dismissed");
  });

  it("renders the suppression notice with the threshold and no digit in the figure region", () => {
    render(<MetricStat observation={SUPPRESSED} label="New-case rate, 365 days" />);
    const root = screen.getByTestId("metric-stat");
    expect(root).toHaveAttribute("data-suppressed", "true");
    const notice = within(root).getByTestId("suppression-notice");
    expect(notice).toHaveTextContent("Suppressed: fewer than 10 eligible members in the denominator");
    // No figure slot exists at all, and no digit appears outside the caller's
    // label, the notice, the period, and the coverage window (the only dated
    // or thresholded text).
    for (const id of ["metric-figures", "metric-figure", "metric-fraction", "metric-eligible", "metric-interval", "metric-sample"]) {
      expect(within(root).queryByTestId(id)).toBeNull();
    }
    const clone = root.cloneNode(true) as HTMLElement;
    for (const id of ["metric-label", "suppression-notice", "metric-period", "metric-coverage"]) {
      clone.querySelector(`[data-testid="${id}"]`)?.remove();
    }
    expect(clone.textContent ?? "").not.toMatch(/\d/);
    expect(within(root).getByTestId("methodology-link")).toHaveAttribute("href", "/methodology#new_case_rate");
  });

  it("falls back to the slug anchor when the API sends no methodology link", () => {
    render(<MetricStat observation={{ ...RATE, methodology_url: "" }} label="x" />);
    expect(stat("methodology-link")).toHaveAttribute("href", "/methodology#new_case_rate");
  });

  it("shows no synthetic badge for a non-synthetic observation", () => {
    render(<MetricStat observation={{ ...RATE, synthetic: false, source: "cook_county" }} label="x" />);
    expect(within(screen.getByTestId("metric-stat")).queryByTestId("synthetic-badge")).toBeNull();
    expect(stat("metric-coverage")).toHaveTextContent("cook_county");
  });
});

describe("MetricNotObservable", () => {
  it("names the source and links the methodology at the slug", () => {
    render(<MetricNotObservable label="Rearrest rate" slug="rearrest_rate" source="synthetic" />);
    const root = screen.getByTestId("metric-stat");
    expect(root).toHaveAttribute("data-observable", "false");
    expect(within(root).getByTestId("not-observable")).toHaveTextContent("Not observable in this source");
    expect(within(root).getByTestId("not-observable")).toHaveTextContent("synthetic");
    expect(within(root).getByTestId("methodology-link")).toHaveAttribute("href", "/methodology#rearrest_rate");
    expect(within(root).queryByTestId("metric-figure")).toBeNull();
  });
});

describe("MetricPanel and MetricRow", () => {
  it("anchors the section, links the eligible cases, and places the court value beside the judge's", () => {
    render(
      <MetricPanel id="pretrial" title="Pretrial" casesHref={`/judges/${JUDGE_ID}/cases`}>
        <MetricRow
          label="Pretrial release share"
          judge={SHARE}
          court={{ ...SHARE, subject_type: "court", numerator: 700, denominator: 1000, rate: 0.7 }}
          comparison={
            <CohortPositionLine
              position={{ judges: 3, published: 3, median: 0.65, rank: 1 }}
              cohort="court"
              kind="share"
              compareHref="/compare?metric=pretrial_release_share&court_id=c"
            />
          }
        />
      </MetricPanel>,
    );
    const panel = screen.getByTestId("metric-panel");
    expect(panel).toHaveAttribute("id", "pretrial");
    expect(within(panel).getByRole("heading", { name: "Pretrial" })).toBeInTheDocument();
    expect(within(panel).getByTestId("eligible-cases-link")).toHaveAttribute("href", `/judges/${JUDGE_ID}/cases`);
    const stats = within(panel).getAllByTestId("metric-stat");
    expect(stats).toHaveLength(2);
    expect(stats[0]).toHaveAttribute("data-variant", "default");
    expect(stats[1]).toHaveAttribute("data-variant", "compact");
    expect(within(stats[1]).getByTestId("metric-label")).toHaveTextContent("court, pooled");
    expect(within(stats[1]).getByTestId("metric-figure")).toHaveTextContent("70.0%");
    const position = within(stats[0]).getByTestId("cohort-position");
    expect(position).toHaveTextContent("Same court, same period");
    expect(position).toHaveTextContent("3 in the cohort, 3 with a published figure");
    expect(within(position).getByTestId("cohort-median")).toHaveTextContent("65.0%");
    expect(within(position).getByTestId("cohort-rank")).toHaveTextContent("1 of 3, highest first");
    expect(within(position).getByTestId("compare-link")).toHaveAttribute("href", "/compare?metric=pretrial_release_share&court_id=c");
  });

  it("says when no pooled value exists and formats a median cohort in days", () => {
    render(
      <MetricRow
        label="Median days"
        judge={MEDIAN}
        court={null}
        comparison={
          <CohortPositionLine
            position={{ judges: 2, published: 1, median: 120, rank: null }}
            cohort="jurisdiction"
            kind="median"
            compareHref="/compare?metric=median_days_to_disposition&jurisdiction_id=j"
          />
        }
      />,
    );
    expect(screen.getByTestId("pooled-missing")).toBeInTheDocument();
    expect(screen.getByTestId("cohort-median")).toHaveTextContent("120 days");
    expect(screen.getByTestId("cohort-rank")).toHaveTextContent("not ranked");
    expect(screen.getByTestId("cohort-position")).toHaveTextContent("Jurisdiction, same period");
  });
});

describe("CompareTable", () => {
  const definition = DEFINITIONS.find((d) => d.slug === "new_case_rate")!;
  const rows = [
    compareRow(),
    compareRow({ subject_id: "b", name: "Moonstone Pistachio", observation_id: "o2", rate: 0.205357, numerator: 46, denominator: 224, eligible_count: 289, coverage_warning: "period differs from the cohort's reference period" }),
    compareRow({ subject_id: "c", name: "Small Cohort", observation_id: "o3", rate: null, numerator: null, denominator: null, lower: null, upper: null, suppressed: true, eligible_count: 4 }),
  ];

  it("renders every row with its fraction, figure, interval, sample size, warning, and suppression", () => {
    render(
      <TooltipProvider>
        <CompareTable rows={rows} definition={definition} sort="rate" order="desc" hrefFor={(s, o) => `/compare?sort=${s}&order=${o}`} highlightJudgeId={JUDGE_ID} />
      </TooltipProvider>,
    );
    const table = screen.getByTestId("compare-table");
    const rendered = within(table).getAllByTestId("compare-row");
    expect(rendered).toHaveLength(3);
    expect(rendered[0]).toHaveAttribute("data-judge", JUDGE_ID);
    expect(rendered[0]).toHaveTextContent("(this judge)");
    expect(within(rendered[0]).getByTestId("compare-fraction")).toHaveTextContent("62 / 281");
    expect(within(rendered[0]).getByTestId("compare-figure")).toHaveTextContent("22.1%");
    expect(within(rendered[0]).getByTestId("compare-interval")).toHaveTextContent("17.6%–27.3%");
    expect(within(rendered[0]).getByTestId("compare-sample")).toHaveTextContent("353");
    expect(within(rendered[0]).queryByTestId("compare-warning")).toBeNull();
    expect(within(rendered[1]).getByTestId("compare-warning")).toHaveTextContent("period differs");
    expect(rendered[2]).toHaveAttribute("data-suppressed", "true");
    expect(within(rendered[2]).getByTestId("compare-suppressed")).toHaveTextContent("Suppressed: fewer than 10");
    expect(within(rendered[2]).queryByTestId("compare-figure")).toBeNull();
    expect(within(rendered[2]).getByTestId("compare-sample")).toHaveTextContent("4");
    // The sortable headers expose the state and flip the order of the active column.
    expect(within(table).getByTestId("sort-rate").closest("th")).toHaveAttribute("aria-sort", "descending");
    expect(within(table).getByTestId("sort-rate")).toHaveAttribute("href", "/compare?sort=rate&order=asc");
    expect(within(table).getByTestId("sort-name")).toHaveAttribute("href", "/compare?sort=name&order=desc");
    expect(within(table).getByTestId("sort-numerator").closest("th")).toHaveAttribute("aria-sort", "none");
  });

  it("sorts a median by value and shows the dimension column for a dimensioned metric", () => {
    const median = { ...DEFINITIONS[0], slug: "m", name: "Median x", kind: "median" as const, dimension: "offense_category" };
    render(
      <TooltipProvider>
        <CompareTable rows={[compareRow({ rate: null, value: 300, dimension_value: "drug" })]} definition={median} sort="value" order="asc" hrefFor={(s, o) => `${s}:${o}`} />
      </TooltipProvider>,
    );
    expect(screen.getByTestId("compare-figure")).toHaveTextContent("300 days");
    expect(screen.getByTestId("sort-value").closest("th")).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getByTestId("sort-value")).toHaveAttribute("href", "value:desc");
    expect(screen.getByRole("columnheader", { name: "Offense Category" })).toBeInTheDocument();
    expect(screen.getByTestId("compare-row")).toHaveTextContent("Drug");
  });
});
