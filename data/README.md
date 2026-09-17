<!-- data/README.md -->
# `data/`

What lives here, and what never enters the repository.

| Path               | Tracked | Contents                                                                 |
|--------------------|---------|--------------------------------------------------------------------------|
| `data/reference/`  | yes     | Small curated reference tables the connectors and normalizers read.      |
| `data/fixtures/`   | yes     | Reserved for shared data fixtures that are not test-only. Today every fixture is test-only and lives under `tests/fixtures/` (the FJC excerpt in `tests/fixtures/fjc/`). |
| `data/lake/`       | no      | The default local raw object lake (`JUDGEMETRICS_RAW_STORE_URL=file://./data/lake`): immutable, content-addressed source artifacts written by `judgemetrics ingest run`. With the Compose services the lake is the MinIO bucket instead (`s3://judgemetrics-raw`). |
| `data/synthetic/`  | no      | Generated synthetic justice datasets (`judgemetrics synthetic generate`), one directory per seed, reproducible from the seed; the golden fixture is tracked under `tests/fixtures/golden/`. |

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

## `data/reference/synthetic_offenses.csv`

The curated offense table the synthetic generator draws charges from
(`docs/SYNTHETIC_DATA.md`): forty invented statutes with columns
`statute_code` (`SYN-###`), `description`, `offense_category`,
`severity`, and `violent_flag`, whose category and severity values are
the case vocabulary in `judgemetrics.synthetic.vocabulary`. It is a
reference table, not generated data: edit it deliberately, then bump
`GENERATOR_VERSION` and regenerate the golden fixture, because the
charges every seed draws change with it.

## `data/synthetic/<seed>/`

`uv run judgemetrics synthetic generate --seed <seed> --scale golden|demo|tiny`
writes one directory per seed (default `data/synthetic/20260916`, scale
`demo`):

```
data/synthetic/<seed>/
├── manifest.json        seed, scale, generator and truth versions, row counts, sha256 per file
├── source/              the nine source-format CSV files the synthetic connector ingests:
│   courts.csv, judges.csv, cases.csv, participants.csv, charges.csv,
│   assignments.csv, events.csv, decisions.csv, sentences.csv
└── truth/               what the simulation knows; never read by a connector, never in the database:
    persons.csv, subsequent_events.csv, resolution_expectations.csv,
    planted.csv, metrics.json, README.md
```

`uv run judgemetrics synthetic verify data/synthetic/<seed>` recomputes
every hash against the manifest. The generator refuses an existing
manifest unless `--force` is given, and it never deletes anything.
