<!-- docs/ARCHITECTURE.md -->
# Architecture

The system-level picture is in
[`docs/roadmap/ROADMAP.md`](roadmap/ROADMAP.md) §3. This document
describes what is built: the ingest pipeline (Phase 1
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
the same row upserts in place — except for a case party, whose
`source_row_id` is `<party_type>:<ordinal>` (revision 0008: the party's
position within its case and party type, never the participant id, which
reaches the database only as a hash); a party's restricted attribute is
`("party_attribute", *case_key[1:], party source_row_id, attribute)`; a
derived justice event is keyed on the person hash, the event type, the
instant (UTC), and the related case. `describe_key` renders any key for
an issue description or log line without the person hash, and no key
carries a restricted attribute's value.

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
The case party row keys on `<party_type>:<ordinal>` — its 1-based
position within the case and party type in code-point order of the
normalized participant ids — not on the participant id: until revision
0008 (Phase 4 Step 1) `case_party.source_row_id` held the normalized
participant id itself, a plaintext identifier in an app-readable
column. The migration rewrote the existing keys in the same order
(`COLLATE "C"`), so a re-ingest upserts onto them unchanged.

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
manifest and builds the court-code index, each participant's case
timeline from `charges.csv`, and each party's ordinal within its case
from `participants.csv`, `validate_raw` checks the manifest's
`generator_version` and each file's header set (missing → error naming
the header, extra → warning), and `normalize` maps rows onto the drafts
(`normalize.py`, one section per file), deriving justice events —
`new_case` when a participant has an earlier case, `reconviction` when a
conviction follows an earlier disposition of another case,
`failure_to_appear` and `revocation` from the court events — and
publishing each party's restricted `age_band` and `synthetic_group` into
`restricted.party_attribute` (parser version 2). `judgemetrics
ingest run synthetic --from-fixture tests/fixtures/golden` reads the
golden fixture through the runner's fixture path, which accepts
contained relative ids for this reason.

### Restricted schema

The PostgreSQL schema `restricted` (revision 0008) holds the attributes
the root roadmap classifies as restricted: `restricted.party_attribute`,
one row per case party per attribute (`age_band`, `synthetic_group`),
keyed `(case_party_id, attribute)` and cascading with its party
(`docs/DATA_MODEL.md` "The restricted schema"). Its boundary:

- **Grants.** `USAGE` for `judgemetrics_ingest` and `judgemetrics_admin`
  only, DML for the ingest role and every privilege for the admin role
  (by table grant and by default privilege), `PUBLIC` revoked, and no
  grant of any kind to `judgemetrics_app`: the public API cannot name the
  table. `03-test-database.sql` revokes the app role's usage again on
  every `uv run poe up`. The admin role holds `CREATE` on the database
  so a migration can create the schema.
- **Writes.** The ingest runner publishes a `PartyAttributeDraft` after
  the parties it belongs to, in the ingest transaction, with the natural-
  key upsert and `IS DISTINCT FROM` guard of the other case-level tables
  (`ingest/publish.py` `upsert_party_attributes`); an attribute whose
  party is not in the run is rejected (`unresolved_party`). The draft's
  `repr` withholds its value; the run log carries the table's row counts
  only.
- **Reads.** Nothing in the public API, the metrics engine, or the
  snapshot reads it: the snapshot checks every table it exports against
  the schema (`refuse_restricted`, by `RESTRICTED_SCHEMA`, never by table
  name), and no module under `metrics/` names a restricted attribute
  (unit test and `verify_phase03.py` check 9, recursively). The one reader
  is the aggregate subgroup calibration (Phase 4 Step 4,
  `validation/fairness.py`, "Validation" under "Risk adjustment"), on the
  ingest role's session only; `tests/unit/test_restricted_readers.py` fails
  when any other module under `src/judgemetrics/` names the table
  (`party_attribute`, `PartyAttribute`, `restricted.<name>`, or
  `schema="restricted"`) outside the ORM model and Step 1's write path.
- **Logs.** `age_band`, `synthetic_group`, and `attribute_value` are on
  the scrubber's denylist (never a bare `age`, which would redact
  `stage=` and `message=`).
- **Migrations.** `alembic/env.py` runs with `include_schemas`, filtered
  to `public` and `restricted`, so `uv run alembic check` compares the
  schema; `RESTRICTED_SCHEMA_TABLES` (`db/models/__init__.py`) lists its
  tables beside `RESTRICTED_TABLES`.

### Refusals

`run_ingest` records `status = refused` without touching anything when
`JUDGEMETRICS_ENV=production` and either the connector's
`source_info.source_type` is `synthetic` or `--from-fixture` is given.
`judgemetrics seed` generates nothing in production and records the same
refusal.

## Database roles

| Role                  | Used by                                              | Rights                                            |
|-----------------------|------------------------------------------------------|---------------------------------------------------|
| `judgemetrics_app`    | the API (`JUDGEMETRICS_DATABASE_URL`), `ingest runs`, `provenance trace` | `SELECT` on public tables; `INSERT` only on `correction_request` (revision 0007); nothing on `person_identifier`, `entity_resolution_candidate`, `audit_log`; no `USAGE` on the `restricted` schema (revision 0008) |
| `judgemetrics_ingest` | `ingest run`, `seed`, `er …` (`JUDGEMETRICS_INGEST_DATABASE_URL`) | `SELECT, INSERT, UPDATE, DELETE` on every table except `audit_log` (`SELECT, INSERT`: append-only), `restricted.party_attribute` included (`USAGE` on `restricted`); no DDL |
| `judgemetrics_admin`  | `db upgrade` / `downgrade` (`JUDGEMETRICS_ADMIN_DATABASE_URL`) | full control of the public and `restricted` schemas and `CREATE` on the database (a migration creates a schema; not a superuser) |

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

- **Routes** (`api/routes/{judges,courts,jurisdictions,cases,search,
  coverage,metrics,corrections}.py`)
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
  newest of all, is what `/ready` reports, with `snapshot_models` — Phase 4
  Step 3, one more statement — counting that snapshot's outcome models by
  status for its newest specification version: counts and versions, never
  a model hash or an artifact path). `repositories.metrics`:
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
  `lower`, `upper`, and (Phase 4 Step 5) the adjusted figures `expected`,
  `expected_rate`, `ratio`, `ratio_lower`, `ratio_upper`, and
  `pooling_weight` in a validator whenever `suppressed` is true, so every
  shape that carries a number (`Observation`, `CompareRow`, the traced
  observation) withholds it whatever the caller passed; `suppression_reason`
  and the cited `model` (`ModelRef`) survive. The stored row keeps its
  numbers for `metrics verify`. `services.metrics.figures` is the one
  mapping from stored columns to those fields: an adjusted row's two bounds
  become `ratio_lower`/`ratio_upper` (the pooled ratio's bootstrap interval,
  unbounded above) and its `lower`/`upper` stay null, so the `[0, 1]`
  bounds of a share never carry a ratio.
- **The model card (Phase 4 Step 5)**: `GET /models/{model_id}`
  (`api/routes/models.py`, `StrictQuery()` with no parameter,
  `cache_public`) is one statement (`repositories.models.model_card_row`:
  the `outcome_model` row with its snapshot hash and source, `storage_uri`
  never selected, and an `EXISTS` that a current observation still cites
  the model's snapshot — a model every observation has moved on from is a
  404, as a superseded observation is) mapped by `services.metrics.model_card`
  from the catalogue row alone, never the artifact: training counts and
  range, the temporal validation and its calibration bins, the coefficient
  table, the versions, and `methodology_url` anchored at
  `#adjusted-statistics`. Every adjusted observation and compare row carries
  a `ModelRef` (`url` is the API path) from an outer join to
  `outcome_model` in its existing statement, so the budgets did not move;
  the provenance route passes `settings` to `trace`, whose artifact check
  (`artifact_ok`) needs the snapshot directory, and names the model with
  its training counts in the body.
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
Tailwind CSS, shadcn/ui, TanStack Table, `next-themes`) is a
presentation layer over API v1 with one write path, the corrections
form (below). It holds no data, sets no cookies, loads no third-party
script, and reads exactly one variable, `NEXT_PUBLIC_API_BASE_URL`
(default `http://localhost:8000`).

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
  (below), `/jurisdictions/[jurisdictionId]` (below), `/corrections`
  and `/corrections/received` (below), `/compare` (below),
  `/methodology` (below), `/coverage` (the "Snapshot" card — registry
  and methodology versions, the newest snapshot hash and time — and one
  card per source with a row-count table, the filing window, the
  declared coverage window, the observable outcomes and the registry
  outcomes the source cannot document, the source's latest snapshot and
  methodology version, the last run, and the source documentation link;
  `/coverage` and `/metrics` are fetched together), `/about`.
- **Metric surfaces (Phase 3 Step 4).** `components/metric-stat.tsx` is
  the presentation-rule component and the only way an observation (a
  published number) is rendered: label, primary figure (a rate as a
  percentage, a median as days, a count as an integer, one value of a
  distribution as its share), numerator / denominator, the eligible
  count when it differs, the interval with its method, the period, the
  coverage (source, window, observable), the sample-size line, the
  methodology link anchored at the slug (`methodology_url` passed
  through), and the synthetic badge; a suppressed observation renders
  the notice with the threshold and no figure slot at all
  (`data-testid="metric-stat"` with `data-slug`, `data-window`,
  `data-dimension`, `data-suppressed`, `data-variant`); `MetricNotObservable`
  is the row for a metric the source cannot document. `lib/metrics.ts`
  groups `SubjectMetrics.observations` by slug → window → dimension,
  resolves the window from the registry's `windows_days` (default 365,
  never a literal in a page), formats every field null-safely, builds
  the cohort labels, the case and compare links, and the cohort
  position (judges, published figures, median, rank) from compare rows;
  `JUDGE_PANELS` names the unwindowed slugs of each panel while windowed
  metrics are placed by the registry's `index_event`, so a new outcome
  metric lands in the right panel and an unlisted judge metric falls
  into "Other metrics" rather than vanishing. The judge page fetches
  `/judges/{id}`, `/judges/{id}/metrics`, and `/metrics` together, then
  `/courts/{id}/metrics` (the judge's current or latest court, for the
  pooled value) and one `/metrics/compare` per compared definition
  (shares, rates, survival estimates, medians; `Promise.all`), and
  renders the association statement, then Cases, Pretrial, Outcomes
  after qualifying release (window and cohort selectors), Disposition
  (with the after-disposition outcomes), Sentencing (with the
  after-sentence outcomes), then the service table, cases panel, and
  provenance panel. Every panel is a `MetricPanel` (`id` is the anchor)
  with a "View eligible cases" link to `/judges/[id]/cases` filtered
  with `status=closed` for Disposition and Sentencing (the cases route
  has no pretrial, disposition, or sentence filter; unfiltered
  otherwise). A failed registry or metrics call renders one `ErrorState`
  in place of the panels; a failed pooled or compare call renders an
  `ErrorState` inside the affected panel and the stats still render.
  The cohort (`?cohort=court|jurisdiction`) and window (`?window=`) are
  query parameters read by the server page; `components/cohort-selector.tsx`
  (`CohortSelector`, `WindowSelector`) and `components/query-select.tsx`
  are client components that render a plain GET form with the other
  parameters as hidden inputs, submitting on change (and through an
  Apply button without JavaScript), so the page state is the URL.
  `/compare` (`app/compare/page.tsx`) holds its whole state in the query
  (`metric`, `window`, `court_id`, `jurisdiction_id`, `sort`, `order`,
  `offset`, plus `judge` to highlight a row), validates it against the
  registry before any fetch (unknown metric, a window the metric lacks,
  a malformed id, an unknown sort or order, a negative offset → an
  `ErrorState` with a 422-shaped validation error, never a crash), and
  renders `components/compare-table.tsx` — the API's order, header
  links that flip `sort`/`order`, `aria-sort`, fraction, figure,
  interval, sample size, period, coverage warning, the suppression
  notice in place of the figures of a suppressed row — with pagination
  and a "Comparison notes" card (cohort definition, reference period,
  formula, methodology link, the association statement and the case-mix
  warning). The court list is two `/courts` pages (100 each; a court
  search arrives with a larger registry). `/methodology` is
  `force-dynamic` from `GET /api/v1/metrics`: the statement (unchanged
  text and test id), the principles, "How to read a number", "Index
  events, exposure, and censoring", "Attribution" (the API's
  `how_to_read`, `semantics`, `attribution_notes` — the renderer's own
  constants, so the page and `docs/METHODOLOGY.md` never diverge), one
  `<section id="<slug>">` per definition, "Suppression", "Known
  limitations" (verbatim list, `data-testid="known-limitations"`), the
  changelog, and the links; every string is a React text node.
- **Adjusted statistics (Phase 4 Step 5).** `components/adjusted-stat.tsx`
  (`AdjustedStat`) is the only renderer of an adjusted figure as a stat:
  label and synthetic badge; for a published ratio the observed and
  expected events, the pooled ratio with its 95% bootstrap interval, the
  pooling weight as a sentence, the eligible count and the members in the
  ratio, and the brief's interpretation (`Registry.adjustment.interpretation`);
  for a suppressed one the reason in words (`adjustedSuppressionText`: the
  threshold and the registry's `minimum_expected`, never literals) and no
  figure region; always the period, the coverage, the cohort definition
  the page passes (`adjustedCohortDefinition`: model and specification, the
  index events it was fitted on from the model card, the source and its
  coverage window, the specification's features, the cohort label), the
  model link (`/models/<id>`), and the methodology version as visible text
  (`data-testid="adjusted-stat"`, `data-slug`, `data-window`,
  `data-suppressed`, `data-reason`). `CompareTable` has its own adjusted
  columns (observed / expected, O/E pooled with the bounds and the method
  in the header, pooling weight, sample size with the members in the
  ratio) and spans a suppressed adjusted row's three figure columns with
  its reason; its court and suppressed cells wrap so the table fits the
  page. The judge page's `JUDGE_PANELS` gains "Risk-adjusted comparison"
  (`id: "adjusted"`, `kind: "observed_expected"`) after the outcomes
  panel: `panelDefinitions` collects exactly the adjusted definitions for
  it and excludes them from every other panel (the new-case ratio shares
  the outcomes panel's index event) and from "Other metrics"
  (`uncoveredDefinitions`); the panel reuses the `?window=` and `?cohort=`
  selectors, places each ratio beside the raw rate it adjusts (`ADJUSTS`,
  compact `MetricStat`) with the cohort position over a `/metrics/compare`
  call sorted by `ratio`, and fetches the model cards of the shown ratios
  (at most three `/models/{id}` reads, cached 60 s). `COURT_PANELS` is
  unchanged: the ratios are judge-only. `/compare` lists the adjusted
  metrics, sorts them by `ratio` by default, and its notes state the
  formula (α + O) / (α + E), the interpretation, and link the model.
  `/models/[modelId]` (`force-dynamic`) renders the model card (status,
  training, versions, validation summary, calibration bins and
  coefficients as tables, a court level linked to its page) with links to
  `/methodology#adjusted-statistics` and the model's calibration section
  of `docs/VALIDATION.md` (`validationSectionUrl`, GitHub's heading
  anchor); a 404 is the not-found page. `/methodology` renders the
  `adjustment` block as `<section id="adjusted-statistics">` and describes
  the adjusted definitions through `KIND_TEXT` (`lib/metrics.ts`) with
  their target and minimum expected count.
- **Court and jurisdiction pages (Phase 3 Step 5).** `/courts/[courtId]`
  fetches `/courts/{id}`, `/metrics`, and `/courts/{id}/metrics`
  together, then the jurisdiction, the judges serving on `?active_on=`,
  and one `/metrics/compare?court_id=` for the selected metric
  (`?metric=`, default `pretrial_release_share`; `?window=` for a
  windowed one), and renders: the header with the jurisdiction link and
  "Report a data error"; the association statement; the court's own
  panels (`COURT_PANELS` in `lib/metrics.ts` — Cases, Pretrial with the
  court-only `statutory_release_count` and `unknown_actor_pretrial_count`,
  Outcomes after qualifying release with the window selector,
  Disposition, Sentencing; windowed metrics placed by `index_event`
  through `panelDefinitions`, every observation through `MetricStat`, a
  not-observable outcome through `MetricNotObservable`); "Comparable
  judges" (a `QuerySelect` over the compared judge-level definitions, the
  window selector, `CompareTable` with the API's order, an "Open in
  Compare" link to `/compare?court_id=…`, `EmptyState` for an empty
  cohort); the judges-serving-on-a-date table; and the provenance
  panel. `/jurisdictions/[jurisdictionId]` fetches `/jurisdictions/{id}`,
  `/courts?jurisdiction_id=`, `/coverage`, and `/metrics` together, then
  one `/metrics/compare?jurisdiction_id=`, and renders the name and type,
  the courts table (linked), the available years and the data
  completeness from the `/coverage` source rows that belong to the
  jurisdiction (`lib/jurisdictions.ts`: the sources in its provenance,
  plus every synthetic source when one of its courts is synthetic — a
  court summary carries the flag, not its provenance; the years span
  their declared coverage windows, and an FJC-only jurisdiction reads
  "no case data"), the jurisdiction-level compare table with the same
  controls, a trends placeholder (Phase 5), and the provenance panel.
  The coverage page lists every jurisdiction (`/jurisdictions`, first
  100) linked to its page, and the court header links its jurisdiction.
- **Corrections (Phase 3 Step 5).** `/corrections` is a server page
  reading `target_type`, `target_id`, and `label` from the query (the
  "Report a data error" links prefill them —
  `components/report-error-link.tsx` on the judge, court, and case
  headers and on every `MetricPanel` with its first observation's id
  through `firstObservationId`); when the type and id are valid it looks
  the target up (`/judges/{id}`, `/courts/{id}`, `/cases/{id}`, or
  `/metrics/{id}/provenance`) to show a summary, explains the correction
  process (received → reviewed against the source → corrected or
  suppressed → audited → answered), and hosts
  `components/correction-form.tsx`, a client component: read-only target
  fields when prefilled (a select and an id input otherwise), the reason
  textarea and contact input with the API's limits from
  `lib/corrections.ts` (`LIMITS`, mirrored from `CorrectionIn`), an
  optional http(s) URL for supporting material (no file upload), the
  consent line, submit disabled until `validateCorrection` passes,
  pending and error states, per-field errors from the handler's map or
  parsed out of the API's 422 message (`fieldErrorsFromMessage`), the
  429 wait from `Retry-After`. The form posts JSON to the route handler
  `app/api/corrections/route.ts` (`POST /api/corrections`;
  `lib/corrections-handler.ts`), never to the API from the browser: one
  origin for the browser (no CORS surface on the API's write path), one
  validated shape, the API's limiter keyed on the web server unless
  `JUDGEMETRICS_TRUST_PROXY` makes it key on the forwarded chain, and
  no way for page JavaScript to post arbitrary fields. The handler
  parses the body, validates it against the same limits, forwards
  exactly `ALLOWED_FIELDS` (`allowListedBody`, never a spread) through
  `submitCorrection(body, { forwardedFor })` with the request's
  `X-Forwarded-For` (Next.js sets it from the socket when no proxy did),
  and answers `202 {id, status}` or the API's error body under the API's
  status (`422`, `429` with `Retry-After`, `503`; an unreachable API is
  `503 network_error`), `Cache-Control: no-store`, no cookie, and no log
  line: the reason and the contact never leave the handler except
  towards the API. On success the form navigates to
  `/corrections/received?id=…`, which shows the id, the status, and what
  happens next, and never anything submitted.
- **Coverage cache.** `lib/coverage-cache.ts` is a module-level,
  in-process, unkeyed cache (`createCoverageCache`; the process-wide
  `coverageCache`) the banner reads `/coverage` through: a successful
  result is reused for sixty seconds, a failure is never cached,
  concurrent misses share one call, and the cache is bypassed under
  `NODE_ENV=test` so unit tests observe every fetch (the factory is
  tested with fake timers). The root layout stays `force-dynamic`.
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
- **Tests.** Vitest (the corrections validator, link builder, and 422
  parser; the route handler over a stubbed `submitCorrection` — the
  allow-list, the forwarded chain, every status mapping, and a spy on
  every console method asserting nothing is logged; the form — submit
  disabled until valid, the read-only target, the consent line, no file
  input, the posted body, the navigation, the API's field errors, 429
  and 503; the jurisdiction helpers; `COURT_PANELS`, `panelDefinitions`,
  `firstObservationId`, and the panel's report link; client helpers with a stubbed `fetch`, the
  provenance panel's truncation, copy, and synthetic label, the banner
  rendering only on `synthetic_present`, the badges, the timeline entry
  rendering, schema freshness, bundle scan; `lib/metrics.ts` helper by
  helper including the null-safe paths; `MetricStat` for every kind with
  every presentation field, the suppressed row's notice and digit-free
  figure region, the not-observable row, the panel, the row, the cohort
  line, and the compare table; the methodology page over a stubbed
  registry — every definition anchored, every limitation verbatim, the
  error state; the coverage cache's TTL with fake timers); Playwright
  `web/tests/e2e/metrics.spec.ts` (a synthetic judge found through
  `/metrics/compare` sorted by denominator → the judge page's statement
  before the panels and a `pretrial_release_share` stat with its fields
  → the window selector to 90 days → the compare link and the judge's
  row with its sample size → the methodology anchor with the formula;
  the compare page's validation and suppressed rows; the coverage v1
  fields), `web/tests/e2e/first-milestone.spec.ts` (the brief's
  checklist items 8–16, one test per item in order over one judge
  discovered through `/metrics/compare` and `/judges/{id}/metrics` — a
  synthetic circuit judge with an unsuppressed pretrial release share
  and 365-day new-case rate and a closed case —, plus the corrections
  submission through the form to the received page), and `web/tests/e2e/smoke.spec.ts` against a running web app and API (home
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
  nothing: the `e2e` CI job generates a throwaway identifier pepper and
  correction contact key into `$GITHUB_ENV` (never stored in the
  workflow), migrates, ingests the FJC fixture, seeds the demo-scale
  synthetic dataset (`judgemetrics seed --out data/synthetic/ci`; its
  judges' cohorts clear the suppression threshold, which the golden
  fixture's mostly do not) and computes the metrics, starts the API
  (with the key) and the built web app, and runs Chromium over the
  three suites; locally the operator runs `uv run poe bootstrap`, then
  `uv run poe dev-api` and `uv run poe dev-web` (or `pnpm build && pnpm
  start`), then `pnpm e2e`.

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
  is the resolved person after merges and the frame's only person column;
  `courts` (id, jurisdiction) carries the courts of the frame's cases
  (Phase 4 Step 2: the model's court and jurisdiction features).
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
- **Exposure** (`metrics.exposure`, methodology 0.2). Time at risk starts
  at the index time — for the `disposition` kind at the end of the index
  case's own term (`sentence_at + incarceration_days`, the latest when
  there are several) — and then moves past every incarceration term
  `[sentence_at, sentence_at + incarceration_days)` of the same (merged)
  person, in any case, that contains it, for every index kind: the first
  instant no recorded term covers. The chain is vectorized (one join of
  the starts to the person's terms per step, the containing term that
  ends last applied each time) and `deferral_days` totals the terms
  applied. Terms the source does not record are not modelled — the
  documented limitation that remains.
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
  restricted table is read and no table of the `restricted` schema is
  exported (`refuse_restricted`), every id is the canonical UUID as text, and
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
- **The truth generator** (`synthetic/truth.py`, `TRUTH_VERSION` 3) is
  the independent oracle: windowed cohorts for every index kind with
  exposure deferred by every incarceration term of the person
  (`deferred_start`, written independently of `metrics.exposure`), every
  outcome's fixed-window rate and Kaplan-Meier estimate per window,
  `release_violation` and `rearrest` under `not_observable`; it imports
  nothing from `metrics/`. `tests/unit/test_metrics_compute.py` proves
  `compute_frame` over `frame_from_world` equals it on the golden world
  and `tests/golden/test_golden_metrics.py` proves the database path
  equals it on the golden fixture (`tests/golden/truth_map.py` is the
  one table both read).

## Risk adjustment

Phase 4 compares observed outcomes with what a versioned model expects for
defendants with similar observable case characteristics (the brief's
`<risk_adjustment>`). Step 2 lands the model itself:
`src/judgemetrics/metrics/adjustment/` reads the specification, builds the
design from the analytic frame, fits it, and records every fitted model as a
canonical artifact and a catalogue row. Step 3 turns its predictions into
expected counts, ratios, pooled estimates, and intervals (below,
"Observed-to-expected ratios").

```
   data/reference/outcome_model.yaml  (version 1, expected-logit-v1)
   targets · features (known_at, missing, leakage) · excluded · model ·
   temporal_split · seed · bootstrap · pooling · thresholds · recovery
          │ spec.load_spec (yaml.safe_load; every feature checked against
          ▼               its builder's contract and the vocabulary)
   Frame (+ courts) ──▶ features.design_rows(frame, spec, target, window)
                         index events (the registry's gate) → feature levels
                         (strictly before the known-at instant) → missing
                         rule → encoding → rows ordered by source keys
          ▼
   fit.fit_frame  per target and window:
          ├─ events-per-column gate ─▶ insufficient_events (no fit)
          ├─ logistic.fit_logistic (L2, Newton, intercept unpenalized)
          │       └─▶ not_converged (no coefficients) | fitted
          ├─ temporal split (cutoff at the 75th percentile of index time)
          │       └─▶ diagnostics.evaluate (Brier, skill, AUC, bins, slope)
          └─ resample.replicates (person clusters, seeded stream) ─▶ refits
                  └─▶ diagnostics.stability
          ▼
   fit.fit_models(snapshot) ─▶ artifacts.render (canonical JSON, sha256 id)
          ▼                   └─▶ <snapshot_dir>/<snapshot>/models/<sha>.json
   catalog.fit_snapshot ─▶ outcome_model (one row per snapshot, source,
                           spec version, target, window, seed)
          ▼
   judgemetrics models fit | list | show | verify [--refit]
```

- **The specification is the contract.** `data/reference/outcome_model.yaml`
  is the third versioned reference file beside the case vocabulary and the
  metric registry. `metrics.adjustment.spec.load_spec` reads it once with
  `yaml.safe_load` and validates every field by name (an unknown field is
  rejected). Each target names a registry metric as its population — the
  release target `pretrial_decisions` (its gate is the published one), the
  windowed targets `new_case_rate` and `failure_to_appear_rate` (their
  pretrial-release cohort and the brief's six windows). Each feature names
  a builder the code implements (`spec.FEATURE_CONTRACTS`, the same keys as
  `features.FEATURE_BUILDERS`) and must state that builder's kind, the frame
  columns it reads, and its known-at instant, plus its levels or bands, its
  reference, its missing rule, and a leakage justification, so the file
  cannot describe a feature differently from what is computed. A feature
  naming a restricted attribute — any value of the vocabulary's
  `restricted_attribute` kind, read from the vocabulary so no module under
  `metrics/` names one — an excluded variable (`judge`, `release_terms`,
  `propensity`, …), or an excluded column is rejected before anything else.
  A change that alters a fitted model or a published figure bumps
  `version`; a `recovery` tolerance does not (the rule is in the file's
  header).
- **The feature builder** (`features.design_rows`). One row per eligible
  index event: the release target's rows are the decisions the population
  metric's rule attributes to any judge of the frame (judge by judge,
  through `attribution.pretrial_decisions_for`), outcome released; a
  windowed target's rows are the pretrial-release cohort with its exposure
  and first outcome (`index_events`, `with_exposure`, `first_outcomes`),
  kept when followed for the window (`censoring.member_windows`), outcome
  the fixed-window numerator membership. Every feature is computed from
  rows strictly before its known-at instant: the index case's charges
  filed before the pretrial decision (lead severity, lead category with
  severity ties broken by the source's charge id, the charge count), and
  every history feature at the index case's filing — 00:00 UTC of its
  filing date, the frame's `cases.filed_at` and the instant the synthetic
  generator's risk index reads, so on the synthetic worlds the model's
  features equal the generator's exactly (a unit test proves it on the
  golden world). A prior case counts when filed on an earlier date; a
  conviction when disposed before the filing; a case is pending when,
  among its charges filed before the filing, one was pending then
  (disposed at or after it, or still pending) or none was disposed before
  it, charges without a recorded disposition being ignored.
  `prior_failures_to_appear` is dropped for a source that cannot document
  failures to appear. The missing rule either excludes the row or maps the
  null to the feature's `missing_level` (`unrecorded`: a case without a
  filing date cannot place its history) and flags the row for Step 4's
  complete-case refit.
- **Order invariance.** Fixed levels follow the specification; data levels
  (court, jurisdiction, calendar year) are ordered by their number of rows
  and then by a source-assigned key — a court's earliest charge
  (`<filing time>|<source_row_id>`), a jurisdiction's earliest court key,
  the year itself — and courts and jurisdictions are labelled by that rank,
  so no artifact carries a canonical id (the catalogue row maps a rank back
  to the court for the model card). The reference level (the
  specification's, or the busiest data level) and every column without a
  row are dropped; a feature left without a column (one jurisdiction) is
  reported as dropped. Rows sort by the index time, the index case's
  earliest charge, the person's cluster key (the merged person's earliest
  charge), the outcome, and the encoded labels. Relabelling every canonical
  id of a frame therefore leaves the design matrix, the coefficients, and
  the bootstrap draws byte-identical (`tests/property/test_feature_leakage.py`).
- **The solver** (`logistic.fit_logistic`). Newton-Raphson on the
  L2-penalized log-likelihood with the intercept unpenalized, step halving
  until the objective does not decrease, and a stop when the gradient's
  infinity norm falls below the tolerance; the result carries the
  coefficients, the iterations, the final gradient norm, `converged`, and
  the per-step trace. Every matrix product is an `np.einsum` with the
  default `optimize=False` (NumPy's own single-threaded loops, never BLAS)
  and the Newton system is solved by a column Cholesky written in NumPy
  rather than LAPACK, so two fits of the same arrays are bit-identical on a
  machine. Without the penalty separated data has no maximizer and the
  coefficients run away until the vanishing gradient meets the tolerance;
  every published fit is penalized.
- **Resampling** (`resample.replicates`). Person-cluster bootstrap weights:
  the cluster keys sorted, `K` draws with replacement per replicate from
  one `random.Random` per model stream (`bootstrap:<target>:<window>`),
  derived exactly as `synthetic/rng.py` derives its streams and drawn only
  through `random()`. Each replicate refit starts from the published
  coefficients.
- **Diagnostics** (`diagnostics`). The temporal split's test set is the
  index events at or after the nearest-rank 75th percentile of index time;
  the split fit keeps the columns with a training row, re-scores a data
  level unseen in training (the calendar year at the last training year,
  a court at the reference), and passes the same events-per-column gate.
  On the test set: the Brier score and its skill against the training base
  rate, ROC AUC by the Mann–Whitney statistic with ties averaged, ten
  equal-count calibration bins of the rows ordered by prediction, observed
  over expected, and the calibration slope. Over the replicates: each
  coefficient's mean, standard deviation, and sign agreement.
  `refit_complete_cases` is the refit Step 4's missing-data sensitivity
  compares with the published fit.
- **Statuses.** A design whose limiting class (the fewer of outcomes and
  non-outcomes) is below `minimum_events_per_column` times the design width
  is `insufficient_events` and is not fitted; a published fit that does not
  converge is `not_converged`; otherwise `fitted`. An outcome the source
  cannot document yields no model. Every golden model is
  `insufficient_events`; every demo model is `fitted`.
- **Artifacts** (`artifacts`). One canonical JSON document per model (keys
  sorted, no whitespace, ASCII, floats rounded to twelve significant
  digits, `artifact_version` 1): the specification, model, and code
  versions, the snapshot hash, the source's register name (never its
  UUID), the target, window, seed, status, the design columns and every
  feature's levels, reference, and drops, the training counts and range,
  the split, the coefficients, the solver trace, the diagnostics, the
  stability summary, and the replicate coefficients. Its sha256 is its id;
  it is written once to `<snapshot_dir>/<snapshot hash>/models/<sha256>.json`
  through `artifact_path`, which validates both hashes as 64 hexadecimal
  characters and keeps the resolved path under the snapshot directory, and
  `open(path, "xb")` (an equal file is a no-op, a different one raises).
  Artifacts are read back as JSON only. No artifact holds an array as long
  as the index events or the persons, a UUID-shaped string, or a 64-hex
  string other than the snapshot hash (`tests/unit/test_model_artifacts.py`
  inspects every artifact a fit writes; the design rows, the cluster keys,
  and the member ids exist only in memory inside a fit).
- **The catalogue and the commands** (`catalog`, migration
  `0009_outcome_models`). `judgemetrics models fit [--snapshot HASH]`
  (ingest role) takes the latest snapshot (`exported_at` descending, as
  `/api/v1/ready` reports it) or the named one, fits only the models of
  the current specification version and seed it lacks, writes their
  artifacts, and inserts one `outcome_model` row each — a second run fits
  nothing. `models list` and `models show <id or content hash>` read the
  catalogue as the app role (the card never shows `storage_uri`).
  `models verify [--snapshot HASH] [--refit]` rebuilds every artifact path
  from the configured snapshot directory and the two hashes (never from the
  stored URI), checks the bytes hash to the row's `content_hash` and the
  row's columns agree with the artifact, and with `--refit` refits every
  model from its snapshot and seed under the code version the row records
  and compares the bytes, naming the model and the first differing field;
  it exits 1 on any problem. Since Step 3 `metrics compute` fits the
  snapshot's missing models first (below), so `models fit` after it finds
  nothing to do; the CI `e2e` job still runs it and `models verify`.

### Observed-to-expected ratios (Phase 4 Step 3)

Registry version 2 (methodology `0.3`) adds the kind `observed_expected`
and three judge metrics over the targets of the specification:
`pretrial_release_observed_expected` (the attributed pretrial decisions,
outcome released), `new_case_observed_expected` and
`failure_to_appear_observed_expected` (the pretrial-release cohort followed
for each of the six windows). Each entry's `adjustment` names its target and
the minimum expected count.

```
   metrics compute (engine.compute_and_publish, kinds = every kind)
          │ export_snapshot → upsert metric_snapshot
          ├─ catalog.fit_snapshot ─▶ the snapshot's missing models (artifacts + rows)
          ├─ catalog.snapshot_parameters ─▶ every model read back from its artifact
          ▼                                 (ModelParameters: columns, coefficients, replicates)
   compute_all ─▶ descriptive kinds per subject (Phase 3)
               └▶ ratios.adjusted_observations per adjusted metric, per source:
                     features.design_rows (every eligible event of the source, once)
                       → expected.expectations   per judge: n, O, E = Σ p_i
                       → pooling.fit_shape       α over every judge with E > 0
                       → pooled (α + O) / (α + E), weight E / (E + α)
                       → bootstrap.interval      replicate r: weights r, coefficients r,
                                                 weighted O and E, refitted α, pooled ratio
                       → drafts for the requested judges (suppression.apply)
          ▼
   publish (kinds) ─▶ metric_observation (+ outcome_model_id, pooling_weight,
                      suppression_reason; migration 0010) and its decision members
```

- **Expected counts** (`adjustment/expected.py`). One design per target and
  window over every eligible index event of the source, so every judge is
  scored by the same model; the judge is never one of its inputs. Per judge
  (the judge the published gate attributed the row to): n, O, and E = the
  sum of the predicted probabilities from the published coefficients
  (`np.bincount` over the rows in design order, so no sum depends on a
  canonical id). The model is read through `ModelParameters`: from a stored
  artifact (`from_artifact`; `metrics compute` and `metrics verify` both read
  the very bytes the catalogue records) or from an in-memory fit
  (`from_fitted`, which applies the artifact's twelve-significant-digit
  rounding so the two give identical floats). A design whose columns differ
  from the model's (another specification) is refused.
- **Pooling** (`adjustment/pooling.py`). The gamma–Poisson model O | θ ~
  Poisson(θE), θ ~ Gamma(α, α): `fit_shape` maximizes the negative-binomial
  marginal log-likelihood over the judges with E > 0, suppressed or not,
  evaluating log Γ(α + O) − log Γ(α) as Σ_{k<O} log(α + k) (exact for
  integer counts, no scipy) on the specification's 200-point log-spaced grid
  over [0.5, 1000], refined by golden-section search in log α between the
  best point's neighbours; a maximum at the upper bound is `pooled_fully`
  (no between-judge variation detectable). The judges enter every sum in one
  canonical order, sorted by (E, O), so the shape is a function of the
  counts alone. The published ratio is the posterior mean (α + O) / (α + E)
  and the pooling weight E / (E + α).
- **The bootstrap interval** (`adjustment/bootstrap.py`). For replicate r the
  person-cluster weights come from `resample.replicates` with the model's
  seed and stream — the same draws the fit refitted replicate r on — and the
  replicate's coefficients from the artifact; per judge the weighted O and E
  (whole numbers for O), the refitted shape, and the pooled ratio. A
  replicate whose refit did not converge is skipped (its weights are still
  drawn, so the streams stay aligned). The interval is the 2.5% and 97.5%
  quantiles by linear interpolation. The model is never refitted here, so a
  recompute from the artifact reproduces the interval exactly; on the demo
  world the three recovery models' 500 replicates take about two seconds.
  The interval describes the pooled estimate, which is shrunk toward 1: on
  the demo world it covers the planted true ratio for 60–68% of the judges,
  not 95% (docs/SYNTHETIC_DATA.md "Recovery"; Step 4 reports it).
- **Suppression.** An adjusted row is suppressed below a cohort of 30
  (`below_threshold`), below an expected count of 5
  (`expected_below_minimum`), or without a fitted model
  (`model_unavailable`), in that order; the stored row keeps its figures and
  the reason. Every suppressed row of every kind now carries its reason
  (`below_threshold` for the descriptive kinds), and only a suppressed row
  does (migration `0010`'s check constraints).
- **Publish, verify, provenance.** `ObservationDraft` carries E, E / n, the
  pooled ratio, the weight, the reason, and the cited model's content hash;
  `publish` resolves the hash to `outcome_model_id` (refusing one the
  catalogue lacks) and its verified columns include all six, quantized to
  the column scales. `metrics verify` recomputes an adjusted observation from
  its snapshot and the artifact of the model it cites (the path rebuilt from
  the snapshot directory and the two hashes, the bytes checked against the
  hash) and reports a missing or altered artifact by observation id with the
  column `outcome_model`; it recomputes a snapshot's observations for the
  kinds the snapshot holds only. The provenance trace names the model
  (content hash, specification and model versions, target, window, seed,
  status) from its first statement and `check_chain` requires the artifact to
  exist and hash to its content hash (`provenance trace` passes the settings
  that locate it; the trace stays three statements).
- **The step-13 exception** (an exception to ROADMAP.md §5 "Performance
  rules", which has a recompute touch only the impacted subjects). An
  adjusted figure depends on a model and a shape fitted over every judge of
  the source, so it cannot be recomputed for the impacted subjects alone:
  pipeline step 13 computes and publishes the descriptive kinds only
  (`kinds=DESCRIPTIVE_KINDS`), `publish` loads, compares, and supersedes only
  the kinds a run computed, and a judge an ingest touches keeps the adjusted
  observations of the last full `metrics compute`, still citing that
  compute's snapshot and model, until the next full compute. That is the one
  place a subject's current rows cite two snapshots.
- **Fitting inside the compute.** `metrics compute` (every kind) records the
  snapshot row, fits the snapshot's missing models of the current
  specification version and seed, and reads them all back before computing,
  so it stays one command; a second run on the same snapshot fits nothing
  and publishes nothing. On the demo seed the first fitting compute takes
  about 35 seconds more than the descriptive compute (thirteen fits with 500
  replicate refits each) plus about 15 seconds for the adjusted figures.
- **The public hold-out, and its end.** `services.metrics.SERVED_KINDS` is
  every kind a public metrics response carries; Phase 4 Step 3 held the
  adjusted kind out of it until Step 4 published the validation (`GET
  /api/v1/metrics` listed only the descriptive definitions, the subject
  routes filtered by kind in their one SQL statement with bound parameters,
  `/metrics/compare` answered an adjusted slug with the unknown-metric 422,
  and the provenance route answered an adjusted id with 404). Phase 4 Step 5
  serves it (every registry kind is in the set; the filters stay as the
  place a future kind is held out) with its schema fields, the model card,
  and the web's `AdjustedStat`. `/api/v1/ready` reports the latest
  snapshot's models as counts and versions only.

### Validation (Phase 4 Step 4)

`judgemetrics.validation` assembles the brief's `model_validation` tests
from the latest snapshot's models and renders them into
`docs/VALIDATION.md` (`judgemetrics validation report [--out] [--check]
[--truth DIR]`, as the ingest role; exit 1 with a unified diff on drift, 2
when no snapshot or model can be read or the truth directory is unreadable
or describes no ingested source):

```
   validation report (ingest role)
          │ resolve_snapshot (latest) → open_snapshot
          ├─ inputs.load_inputs ─▶ per source (register-name order): the frame, and per
          │                        model (specification order) its catalogue row, its
          │                        parameters from the artifact, and its design rebuilt
          │                        with features.design_rows (in memory only)
          ├─ report.model_summary ─▶ the row's temporal-split diagnostics and bins, the
          │                          observed rate and mean prediction per calendar year,
          │                          the coefficients' bootstrap stability (rank labels)
          ├─ sensitivity ─▶ complete-case refit vs the published fit (pooled ratios)
          ├─ stability   ─▶ bootstrap.interval replayed: widths, share excluding 1,
          │                 rank-interval widths (distributions over judges)
          ├─ fairness    ─▶ ONE parameterized statement: decision → case_party →
          │                 the restricted attributes; aggregate cells only
          └─ recovery    ─▶ the published observations against truth/effects.json
          ▼
   render_report ─▶ docs/VALIDATION.md (80 columns, fixed orders, no id, hash, or path)
```

- **Order invariance.** The report names no UUID, hash, code version, run
  timestamp, judge, or local path, and every list has an order the data
  fixes (specification, vocabulary, and calendar order); the statistics over
  judges are rank correlations with ties averaged, medians, quartiles, and
  shares, which do not depend on the order the judges come in (their
  canonical ids). The rows of a source are the snapshot frame's, so a
  database that also holds a live FJC ingest renders the same document as
  CI's. The committed document is the demo seed's; the `e2e` CI job
  re-renders it from `data/synthetic/ci`, whose manifest is byte-identical,
  with `--check`.
- **The restricted read** (`validation/fairness.py`). `require_ingest_role`
  compares `current_user` with the user of the configured ingest URL and
  refuses any other session before a statement runs (the app role would fail
  with `InsufficientPrivilege` anyway). `attribute_statement` is one `SELECT`
  over `decision`, `case_party` (the defendant party of the decision's case
  and person), and the attribute table, grouped by decision and attribute,
  with the decision ids bound as one array (`= ANY(:member_ids)`) and the
  attribute names as bound values; a decision whose party carries two values
  of one attribute (two merged participants of one case) has none for it.
  The values live in one dictionary inside `subgroup_calibration`, which is
  cleared before it returns; the pure `calibration_cells` aggregates per
  vocabulary value O, E (from the published coefficients), O / E, and the
  percentile interval over the stored replicates (per replicate
  `sum w y / sum w p_r`, the fit's own cluster weights), and withholds a cell
  below `minimum_cohort` index events or `minimum_expected` expected events,
  or without a fitted model, with its reason and no figure. The log line
  carries counts only.
- **Sensitivity and stability.** The complete-case refit
  (`diagnostics.refit_complete_cases`) and the published fit both score
  every design row, so each judge's cohort is unchanged and only the model
  differs; the comparison runs over the judges whose ratio would be
  published (the ratios' suppression rule). The bootstrap stability replays
  `bootstrap.interval` (the computation the published bounds come from) and
  ranks the judges within each replicate with ties averaged.
- **Recovery on the database path.** `recovery.read_truth` reads
  `manifest.json` and `truth/effects.json` with `json.loads` from paths that
  must resolve inside the directory given; `truth_matches` requires the
  manifest's sha256 among the source's retrieved artifacts, so a truth is
  never compared with another dataset. `published_figures` reads the current
  adjusted observations of the snapshot with each judge's
  `synthetic_judge_code` in one statement; `evaluate` applies the
  specification's `recovery` tolerances. `judgemetrics validation recovery
  --truth DIR [--json]` prints the figures and exits 1 below a tolerance.
- **Cost.** On the demo seed the report takes about 17 seconds (the frame,
  thirteen designs, the replayed bootstraps, the complete-case refits).
