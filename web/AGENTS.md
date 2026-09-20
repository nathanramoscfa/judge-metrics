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
- The one write path is the corrections form (`components/correction-form.tsx`)
  posting JSON to the route handler `app/api/corrections/route.ts`
  (`lib/corrections-handler.ts`), never to the API directly from the
  browser. The handler validates against the limits in `lib/corrections.ts`
  (mirrored from `CorrectionIn`), forwards the `ALLOWED_FIELDS` and
  nothing else with the caller's `X-Forwarded-For`, returns `{id,
  status}` or the API's error body under its status, sets no cookie, and
  logs nothing — no `console.*` in that path, ever (the Vitest suite spies
  every console method). No file upload anywhere: supporting material is
  an http(s) URL field.
- "Report a data error" is `components/report-error-link.tsx`
  (`correctionHref` from `lib/corrections.ts`): on the judge, court, and
  case headers with the entity's id, and on every `MetricPanel` through
  `reportObservationId` (the panel's first observation, from
  `firstObservationId`). A new entity page gets the link in its header.
- The court page renders its own observations through `MetricStat`
  (`COURT_PANELS` in `lib/metrics.ts`; the court-only counts belong to the
  Pretrial panel) and the comparable-judge table through `CompareTable`
  with `?metric=` and `?window=` in the query; the jurisdiction page reads
  its sources and years through `lib/jurisdictions.ts`. Both keep their
  page state in the URL like `/compare`.
- `tests/e2e/first-milestone.spec.ts` is the brief's checklist, items
  8–16, one test per item in order, sharing one judge discovered through
  the API; keep the order and the numbering when a page changes.
