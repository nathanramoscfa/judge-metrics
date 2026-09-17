<!-- docs/ARCHITECTURE.md -->
# Architecture

The system-level picture is in the root [`ROADMAP.md`](../ROADMAP.md)
§3. This document describes what is built: the ingest pipeline (Phase 1
Step 3), the raw lake, the idempotency rules, the database roles, the
public API (Step 4), and the web tier (Step 5).

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

## Public API v1

The API (`src/judgemetrics/api`, contract in [`API.md`](API.md)) is a
read-only view over the canonical tables, connected as the
`judgemetrics_app` role. Requests pass through four layers, each of
which knows only the one beneath it:

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

- **Routes** (`api/routes/{judges,courts,jurisdictions,search}.py`)
  declare parameters with validation (`limit` 1–100, `offset` ≥ 0,
  enum statuses, UUID ids, ISO dates) and a `StrictQuery` allow-list
  per route, so an undeclared query parameter is a 422 rather than an
  ignored filter; a unit test checks each allow-list against the
  parameters the OpenAPI document declares. List and detail routes add
  `Cache-Control: public, max-age=60` through a router dependency, which
  a raised error bypasses.
- **Services** (`services/`) return the schemas. `services.search`
  normalizes the query with `normalize_person_name`, sets
  `pg_trgm.similarity_threshold` for the request's transaction with
  `set_config(…, true)` (a bound parameter from
  `JUDGEMETRICS_SEARCH_SIMILARITY_THRESHOLD`), and unions judge and
  court matches ordered by `similarity()`. `services.provenance` builds
  the provenance block from the public columns of `source_record`.
- **Repositories** (`repositories/`) take a `Session` and return ORM
  rows plus totals. `paginate` adds `count(*) OVER ()` to the page query
  so a list is one statement (a plain count only when the page is
  empty); `get_judge` loads service records with `selectinload` and
  their courts with a chained `joinedload`, so a judge detail is three
  statements including provenance. `tests/integration/test_query_counts.py`
  counts statements at the cursor and fails on more.
- **Errors** (`api/errors.py`): every non-2xx response is an `ErrorBody`
  (`code`, `message`, `request_id`). Validation errors name the
  parameter; `ApiError` carries its code; a `SQLAlchemyError` is a 503
  whose text is never returned (it can embed SQL); anything else is a
  500 `internal_error`. Stack traces stay in the logs.
- **Sessions**: `create_app` binds an engine and a session factory to
  the app (`app.state`), and `api.deps.get_session` opens one session
  per request from it, so an app built with explicit settings (tests)
  never reaches for the process-wide engine.
- **Identity** (`api/identity.py`, ROADMAP.md §1.4): a request resolves
  to a rate-limit bucket; anonymous keyed by client address is the only
  bucket until Phase 9 issues API keys. The OpenAPI document declares
  the `X-API-Key` scheme as optional.

### The rate limiter

`api/ratelimit.py` is an in-process token bucket per
`RequestIdentity.rate_limit_key`: `search_rate_limit_burst` tokens
(default 10) refilled at `search_rate_limit_per_minute` (default 60);
an empty bucket answers 429 with `Retry-After` and the `rate_limited`
error body. It is applied to `/search` only, before parameter
validation, so an over-limit client never reaches the database. The
client address is the TCP peer unless `JUDGEMETRICS_TRUST_PROXY=true`,
in which case it is the rightmost `X-Forwarded-For` entry — the one the
trusted proxy appended. This is the local layer beneath the Phase 8
edge limits: not shared across workers, forgotten on restart, and off
under `JUDGEMETRICS_ENV=test` unless
`JUDGEMETRICS_SEARCH_RATE_LIMIT_ENABLED=true` (the integration test
enables it with a held clock). Buckets are pruned once more than 10,000
keys are tracked; a full bucket carries no state, so dropping it is
exact.

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

Logs (structlog, scrubbed) carry counts, identifiers, hashes, and keys
— never raw rows.

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
- **Rendering.** Every data page is `force-dynamic`: it fetches on the
  server per request, so nothing is baked in at build time (the `web`
  CI job and the image build run without an API). Static pages
  (`/methodology`, `/coverage`, `/about`) are prerendered.
- **Pages.** `/` (headline, global search, coverage tiles from
  `/jurisdictions` and the list totals, methodology link), `/search`
  (`?q=` → `/search`, entity-type badges, the 429 wait time when the
  limiter answers), `/judges/[judgeId]` (identity, status, sortable
  service table, FJC biography link by `nid`, the "Source coverage"
  panel: source name, retrieved-at, truncated sha256 with copy, parser
  version, ingest run, source export link, "Report a data issue" to the
  GitHub data-source issue form), `/courts/[courtId]` (court, type,
  jurisdiction, a date form driving `/judges?court_id=&active_on=`,
  paginated), `/methodology` (the ten principles, the
  association-is-not-causation statement, the Phase 3 note),
  `/coverage` (Phase 2 note), `/about`.
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
  provenance panel's truncation and copy, schema freshness, bundle
  scan); Playwright `web/tests/e2e/smoke.spec.ts` against a running web
  app and API (home and the `/` shortcut, search by a fixture surname,
  judge page service rows and source panel, theme toggle, court page by
  date, 404 and the methodology statement). The Playwright config starts
  nothing: the `e2e` CI job migrates, ingests the FJC fixture, starts
  the API and the built web app, and runs Chromium; locally the operator
  runs `uv run poe dev-api` and `pnpm dev` (or `pnpm build && pnpm
  start`) first.
