// web/tests/unit/coverage-cache.test.ts
// The banner's coverage cache with fake timers: a successful read is
// reused within sixty seconds and refetched after; a failed read is never
// cached; concurrent misses share one call; the process-wide instance is
// bypassed under NODE_ENV=test so every other test observes its fetches.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiResult, Coverage } from "@/lib/api/client";
import { COVERAGE_TTL_MS, coverageCache, createCoverageCache } from "@/lib/coverage-cache";

function coverage(present: boolean): ApiResult<Coverage> {
  return {
    ok: true,
    data: {
      sources: [],
      synthetic_present: present,
      registry_version: 1,
      methodology_version: "0.1",
      generated_at: "2026-09-20T00:00:00Z",
    },
  };
}

const failure: ApiResult<Coverage> = {
  ok: false,
  error: { status: 0, code: "network_error", message: "down", requestId: null, retryAfterSeconds: null },
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-20T00:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("createCoverageCache", () => {
  it("reuses a successful read for sixty seconds and refetches after", async () => {
    const fetcher = vi.fn<() => Promise<ApiResult<Coverage>>>().mockResolvedValue(coverage(true));
    const cache = createCoverageCache({ fetcher });
    expect(COVERAGE_TTL_MS).toBe(60_000);

    expect(await cache.get()).toEqual(coverage(true));
    expect(await cache.get()).toEqual(coverage(true));
    vi.advanceTimersByTime(59_999);
    expect(await cache.get()).toEqual(coverage(true));
    expect(fetcher).toHaveBeenCalledTimes(1);

    fetcher.mockResolvedValue(coverage(false));
    vi.advanceTimersByTime(1);
    expect(await cache.get()).toEqual(coverage(false));
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("never caches a failure", async () => {
    const fetcher = vi.fn<() => Promise<ApiResult<Coverage>>>().mockResolvedValue(failure);
    const cache = createCoverageCache({ fetcher });
    expect(await cache.get()).toEqual(failure);
    expect(await cache.get()).toEqual(failure);
    expect(fetcher).toHaveBeenCalledTimes(2);

    fetcher.mockResolvedValue(coverage(true));
    expect(await cache.get()).toEqual(coverage(true));
    expect(await cache.get()).toEqual(coverage(true));
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it("shares one upstream call between concurrent misses and can be cleared", async () => {
    const fetcher = vi.fn<() => Promise<ApiResult<Coverage>>>().mockResolvedValue(coverage(true));
    const cache = createCoverageCache({ fetcher, ttlMs: 1_000 });
    await Promise.all([cache.get(), cache.get(), cache.get()]);
    expect(fetcher).toHaveBeenCalledTimes(1);
    cache.clear();
    await cache.get();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("bypasses the cache when asked, calling the fetcher every time", async () => {
    const fetcher = vi.fn<() => Promise<ApiResult<Coverage>>>().mockResolvedValue(coverage(true));
    const cache = createCoverageCache({ fetcher, bypass: true });
    await cache.get();
    await cache.get();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

describe("coverageCache (process-wide)", () => {
  it("is bypassed under the test environment so every read reaches fetch", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () =>
      new Response(JSON.stringify(coverage(true).data), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    expect(process.env.NODE_ENV).toBe("test");
    await coverageCache.get();
    await coverageCache.get();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
