<!-- data/README.md -->
# `data/`

What lives here, and what never enters the repository.

| Path               | Tracked | Contents                                                                 |
|--------------------|---------|--------------------------------------------------------------------------|
| `data/reference/`  | yes     | Small curated reference tables the connectors and normalizers read.      |
| `data/fixtures/`   | yes     | Reserved for shared data fixtures that are not test-only. Today every fixture is test-only and lives under `tests/fixtures/` (the FJC excerpt in `tests/fixtures/fjc/`). |
| `data/lake/`       | no      | The default local raw object lake (`JUDGEMETRICS_RAW_STORE_URL=file://./data/lake`): immutable, content-addressed source artifacts written by `judgemetrics ingest run`. With the Compose services the lake is the MinIO bucket instead (`s3://judgemetrics-raw`). |
| `data/synthetic/`  | no      | Generated synthetic justice datasets (Phase 2), reproducible from a seed; the golden fixture is tracked under `tests/fixtures/golden/`. |

`data/lake/`, `data/raw/`, `data/snapshots/`, and `data/synthetic/` are
ignored by `.gitignore`. A raw artifact is never edited or deleted by
hand: the lake is the evidence every published number traces back to.

## `data/reference/us_states.csv`

USPS two-letter codes for the fifty states, the District of Columbia,
and the inhabited territories, with a `kind` column (`state`,
`federal_district`, `territory`). `judgemetrics.normalization.geography`
loads it; the FJC connector uses it to fill `court.state_code` from
district-court names (`U.S. District Court for the Southern District of
New York` → `NY`; unparseable names stay null). The API image copies
this directory so the connector works inside the container.
