// web/tests/unit/client.test.ts
// The typed client helpers against a mocked fetch: request shape (path,
// query encoding), the success envelope, the API error envelope, 429 with
// Retry-After, a non-JSON upstream error, and a transport failure.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  API_BASE_URL,
  getCourt,
  getJudge,
  listJudges,
  listJurisdictions,
  search,
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
