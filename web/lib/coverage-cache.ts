// web/lib/coverage-cache.ts
// A module-level, in-process cache for the `/coverage` read the root layout's
// demo-data banner makes on every request (Phase 2 carry-over item 7): a
// successful result is reused for sixty seconds, a failed one is never
// cached (the next request retries), and the cache holds no per-client
// state — one entry for the whole process, unkeyed. It is bypassed under
// NODE_ENV=test so unit tests observe every call; the factory exists so the
// TTL can be tested with fake timers on a cache that is not bypassed.
import { getCoverage, type ApiResult, type Coverage } from "@/lib/api/client";

export const COVERAGE_TTL_MS = 60_000;

export interface CoverageCache {
  /** The cached result when fresh, else a new read (cached when it succeeds). */
  get(): Promise<ApiResult<Coverage>>;
  /** Drop the entry (a test helper; the TTL is the only expiry in production). */
  clear(): void;
}

export function createCoverageCache({
  ttlMs = COVERAGE_TTL_MS,
  bypass = false,
  fetcher = getCoverage,
  now = () => Date.now(),
}: {
  ttlMs?: number;
  bypass?: boolean;
  fetcher?: () => Promise<ApiResult<Coverage>>;
  now?: () => number;
} = {}): CoverageCache {
  let entry: { expiresAt: number; result: ApiResult<Coverage> } | null = null;
  let inFlight: Promise<ApiResult<Coverage>> | null = null;
  return {
    async get() {
      if (bypass) return fetcher();
      if (entry && entry.expiresAt > now()) return entry.result;
      // Concurrent requests during a miss share one upstream call.
      inFlight ??= fetcher().then((result) => {
        if (result.ok) entry = { expiresAt: now() + ttlMs, result };
        inFlight = null;
        return result;
      });
      return inFlight;
    },
    clear() {
      entry = null;
    },
  };
}

/** The process-wide cache the banner reads through. */
export const coverageCache: CoverageCache = createCoverageCache({
  bypass: process.env.NODE_ENV === "test",
});
