// web/tests/unit/client.test.ts
// The typed client helpers against a mocked fetch: request shape (path,
// query encoding), the success envelope, the API error envelope, 429 with
// Retry-After, a non-JSON upstream error, and a transport failure.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  API_BASE_URL,
  compareMetrics,
  getCase,
  getCaseTimeline,
  getCourt,
  getCourtMetrics,
  getCoverage,
  getJudge,
  getJudgeCases,
  getJudgeMetrics,
  getObservationProvenance,
  getRegistry,
  listJudges,
  listJurisdictions,
  search,
  submitCorrection,
} from "@/lib/api/client";

const JUDGE_ID = "3a221440-e710-4f65-b5b9-215b52a17d08";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
    ...init,
  });
}

const fetchMock = vi.fn<typeof fetch>();

function lastRequestUrl(): URL {
  const input = fetchMock.mock.calls.at(-1)?.[0];
  if (input instanceof Request) return new URL(input.url);
  return new URL(String(input));
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("API_BASE_URL", () => {
  it("defaults to the local API", () => {
    expect(API_BASE_URL).toBe("http://localhost:8000");
  });
});

describe("getJudge", () => {
  it("returns the judge on 200", async () => {
    const judge = { id: JUDGE_ID, canonical_name: "Sonia Sotomayor", status: "active" };
    fetchMock.mockResolvedValueOnce(jsonResponse(judge));

    const result = await getJudge(JUDGE_ID);

    expect(result.ok).toBe(true);
    expect(result.data?.canonical_name).toBe("Sonia Sotomayor");
    const url = lastRequestUrl();
    expect(url.origin).toBe("http://localhost:8000");
    expect(url.pathname).toBe(`/api/v1/judges/${JUDGE_ID}`);
  });

  it("returns the API error envelope on 404", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { code: "not_found", message: "judge not found", request_id: "req-1" },
        { status: 404 },
      ),
    );

    const result = await getJudge(JUDGE_ID);

    expect(result.ok).toBe(false);
    expect(result.error).toMatchObject({
      status: 404,
      code: "not_found",
      message: "judge not found",
      requestId: "req-1",
      retryAfterSeconds: null,
    });
  });

  it("describes a non-JSON upstream failure without throwing", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("<html>Bad Gateway</html>", {
        status: 502,
        statusText: "Bad Gateway",
        headers: { "content-type": "text/html", "x-request-id": "edge-7" },
      }),
    );

    const result = await getJudge(JUDGE_ID);

    expect(result.ok).toBe(false);
    expect(result.error?.status).toBe(502);
    expect(result.error?.code).toBe("http_error");
    expect(result.error?.requestId).toBe("edge-7");
  });

  it("reports a transport failure as status 0", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("fetch failed"));

    const result = await getJudge(JUDGE_ID);

    expect(result.ok).toBe(false);
    expect(result.error?.status).toBe(0);
    expect(result.error?.code).toBe("network_error");
    expect(result.error?.message).toContain("http://localhost:8000");
  });
});

describe("listJudges", () => {
  it("serializes only the filters that are set", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], total: 0, limit: 50, offset: 0, next_offset: null }),
    );

    const result = await listJudges({
      court_id: "d8d5d586-9a10-4361-aeff-67db049e6701",
      active_on: "2010-01-01",
      limit: 50,
      q: undefined,
    });

    expect(result.ok).toBe(true);
    const url = lastRequestUrl();
    expect(url.pathname).toBe("/api/v1/judges");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      court_id: "d8d5d586-9a10-4361-aeff-67db049e6701",
      active_on: "2010-01-01",
      limit: "50",
    });
  });
});

describe("getCourt and listJurisdictions", () => {
  it("call the court and jurisdiction routes", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ id: "c1", canonical_name: "Supreme Court" }))
      .mockResolvedValueOnce(
        jsonResponse({ items: [{ name: "US" }], total: 1, limit: 25, offset: 0, next_offset: null }),
      );

    const court = await getCourt("c1");
    expect(court.ok).toBe(true);
    expect(lastRequestUrl().pathname).toBe("/api/v1/courts/c1");

    const jurisdictions = await listJurisdictions();
    expect(jurisdictions.ok).toBe(true);
    expect(jurisdictions.data?.total).toBe(1);
    expect(lastRequestUrl().pathname).toBe("/api/v1/jurisdictions");
  });
});

describe("search", () => {
  it("encodes the query and default limit", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ query: "o'brien", limit: 25, items: [] }));

    const result = await search("O'Brien & co");

    expect(result.ok).toBe(true);
    const url = lastRequestUrl();
    expect(url.pathname).toBe("/api/v1/search");
    expect(url.searchParams.get("q")).toBe("O'Brien & co");
    expect(url.searchParams.get("limit")).toBe("25");
  });

  it("surfaces Retry-After on 429", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { code: "rate_limited", message: "slow down", request_id: "req-9" },
        { status: 429, headers: { "content-type": "application/json", "retry-after": "7" } },
      ),
    );

    const result = await search("x");

    expect(result.ok).toBe(false);
    expect(result.error?.code).toBe("rate_limited");
    expect(result.error?.retryAfterSeconds).toBe(7);
  });
});

describe("cases, judge cases, and coverage", () => {
  const CASE_ID = "cf20b745-230e-461f-afd6-9d5fa882fa26";

  it("fetches a case and its timeline by id", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ id: CASE_ID, case_number: "SYN-2020-000005" }))
      .mockResolvedValueOnce(jsonResponse({ case_id: CASE_ID, synthetic: true, entries: [] }));

    const detail = await getCase(CASE_ID);
    expect(detail.ok).toBe(true);
    expect(detail.data?.case_number).toBe("SYN-2020-000005");
    expect(lastRequestUrl().pathname).toBe(`/api/v1/cases/${CASE_ID}`);

    const timeline = await getCaseTimeline(CASE_ID);
    expect(timeline.ok).toBe(true);
    expect(timeline.data?.entries).toEqual([]);
    expect(lastRequestUrl().pathname).toBe(`/api/v1/cases/${CASE_ID}/timeline`);
  });

  it("passes only the case filters that are set", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], total: 0, limit: 25, offset: 0, next_offset: null }),
    );

    const result = await getJudgeCases(JUDGE_ID, {
      filed_from: "2020-01-01",
      status: "closed",
      limit: 25,
      offset: 0,
      filed_to: undefined,
    });

    expect(result.ok).toBe(true);
    const url = lastRequestUrl();
    expect(url.pathname).toBe(`/api/v1/judges/${JUDGE_ID}/cases`);
    expect(Object.fromEntries(url.searchParams)).toEqual({
      filed_from: "2020-01-01",
      status: "closed",
      limit: "25",
      offset: "0",
    });
  });

  it("returns the inverted-range 422 as an error", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          code: "validation_error",
          message: "filed_to: must not be earlier than filed_from",
          request_id: "req-3",
        },
        { status: 422 },
      ),
    );
    const result = await getJudgeCases(JUDGE_ID, { filed_from: "2021-01-01", filed_to: "2020-01-01" });
    expect(result.ok).toBe(false);
    expect(result.error?.code).toBe("validation_error");
    expect(result.error?.message).toContain("filed_to");
  });

  it("fetches coverage without parameters", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ sources: [], synthetic_present: false, generated_at: "2026-09-18T00:00:00Z" }),
    );
    const result = await getCoverage();
    expect(result.ok).toBe(true);
    expect(result.data?.synthetic_present).toBe(false);
    const url = lastRequestUrl();
    expect(url.pathname).toBe("/api/v1/coverage");
    expect(url.search).toBe("");
  });
});

describe("metrics, compare, provenance, and corrections", () => {
  const OBSERVATION_ID = "a580e920-1da4-4dd1-942d-4b4d1a526dcc";

  it("fetches the registry and a subject's metrics", async () => {
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({ registry_version: 1, methodology_version: "0.1", definitions: [] }),
      )
      .mockResolvedValueOnce(jsonResponse({ total: 0, observations: {} }))
      .mockResolvedValueOnce(jsonResponse({ total: 0, observations: {} }));

    const registry = await getRegistry();
    expect(registry.ok).toBe(true);
    expect(registry.data?.methodology_version).toBe("0.1");
    expect(lastRequestUrl().pathname).toBe("/api/v1/metrics");

    const judge = await getJudgeMetrics(JUDGE_ID);
    expect(judge.ok).toBe(true);
    expect(lastRequestUrl().pathname).toBe(`/api/v1/judges/${JUDGE_ID}/metrics`);

    const court = await getCourtMetrics(JUDGE_ID);
    expect(court.ok).toBe(true);
    expect(lastRequestUrl().pathname).toBe(`/api/v1/courts/${JUDGE_ID}/metrics`);
  });

  it("serializes the compare parameters that are set", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ items: [], total: 0, limit: 25, offset: 0, next_offset: null }),
    );
    const result = await compareMetrics({
      metric: "new_case_rate",
      window: 365,
      court_id: JUDGE_ID,
      sort: "rate",
      order: "desc",
      jurisdiction_id: undefined,
    });
    expect(result.ok).toBe(true);
    const url = lastRequestUrl();
    expect(url.pathname).toBe("/api/v1/metrics/compare");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      metric: "new_case_rate",
      window: "365",
      court_id: JUDGE_ID,
      sort: "rate",
      order: "desc",
    });
  });

  it("fetches an observation's provenance by id", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ complete: true, members: [] }));
    const result = await getObservationProvenance(OBSERVATION_ID);
    expect(result.ok).toBe(true);
    expect(result.data?.complete).toBe(true);
    expect(lastRequestUrl().pathname).toBe(`/api/v1/metrics/${OBSERVATION_ID}/provenance`);
  });

  it("posts a correction and returns the acknowledgement or the error envelope", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { id: OBSERVATION_ID, status: "received", received_at: "2026-09-19T00:00:00Z" },
        { status: 202 },
      ),
    );
    const body = {
      target_type: "judge" as const,
      target_id: JUDGE_ID,
      reason: "The appointment date on this profile is a year off.",
      contact: "requester@example.invalid",
    };
    const accepted = await submitCorrection(body);
    expect(accepted.ok).toBe(true);
    expect(accepted.data?.status).toBe("received");
    const request = fetchMock.mock.calls.at(-1)?.[0];
    expect(request).toBeInstanceOf(Request);
    expect((request as Request).method).toBe("POST");
    expect(new URL((request as Request).url).pathname).toBe("/api/v1/corrections");
    expect(await (request as Request).json()).toEqual(body);

    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { code: "rate_limited", message: "corrections rate limit exceeded", request_id: "r" },
        { status: 429, headers: { "content-type": "application/json", "retry-after": "720" } },
      ),
    );
    const refused = await submitCorrection(body);
    expect(refused.ok).toBe(false);
    expect(refused.error).toMatchObject({ status: 429, code: "rate_limited", retryAfterSeconds: 720 });
  });
});
