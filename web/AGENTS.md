<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## JudgeMetrics web tier

- Every observation (a published number from `/judges/{id}/metrics`,
  `/courts/{id}/metrics`, or a `/metrics/compare` row) is rendered
  through the presentation-rule component, `components/metric-stat.tsx`
  (`MetricStat`) or, for a compare row, `components/compare-table.tsx`,
  which show the numerator, denominator, date range, coverage, sample
  size, interval, methodology link, and synthetic badge, and render the
  suppression notice with no figure when `suppressed` is true. Never
  print `rate`, `value`, `numerator`, or `denominator` from a page or
  another component. The one derived figure on a page is the cohort
  position line (`CohortPositionLine`: judges, median, rank), and it
  names the compare rows it was derived from.
- Windows come from the registry response (`windows_days`), the default
  is `DEFAULT_WINDOW_DAYS` in `lib/metrics.ts`; no page hard-codes a
  window list.
- Page state is the query string (`cohort`, `window` on the judge page;
  `metric`, `window`, `court_id`, `jurisdiction_id`, `sort`, `order`,
  `offset` on `/compare`), validated against the registry before any
  fetch; an invalid value renders `ErrorState`, never a crash.
- No `dangerouslySetInnerHTML`; the methodology text is React text nodes.
  No page fetches a person route. The banner reads `/coverage` through
  `lib/coverage-cache.ts` (sixty seconds, bypassed under `NODE_ENV=test`).
- Regenerate `lib/api/schema.d.ts` (`pnpm generate:api`) after any change
  to `docs/openapi.json`; `tests/unit/schema-freshness.test.ts` fails
  otherwise.
