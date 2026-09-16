<!-- docs/ROADMAP.md -->
# JudgeMetrics — status, open questions, and next milestones

This is the living status document the brief asks for: the current
phase, completed items, unresolved issues (above all, unresolved
data-access questions, which are recorded here rather than answered by
guesswork), and the next milestones. The plan itself is the root
[`ROADMAP.md`](../ROADMAP.md); the per-phase execution plans are
`docs/phaseNN-roadmap.md`. Update this file at the end of every step
(Stage 6 of the step lifecycle).

## Current phase

**Phase 1 — Foundation, Canonical Schema, and the FJC Judge Slice.**
In progress. Steps 1 (repository bootstrap, command interface, security
gate, CI), 2 (application core, canonical schema, API image), 3 (ingest
framework and the FJC connector), and 4 (public API v1) are complete;
Step 5 (web foundation) begins on branch `feature/phase01-step5-web`
in a fresh session per [`docs/phase01-roadmap.md`](phase01-roadmap.md).

## Completed

| Date       | Item                                                                                              |
|------------|---------------------------------------------------------------------------------------------------|
| 2026-09-15 | Repository scaffolded: uv project on Python 3.13, ruff, mypy (strict), pytest, pytest-cov, poethepoet task interface with a `Makefile` shim; `uv run poe check` green. |
| 2026-09-15 | roadmodel 0.2.33 installed in the `planning` group; planning kit exported to `planning/`.         |
| 2026-09-15 | Brief archived verbatim under `docs/brief/`.                                                      |
| 2026-09-15 | Project roadmap (`ROADMAP.md`, v2) and Phase 1 execution roadmap authored with per-step model selections. |
| 2026-09-15 | Data-source register (`docs/DATA_SOURCES.md`) with live verification of FJC, Cook County, and CourtListener. |
| 2026-09-16 | Root roadmap v2.1: post-launch Phase 9 (sustainability and data products) added; §1.4 request-identity hook, §5.5 redistribution rights, and §6.4 commercial-licensing scope pulled forward; **Redistribution** field added to every source-register entry. |
| 2026-09-16 | Scaffold pushed as the initial commit; public repository `nathanramoscfa/judge-metrics` created. |
| 2026-09-16 | **Phase 1 Step 4.** Public API v1 (`docs/API.md`): `schemas/` (`Page[T]` with `items`/`total`/`limit`/`offset`/`next_offset`, `Provenance`, `ErrorBody`, judge/court/jurisdiction summaries and details, `SearchResult`; Pydantic v2 `from_attributes`); `repositories/` (typed queries returning rows plus totals; `count(*) OVER ()` pagination so a list is one statement; `selectinload` + chained `joinedload` so a judge detail is three; trigram `%` matches on `normalized_name`; `active_on`/`court_id`/`status` and `jurisdiction_id`/`court_type` filters; provenance selects only public columns, never `raw_object_path`); `services/` (search normalizing `q` with `normalize_person_name`, `pg_trgm.similarity_threshold` set per request with a bound `set_config`, judge and court matches unioned and ordered by `similarity()`; provenance blocks); `api/deps.py` (app-bound session per request, `PageParams` with `limit` default 25 / max 100 and `offset` ≥ 0, `StrictQuery` allow-lists rejecting unknown parameters with 422, `Cache-Control: public, max-age=60` on lists and details); `api/errors.py` (every non-2xx response an `ErrorBody`; validation errors name the parameter; database errors 503 without SQL; unhandled errors 500 without a trace); `api/identity.py` (ROADMAP §1.4 request identity: anonymous bucket keyed by client address, `X-Forwarded-For` honoured only with `trust_proxy`; optional `X-API-Key` scheme declared in OpenAPI); `api/ratelimit.py` (in-process token bucket on `/search`, burst 10 / 60 per minute by default, 429 with `Retry-After`, off under `env == test` unless enabled); routes `GET /judges`, `/judges/{id}`, `/judges/{id}/service`, `/courts`, `/courts/{id}`, `/jurisdictions`, `/jurisdictions/{id}`, `/search`; settings `trust_proxy`, `search_rate_limit_per_minute`, `search_rate_limit_burst`, `search_rate_limit_enabled`, `search_similarity_threshold`; CLI `judgemetrics openapi export [--out docs/openapi.json]` and the committed `docs/openapi.json` (exactly the health probes and the eight v1 paths) guarded by a unit test; `tests/` made a package with a module-scoped committed fixture ingest for the API tests (pagination bounds, unknown parameters, filters, 404/422/429/500/503 envelopes, provenance with 64-character sha256, no `raw_object_path` in any response) and the cursor-level query-count guard (judge detail ≤ 3, lists ≤ 2, search ≤ 2); `docs/API.md`, `docs/ARCHITECTURE.md` API layering and limiter, README endpoint list. Verified against the live local ingest (4,075 judges): all eight endpoints, `Sotomayer` → Sonia Sotomayor first, 429 after the burst. |
| 2026-09-16 | **Phase 1 Step 3.** `ingest/base.py` (the brief's connector protocol plus `source_id`, `parser_version`, `source_info`, and an optional checkpoint protocol; frozen drafts with natural keys); `ingest/store.py` (content-addressed immutable raw lake, `<source>/<yyyy>/<mm>/<sha256>.csv`, filesystem and S3/MinIO backends that refuse to overwrite); `ingest/http.py` (HTTPS-only downloads: 30 s timeout, 3 retries with backoff, 200 MB cap, `If-None-Match`/`If-Modified-Since`); `ingest/runner.py` (the fourteen steps; one publish transaction; `INSERT … ON CONFLICT` upserts that write only changed rows and merge JSONB identifiers; last-substantive-writer provenance on jurisdiction, court, judge; unchanged hashes short-circuit; new parser versions re-derive; refusals of synthetic sources and fixture ingests in production); `ingest/fjc/` (verified headers and vocabularies in `schema.py`, Polars string-only parsing projected to expected columns, normalization of names, status, court types, and state codes from `data/reference/us_states.csv`); `quality/checks.py` (service dates, overlaps, missing start dates, provenance); migration `0002_ingest_provenance` (`source_record_id` on the reference entities, natural-key unique indexes with `NULLS NOT DISTINCT`, `court.state_code`, JSONB `metadata` on `judge_service` and `source_record`, `ingest_run.parser_version`/`checkpoint`/`failure_reason`); CLI `ingest list-sources`, `ingest run <source> [--from-fixture DIR] [--force]`, `ingest runs`; the `ingest-fjc` target; Compose `minio-init` provisions the S3 application user; CI starts MinIO for the S3 contract test; fixture excerpt (25 judges, 42 service rows, 28 courts) with two data-quality issues chosen by row selection; unit tests (store, connector, normalizer, checks, registry) and integration tests (first run, idempotent second and forced runs, changed artifact, provenance to stored bytes, issues, validation failure, refusals, CLI); `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `data/README.md`; `docs/DATA_SOURCES.md` `fjc` entry with the verified headers. Live ingest verified 2026-09-16 against the Compose services (MinIO lake, ingest role): 4,075 judges, 4,775 service records, 159 courts, 1 jurisdiction (9,010 rows created), 20 data-quality issues (18 `service_overlap` warnings, 2 `missing_start_date`); the second live run received `304 Not Modified` for both files and created and updated nothing; a forced run re-parsed 8,850 rows and changed nothing. |
| 2026-09-16 | **Phase 1 Step 2.** `config.py` (pydantic-settings, `JUDGEMETRICS_` prefix, `.env` only when local, one URL per database role, `SecretStr` secrets); `logging.py` (structlog, ISO timestamps, JSON or console renderer, stdlib loggers routed through the same chain, `scrub_sensitive` processor with a documented denylist tested recursively); `main.py` `create_app()` with request-id and access-log middleware; `GET /api/v1/health` (version, git SHA, Alembic head, nothing else) and `GET /api/v1/ready` (200 at head, 503 with a reason, DSN never echoed); SQLAlchemy 2 models for all twenty-three canonical entities with the brief's field names and enums; reversible Alembic baseline `0001` (`pg_trgm`, enums, foreign-key and event-time indexes, trigram and JSONB GIN indexes, unique FJC `nid` expression index, grants that deny `judgemetrics_app` on `person_identifier` and `correction_request`); `normalization/names.py`; Typer CLI `judgemetrics` (`db upgrade|downgrade|current`, `serve`, `ingest list-sources`); `infra/docker/api.Dockerfile` (multi-stage, locked runtime deps, non-root, no `.env`, HEALTHCHECK) with the compose `api` service (profile `app`) and the CI `container` job (build, smoke, Trivy HIGH/CRITICAL gate) required by `test`; `migrate` and `dev-api` targets; unit tests (settings, scrubber, names, CLI) and integration tests (migration round trip, `Decision` requires `source_record_id`, app-role grants, both health probes) against the CI `postgres:17` service with the three roles created from the Compose init scripts. |
| 2026-09-16 | **Phase 1 Step 1.** Apache-2.0 `LICENSE`; `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue and PR templates; fail-closed `pre-commit` gate (ruff, mypy, bandit, detect-secrets with baseline, pip-audit over `uv.lock` at pre-push) observed to block a planted synthetic credential; `ci.yml` (`python`, `security`, aggregate `test`) with SHA-pinned actions and read-only `contents` permissions; `dependabot.yml` (uv, github-actions); `docker-compose.yml` with PostgreSQL 17 (`pg_trgm`, roles `judgemetrics_app`/`_ingest`/`_admin`) and MinIO (`judgemetrics-raw`, versioning on); `.env.example`; `up`/`down`/`gate` tasks; branch protection (`enforce_admins`, linear history, required `test`), squash-only merges, secret scanning and push protection; `tests/unit/test_repo_hygiene.py`. |

## Unresolved data-access questions

| # | Question                                                                                     | Source            | Blocks                    | Owner    | Status |
|---|----------------------------------------------------------------------------------------------|-------------------|---------------------------|----------|--------|
| 1 | Exact column headers of `judges.csv` and `federal-judicial-service.csv`; conditional-request support | `fjc`         | Phase 1 Step 3            | agent    | **resolved 2026-09-16** — 201 and 30 headers recorded in `docs/DATA_SOURCES.md` and `src/judgemetrics/ingest/fjc/schema.py`; the server sends `ETag` and `Last-Modified` and the connector uses both |
| 2 | Cook County open-data portal terms: republication of derived aggregates and pseudonymous case views, and commercial redistribution (Phase 9 snapshot tier) | `cook_sao`   | Phase 5 Step 1; Phase 9 §9.2 | operator | open   |
| 3 | Documented value sets for `charge_disposition`, `charge_disposition_reason`, bond types, sentence fields | `cook_sao` | Phase 5 attribution rules | agent    | open   |
| 4 | Stability of `case_participant_id` across the five Cook County datasets                       | `cook_sao`        | Phase 5 person resolution | agent    | open   |
| 5 | CourtListener API rate limits and terms including redistribution of API responses; whether docket entries and parties are bulk or API-only; RECAP coverage of federal criminal dockets | `courtlistener` | Phase 7; Phase 9 §9.2 | agent | open |
| 6 | PACER account, Case Locator API terms including redistribution, fee schedule, waiver threshold | `pacer`           | Phase 7 (feature-flagged); Phase 9 §9.2 | operator | open   |
| 7 | New York pretrial release data: files, cadence, data dictionary, presence of judge names, terms including redistribution (page returned HTTP 403 to automated fetch) | `ny_oca_pretrial` | Phase 7 candidate; Phase 9 §9.2 | operator | open — verify manually |
| 8 | Florida target jurisdiction: JDMS/UCR credentials, county clerk bulk or API offering, public-records process, cost, terms, fields; redistribution rights (aggregates, pseudonymous case-level, commercial) requested as a term of every agreement | `fl_jdms`, `fl_clerks` | Phase 5 §5.5, Phase 7; Phase 9 §9.2 | operator | open — research in Phase 5 |

## Known issues and limitations

- Only the FJC source is ingested; case, charge, disposition, and
  defendant data begin with the synthetic dataset in Phase 2. The FJC
  export is regenerated nightly, so a later live run records new
  source records for the changed files and updates only the rows whose
  values changed.
- `judge.status` is derived from the latest appointment's termination
  and senior-status fields with a fixed mapping
  (`src/judgemetrics/ingest/fjc/schema.py`); an unmapped termination
  value yields `unknown` rather than a guess, and `court_type` values
  outside the verified vocabulary map to `other`.
- The unique indexes of revision 0002 use `NULLS NOT DISTINCT`, which
  needs PostgreSQL 15 or newer (Compose and CI run 17).
- The integration suite's migration round-trip test
  (`tests/integration/test_migrations.py`) downgrades the configured
  database to base and back, so `uv run poe check` empties a local live
  ingest; run `uv run poe ingest-fjc` again afterwards (a few seconds,
  conditional requests reuse the lake). A dedicated scratch database
  for that test is a process improvement for a later step.
- A `.env` written before Step 3 may name an S3 application user that
  MinIO does not know; `uv run poe up` (its `minio-init` job) now
  creates that user, so run it once more on such machines.
- Search similarity is computed over the whole normalized name with
  the `%` operator at threshold 0.3, so a misspelt surname finds a
  judge when the surname is a large share of the full name
  ("Sotomayer" → Sonia Sotomayor) but a short token against a long
  name ("Ginsberg" → "ruth bader ginsburg", 0.26) does not. Word
  similarity (`<%`, also GIN-indexable) would fit surname-only queries
  better; a candidate for Step 5 when the search page is built.
- `active_on` follows the FJC service interval, which ends with the
  appointment's termination (death, resignation, retirement), not with
  senior status; a judge on senior status is "active on" a date within
  the appointment, and `senior_status_date` is in the service record's
  `metadata`.
- The `/search` limiter is per process and per client address; a
  multi-worker deployment gets `workers × burst` until the Phase 8
  edge limits sit in front of it.
- API integration tests commit a fixture ingest per module and purge
  exactly that run afterwards. On a database that also holds the live
  ingest the fixture rows resolve to the existing judges, so a fixture
  row whose values differ from the live export (the nightly
  regeneration) would move that judge's provenance to the fixture run
  and the purge would remove the judge; rerun `uv run poe ingest-fjc`
  afterwards, as after the migration round-trip test.
- `judicial_discretion_classification`, case status, charge disposition,
  release type, position type, and event type are free text until the
  versioned attribution rules and registries of Phases 2 and 5 define
  their vocabularies; the brief fixes only the enums the baseline creates.
- `correction_request.requester_contact` is Fernet-encrypted under
  `JUDGEMETRICS_CORRECTION_CONTACT_KEY` (`judgemetrics.security.crypto`);
  the corrections workflow that writes it arrives in Phase 3.
- The API image reports `git_sha: unknown` unless built with
  `--build-arg GIT_SHA=…` (CI passes `GITHUB_SHA`; Compose reads
  `GIT_SHA` from the environment).
- On the maintainer's machine native PostgreSQL instances hold ports
  5432 and 5433 and Windows reserves 9000, so the local `.env` overrides
  `POSTGRES_PORT` (5440) and `MINIO_API_PORT`; CI and fresh machines use
  the defaults.
- MinIO's community images are pulled from `quay.io/minio` (Docker Hub
  no longer serves them) and MinIO has announced maintenance mode for
  the community edition; the raw store is S3-compatible, so swapping
  the local object store later is a Compose change only.
- The first real state-court corpus (Cook County) is frozen at
  2024-12-30, lacks judge attribution on pretrial decisions, and has no
  failure-to-appear, rearrest, or release-violation events.
- GNU make is not installed on the maintainer's machine; the `Makefile`
  is a shim and `uv run poe <task>` is the primary interface.

## Next milestones

1. **Phase 1 exit (`v0.1.0-phase-1`).** Canonical schema behind
   reversible migrations; FJC judges ingested idempotently with
   provenance; API v1 and the web judge page running locally; CI with
   the security gate and container scan; branch protection live.
2. **First milestone (`v0.3.0-phase-3`).** The brief's seventeen-item
   checklist passes end to end on synthetic data plus FJC judges from
   `uv run poe bootstrap` alone.
3. **First real metrics (`v0.5.0-phase-5`).** Cook County ingested with
   attribution and coverage; the first real metric published with a
   complete provenance trace; the Florida acquisition plan written.
