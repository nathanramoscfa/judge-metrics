// web/tests/unit/methodology-page.test.tsx
// The methodology page rendered from a stubbed GET /api/v1/metrics: the
// association statement and its test id are unchanged, every definition
// has a section anchored at its slug with its formula, every known
// limitation is present verbatim, the prose sections are the API's text,
// and a failed registry fetch renders the error state while the statement
// and principles still render.
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MethodologyPage from "@/app/methodology/page";
import { ASSOCIATION_STATEMENT, KIND_TEXT } from "@/lib/metrics";

import { KNOWN_LIMITATIONS, REGISTRY } from "./fixtures/observations";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("MethodologyPage", () => {
  it("renders the statement, one anchored section per definition, and the limitations verbatim", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REGISTRY));
    render(await MethodologyPage());

    expect(screen.getByTestId("association-statement")).toHaveTextContent(ASSOCIATION_STATEMENT);
    expect(screen.getByTestId("association-statement").textContent).toBe(ASSOCIATION_STATEMENT);
    expect(within(screen.getByTestId("principles")).getAllByRole("listitem")).toHaveLength(10);

    const sections = screen.getAllByTestId("metric-definition");
    expect(sections.map((section) => section.getAttribute("id"))).toEqual(REGISTRY.definitions.map((d) => d.slug));
    for (const definition of REGISTRY.definitions) {
      const section = document.getElementById(definition.slug);
      expect(section, definition.slug).not.toBeNull();
      const scope = within(section as HTMLElement);
      expect(scope.getByRole("heading", { name: definition.name })).toBeInTheDocument();
      expect(scope.getByTestId("definition-formula")).toHaveTextContent(definition.numerator);
      expect(scope.getByTestId("definition-formula")).toHaveTextContent(definition.denominator);
      expect(section).toHaveTextContent(`version ${definition.version}`);
      expect(section).toHaveTextContent(definition.eligibility);
      expect(section).toHaveTextContent(`unit: ${definition.unit}`);
      expect(section).toHaveTextContent(`subjects: ${definition.subject_types.join(", ")}`);
    }
    // The windowed definition states its windows and the attribution gate in words.
    const rate = document.getElementById("new_case_rate") as HTMLElement;
    expect(rate).toHaveTextContent("windows 30, 90, 180, 365, 730, 1095 days");
    expect(rate).toHaveTextContent("gate: the deciding judge (the decision's judge is the subject)");
    expect(rate).toHaveTextContent("10 (suppressed below this denominator)");
    expect(document.getElementById("eligible_cases")).toHaveTextContent("0 (never suppressed: a count)");

    const limitations = within(screen.getByTestId("known-limitations")).getAllByRole("listitem");
    expect(limitations.map((item) => item.textContent)).toEqual(KNOWN_LIMITATIONS);
    expect(limitations).toHaveLength(8);

    // The prose sections are the API's text, rendered as text nodes.
    expect(screen.getByTestId("how-to-read")).toHaveTextContent("Numerator");
    expect(screen.getByTestId("semantics")).toHaveTextContent("Index events. An index event is one person");
    expect(screen.getByTestId("attribution-notes")).toHaveTextContent(REGISTRY.attribution_notes[0]);
    expect(screen.getByTestId("suppression-rule")).toHaveTextContent(REGISTRY.suppression.rule);
    expect(screen.getByTestId("changelog")).toHaveTextContent("0.1");
    expect(screen.getByRole("heading", { name: "Index events, exposure, and censoring" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "How to read a number" })).toBeInTheDocument();
    expect(screen.queryByTestId("metrics-note")).toBeNull();
    expect(screen.getByRole("link", { name: "docs/METHODOLOGY.md" })).toBeInTheDocument();
  });

  it("renders the adjustment block in an anchored section and the adjusted definitions by kind", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(REGISTRY));
    render(await MethodologyPage());
    const section = document.getElementById("adjusted-statistics") as HTMLElement;
    expect(section).not.toBeNull();
    expect(section).toHaveAttribute("data-testid", "adjusted-statistics");
    const scope = within(section);
    expect(scope.getByRole("heading", { name: "Adjusted statistics" })).toBeInTheDocument();
    const adjustment = REGISTRY.adjustment;
    expect(section).toHaveTextContent(`Outcome model specification ${adjustment.specification_version}`);
    expect(section).toHaveTextContent(adjustment.model_version);
    expect(scope.getByTestId("adjustment-interpretation").textContent).toBe(adjustment.interpretation);
    expect(scope.getByTestId("adjustment-pooling")).toHaveTextContent(adjustment.pooling);
    expect(scope.getByTestId("adjustment-interval")).toHaveTextContent(adjustment.interval);
    expect(scope.getByTestId("adjustment-targets")).toHaveTextContent("pretrial_release");
    const features = within(scope.getByTestId("adjustment-features")).getAllByRole("row");
    expect(features).toHaveLength(adjustment.features.length + 1);
    expect(features[1]).toHaveTextContent(adjustment.features[0].leakage);
    expect(scope.getByTestId("adjustment-exclusions")).toHaveTextContent("judge");
    expect(scope.getByTestId("adjustment-thresholds")).toHaveTextContent("Cohort");
    expect(scope.getByTestId("adjustment-controls")).toHaveTextContent("Temporal");
    expect(within(scope.getByTestId("adjustment-limitations")).getAllByRole("listitem")).toHaveLength(
      adjustment.limitations.length,
    );
    expect(scope.getByTestId("validation-link").getAttribute("href")).toMatch(/docs\/VALIDATION\.md$/);
    // Each adjusted definition is described through KIND_TEXT with its adjustment.
    const ratio = document.getElementById("new_case_observed_expected") as HTMLElement;
    expect(ratio).toHaveTextContent(KIND_TEXT.observed_expected);
    expect(ratio).toHaveTextContent("unit: ratio");
    expect(within(ratio).getByTestId("definition-adjustment")).toHaveTextContent(
      "model target new_case; withheld below 5 expected events",
    );
    expect(ratio).toHaveTextContent("30 (suppressed below this many members in the ratio, below 5 expected events");
    expect(within(ratio).getByRole("link", { name: "adjusted statistics" })).toHaveAttribute(
      "href",
      "#adjusted-statistics",
    );
  });

  it("keeps the statement and renders the error state when the registry fetch fails", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    render(await MethodologyPage());
    expect(screen.getByTestId("association-statement")).toHaveTextContent(ASSOCIATION_STATEMENT);
    expect(screen.getByTestId("error-state")).toHaveTextContent("Could not load the metric registry");
    expect(screen.queryByTestId("known-limitations")).toBeNull();
  });
});
