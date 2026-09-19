<!-- docs/ARCHITECTURE.md -->
# Architecture

The system-level picture is in the root [`ROADMAP.md`](../ROADMAP.md)
§3. This document describes what is built: the ingest pipeline (Phase 1
Step 3, extended to case-level data in Phase 2 Step 2), the raw lake,
the idempotency rules, person hashing and resolution, the database
roles, the public API (Step 4), and the web tier (Step 5).

## Ingest pipeline

```
   docs/DATA_SOURCES.md            src/judgemetrics/ingest/
   (verified register)             ┌──────────────────────────────────────┐
          │                        │ registry: @register / get_connector  │
          ▼                        └───────────────┬──────────────────────┘
   ┌──────────────┐  discover/fetch  ┌─────────────▼──────────────┐
   │ Source (FJC, │ ───────────────▶ │ SourceConnector            │
   │ synthetic)   │  validate/parse  │ (ingest/fjc, ingest/       │
   └──────────────┘  normalize       │  synthetic)                │
                                     └─────────────┬──────────────┘
                                                   │ drafts
                       ┌───────────────────────────▼──────────────────────────┐
                       │ runner.run_ingest — the fourteen steps, one run      │
                       │  1 discover · 2 fetch · 3 sha256 · 4 store · 5 record│
                       │  (load_context) · 7 validate · 6 parse · 8 normalize │
                       │  9 dedupe · 10 resolve (+ resolve_persons hook)      │
                       │ 11 quality checks · 12 publish (upserts: runner for  │
                       │    reference tables, ingest/publish.py for cases)    │
                       │ 13 recompute impacted metric subjects · 14 lineage   │
                       └──────┬─────────────────────────────┬─────────────────┘
                              │ immutable bytes             │ one transaction
                              ▼                             ▼
                   ┌──────────────────────┐     ┌────────────────────────────┐
                   │ Raw lake             │     │ PostgreSQL (ingest role)   │
                   │ file:// or s3://     │     │ source, ingest_run,        │
                   │ <src>/<yyyy>/<mm>/   │     │ source_record → reference  │
                   │   <sha256>.csv       │     │ tables, person (+ hashed   │
                   └──────────────────────┘     │ identifiers), the case     │
                                                │ tables, data_quality_issue │
                                                └────────────────────────────┘
```

### The connector protocol

`judgemetrics.ingest.base.SourceConnector` reproduces the brief's
interface exactly and adds the identifying attributes:

| Member                  | Role                                                          |
|-------------------------|---------------------------------------------------------------|
| `source_id`             | The register key in `docs/DATA_SOURCES.md` (`fjc`).           |
| `parser_version`        | Bumped whenever parsing or normalization changes; recorded on every source record and run. |
| `source_info`           | Owner, source type, access method, terms for the `source` row. |
| `async discover()`      | The artifacts to retrieve (`SourceArtifact`: external id, URI, content type, metadata). |
| `async fetch(artifact)` | Retrieve one artifact as a `RawArtifact` (bytes or path, sha256, retrieval time, response-header subset, `not_modified`). |
| `validate_raw(raw)`     | `ValidationResult` — errors fail the run, warnings are logged. |
| `parse(raw)`            | Row-level `SourceRecordDraft`s (external record id, effective time, payload, record type). |
| `normalize(record)`     | Canonical drafts: the reference drafts `JurisdictionDraft`, `CourtDraft`, `JudgeDraft`, `JudgeServiceDraft` and the case-level drafts `PersonDraft`, `CaseDraft`, `CasePartyDraft`, `JudgeAssignmentDraft`, `ChargeDraft`, `CourtEventDraft`, `DecisionDraft` (with an optional `PretrialReleaseDraft`), `SentenceDraft`, `JusticeEventDraft`. |
| `SupportsCheckpoint`    | Optional: `restore_checkpoint` / `checkpoint` for cursoring sources; stored on `ingest_run.checkpoint`. |
| `SupportsContext`       | Optional: `load_context(artifacts)` receives the raw artifact of *every* discovered artifact (changed or not) before parsing, so a multi-file source builds its cross-file lookups from the complete export; raising `IngestError` fails the run (the synthetic connector fails on manifest drift here). |

Every draft has a `natural_key`; the runner deduplicates drafts by it
within a run and upserts on the matching unique index. Source-specific
parsing (column names, date formats, vocabularies) lives under the
connector package; canonical rules (name and case-number normalization,
the state-code lookup, the versioned case vocabulary in
`normalization/vocabulary.py`, which loads
`data/reference/case_vocabulary.yaml` once and rejects a row whose value
is not listed) live in `judgemetrics.normalization`.

Natural keys of the case-level drafts: a person is
`("person", <identifier kind>, <hash>)`, the peppered hash of the
source's stable identifier; a case is `("case", <court name>, <court
type>, <normalized case number>)`; every row that belongs to a case is
`("<table>", *case_key[1:], source_row_id)`, where `source_row_id` is the
source's own row identifier (a charge id, an event id), so a re-export of
the same row upserts in place; a derived justice event is keyed on the
person hash, the event type, the instant (UTC), and the related case.
`describe_key` renders any key for an issue description or log line
without the person hash.

### The fourteen steps and where they run

| # | Brief step                     | Runner                                                     |
|---|--------------------------------|------------------------------------------------------------|
| 1 | Discover source artifacts      | `connector.discover()` in `_execute`                       |
| 2 | Download or retrieve           | `_retrieve`: `connector.fetch()`, or `<fixture dir>/<external_id>` with `--from-fixture` |
| 3 | Calculate cryptographic hash   | `RawArtifact` sha256, re-computed by the runner over the bytes it stores |
| 4 | Save immutable raw object      | `store.put(data, object_key(...))`                         |
| 5 | Create `source_record`         | `_retrieve`: one record per `(source, external_id, sha256)` |
| 6 | Parse                          | `connector.parse()`                                        |
| 7 | Schema validate                | `connector.validate_raw()` — executed before step 6, because the raw artifact must be validated before it is parsed; errors end the run as `failed` before anything is derived |
| 8 | Normalize                      | `connector.normalize()` per parsed row; a `NormalizationError` rejects the row and records a `normalize_failed` issue. A `SupportsContext` connector received every artifact through `load_context` before step 7. |
| 9 | Deduplicate                    | `_deduplicate` by `natural_key` (first draft wins; conflicting duplicates are counted in the log). `case_number_duplicate` runs just before, over the drafts as parsed, because the collapse would hide it. |
| 10 | Resolve entities              | `_resolve`: judges by exact `external_ids->>'<system>'` (`fjc_nid`, `synthetic_judge_code`), courts by exact `(canonical_name, court_type)`, jurisdictions by `(name, type)`, cases by `(court, case_number_normalized)`, persons through `entity_resolution.pipeline.resolve_persons(session, drafts, run)` — the deterministic stage: a draft whose `source_participant_id` hash already sits in `person_identifier` is that person, otherwise a new person and its identifier rows are written here. The rule, probabilistic, and review stages (`pipeline.resolve_candidates`) run right after step 12, because case linkage is a feature they read from the published rows: the run's persons are blocked against every person they share a name or identifier hash with, candidates are stored, system merges applied, and the run's published person ids follow the merges (`docs/ENTITY_RESOLUTION.md`). A case-level draft whose case, person, judge, or court cannot be resolved is rejected with an `unresolved_case` / `unresolved_person` / `unresolved_judge` / `unresolved_court` issue and counted, never dropped. |
| 11 | Run data-quality checks       | `judgemetrics.quality.checks.run_checks` over the resolved drafts (the reference checks of Phase 1 and the case-level checks: `disposition_before_filing`, `event_order_impossible`, `subsequent_before_index`, `missing_judge_on_decision`, `missing_disposition`, `unknown_category_measured`, `person_resolution_confidence_missing`) |
| 12 | Publish canonical rows        | `_publish`: `INSERT … ON CONFLICT DO UPDATE` per entity type, in dependency order — jurisdiction → court → judge → judge_service in the runner, then persons (+ identifier rows) → cases → parties → assignments → charges → court events → decisions (+ pretrial release) → sentences → justice events in `ingest/publish.py`, batched 500 rows per statement |
| 13 | Recompute affected metrics    | `recompute_metrics`: the judges and courts the run's published rows can change (`impacted_subjects`, "Metrics engine" below) are exported, computed, and published inside the same transaction when `JUDGEMETRICS_METRICS_RECOMPUTE_ON_INGEST` is on; the snapshot is recorded in `ingest_run.metrics_snapshot_id` |
| 14 | Record lineage and statistics | issues persisted with their source record and entity id; `ingest_run` counts, `code_version` (git SHA), `parser_version`, status, checkpoint, `metrics_snapshot_id` |

### The raw lake

- **Key scheme:** `<source_id>/<yyyy>/<mm>/<sha256><ext>`, year and month
  of the retrieval in UTC. The key is derived from the content hash,
  never from a source-supplied file name, so one key names one payload.
- **Immutability:** `put(data, key)` refuses a different payload at an
  existing key (`ImmutableObjectError`) and treats the same payload as a
  no-op that returns the existing reference. Nothing deletes or
  overwrites.
- **Backends:** `FilesystemRawObjectStore` (`file://<dir>`; temp file,
  `fsync`, rename into place) and `S3RawObjectStore` (`s3://bucket[/prefix]`
  through `JUDGEMETRICS_S3_ENDPOINT_URL`, MinIO locally; the sha256 is
  stored as object metadata and checked on conflict). `open_raw_store(settings)`
  chooses by `JUDGEMETRICS_RAW_STORE_URL`; in production the S3 endpoint
  must be HTTPS.
- **Lineage:** `source_record.raw_object_path` is the key and
  `source_record.raw_sha256` the hash; the integration test verifies that
  the stored bytes hash to the recorded value for every published row.

### Idempotency rules

1. A `source_record` is unique on `(source_id, external_record_id,
   raw_sha256)`. An artifact whose hash is already recorded is not
   parsed again — the run logs `ingest.artifact.unchanged` and counts
   nothing — unless `--force` is given or the connector's
   `parser_version` differs from the record's (a new parser must
   re-derive its rows; the record's `parser_version` is updated).
2. Conditional requests: the runner passes the latest record's `ETag`,
   `Last-Modified`, and sha256 to `fetch()` through the artifact
   metadata; a `304 Not Modified` maps to the existing record.
3. Publishing uses `INSERT … ON CONFLICT DO UPDATE … WHERE <substantive
   column> IS DISTINCT FROM excluded.<column>`: rows whose substantive
   columns are unchanged are not written at all (no `updated_at` bump,
   no provenance change), so a rerun over unchanged files reports
   `records_created = records_updated = 0`. JSONB `external_ids` and
   `metadata` are merged (`||`), never replaced, so identifiers added by
   another source survive.
4. `source_record_id` on `jurisdiction`, `court`, `judge`, and `person`
   is last-substantive-writer provenance: it moves to the newer artifact
   only when that artifact changed the row. `judge_service` rows and every
   case-level row carry the record of the artifact that produced their
   current values.
5. Data-quality issues are keyed by `(source_record_id, entity_type,
   entity_id, issue_code, description)`; run-level issues without a
   source record (the unknown-category counts) by code and description;
   a rerun never duplicates an open issue.
6. The `ingest_run` row is committed first, so a failed run is always
   recorded; the whole publish (source records, canonical rows, issues,
   run statistics) is one transaction that a failure rolls back, leaving
   `status = failed` and `failure_reason` on the run and the immutable
   raw object in the lake.

7. A new `person` receives `public_person_key = secrets.token_urlsafe(12)`
   once, at insert; the key is never in an update set. Identifier rows are
   inserted with `ON CONFLICT DO NOTHING` on `(person_id, identifier_type,
   value_hash)`.

### The audit log

`audit_log` (revision 0004) records every administrative and
entity-resolution decision: `occurred_at`, `actor` (an operator label or
`system:<model version>`), `action` (`er.merge`, `er.decide`, …), the
entity, a JSON payload of ids, counts, decisions, and reasons, and a
request id. The trigger `audit_log_append_only()` raises on `UPDATE` and
`DELETE` for every role, so a written row is history; the ingest role
inserts and reads, the public API role has no privilege. Phase 6's admin
surface writes to the same table.

### Person hashing and resolution

A participant's name, date of birth, and source identifier never reach a
canonical column, a log line, or an issue description. The connector
hashes each with `judgemetrics.security.identifiers.hash_identifier`:
`sha256(pepper || "\x00" || kind || "\x00" || normalized value)` under
`JUDGEMETRICS_IDENTIFIER_PEPPER` (a per-deployment secret; the ingest CLI
and `seed` refuse to start without it), with the normalization per kind
(`source_participant_id` stripped and upper-cased, `full_name` through
`normalize_person_name`, `date_of_birth` as ISO, `name_dob` as
`<normalized name>|<iso date>` when both exist). `PersonDraft` carries
those hashes only; the publish step writes them to the restricted
`person_identifier` table (`encrypted_value` stays NULL in this phase).

`entity_resolution.pipeline.resolve_persons(session, drafts, run)` is the
deterministic stage applied to incoming rows: a draft whose
stable-identifier hash already sits in `person_identifier` (partial
unique index `uq_person_identifier_stable`) resolves to that person;
every other draft becomes a new `person` with `resolution_status =
deterministic` and confidence 1. The staged framework — rules that never
merge on a name alone, a stubbed probabilistic scorer, the manual-review
queue, merges, and the audit log — is documented in
[`ENTITY_RESOLUTION.md`](ENTITY_RESOLUTION.md). The participant id is
used in the namespace the source assigns it (the generator's ids are one
per person across its courts; a real clerk system's ids are scoped the
same way), never combined with a court code. A merged person keeps its
row with `merged_into_person_id` set and every public query filters it
out (`entity_resolution.merge.unmerged()`).

### The synthetic connector

`ingest/synthetic/` reads a generated dataset (`docs/SYNTHETIC_DATA.md`)
from `Settings.synthetic_dir` (the directory holding `manifest.json` and
`source/`; default `data/synthetic/20260916`): `discover` lists
`manifest.json` first and then the nine source files as
`source/<name>` (`truth/` is never discovered), `fetch` reads bytes from
disk after checking the id is a plain relative path inside the directory,
`load_context` fails the run when a file's sha256 differs from the
manifest and builds the court-code index and each participant's case
timeline from `charges.csv`, `validate_raw` checks the manifest's
`generator_version` and each file's header set (missing → error naming
the header, extra → warning), and `normalize` maps rows onto the drafts
(`normalize.py`, one section per file), deriving justice events —
`new_case` when a participant has an earlier case, `reconviction` when a
conviction follows an earlier disposition of another case,
`failure_to_appear` and `revocation` from the court events. `judgemetrics
ingest run synthetic --from-fixture tests/fixtures/golden` reads the
golden fixture through the runner's fixture path, which accepts
contained relative ids for this reason.

### Refusals

`run_ingest` records `status = refused` without touching anything when
`JUDGEMETRICS_ENV=production` and either the connector's
`source_info.source_type` is `synthetic` or `--from-fixture` is given.
`judgemetrics seed` generates nothing in production and records the same
refusal.

## Database roles

| Role                  | Used by                                              | Rights                                            |
|-----------------------|------------------------------------------------------|---------------------------------------------------|
| `judgemetrics_app`    | the API (`JUDGEMETRICS_DATABASE_URL`), `ingest runs`, `provenance trace` | `SELECT` on public tables; `INSERT` only on `correction_request` (revision 0007); nothing on `person_identifier`, `entity_resolution_candidate`, `audit_log` |
| `judgemetrics_ingest` | `ingest run`, `seed`, `er …` (`JUDGEMETRICS_INGEST_DATABASE_URL`) | `SELECT, INSERT, UPDATE, DELETE` on every table except `audit_log` (`SELECT, INSERT`: append-only); no DDL |
| `judgemetrics_admin`  | `db upgrade` / `downgrade` (`JUDGEMETRICS_ADMIN_DATABASE_URL`) | full control of the public schema (not a superuser) |

The roles are created by `infra/docker/postgres/02-roles.sql`; migrations
grant per table (`alembic/versions/0001_baseline.py`) and default
privileges cover objects created later. CI runs every URL as the service
container's owner, which is why the ingest and admin URLs fall back to
`JUDGEMETRICS_DATABASE_URL` when unset.

## Public API v1

The API (`src/judgemetrics/api`, contract in [`API.md`](API.md)) is a
read-only view over the canonical tables and the published metric
observations, connected as the `judgemetrics_app` role, with one write
path — `POST /corrections`, an `INSERT` the role can make and never read
back. Requests pass through four layers, each of which knows only the
one beneath it:

```
   GET /api/v1/judges?q=…            src/judgemetrics/
   ┌───────────────────────────────────────────────────────────────────┐
   │ api/routes/   HTTP: query parameters (PageParams, StrictQuery),   │
   │               path ids, 404s, Cache-Control, the /search limiter  │
   └───────────────────────────────┬───────────────────────────────────┘
                                   │ typed arguments
   ┌───────────────────────────────▼───────────────────────────────────┐
   │ services/     assemble response models: name normalization for   │
   │               search, the similarity threshold, provenance blocks │
   └───────────────────────────────┬───────────────────────────────────┘
                                   │ Session + filters
   ┌───────────────────────────────▼───────────────────────────────────┐
   │ repositories/ SQLAlchemy queries: window-count pagination,        │
   │               selectinload, trigram `%` matches; bound parameters │
   └───────────────────────────────┬───────────────────────────────────┘
                                   │ ORM rows
   ┌───────────────────────────────▼───────────────────────────────────┐
   │ db/models/    the canonical tables                                │
   └───────────────────────────────────────────────────────────────────┘
   schemas/       the only shapes that leave the API (Pydantic v2,
                  `from_attributes`): Page[T], Provenance, ErrorBody, …
```

- **Routes** (`api/routes/{judges,courts,jurisdictions,cases,search,coverage,metrics,corrections}.py`)
  declare parameters with validation (`limit` 1–100, `offset` ≥ 0,
  enum statuses, UUID ids, ISO dates, vocabulary values by shape) and a
  `StrictQuery` allow-list per route, so an undeclared query parameter
  is a 422 rather than an ignored filter; a unit test checks each
  allow-list against the parameters the OpenAPI document declares.
  `/judges/{id}/cases` rejects `filed_to < filed_from` with a 422 that
  names the parameter; `/metrics/compare` rejects a missing or doubled
  cohort, an inverted period, an unknown metric, and a window the
  metric lacks the same way. List, detail, and metrics routes add
  `Cache-Control: public, max-age=60` through a router dependency, which
  a raised error bypasses; `POST /corrections` answers `no-store`.
  The judge- and court-level observation routes
  (`/judges/{id}/metrics`, `/courts/{id}/metrics`) live beside their
  subjects and share one handler in `routes/metrics.py`.
- **Services** (`services/`) return the schemas. `services.search`
  normalizes the query twice — with `normalize_person_name` for the
  trigram arms and `normalize_case_number` for the exact case-number
  arm — sets `pg_trgm.similarity_threshold` for the request's
  transaction with `set_config(…, true)` (a bound parameter from
  `JUDGEMETRICS_SEARCH_SIMILARITY_THRESHOLD`), and returns the union
  ordered by `similarity()` (an exact case number scores 1).
  `services.provenance` builds the provenance block from the public
  columns of `source_record` and its source's type. `services.cases`
  assembles the case detail and the timeline from one
  `repositories.cases.load_case` result: the timeline's entries are the
  same loaded rows re-keyed by time, kind rank, and row id — never a
  second round of queries — each citing its row's artifact.
  `services.coverage` folds the per-source counts, latest runs, and
  latest snapshots into the `Coverage` response, derives
  `synthetic_present` from rows, not from registered sources, and takes
  the registry versions from the registry file. `services.metrics`
  builds every `Observation` from one joined repository row
  (`numerator` ← `observed_count`, `denominator` ← `cohort_size`, the
  interval method from the kind, the coverage block from the source,
  the methodology link from `Settings.methodology_url_for`), serves the
  registry from `load_registry` alone, validates a compare request's
  metric and window against the registry before any query, computes
  each compare row's `coverage_warning` against the cohort's reference
  period, and maps `metrics.provenance.trace` onto
  `ObservationProvenance` (404 for a superseded id; the snapshot's
  storage URI and any non-public artifact URI withheld).
  `services.corrections` checks the target exists, encrypts the contact
  with `security.crypto.encrypt_contact` and nothing else, inserts, and
  commits — the only commit in the API.
- **Repositories** (`repositories/`) take a `Session` and return ORM
  rows plus totals. `paginate_rows` adds `count(*) OVER ()` to the page
  query so a list is one statement (a plain count only when the page
  is empty); every list and detail statement joins `source_record` and
  `source` through `repositories.provenance.with_source` and selects
  `synthetic_flag()` (`source.source_type = 'synthetic'`) beside the
  entity, so the flag costs no extra statement. `get_judge` loads
  service records with `selectinload` and their courts with a chained
  `joinedload`, and `case_window` aggregates the judge's assigned cases
  in one statement, so a judge detail is four statements including
  provenance. `repositories.cases.load_case` is one explicit statement
  per case-level table (the case with its court; parties joined to
  persons; assignments, events, decisions with pretrial releases, and
  sentences joined to judges; charges) plus one for the provenance rows:
  eight whatever the case holds. Every person join applies
  `entity_resolution.merge.unmerged()` and selects `public_person_key`
  only. `list_judge_cases` filters with `Case.assignments.any(...)`;
  when a page is empty, one more statement returns the total together
  with the judge's existence, so the route can answer 404 without a
  separate lookup. `repositories.coverage` is one statement over
  `source` with a correlated count per canonical table, the filing
  window, and the declared coverage window, plus one `DISTINCT ON` for
  the latest completed run per source and one for the latest snapshot
  behind each source's current observations (`latest_snapshot`, the
  newest of all, is what `/ready` reports). `repositories.metrics`:
  `subject_observations` is one statement joining the current
  observations to their definition, source, and snapshot;
  `compare_page` is one page statement — the judges with a service
  record at the court or a court of the jurisdiction (a `LATERAL`
  subquery for the judge's court within the cohort, which also filters
  the rows), the observation's figures, `count(*) OVER ()`, the cohort's
  reference period from window functions over the whole cohort, and
  sort columns that are null whenever the row is suppressed so a page's
  order cannot leak a withheld number — with the `list_judge_cases`
  fallback for an empty page. `repositories.corrections` is the target
  lookup (one statement against the table the type names) and an
  `insert(CorrectionRequest)` with a client-generated id and no
  `RETURNING`, because PostgreSQL requires `SELECT` on every column a
  `RETURNING` clause names and the role has none. The trace's three
  statements live in `metrics/provenance.py` (docs/PROVENANCE.md).
  `tests/integration/test_query_counts.py` counts statements at the
  cursor and fails on more.
- **Errors** (`api/errors.py`): every non-2xx response is an `ErrorBody`
  (`code`, `message`, `request_id`). Validation errors name the
  parameter; `ApiError` carries its code; a `SQLAlchemyError` is a 503
  whose text is never returned (it can embed SQL); anything else is a
  500 `internal_error`. Stack traces stay in the logs.
- **Sessions**: `create_app` binds an engine and a session factory to
  the app (`app.state`), and `api.deps.get_session` opens one session
  per request from it, so an app built with explicit settings (tests)
  never reaches for the process-wide engine. The module attribute
  `judgemetrics.main.app` (what uvicorn serves) is built lazily on first
  access (PEP 562), so importing the module for `create_app` never
  constructs the process app. Outside the test environment `create_app`
  requires a usable `JUDGEMETRICS_CORRECTION_CONTACT_KEY`
  (`security.crypto.require_contact_key`) and fails at startup naming
  the variable, never its value.
- **Suppression at the schema layer**: `schemas.metrics.SuppressibleFigures`
  nulls `numerator`, `denominator`, `rate`, `value`, `distribution`,
  `lower`, and `upper` in a validator whenever `suppressed` is true, so
  every shape that carries a number (`Observation`, `CompareRow`, the
  traced observation) withholds it whatever the caller passed; the
  stored row keeps its numbers for `metrics verify`.
- **Identity** (`api/identity.py`, ROADMAP.md §1.4): a request resolves
  to a rate-limit bucket; anonymous keyed by client address is the only
  bucket until Phase 9 issues API keys. The OpenAPI document declares
  the `X-API-Key` scheme as optional.

### The rate limiters

`api/ratelimit.py` is an in-process token bucket per
`RequestIdentity.rate_limit_key`. The search limiter
(`app.state.search_limiter`) holds `search_rate_limit_burst` tokens
(default 10) refilled at `search_rate_limit_per_minute` (default 60)
and guards `/search`; the corrections limiter
(`app.state.corrections_limiter`, Phase 3 Step 3) holds
`corrections_rate_limit_burst` tokens (default 5) refilled at
`corrections_rate_limit_per_hour` (default 5) and guards
`POST /corrections`. Each runs before parameter or body validation, so
an over-limit client never reaches the database; an empty bucket
answers 429 with `Retry-After` and the `rate_limited` error body. The
client address is the TCP peer unless `JUDGEMETRICS_TRUST_PROXY=true`,
in which case it is the rightmost `X-Forwarded-For` entry — the one the
trusted proxy appended. These are the local layer beneath the Phase 8
edge limits: not shared across workers, forgotten on restart, and off
under `JUDGEMETRICS_ENV=test` unless
`JUDGEMETRICS_SEARCH_RATE_LIMIT_ENABLED=true` or
`JUDGEMETRICS_CORRECTIONS_RATE_LIMIT_ENABLED=true` (the integration
tests enable them with a held clock). Buckets are pruned once more than
10,000 keys are tracked; a full bucket carries no state, so dropping it
is exact.

### The OpenAPI snapshot

`judgemetrics openapi export` writes `docs/openapi.json` (sorted keys,
two-space indent, LF, trailing newline) from an app built with test
settings, so the document depends on the routes and the package version
only. `tests/unit/test_openapi.py` fails when the committed file differs
from the rendered one: a route change must regenerate the document,
because the web client is generated from it ("Web tier" below).

## Command interface for ingest

| Command                                          | Role   | Notes                                                   |
|--------------------------------------------------|--------|---------------------------------------------------------|
| `judgemetrics ingest list-sources`               | none   | Registered connectors with parser versions.             |
| `judgemetrics ingest run <source> [--from-fixture DIR] [--force]` | ingest | Exit 0 on `succeeded`, 1 on `failed`/`refused`, 2 on usage errors. `uv run poe ingest-fjc` runs the FJC connector. |
| `judgemetrics ingest runs [--source ID] [--limit N]` | app | A table of runs with counts, status, and parser version. |
| `judgemetrics seed [--seed 20260916] [--scale demo] [--force]` | ingest | Generate `data/synthetic/<seed>` (skipped when its manifest already records the seed, scale, and generator version) and ingest it through the synthetic connector. `uv run poe seed`. |
| `judgemetrics er run [--source ID]`              | ingest | Recompute person candidates under the current model version and apply system merges; prints pairs, candidates created and updated, matched, rejected, review, merges. |
| `judgemetrics er review list [--entity-type person] [--limit N] [--json]` | ingest | The manual-review queue: candidate ids, public person keys, stage, score, feature booleans. |
| `judgemetrics er review decide <id> --decision matched\|rejected --reviewer LABEL --reason TEXT` | ingest | Record a reviewer's decision (merge or rejection) with an `er.decide` audit row; refused in production until Phase 6. |
| `judgemetrics provenance trace <observation id> [--json]` | app | The chain from a published number to the raw artifacts, top-down (docs/PROVENANCE.md); exit 1 when incomplete, 2 for a malformed or unknown id. |

Logs (structlog, scrubbed) carry counts (per table on `ingest.published`
and `ingest.succeeded`), source identifiers, file hashes, and object keys
— never a raw row, a participant name, a date of birth, an identifier
hash, or the pepper (the scrubber's denylist covers `pepper`,
`value_hash`, `date_of_birth`, and `full_name`), and never a
correction's `reason`, `contact`, `supporting_material`, or the
`correction_contact_key` (denylisted too; operational log lines name
their cause `failure`, `refusal`, or `because` so they survive the
`reason` entry).

## Web tier

The web application (`web/`, Next.js App Router, TypeScript strict,
Tailwind CSS, shadcn/ui, TanStack Table, `next-themes`) is a read-only
presentation layer over API v1. It holds no data, sets no cookies, loads
no third-party script, and reads exactly one variable,
`NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`).

```
   browser ──GET /judges/<id>──▶ Next.js server (web/, port 3000)
                                   │ server component
                                   │ lib/api/client.ts  (openapi-fetch,
                                   │   types from lib/api/schema.d.ts)
                                   ▼
                                 API v1 (port 8000) ── PostgreSQL (app role)
```

- **Generated client.** `pnpm generate:api` runs `openapi-typescript`
  over the committed `docs/openapi.json` and writes
  `web/lib/api/schema.d.ts`, which is committed; a Vitest test
  regenerates it into a temp file and fails on any difference, so a
  route change reaches the web tier as a type error, not a runtime one.
  `web/lib/api/client.ts` wraps an `openapi-fetch` client in helpers
  (`getJudge`, `listJudges`, `getCourt`, `listCourts`,
  `getJurisdiction`, `listJurisdictions`, `search`, …) that never
  throw: every call returns `{ ok: true, data }` or `{ ok: false, error }`
  with the API's stable error code, HTTP status, request id, and
  `Retry-After`, or `network_error` with status 0 when the API is
  unreachable. Pages render an `ErrorState` (code, status, request id)
  or an `EmptyState` for every fetch; a 404 from the API becomes the
  Next.js not-found page, and a malformed id never reaches the API.
- **Rendering.** The root layout is `force-dynamic` because it renders
  the demo-data banner (below) from `/coverage` on every request, so
  every page — including `/methodology` and `/about` — is
  server-rendered on demand and nothing is baked in at build time (the
  `web` CI job and the image build run without an API: a failed call
  simply shows no banner). Data pages declare `force-dynamic` themselves
  as well.
- **Synthetic labelling.** `components/synthetic-banner.tsx` is an
  async server component the layout renders: it calls `getCoverage()`
  and shows a persistent, non-dismissable `role="note"` banner ("Demo
  data: this site currently includes a synthetic dataset; synthetic
  records are labelled") when `synthetic_present` is true, and nothing
  when it is false or the call fails. `SyntheticBadge`
  (`components/badges.tsx`) sits beside every entity whose `synthetic`
  flag is true: a judge, court, or case header, a search result, a case
  row, a provenance entry, a coverage source. `ActorBadge` covers every
  `ActorType` (the judge alone takes the filled variant) and
  `DiscretionBadge` the discretion classification, so a prosecutor's
  dismissal is visibly not a judge's.
- **Pages.** `/` (headline, global search, coverage tiles from
  `/jurisdictions`, the list totals, and the case counts of
  `/coverage`, methodology link), `/search` (`?q=` → `/search`,
  entity-type badges for judges, courts, and exact case numbers, the
  synthetic badge, the 429 wait time when the limiter answers),
  `/judges/[judgeId]` (identity, status, sortable service table, FJC
  biography link by `nid`, the "Cases" panel — count, coverage window,
  link to the case list — and the "Source coverage" panel: source name,
  retrieved-at, truncated sha256 with copy, parser version, ingest run,
  source export link, "Report a data issue" to the GitHub data-source
  issue form), `/judges/[judgeId]/cases` (the four API filters as a
  plain GET form, a paginated table newest filing first, rows linking to
  the case page; malformed query values are dropped before the API is
  called and the API's inverted-range 422 becomes the error state),
  `/cases/[caseId]` (header with court link, number, type, status,
  filed and closed dates, pseudonymous parties; the timeline as an
  ordered list with `<time>` elements, actor and discretion badges, and
  the source per entry (`components/case-timeline.tsx`); the charges
  table with the disposing actor; judge assignments; the disposition;
  attributed decisions with pretrial detail; the sentence; and the
  "Sources" panel through `ProvenancePanel`), `/courts/[courtId]`
  (court, type, jurisdiction, a date form driving
  `/judges?court_id=&active_on=`, paginated), `/methodology` (the ten
  principles, the association-is-not-causation statement, the Phase 3
  note), `/coverage` (one card per source with a row-count table, the
  filing window, the last run, and the source documentation link; the
  Phase 3 completeness note), `/about`.
- **Accessibility.** Skip link, `header`/`nav`/`main`/`footer`
  landmarks, `scope="col"` on every table header, `aria-sort` on the
  sortable table, visible `:focus-visible` rings, the `/` shortcut
  focusing search, forms that work without JavaScript (plain GET).
- **Theme.** `next-themes` writes `data-theme="light|dark"` on `<html>`
  before paint (preference in `localStorage`, never a cookie); the
  Tailwind `dark` variant and the shadcn tokens key on that attribute.
- **Security gate for the web tier.** `pnpm lint` runs ESLint with
  `eslint-plugin-security` and `--max-warnings 0` (`react/no-danger`
  and `no-eval` are errors); `pnpm audit --audit-level=high` runs in
  CI; `tests/unit/bundle-secrets.test.ts` scans the production build
  for any `JUDGEMETRICS_` variable; the Python hygiene test checks that
  no `process.env` read outside `NEXT_PUBLIC_*` exists in `web/`.
  Response headers add `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, and a strict referrer policy;
  `poweredByHeader` is off.
- **Image.** `infra/docker/web.Dockerfile` builds on `node:22-alpine`
  with pnpm from corepack (the version pinned by `packageManager`), the
  Next.js standalone output, a non-root user (uid 10001), Alpine
  security updates, and npm/corepack/yarn removed from the runtime
  stage (their vendored modules are what scanners flag; only `node`
  runs the server). `NEXT_PUBLIC_API_BASE_URL` is a build argument
  because Next.js inlines it at build time; the Compose `web` service
  (profile `app`, port 3000) builds it with `http://api:8000` unless
  `WEB_API_BASE_URL` overrides it. CI builds, smokes, and Trivy-scans
  both images.
- **Tests.** Vitest (client helpers with a stubbed `fetch`, the
  provenance panel's truncation, copy, and synthetic label, the banner
  rendering only on `synthetic_present`, the badges, the timeline entry
  rendering, schema freshness, bundle scan); Playwright
  `web/tests/e2e/smoke.spec.ts` against a running web app and API (home
  and the `/` shortcut, search by a fixture surname, judge page service
  rows and source panel, theme toggle, court page by date, 404 and the
  methodology statement, the case flow — search a synthetic judge → the
  judge page shows the banner, badge, and cases panel → the filtered
  cases list → the case page renders the timeline, charges, a
  prosecutor and a judge actor badge, the sentence, and the sources
  panel — and the coverage page). The golden fixture and the demo seed
  name different judges, so the case flow discovers its judge and case
  through the API (a synthetic circuit court → its judges → a closed
  case with a prosecutor dismissal, a judicial decision, and a
  sentence) and holds on either dataset. The Playwright config starts
  nothing: the `e2e` CI job migrates, ingests the FJC fixture and the
  golden synthetic fixture (`tests/fixtures/golden`, with the job's
  `JUDGEMETRICS_IDENTIFIER_PEPPER`), starts the API and the built web
  app, and runs Chromium; locally the operator runs `uv run poe dev-api`
  and `pnpm dev` (or `pnpm build && pnpm start`) over a database that
  holds the FJC fixture (or live ingest) and `uv run poe seed` first.

## Metrics engine

The metrics engine (`src/judgemetrics/metrics/`, Phase 3) computes every
published number from a versioned registry over a typed analytic frame.
Step 1 landed the contract and the pure functions below; Step 2 adds the
snapshot export, the compute dispatch, suppression, publishing,
verification, and pipeline step 13 on top of them.

```
   data/reference/metric_registry.yaml        docs/METHODOLOGY.md
   version · methodology_version ·            (rendered from the registry:
   known_limitations · suppression · metrics   judgemetrics methodology
          │ load_registry (yaml.safe_load,      render [--check])
          │  validated against the vocabulary)
          ├──▶ metric_definition  (sync_definitions: upsert on slug + version)
          ▼
   Frame  cases · assignments · charges · decisions · sentences · events ·
          justice_events · persons · coverage window · observable outcomes
          ◀── tests/property/support.frame_from_world   (in-memory world)
          ◀── metrics/snapshot.py  Snapshot.frame(source) (DuckDB views over
          ▼                        <snapshot_dir>/<content_hash>/*.parquet)
   attribution ─▶ index_events ─▶ exposure ─▶ windows ─▶ censoring
   (the gate)     (the cohort)    (time at    (first      (followed members,
                                   risk)       outcome)    Kaplan-Meier)
                                                          └─▶ intervals
                                                              (Wilson, Greenwood)
          ▼
   compute.py  compute_all → ObservationDraft per metric, subject, window,
               dimension (members: kind, id, counted, followed) | NotObservable
          ▼ suppression.apply (threshold per metric)
   publish.py  metric_snapshot ⊕ metric_observation ⊕ metric_observation_member
               (chain completeness, supersession, unchanged subjects skipped)
          ▼
   verify.py   every current observation recomputed from its own snapshot
```

- **The registry is the contract.** `data/reference/metric_registry.yaml`
  carries `version`, `methodology_version`, the brief's eight statistical
  warnings verbatim as `known_limitations`, the suppression rule and its
  rationale, and one entry per metric (`slug`, `name`, `kind`,
  `subject_types`, `population`, the prose `description`, `numerator`,
  `denominator`, and `eligibility`, the structured `attribution` block,
  optional `counted` conditions and a median's `measure`, `index_event`,
  `outcome`, `windows_days`, `dimension`, `suppression_threshold`,
  `unit`, `version`). `metrics.registry.load_registry` reads it once with
  `yaml.safe_load` and validates every value on load — slugs unique and
  snake_case, kinds, subject types, gates, units, populations, and
  dimensions in their fixed enumerations, every actor, discretion,
  decision type, outcome, and counted value in the case vocabulary, every
  windowed rate and survival estimate carrying an index event, an outcome,
  and the brief's six windows — and raises `RegistryError` naming the slug
  and the field otherwise. `sync_definitions(session)` mirrors the entries
  into `metric_definition` on `(slug, version)` with `IS DISTINCT FROM`
  guards: new versions insert, changed rows update, unchanged rows are not
  written, nothing is deleted. A data-semantics finding edits the entry,
  bumps its `version` (and the registry `version`), and re-renders the
  methodology; `docs/METHODOLOGY.md` is a committed snapshot that the
  unit test and `methodology render --check` compare with the render.
- **The frame.** `metrics.frame.Frame` is a frozen bundle of Polars
  DataFrames with documented schemas (`cases`, `assignments`, `charges`,
  `decisions` with their pretrial-release columns, `sentences`, `events`,
  `justice_events`, `persons`) plus the source's `coverage_start`,
  `coverage_end` (`coverage_end_exclusive_at` is the day after at 00:00
  UTC), and `observable_outcomes`. Every timestamp is a UTC `Datetime`;
  every id column shares one dtype per frame (`String` for the synthetic
  world's ids and for UUIDs rendered as text; Polars has no UUID type),
  and the functions only compare, join, group, and sort ids. `persons.id`
  is the resolved person after merges and the frame's only person column.
  Loaders: `tests/property/support.frame_from_world` builds one from an
  in-memory synthetic world (true person ids), and Step 2's
  `snapshot.py` from a Parquet snapshot of one source's rows.
- **Attribution gates** (`metrics.attribution`). A registry rule filters
  rows (`decision_type`, `actor_types`, `discretion`) and ties them to a
  subject through its gate: `deciding_judge` (the decision's judge),
  `assigned_at_time` (the event time falls in one of the judge's
  assignment intervals on the case, `start_at <= t < end_at`, a null end
  open), `assigned_ever` (any assignment of the judge on the case: the
  eligibility gate), `sentencing_judge` (the sentence's judge), and
  `court_of_case` (the court's cases, which is what a court subject always
  gets). A judge never receives a statutory release or a decision with an
  unknown actor or discretion, whatever a rule admits; the court-level
  `statutory_release_count` and `unknown_actor_pretrial_count` count them
  explicitly.
- **Index events** (`metrics.index_events`). `(person, case, kind,
  index_at)`, identified by the canonical row it comes from
  (`member_kind`, `member_id`): `pretrial_release` (an attributed pretrial
  decision with `detained_flag = false` and a release time; the decision),
  `disposition` (a disposed case at the latest `disposed_at` of its
  disposed charges, attributed at that time, one per person with a
  disposed charge; the case), `sentence` (an attributed sentence at
  `sentence_at`; the sentence).
- **Exposure** (`metrics.exposure`). Time at risk starts at the index
  time; for the `disposition` and `sentence` kinds a sentence with a
  positive `incarceration_days` defers it to `sentence_at +
  incarceration_days` (the member sentence, or the latest term of the same
  case and person). Only the index case's sentence defers exposure; other
  terms the person serves are not modelled — a documented limitation.
- **Windows and censoring** (`metrics.windows`, `metrics.censoring`). An
  outcome counts for window `w` when an event of the type occurs in
  `(exposure_start, exposure_start + w days]`; `new_case`, `new_charge`,
  and `reconviction` count only in another case of the person
  (`related_case_id`), the rest in any case. `first_outcomes` computes
  each member's first qualifying outcome once; `outcome_flags`,
  `followed_flags`, and `member_windows` evaluate the six windows from it
  (the member rows Step 2 publishes: `has_outcome`, `followed`,
  `counted`). A member is followed for `w` when `exposure_start + w days
  < coverage_end_exclusive_at`; `fixed_window_rates` divides the followed
  members with an outcome by the followed members and reports `eligible`
  (the whole cohort) beside them. `kaplan_meier` runs the product-limit
  estimator over the whole cohort with censoring at the coverage end,
  events before censorings at the same time, and publishes `1 - S(w)` with
  the Greenwood standard error; when every member is followed for `w` it
  equals the fixed-window rate. A metric whose outcome is not among the
  source's observable outcomes yields `NotObservable`, never a zero.
- **Intervals** (`metrics.intervals`). `wilson(numerator, denominator)`
  for shares and fixed-window rates, `normal_interval(estimate,
  standard_error)` clipped to `[0, 1]` for Kaplan-Meier; a zero
  denominator yields nulls; everything is rounded to six decimals at the
  boundary only.
- **Tests.** `tests/unit/test_metric_registry.py` (the file loads, a
  tampered copy fails naming the slug and field, the warnings equal the
  brief's XML, the pretrial and dismissal prose equals the golden truth's
  definitions or states the difference), `test_attribution.py` (each gate
  over a hand-built frame, the two exclusions), `test_methodology_render.py`
  (the committed document equals the render, 80 columns, verbatim
  warnings, the CLI's `--check`), `tests/property/test_frame_invariants.py`
  (Hypothesis over in-memory `TINY` worlds: no outcome before its exposure
  start, `numerator <= followed <= eligible`, monotone numerators, bounded
  monotone survival equal to the rate when fully followed, exposure
  deferral, the statutory exclusion, and equality with `synthetic/truth.py`
  for the pretrial-release cohorts, followed counts, and numerators),
  `tests/integration/test_metric_registry_sync.py`, and the migration
  round trip through `0005`.
- **Snapshots** (`metrics.snapshot`, Step 2). `export_snapshot(session,
  settings)` reads the canonical tables a metric reads — `court_case`
  with its source through `source_record`, `judge_assignment`, `charge`,
  `decision` joined to `pretrial_release`, `sentence`, `court_event`,
  `justice_event`, `person` (id and `merged_into_person_id` only),
  `judge` (id), `court` (id, jurisdiction), `source` (id, name, type,
  coverage window, observable outcomes) — through SQLAlchemy Core into
  Polars and writes one Parquet file per table plus `manifest.json`
  (table → sha256 and row count) under `<snapshot_dir>/<content_hash>/`
  (`JUDGEMETRICS_SNAPSHOT_DIR`, default `data/snapshots`, git-ignored),
  where `content_hash` is the sha256 over the sorted `table:sha256`
  lines. Rows are ordered by id and Polars writes Parquet
  deterministically, so the same data always yields the same hash; the
  directory is created with `mkdir(exist_ok=False)` and never
  overwritten — an export whose hash already exists reuses it. No
  restricted table is read, every id is the canonical UUID as text, and
  every timestamp is stored as a naive UTC microsecond `Datetime` (DuckDB
  returns timezone-aware values only through `pytz`, which is not a
  dependency); the loader re-attaches `UTC`. `open_snapshot(settings,
  hash)` validates the hash as 64 hexadecimal characters before it
  becomes a path, checks every file against the manifest, and registers
  each Parquet file as a view of an in-memory DuckDB database through the
  relation API (`read_parquet` over a path the module built; no extension
  is installed or loaded). `Snapshot.frame(source_id)` runs parameterized
  queries over those views and builds the `Frame` of one source: the
  cases of the source's records and their child rows, every person
  column re-pointed at its merge survivor, the stored justice events of
  those persons for the any-case outcomes (`failure_to_appear`,
  `release_violation`, `revocation`, `rearrest`), and the other-case
  outcomes derived at load time from the merged person's cases and
  charges exactly as the truth's `outcomes_of` does — `new_case` at the
  earliest charge filing of each case (the case row carries a date only),
  `new_charge` at every charge filing, `reconviction` at every convicted
  charge's disposition, each keyed by its own case — because the
  synthetic connector derives `new_case` and `reconviction` per
  participant id before the rule stage merges the planted split persons
  and never derives `new_charge`. Derived rows carry ids of the form
  `derived:<type>:<case id>:<instant>` and are never observation
  members. The `charges` frame table carries the source's `source_row_id`
  (Step 2 addition) because the lead convicted charge of a case breaks
  severity ties by the source's charge id — the canonical UUID would make
  a re-ingest choose a different lead (the demo world has 51 such ties).
- **The compute dispatch** (`metrics.compute`). `compute_all(snapshot,
  registry, subjects=None)` iterates the sources with case data (a
  source without a declared coverage window is skipped and named),
  builds the frame, enumerates the subjects — every judge with an
  assignment, decision, or sentence in the source, every court with a
  case — and dispatches each registry metric on `kind`: `count` (the
  attributed population rows with the `counted` conditions;
  `eligible_defendants` counts distinct resolved persons among the
  eligible cases and its members are the cases, never a person id),
  `share` (numerator over denominator, Wilson interval),
  `windowed_rate` (index events → exposure → first outcome → one
  observation per window: `eligible_count` the whole cohort,
  `cohort_size` the followed members, `observed_count` the followed
  members with the outcome), `survival` (the Kaplan-Meier `1 - S(w)` per
  window over the whole cohort with the Greenwood interval),
  `distribution` (one observation per vocabulary value of the dimension,
  zero counts included, the whole map in `distribution`), and `median`
  (over the rows with a value, `cohort_size` the `n`, grouped by the
  offense category of the case's lead convicted charge when the
  dimension says so). Shares, rates, and survival estimates fill
  `observed_rate` (six decimals) with their interval in the two bounds;
  medians fill `value`; distributions fill `distribution`. A metric whose
  outcome the source cannot document returns `NotObservable`: no
  observation, never a zero. Every draft carries its members `(kind, id,
  counted, followed)` — the population rows of a count, share,
  distribution, or median (`followed` and `counted` mark the denominator
  and numerator), the index events of a windowed metric — and
  `suppression.apply` sets `suppressed_flag` when `cohort_size` is below
  the metric's threshold; the stored row keeps its numbers (the API
  withholds them in Step 3).
- **Publishing** (`metrics.publish`), in the caller's transaction.
  First the chain-completeness rule: every member id of every draft must
  be present in the snapshot's own tables, otherwise `ProvenanceError`
  is raised before anything is written and the caller rolls back (Step
  3's trace test relies on it). Then `metric_snapshot` is upserted on
  `content_hash`, `sync_definitions` runs, and per subject and source
  the current observations (`superseded_at IS NULL`) and their members
  are compared with the drafts over every column of `VERIFIED_COLUMNS`
  and the member multiset: an unchanged subject is left in place — no
  supersede, no insert, so a recompute without data changes writes
  nothing — and a changed one has its current observations superseded
  (`superseded_at = now()`) and the new observations and members
  inserted in batches of 500 rows per statement. Nothing is ever
  deleted; an observation a previous publish superseded and that the
  same snapshot and definition produce again is revived rather than
  re-inserted (`uq_metric_observation_key` spans superseded rows).
  Observation and member rows carry entity ids only; log lines carry the
  snapshot id, counts, and slugs.
- **Verification** (`metrics.verify`). `verify(session, settings,
  snapshot=None)` loads every current observation (or one snapshot's),
  opens each snapshot from `snapshot_dir`, recomputes the observations'
  subjects with the registry version they record — the current registry
  file must carry that `registry_version` and the definition's `(slug,
  version)`, otherwise the observation is `unverifiable` — and compares
  every column of `VERIFIED_COLUMNS` and the member multiset exactly,
  reporting each mismatch with the observation id, slug, subject,
  window, dimension, column, and both values; an observation the
  recompute no longer produces, and a recomputed observation the store
  lacks for a subject it holds, are mismatches too. `judgemetrics
  metrics verify [--snapshot HASH] [--json]` exits 1 on any mismatch or
  unverifiable observation.
- **Pipeline step 13** (`ingest.runner.recompute_metrics`). After the
  publish and the resolution rule stages, `impacted_subjects` closes
  over what the run published: the touched cases (every published
  case-level draft and the related cases of published justice events),
  widened to every case of the persons those rows name — an outcome is
  the person's, so a changed charge or event in one case moves the
  cohorts of the person's other cases; the judges are those the
  published assignment, decision, and sentence drafts name plus every
  judge with an assignment, decision, or sentence on a touched case; the
  courts are those of the published case drafts plus the courts of every
  touched case. When `Settings.metrics_recompute_on_ingest` is on and
  the set is non-empty, `metrics.engine.compute_and_publish` exports a
  snapshot through the same session (so the run's rows are in it),
  computes and publishes those subjects only — unchanged ones are left in
  place — and records the snapshot in `ingest_run.metrics_snapshot_id`
  (revision 0006; a column rather than a `checkpoint` key because the
  whole checkpoint is handed back to a checkpointing connector). A
  reference-only run (FJC) touches nothing and computes nothing; an
  unchanged rerun publishes no draft and computes nothing. The test
  suite turns the setting off (`tests/conftest.py`) and the step-13
  tests enable it per test.
- **Commands.** `judgemetrics metrics compute [--label TEXT] [--subject
  judge:<uuid> ...] [--json]` (export, compute, publish; prints the
  snapshot hash and counts) and `metrics verify [--snapshot HASH]
  [--json]`, both as the ingest role; `uv run poe compute-metrics` and
  `make compute-metrics`.
- **Coverage and observability.** `SourceInfo.observable_outcomes`
  (synthetic: `new_case`, `new_charge`, `reconviction`,
  `failure_to_appear`, `revocation`; FJC: none) fills
  `source.observable_outcomes`, and the optional `SupportsCoverage`
  protocol (`coverage_window()`, read by the runner after `load_context`
  so a connector may read it from the export — the synthetic connector
  reports the manifest's `corpus` dates, `GENERATOR_VERSION` 2) fills
  `source.coverage_start`/`coverage_end`; both are written only when they
  differ.
- **The truth generator** (`synthetic/truth.py`, `TRUTH_VERSION` 2) is
  the independent oracle: windowed cohorts for every index kind with
  exposure deferred by the index case's incarceration term, every
  outcome's fixed-window rate and Kaplan-Meier estimate per window,
  `release_violation` and `rearrest` under `not_observable`; it imports
  nothing from `metrics/`. `tests/unit/test_metrics_compute.py` proves
  `compute_frame` over `frame_from_world` equals it on the golden world
  and `tests/golden/test_golden_metrics.py` proves the database path
  equals it on the golden fixture (`tests/golden/truth_map.py` is the
  one table both read).
