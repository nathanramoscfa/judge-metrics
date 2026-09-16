<!-- docs/ARCHITECTURE.md -->
# Architecture

The system-level picture is in the root [`ROADMAP.md`](../ROADMAP.md)
§3. This document describes what is built: the ingest pipeline (Phase 1
Step 3), the raw lake, the idempotency rules, and the database roles.
Later steps add the API layering and the web tier.

## Ingest pipeline

```
   docs/DATA_SOURCES.md            src/judgemetrics/ingest/
   (verified register)             ┌──────────────────────────────────────┐
          │                        │ registry: @register / get_connector  │
          ▼                        └───────────────┬──────────────────────┘
   ┌──────────────┐  discover/fetch  ┌─────────────▼──────────────┐
   │ Source (FJC) │ ───────────────▶ │ SourceConnector            │
   │ HTTPS files  │  validate/parse  │ (ingest/fjc/connector.py)  │
   └──────────────┘  normalize       └─────────────┬──────────────┘
                                                   │ drafts
                       ┌───────────────────────────▼──────────────────────────┐
                       │ runner.run_ingest — the fourteen steps, one run      │
                       │  1 discover · 2 fetch · 3 sha256 · 4 store · 5 record│
                       │  7 validate · 6 parse · 8 normalize · 9 dedupe       │
                       │ 10 resolve · 11 quality checks · 12 publish (upsert) │
                       │ 13 recompute metrics (no-op) · 14 lineage + stats    │
                       └──────┬─────────────────────────────┬─────────────────┘
                              │ immutable bytes             │ one transaction
                              ▼                             ▼
                   ┌──────────────────────┐     ┌────────────────────────────┐
                   │ Raw lake             │     │ PostgreSQL (ingest role)   │
                   │ file:// or s3://     │     │ source, ingest_run,        │
                   │ <src>/<yyyy>/<mm>/   │     │ source_record → jurisdiction│
                   │   <sha256>.csv       │     │ court, judge, judge_service,│
                   └──────────────────────┘     │ data_quality_issue         │
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
| `normalize(record)`     | Canonical drafts: `JurisdictionDraft`, `CourtDraft`, `JudgeDraft`, `JudgeServiceDraft` (case-level drafts arrive in Phase 2). |
| `SupportsCheckpoint`    | Optional: `restore_checkpoint` / `checkpoint` for cursoring sources; stored on `ingest_run.checkpoint`. |

Every draft has a `natural_key`; the runner deduplicates drafts by it
within a run and upserts on the matching unique index. Source-specific
parsing (column names, date formats, vocabularies) lives under the
connector package; canonical rules (name normalization, the state-code
lookup) live in `judgemetrics.normalization`.

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
| 8 | Normalize                      | `connector.normalize()` per parsed row; a `NormalizationError` rejects the row and records a `normalize_failed` issue |
| 9 | Deduplicate                    | `_deduplicate` by `natural_key` (first draft wins; conflicting duplicates are counted in the log) |
| 10 | Resolve entities              | `_resolve`: judges by exact `external_ids->>'fjc_nid'`, courts by exact `(canonical_name, court_type)`, jurisdictions by `(name, type)`; drafts referencing an unknown parent are rejected with an issue |
| 11 | Run data-quality checks       | `judgemetrics.quality.checks.run_checks` over the resolved drafts |
| 12 | Publish canonical rows        | `_publish`: `INSERT … ON CONFLICT DO UPDATE` per entity type, in dependency order (jurisdiction → court → judge → judge_service) |
| 13 | Recompute affected metrics    | `recompute_metrics` — a no-op hook until the Phase 3 metrics engine |
| 14 | Record lineage and statistics | issues persisted with their source record and entity id; `ingest_run` counts, `code_version` (git SHA), `parser_version`, status, checkpoint |

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
4. `source_record_id` on `jurisdiction`, `court`, and `judge` is
   last-substantive-writer provenance: it moves to the newer artifact
   only when that artifact changed the row. `judge_service` rows carry
   the record of the artifact that produced them.
5. Data-quality issues are keyed by `(source_record_id, entity_type,
   entity_id, issue_code, description)`; a rerun never duplicates an
   open issue.
6. The `ingest_run` row is committed first, so a failed run is always
   recorded; the whole publish (source records, canonical rows, issues,
   run statistics) is one transaction that a failure rolls back, leaving
   `status = failed` and `failure_reason` on the run and the immutable
   raw object in the lake.

### Refusals

`run_ingest` records `status = refused` without touching anything when
`JUDGEMETRICS_ENV=production` and either the connector's
`source_info.source_type` is `synthetic` or `--from-fixture` is given.

## Database roles

| Role                  | Used by                                              | Rights                                            |
|-----------------------|------------------------------------------------------|---------------------------------------------------|
| `judgemetrics_app`    | the API (`JUDGEMETRICS_DATABASE_URL`), `ingest runs` | `SELECT` on public tables; nothing on `person_identifier`, `correction_request` |
| `judgemetrics_ingest` | `ingest run` (`JUDGEMETRICS_INGEST_DATABASE_URL`)    | `SELECT, INSERT, UPDATE, DELETE` on every table; no DDL |
| `judgemetrics_admin`  | `db upgrade` / `downgrade` (`JUDGEMETRICS_ADMIN_DATABASE_URL`) | full control of the public schema (not a superuser) |

The roles are created by `infra/docker/postgres/02-roles.sql`; migrations
grant per table (`alembic/versions/0001_baseline.py`) and default
privileges cover objects created later. CI runs every URL as the service
container's owner, which is why the ingest and admin URLs fall back to
`JUDGEMETRICS_DATABASE_URL` when unset.

## Command interface for ingest

| Command                                          | Role   | Notes                                                   |
|--------------------------------------------------|--------|---------------------------------------------------------|
| `judgemetrics ingest list-sources`               | none   | Registered connectors with parser versions.             |
| `judgemetrics ingest run <source> [--from-fixture DIR] [--force]` | ingest | Exit 0 on `succeeded`, 1 on `failed`/`refused`, 2 on usage errors. `uv run poe ingest-fjc` runs the FJC connector. |
| `judgemetrics ingest runs [--source ID] [--limit N]` | app | A table of runs with counts, status, and parser version. |

Logs (structlog, scrubbed) carry counts, identifiers, hashes, and keys
— never raw rows.
