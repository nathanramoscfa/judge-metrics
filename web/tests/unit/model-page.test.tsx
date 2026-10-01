// web/tests/unit/model-page.test.tsx
// The model card page rendered from a stubbed GET /api/v1/models/{id}: the
// target, window, status, and synthetic badge; the training counts and range;
// the validation summary with the calibration bins as a table; the
// coefficient table with a court level linked to its page; the versions; and
// the links to the methodology's adjusted statistics section and the
// validation report's section of the model. An unfitted model says so
// without tables; a 404 is the not-found page; another failure is the error
// state.
import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ModelPage from "@/app/models/[modelId]/page";

import { COURT_ID, MODEL_CARD, MODEL_ID } from "./fixtures/observations";

const fetchMock = vi.fn<typeof fetch>();
const notFound = vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
});

vi.mock("next/navigation", () => ({ notFound: () => notFound() }));

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

async function renderPage(modelId = MODEL_ID) {
  render(await ModelPage({ params: Promise.resolve({ modelId }) }));
}

beforeEach(() => {
  fetchMock.mockReset();
  notFound.mockClear();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ModelPage", () => {
  it("renders the card's header, training, validation, calibration bins, coefficients, and links", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(MODEL_CARD));
    await renderPage();
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.url).toContain(`/api/v1/models/${MODEL_ID}`);

    expect(screen.getByTestId("model-target")).toHaveTextContent("New Case, 365 days");
    expect(screen.getByTestId("model-status")).toHaveAttribute("data-status", "fitted");
    expect(screen.getByTestId("model-status")).toHaveTextContent("Fitted");
    expect(screen.getAllByTestId("synthetic-badge").length).toBeGreaterThan(0);

    expect(screen.getByTestId("model-index-events")).toHaveTextContent("4,534");
    expect(screen.getByTestId("model-events")).toHaveTextContent("702");
    expect(screen.getByTestId("model-range")).toHaveTextContent("2016");
    expect(screen.getByTestId("model-version")).toHaveTextContent("expected-logit-v1");
    expect(screen.getByTestId("model-spec-version")).toHaveTextContent("1");
    expect(screen.getByTestId("model-hash")).toHaveAttribute("title", MODEL_CARD.content_hash);

    const summary = screen.getByTestId("model-summary");
    expect(summary).toHaveTextContent("Brier score0.1187");
    expect(summary).toHaveTextContent("AUC0.6604");
    expect(summary).toHaveTextContent("Calibration slope0.9481");
    const bins = within(screen.getByTestId("calibration-table")).getAllByTestId("calibration-bin");
    expect(bins).toHaveLength(10);
    expect(bins[0]).toHaveTextContent("113");
    expect(bins[0]).toHaveTextContent("5.0%");

    const coefficients = within(screen.getByTestId("coefficient-table")).getAllByTestId("coefficient-row");
    expect(coefficients).toHaveLength(3);
    expect(coefficients[0]).toHaveTextContent("Intercept");
    expect(coefficients[0]).toHaveTextContent("-1.912");
    expect(coefficients[1]).toHaveTextContent("lead severity");
    expect(coefficients[1]).toHaveTextContent("felony 1");
    expect(coefficients[1]).toHaveTextContent("0.093");
    expect(coefficients[1]).toHaveTextContent("100%");
    expect(within(coefficients[2]).getAllByRole("link")[0]).toHaveAttribute("href", `/courts/${COURT_ID}`);

    expect(screen.getByTestId("model-methodology-link")).toHaveAttribute("href", "/methodology#adjusted-statistics");
    expect(screen.getByTestId("model-validation-link").getAttribute("href")).toMatch(
      /docs\/VALIDATION\.md#synthetic-new_case-365-days$/,
    );
  });

  it("says an unfitted model has no bins or coefficients", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        ...MODEL_CARD,
        status: "insufficient_events",
        window_days: null,
        target: "pretrial_release",
        validation: { ...MODEL_CARD.validation, bins: [], brier: null, auc: null },
        coefficients: [],
      }),
    );
    await renderPage();
    expect(screen.getByTestId("model-status")).toHaveTextContent("Not fitted");
    expect(screen.getByTestId("model-target")).toHaveTextContent("Pretrial Release");
    expect(screen.getByTestId("model-no-bins")).toBeInTheDocument();
    expect(screen.getByTestId("model-no-coefficients")).toBeInTheDocument();
    expect(screen.queryByTestId("calibration-table")).toBeNull();
    expect(screen.getByTestId("model-summary")).toHaveTextContent("Brier score—");
    expect(screen.getByTestId("model-validation-link").getAttribute("href")).toMatch(/#synthetic-pretrial_release$/);
  });

  it("is the not-found page for an unknown or malformed id and an error state otherwise", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ code: "not_found", message: "model not found", request_id: "r" }, { status: 404 }),
    );
    await expect(renderPage()).rejects.toThrow("NEXT_NOT_FOUND");
    await expect(renderPage("not-a-uuid")).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalledTimes(2);
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));
    await renderPage();
    expect(screen.getByTestId("error-state")).toHaveTextContent("Could not load this model");
  });
});
