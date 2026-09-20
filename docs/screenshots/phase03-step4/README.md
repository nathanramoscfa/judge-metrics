<!-- docs/screenshots/phase03-step4/README.md -->
# Phase 3 Step 4 screenshots

The metric surfaces in light and dark mode, captured with Playwright
against the local API over the demo seed (`uv run poe seed` followed by
`uv run poe compute-metrics`) on 2026-09-20, for the Step 4 pull
request. Pages: the judge page (the header, the section navigation, the
association statement, and the Cases panel; `judge-*.png`), the judge
page's "Outcomes after qualifying release" panel with the window and
cohort selectors, the judge's stat beside the court's pooled stat, the
cohort position line, and the not-observable rows
(`judge-outcomes-*.png`), `/compare` for the 365-day new-case rate
after pretrial release within a synthetic court with the judge's row
highlighted (`compare-*.png`), `/methodology` rendered from
`GET /api/v1/metrics` (`methodology-*.png`, the top of the page), and
`/coverage` v1 with the Snapshot card and the per-source coverage
windows, observable and not-observable outcomes, snapshot, and
methodology version (`coverage-*.png`).

Every judge and court shown is synthetic (the demo dataset's generated
names); no real person or court appears.
