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

## `data/reference/case_vocabulary.yaml`

The versioned case-level vocabulary (`version: 1`) every connector maps
its source values onto before a draft leaves `normalize`:
`judgemetrics.normalization.vocabulary` loads it once with
`yaml.safe_load` and `require(kind, value)` rejects a row whose value is
not listed. It equals the constants in `judgemetrics.synthetic.vocabulary`
(unit test). Adding, renaming, or removing a value bumps `version`,
updates those constants, and is recorded in `docs/DATA_MODEL.md`
"Vocabularies".

## `data/reference/entity_resolution_thresholds.yaml`

The versioned decision thresholds of the probabilistic entity-resolution
stage per entity type (`version: 1`; `auto_match` 0.95, `auto_reject`
0.20): `judgemetrics.entity_resolution.config` loads it with
`yaml.safe_load` and a unit test asserts it equals the constants. A
change bumps `version` and is recorded in `docs/ENTITY_RESOLUTION.md`.

## `data/reference/metric_registry.yaml`

The versioned metric registry (`version: 1`, `methodology_version:
"0.1"`): the contract every published number is computed against —
the brief's eight statistical warnings verbatim as `known_limitations`,
the suppression rule, and one entry per metric with its slug, kind,
subject types, population, prose definitions, structured attribution
rule, index event, outcome, windows, dimension, suppression threshold,
unit, and version. `judgemetrics.metrics.registry` loads it with
`yaml.safe_load` and validates every value against the case vocabulary
and the fixed enumerations; `sync_definitions` mirrors it into
`metric_definition`; `judgemetrics methodology render` writes
`docs/METHODOLOGY.md` from it (`--check` exits 1 when the committed
document is stale). A data-semantics finding edits the entry and bumps
its `version` and the registry `version`; a change of semantics bumps
`methodology_version` and adds a changelog entry
(`docs/DATA_MODEL.md` "Metric registry").

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
