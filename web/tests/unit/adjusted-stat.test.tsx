// web/tests/unit/adjusted-stat.test.tsx
// The presentation-rule component of an adjusted statistic: a published
// observed-to-expected ratio shows every field the brief requires —
// observed and expected events, the pooled ratio with its 95% bootstrap
// interval and method, the pooling weight in words, the cohort size and the
// eligible count, the period, the coverage, the cohort definition, the model
// link, the methodology version as visible text, and the brief's
// interpretation — and a suppressed one shows its reason in words and no
// digit in a figure region, for each of the three suppression reasons.
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AdjustedStat } from "@/components/adjusted-stat";

import { ADJUSTED, MODEL_ID, REGISTRY, suppressedAdjusted } from "./fixtures/observations";

const INTERPRETATION = REGISTRY.adjustment.interpretation;
const COHORT =
  "Expected counts from model expected-logit-v1, specification 1, fitted on 4,534 events of synthetic (Jan 1, 2016 – Dec 31, 2023), adjusting for lead severity; compared within Same court, same period (Jan 1, 2016 – Dec 31, 2023).";

function field(testId: string) {
  return within(screen.getByTestId("adjusted-stat")).getByTestId(testId);
}

describe("AdjustedStat", () => {
  it("renders every presentation field for a published ratio", () => {
    render(
      <AdjustedStat
        observation={ADJUSTED}
        label="New cases after pretrial release, observed to expected, 365 days"
        interpretation={INTERPRETATION}
        minimumExpected={5}
        cohortDefinition={COHORT}
      />,
    );
    const root = screen.getByTestId("adjusted-stat");
    expect(root).toHaveAttribute("data-slug", "new_case_observed_expected");
    expect(root).toHaveAttribute("data-window", "365");
    expect(root).toHaveAttribute("data-suppressed", "false");
    expect(root).not.toHaveAttribute("data-reason");
    expect(field("adjusted-label")).toHaveTextContent("observed to expected, 365 days");
    expect(field("synthetic-badge")).toBeInTheDocument();
    // Observed and expected events, the ratio, its interval and method.
    expect(field("adjusted-observed")).toHaveTextContent("304");
    expect(field("adjusted-expected")).toHaveTextContent("276.4");
    expect(field("adjusted-ratio")).toHaveTextContent("1.10");
    expect(field("adjusted-interval")).toHaveTextContent("0.99–1.21 (95% bootstrap interval)");
    expect(field("adjusted-pooling")).toHaveTextContent(
      "estimate pooled toward 1.0; this judge's own data carries weight 0.62",
    );
    // The cohort size and the eligible count.
    expect(field("adjusted-sample")).toHaveTextContent("2,391 eligible, 2,140 in the ratio");
    expect(field("adjusted-period")).toHaveTextContent("Jan 1, 2016 – Dec 31, 2023");
    expect(field("adjusted-coverage")).toHaveTextContent(
      "synthetic · Jan 1, 2016 – Dec 31, 2023 · outcome observable",
    );
    expect(field("adjusted-cohort")).toHaveTextContent(COHORT);
    // The model link and the methodology version as visible text.
    expect(field("adjusted-model")).toHaveAttribute("href", `/models/${MODEL_ID}`);
    expect(field("adjusted-model")).toHaveTextContent("Model expected-logit-v1 (specification 1)");
    expect(field("methodology-link")).toHaveAttribute("href", "/methodology#new_case_observed_expected");
    expect(field("methodology-version")).toHaveTextContent("Methodology 1.0");
    expect(field("methodology-version")).toBeVisible();
    // The brief's interpretation beside the figures; no causal claim.
    expect(field("adjusted-interpretation")).toHaveTextContent(INTERPRETATION);
    expect(root.textContent ?? "").not.toMatch(/\bcaus(e|ed|es)\b/i);
  });

  it.each([
    ["below_threshold", "fewer than 30 followed members in the ratio"],
    ["expected_below_minimum", "fewer than 5 expected events"],
    ["model_unavailable", "the expected-outcome model could not be fitted for this window"],
  ] as const)("renders the reason and no digit in the figure region for %s", (reason, words) => {
    render(
      <AdjustedStat
        observation={suppressedAdjusted(reason)}
        label="New cases after pretrial release, observed to expected"
        interpretation={INTERPRETATION}
        minimumExpected={5}
      />,
    );
    const root = screen.getByTestId("adjusted-stat");
    expect(root).toHaveAttribute("data-suppressed", "true");
    expect(root).toHaveAttribute("data-reason", reason);
    expect(within(root).getByTestId("adjusted-suppression")).toHaveTextContent(words);
    // No figure region and no figure slot at all.
    for (const id of [
      "adjusted-figures",
      "adjusted-ratio",
      "adjusted-observed",
      "adjusted-expected",
      "adjusted-interval",
      "adjusted-pooling",
      "adjusted-sample",
      "adjusted-interpretation",
    ]) {
      expect(within(root).queryByTestId(id)).toBeNull();
    }
    // No digit outside the label, the reason, the period, the coverage, the
    // model reference, and the methodology version (the only numbered text).
    const clone = root.cloneNode(true) as HTMLElement;
    for (const id of [
      "adjusted-label",
      "adjusted-suppression",
      "adjusted-period",
      "adjusted-coverage",
      "adjusted-model",
      "methodology-link",
    ]) {
      clone.querySelector(`[data-testid="${id}"]`)?.remove();
    }
    expect(clone.textContent ?? "").not.toMatch(/\d/);
    // The model and the methodology survive suppression.
    expect(within(root).getByTestId("adjusted-model")).toHaveAttribute("href", `/models/${MODEL_ID}`);
    expect(within(root).getByTestId("methodology-version")).toHaveTextContent("Methodology 1.0");
  });

  it("omits the model link when the observation cites none", () => {
    render(<AdjustedStat observation={{ ...ADJUSTED, model: null }} label="x" interpretation={INTERPRETATION} />);
    expect(within(screen.getByTestId("adjusted-stat")).queryByTestId("adjusted-model")).toBeNull();
    expect(within(screen.getByTestId("adjusted-stat")).queryByTestId("adjusted-cohort")).toBeNull();
  });
});
