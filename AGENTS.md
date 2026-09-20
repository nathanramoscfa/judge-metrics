<!-- AGENTS.md -->
# JudgeMetrics — operating instructions for AI coding agents

JudgeMetrics is a transparent, reproducible analytics platform over
public criminal-court records: judicial assignments, case events,
dispositions, sentences, and documented subsequent justice-system
events, with every published statistic traceable to versioned source
records and code. Python 3.13, uv, FastAPI, SQLAlchemy 2, Alembic,
PostgreSQL, Polars, DuckDB; Next.js and TypeScript in `web/`.

## Where the plan lives

- `docs/brief/judgemetrics-master-project-specification.xml` — the
  product specification (do not edit; it is the source of truth for
  the canonical data model, attribution model, outcome definitions,
  presentation rules, security requirements, and testing strategy).
- `ROADMAP.md` — the project roadmap (phases, architecture, branch,
  security, release, and operations strategy). Read §5 before any work.
- `docs/phaseNN-roadmap.md` — the executable plan for one phase, one
  step per agent session. Start from the step you were given.
- `docs/ROADMAP.md` — the living status document: current phase,
  completed items, unresolved data-access questions, next milestones.
  Update it at the end of every step; record a data-access question
  there instead of inventing an answer.
- `docs/DATA_SOURCES.md` — the source register. A connector may depend
  only on facts marked verified there.
- `planning/` — the roadmodel planning kit. When asked to recommend a
  model for a step, run `planning/model-selector.txt` yourself against
  `planning/user-context.md`; do not call an external API or MCP tool
  (`planning/HOW-TO-USE.md`, "you are the engine"). Re-export the kit
  at the start of each phase: `uv run poe kit`.

## Step discipline (binding)

1. First action of every step: `git checkout -b <branch>` using the
   step's `**Branch:**` line, from a clean, up-to-date `main`.
2. Pass the security gate before every commit (pre-commit: secret scan,
   SAST, dependency audit, sensitive-data diff review). It is
   fail-closed; fix findings in the step, never defer them.
3. One PR per step; Conventional Commits title; body references the
   roadmap step and acceptance criteria; wait for green; squash-merge;
   retire the branch; update `docs/ROADMAP.md`; declare completion with
   the verbatim line "Step N is complete. You can now move on to
   Step N+1." only when every acceptance criterion is met; then a new
   conversation.
4. Classify every finding before acting on it (spec rot, upstream gap,
   implementation bug, architectural question, process improvement,
   security finding, data-semantics finding, data-access question) per
   `ROADMAP.md` §5 "Defect handling & triage".

## Definition of done for any feature (from the brief)

Feature implemented; types added; database migration added if
required; unit tests added; integration tests added when relevant;
relevant documentation updated; lint passes; type checking passes;
tests pass; frontend production build passes when the frontend is
affected; no credentials committed; data lineage preserved when data is
affected.

## Working rules (from the brief)

- Build working software; do not spend a session writing architecture
  documents, and do not build national-scale infrastructure before the
  vertical slice works.
- Never create fake production integrations. When external access is
  unavailable, create the adapter interface plus fixtures and document
  exactly what credential or access step remains.
- Prefer explicit, readable code over abstraction during the MVP.
- Use migrations from the beginning. Use deterministic random seeds for
  synthetic data.
- Keep source-specific parsing separate from canonical-domain logic,
  and statistical methodology separate from presentation logic.
- Never overwrite a raw source artifact. Every transformation from
  source record to published metric must be reproducible.
- Update this file whenever an architectural decision matters for
  future sessions.

## Domain rules (non-negotiable)

- An arrest never proves a crime. Arrest, charge, conviction, dismissal,
  acquittal, release, sentence, and later events are separate concepts
  and separate rows.
- Every judge-level metric uses only events whose actor attribution
  satisfies the metric's documented inclusion rules. A prosecutor's
  dismissal is not a judicial dismissal; a statutory release is not a
  discretionary decision.
- Associations are never presented as causation. There is no composite,
  ideological, partisan, or "best/worst judge" score. The brief's
  statistical warnings are published as known limitations on the
  methodology page and are never softened for presentation.
- Persons are pseudonymous in every public surface. Never merge persons
  on name alone. Restricted attributes never leave the restricted
  schema, are never model features by default, and never appear in
  logs.
- Synthetic data is labelled synthetic on every surface and is refused
  by the ingest runner in production.
- Never scrape a source against its terms, robots rules, or law. Never
  fabricate a data-source capability.
- Every published number shows numerator, denominator, date range,
  coverage, sample size, and (for adjusted statistics) an interval and
  a methodology version, and traces to raw artifacts through
  `judgemetrics provenance trace`. Suppress small cohorts.

## Conventions

- Prose in Markdown wraps at 80 columns; Python line length is 100.
- Every new source file starts with its repo-relative path as a comment
  on the first line (`# src/judgemetrics/x.py`, `// web/lib/x.ts`,
  `<!-- docs/x.md -->`, `-- infra/docker/x.sql`).
- `uv sync` installs everything; `uv run <tool>` runs it. Never
  `pip install` into the environment by hand.
- ruff (lint and format), mypy `--strict`, pytest, hypothesis for
  property tests. Tests live in `tests/`; integration tests need the
  Compose services (`uv run poe up`).
- Verify scripts are Python (`scripts/verify_phaseNN.py`) so they run
  identically on Windows and Ubuntu CI.
- Line endings are LF everywhere (`.gitattributes`).

## Commands

`uv run poe <task>` is the primary interface (cross-platform); the
`Makefile` mirrors every target for environments with GNU make.

```sh
uv sync                    # environment (make install)
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run poe check           # lint + format check + type check + tests
uv run poe test            # tests only
uv run poe lint            # ruff check
uv run poe fmt             # ruff format
uv run poe typecheck       # mypy --strict
uv run poe gate            # the security gate: all hooks + pre-push stage
uv run poe up              # docker compose: postgres + minio healthy, bucket
uv run poe down            # docker compose down
uv run poe kit             # refresh the planning kit
uv run poe migrate         # alembic upgrade head as the admin role
uv run poe dev-api         # uvicorn with reload: /api/v1/health, /api/v1/ready
uv run poe dev-web         # Next.js dev server in web/ (pnpm) against the local API
uv run poe ingest-fjc      # FJC judges, courts, service records → raw lake + canonical tables (ingest role)
uv run judgemetrics        # CLI: db upgrade|downgrade|current, serve, ingest list-sources|run|runs, openapi export
uv run judgemetrics synthetic generate --seed 7 --scale golden --out DIR   # deterministic synthetic dataset: source/, truth/, manifest.json
uv run judgemetrics synthetic verify DIR                                   # recompute every file hash; exit 1 on a mismatch
uv run poe seed            # generate data/synthetic/20260916 (demo scale, skipped when current) and ingest it through the synthetic connector
uv run judgemetrics ingest run synthetic --from-fixture tests/fixtures/golden   # the golden fixture through the runner
uv run judgemetrics er run [--source synthetic]   # recompute person candidates, apply system merges (idempotent)
uv run judgemetrics er review list [--json]       # the manual-review queue: public keys, stage, score, feature flags
uv run judgemetrics er review decide <id> --decision matched|rejected --reviewer <label> --reason <text>
uv run judgemetrics methodology render [--out docs/METHODOLOGY.md] [--check]   # docs/METHODOLOGY.md from the metric registry; --check exits 1 on drift
uv run poe compute-metrics                       # judgemetrics metrics compute: snapshot → every registry metric for every judge and court → observations (ingest role)
uv run judgemetrics metrics compute [--label TEXT] [--subject judge:<uuid> ...] [--json]
uv run judgemetrics metrics verify [--snapshot HASH] [--json]   # recompute every current observation from its snapshot; exit 1 on any mismatch
uv run judgemetrics provenance trace <observation id> [--json]  # the chain from a published number to the raw artifacts, top-down (app role); exit 1 when incomplete
```

`ingest run` and `seed` need `JUDGEMETRICS_IDENTIFIER_PEPPER` (a real
random value in the untracked `.env`; the tests set a fixed one). The
API (`dev-api`, `serve`) needs `JUDGEMETRICS_CORRECTION_CONTACT_KEY` (a
Fernet key in `.env`) outside the test environment and refuses to start
without one.

In `web/`: `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`,
`pnpm e2e`, `pnpm generate:api`. A later step adds `bootstrap`.

## Architectural decisions that matter for future sessions

- The dependency audit runs `pip-audit --strict --require-hashes` over
  an export of `uv.lock` (`scripts/audit_deps.py`), not over the live
  environment: the editable `judgemetrics` project is not on PyPI, so
  a raw `pip-audit --strict` fails for the wrong reason.
- `up` is a sequence task: `docker compose up -d --wait postgres minio`
  and then `docker compose run --rm minio-init`, because `--wait`
  treats a cleanly exited one-shot job as a failure.
- MinIO images are pulled from `quay.io/minio` (the Docker Hub
  repository is no longer served) and pinned to a release tag.
- Host ports are overridable in `.env` (`POSTGRES_PORT`,
  `MINIO_API_PORT`, `MINIO_CONSOLE_PORT`); the maintainer's machine has
  a native PostgreSQL on 5432 and Windows reserves 9000.
- Database roles: `judgemetrics_app` (read-only), `judgemetrics_ingest`
  (DML), `judgemetrics_admin` (DDL, not superuser); default privileges
  are set for objects created by the admin role or the Compose
  superuser, so migrations may run as either.
- `detect-secrets` false positives are allowlisted inline with
  `# pragma: allowlist secret`; the hygiene test strips ` #` inline
  comments from `.env.example` values the way Docker Compose does.
- Settings carry one URL per database role: `JUDGEMETRICS_DATABASE_URL`
  is the API's read-only `judgemetrics_app`; `JUDGEMETRICS_ADMIN_DATABASE_URL`
  (migrations, `alembic/env.py`) and `JUDGEMETRICS_INGEST_DATABASE_URL`
  (the ingest runner) fall back to it when unset, which is how CI runs
  everything as the service container's owner. `JUDGEMETRICS_ENV` is read
  from the process environment only; `.env` is loaded when it is `local`.
- The Alembic config is built in code (`judgemetrics.db.migrations`):
  `alembic/` is resolved relative to the package so the CLI, the
  container, and pytest find the same scripts, and the URL never comes
  from `alembic.ini`. Migrations are self-contained (they never import
  the models); enums are created and dropped explicitly with
  `create_type=False` on the columns; grants revoke the app role on
  `person_identifier` and `correction_request`. `uv run alembic check`
  must report no drift between the models and the head.
- The API image installs the project editable so `alembic/` sits beside
  `src/` under `/app`; the runtime stage applies Debian security
  updates and removes pip (its vendored packages are what image
  scanners flag) so the Trivy HIGH/CRITICAL gate stays clean.
- Logging: `configure_logging` replaces only its own root handler (a
  marker subclass) so pytest's capture keeps working; uvicorn's access
  log is disabled in favour of the request-id-bound middleware, and
  `alembic.runtime.migration` is raised to WARNING because
  `/api/v1/ready` asks Alembic for the current revision on every probe.
- `make_engine` sets a 5-second psycopg `connect_timeout`; without it a
  readiness probe against an unreachable host hangs for minutes on
  Windows.
- Ingest (docs/ARCHITECTURE.md): a `source_record` is one retrieved
  artifact (unique on source, external id, sha256), not one row;
  parsed rows are `SourceRecordDraft`s attributed to it. Every draft
  has a `natural_key`; the runner deduplicates on it and publishes with
  `INSERT … ON CONFLICT DO UPDATE` on the matching unique index, writing
  only rows whose substantive columns changed (JSONB identifiers and
  metadata are merged with `||`). An artifact whose hash is already
  recorded is not re-parsed unless `--force` or the connector's
  `parser_version` changed. The run row is committed first; the whole
  publish is one transaction; a failure rolls it back and records
  `failed` with a reason. Synthetic sources and fixture ingests are
  refused in production.
- Revision 0002 adds `source_record_id` to `jurisdiction`, `court`, and
  `judge` (last-substantive-writer provenance: it moves only when the
  newer artifact changed the row), `court.state_code`,
  `judge_service.metadata`, `source_record.metadata` (HTTP validators
  and the artifact URI, which is how conditional requests work),
  `ingest_run.parser_version`/`checkpoint`/`failure_reason`, and the
  natural-key unique indexes (`NULLS NOT DISTINCT`, PostgreSQL 15+).
  `jurisdiction.source_record_id` uses `use_alter=True` to break the
  source → jurisdiction → source_record cycle for table sorting.
- Raw-lake keys are `<source_id>/<yyyy>/<mm>/<sha256><ext>`; `put` never
  overwrites. `open_raw_store(settings)` picks the backend from
  `JUDGEMETRICS_RAW_STORE_URL`; the S3 endpoint must be HTTPS in
  production. Compose `minio-init` creates the application user named
  by `JUDGEMETRICS_S3_ACCESS_KEY_ID` when it differs from the root user.
- Connector headers: `schema.py` keeps the full verified header set
  (drift → warning) apart from the expected set the connector reads
  (missing → the run fails naming the header). The parser projects
  rows to the expected columns, so `judges.csv`'s `Gender` and
  `Race or Ethnicity` never enter a payload; `demographics.csv` is
  never fetched. Fixture CSVs are real rows with those two columns
  dropped; data-quality issues in fixtures are planted by row
  selection, never by editing a real record.
- The API image copies `data/reference/` so connectors that read
  curated tables (`us_states.csv`) work inside the container.
- API v1 (docs/ARCHITECTURE.md "Public API v1", docs/API.md): routes →
  services → repositories → models, with `schemas/` as the only shapes
  that leave the API. `create_app` binds the engine and a session
  factory to `app.state`; `api.deps.get_session` opens sessions from
  it, so a test app built with explicit settings never uses the
  process-wide engine (`db.session` keeps only the factories). Lists
  paginate with `count(*) OVER ()` in the page query (one statement; a
  plain count only for an empty page); `limit` ≤ 100 is enforced by the
  route and again in `paginate`. Unknown query parameters are rejected
  by an explicit `StrictQuery` allow-list per route, checked against
  the OpenAPI parameters by `tests/unit/test_openapi.py`. Search and
  the judges `q` filter set `pg_trgm.similarity_threshold` per request
  with `set_config(…, true)` (bound parameter) and match with `%` so
  the GIN trigram indexes apply; similarity is over the whole
  normalized name, so a lone misspelt surname only matches when it is
  a large share of the name. Every non-2xx response is an `ErrorBody`;
  `SQLAlchemyError` is a 503 whose text is never echoed. The `/search`
  token-bucket limiter lives in `app.state.search_limiter`, is `None`
  under `env == test` unless `search_rate_limit_enabled` is set, and
  keys on the rightmost `X-Forwarded-For` entry only when
  `trust_proxy` is true. `docs/openapi.json` is a committed snapshot:
  regenerate it with `uv run judgemetrics openapi export` after any
  route or schema change or the unit test fails. `tests/` is a package
  (`__init__.py` files) so `tests/integration/conftest.py` can coexist
  with the root conftest under mypy and its helpers can be imported;
  API integration tests ingest the FJC fixture per module, committed,
  and purge exactly that run afterwards, asserting through the
  fixture's FJC ids rather than absolute totals because a developer's
  database may also hold the live ingest.
- Web tier (docs/ARCHITECTURE.md "Web tier"): `web/lib/api/schema.d.ts`
  is generated from `docs/openapi.json` by `pnpm generate:api` and
  committed; a Vitest test regenerates and diffs it, so regenerate both
  after any route or schema change. The client helpers never throw
  (`ApiResult`), pages render `ErrorState`/`EmptyState` for every fetch,
  and every data page is `force-dynamic` so builds need no API. The
  client resolves `globalThis.fetch` per call (openapi-fetch would
  otherwise capture it at import time and bypass test stubs).
  `next-themes` keys on `data-theme`, not a class. `NEXT_PUBLIC_API_BASE_URL`
  is inlined at build time, hence a Docker build argument; the Compose
  `web` service bakes `http://api:8000`. ESLint runs
  `eslint-plugin-security` with `--max-warnings 0`; the `web` CI job
  builds before it tests so the bundle scan has output to inspect. The
  Playwright config starts no server; the `e2e` job (and the operator)
  start the API and web app first. The web runtime image strips
  npm/corepack/yarn the way the API image strips pip. `eslint-config-next`
  16 still depends on `eslint-plugin-react` 7, which does not load under
  ESLint 10, so `web/` stays on ESLint 9 until that plugin supports 10.
  The shadcn CLI resolves `cn` to a separate `cn` npm package and adds
  the `shadcn` CLI as a runtime dependency for one CSS file; both were
  replaced (`lib/utils.ts` over clsx + tailwind-merge; the two Radix
  state variants inlined in `globals.css`), so re-running `shadcn add`
  needs the same cleanup.
- Phase verification (Step 6 of each phase): `scripts/verify_phaseNN.py`
  is standard-library only, with mutually exclusive argparse modes
  (`--fast`, `--py`, `--node`, `--e2e`, `--security`, `--all`, `--post`;
  default `--fast` plus `--py`), numbered static checks over `pathlib`,
  `re`, `json`, and `git ls-files` (`[PASS] NN` / `[FAIL] NN — reason`),
  subprocess suites with argument lists over PATH-resolved `uv`, `pnpm`,
  and `gh`, the phase roadmap's V-matrix in `--post` (read through
  `gh pr checks` where a check is a CI job), and a summary table; it
  prints names and paths, never file contents. `phase-verify.yml` runs
  `--fast` then `--security` per matrix entry and its check
  `phase-verify (NN)` is a required context on `main` beside `test`
  (`CONTRIBUTING.md` "Repository settings"). The `--security` mode uses
  `detect-secrets-hook --baseline` over the tracked files, batched under
  the Windows argv limit, because `detect-secrets scan --baseline`
  rewrites the baseline and exits 0. A unit test runs `--fast`, so the
  aggregate `test` check and the `phase-verify` check fail together on
  a broken deliverable. The SAST surface is `src alembic scripts`
  (pre-commit, the CI `security` job, `--security`); a bandit
  suppression sits after the ruff one with the justification between
  them (`# noqa: S603 - fixed argv, no shell  # nosec B603`) because
  bandit reads every word after `# nosec` as a test id and warns. An
  earlier phase's OpenAPI check asserts its paths as a subset (Phase 1
  check 29, Phase 2 check 27) so a later phase's route never fails a
  required check; `tests/unit/test_openapi.py` pins the exact set.
  `verify_phase02.py --post` adds the seed idempotency probe (row
  counts through `uv run python -c … <tables>`, then `judgemetrics
  seed`, then counts again) against the configured database.
- Synthetic generator (docs/SYNTHETIC_DATA.md): `judgemetrics.synthetic`
  derives one `random.Random` per named stream (`world`, `persons`,
  `cases`, `events`, `edge_cases`) from `sha256(f"{seed}:{name}")` and
  draws only through the `random()`-based helpers in `rng.py`, so a new
  draw in one stage cannot move another stage and the output is stable
  across Python versions; identifiers are formatted counters assigned in
  one pass in filed order after the world is built; names are composed
  from the dictionary word lists in `wordlists.py` (unique across judges
  and persons except the planted collisions) and never from lists of
  real people; `truth/` (true identities, subsequent events with a
  ceiling `days_after`, resolution expectations, planted items,
  `metrics.json` with a definition per metric) is written beside
  `source/` and is never read by any connector or loaded into the
  database; `manifest.json` records the sha256 of every file and
  `verify_dataset` recomputes them; `GENERATOR_VERSION` is bumped
  whenever a fixed seed's output changes and the golden fixture
  (`tests/fixtures/golden/`, seed 7) is regenerated, never hand-edited,
  after which `.secrets.baseline` is refreshed by scanning only the
  manifest (`uv run detect-secrets scan --baseline .secrets.baseline
  tests/fixtures/golden/manifest.json`, then forward slashes in its
  `filename` entries) because `detect-secrets` flags the manifest's
  digests as high-entropy strings; the case vocabulary Step 2 writes to
  `data/reference/case_vocabulary.yaml` is fixed first in
  `synthetic/vocabulary.py` (`non_judicial` added to the discretion
  classifications for prosecutor and jury decisions).
- Case-level publishing (Phase 2 Step 2, docs/ARCHITECTURE.md "Person
  hashing and resolution", docs/DATA_MODEL.md): every row that belongs
  to a case carries `source_row_id`, the source's own row identifier,
  and upserts on `(case_id, source_row_id)` (`uq_<table>_case_source_row`,
  revision 0003); a justice event has no source row and is keyed on
  `(person_id, event_type, event_at, related_case_id)` `NULLS NOT
  DISTINCT`. The case-level upserts live in `ingest/publish.py`
  (batched 500 rows per statement; `IS DISTINCT FROM` guards as in Phase
  1) and run after the reference tables in dependency order. Person
  identifiers reach the database only as peppered sha256 hashes
  (`security/identifiers.py`, `sha256(pepper || "\x00" || kind ||
  "\x00" || normalized value)`) in the restricted `person_identifier`
  table, kinds `source_participant_id` (stable: partial unique index
  `uq_person_identifier_stable`, the deterministic resolution key),
  `full_name`, `date_of_birth`, `name_dob`; `person` has no name or date
  column and `public_person_key` is generated once at insert and never
  updated. `resolve_persons(session, drafts, run)` in `ingest/runner.py`
  is the hook Step 3 replaces. The participant id is hashed in the
  namespace the source assigns (the generator's `PT-` ids are one per
  person across courts), never prefixed with a court code — prefixing
  would split every multi-court person into pairs the truth files do
  not list. The scrubber denylist covers `pepper`, `value_hash`,
  `date_of_birth`, `full_name`; `describe_key` renders person-keyed
  drafts without the hash in issue descriptions.
- The case vocabulary is versioned in `data/reference/case_vocabulary.yaml`
  (`version: 1`), loaded once by `normalization/vocabulary.py` with
  `yaml.safe_load` (pyyaml is a runtime dependency) and equal to
  `synthetic/vocabulary.py` by unit test; `require(kind, value)` rejects
  a row whose value is unlisted, `unknown` is allowed only for
  `actor_type` and `judicial_discretion_classification`. Adding,
  renaming, or removing a value bumps `version`, updates the generator's
  constants, and is recorded in docs/DATA_MODEL.md "Vocabularies".
  Case numbers normalize through `normalization/case_numbers.py` (every
  run of whitespace or punctuation becomes one `-`; `names.py`
  re-exports it), which replaced the Phase 1 strip-everything rule so
  the planted duplicate formats collapse while the key stays readable.
- The synthetic connector (`ingest/synthetic/`) reads a dataset root
  (`JUDGEMETRICS_SYNTHETIC_DIR`, default `data/synthetic/20260916`:
  `manifest.json` plus `source/`; `truth/` is never discovered), so
  artifact ids are `manifest.json` and `source/<file>` and the runner's
  fixture reader accepts contained relative ids. `SupportsContext`
  (`load_context(artifacts)`) gives a multi-file connector every raw
  artifact of the run — changed or not — before parsing, which is where
  manifest drift fails the run and the court-code and participant-case
  indexes are built. `run_ingest(..., connector=)` lets `seed` point
  the connector at the dataset it just wrote; `seed` skips generation
  when the manifest already records the seed, scale, and
  `GENERATOR_VERSION`, generates nothing in production, and is refused
  there like any synthetic ingest. `charge.disposition_actor` (0003) is a
  documented departure from the brief's field list: the
  judicial-dismissal rule is evaluated per charge.
- Entity resolution (Phase 2 Step 3, docs/ENTITY_RESOLUTION.md):
  `entity_resolution/` is the staged framework — deterministic (stable
  identifier), rules (never a name alone: `same_name_dob` plus a shared
  case or a `related_case_number` link merges at 0.98; same court only
  reviews at 0.70; a missing or differing date of birth rejects), the
  stubbed `Scorer` (Phase 7), and the review queue. Features are
  computed from hash *equality* and the published case linkage and never
  carry a hash, name, date, or participant id; blocking is by shared
  `full_name` or `source_participant_id` hash. The ingest runner calls
  `pipeline.resolve_persons` at step 10 (find-or-create by stable id)
  and `pipeline.resolve_candidates` right after step 12, because case
  linkage is read from the published rows — one feature code path for
  the hook and `er run`. Candidates are one row per ordered pair per
  `MODEL_VERSION` (`person-rules-v0`; bump it when a rule, score, or
  threshold changes and old rows stay as history); a human decision
  (`decided_by` not starting with `system:`) is never overwritten by a
  rerun. `merge_persons` re-points every person-bearing row with Core
  updates, drops colliding justice-event and identifier rows as counted
  duplicates, and keeps the merged row with `merged_into_person_id` (no
  unmerge until Phase 6; public queries filter with `merge.unmerged()`).
  `audit_log` is append-only by trigger for every role; the app role
  has no privilege on it or on `entity_resolution_candidate`. Thresholds
  live in `data/reference/entity_resolution_thresholds.yaml` (versioned;
  equal to `config.THRESHOLDS` by test). `er review decide` is refused
  in production until Phase 6's admin authentication; the reviewer is a
  command-line label, never a git identity. Integration tests that purge
  synthetic persons must null `merged_into_person_id` (self FK,
  RESTRICT) and delete candidates first; audit rows cannot be deleted,
  so tests write them inside the rolled-back session only.
- Case API and pages (Phase 2 Step 4, docs/API.md, docs/ARCHITECTURE.md):
  the `synthetic` flag on every summary, detail, search result, and
  provenance block is derived per row from `source.source_type ==
  SYNTHETIC_SOURCE_TYPE` (the constant lives in `db/models/provenance.py`;
  the runner re-imports it) through a join to `source_record` and
  `source` in the same statement (`repositories.provenance.with_source`
  + `synthetic_flag()`), never from a column of the row, so a list stays
  one statement; `paginate_rows` returns whole rows for that. Merged
  persons are filtered at the repository: every person join applies
  `entity_resolution.merge.unmerged()` and selects `public_person_key`
  only. `repositories.cases.load_case` is one explicit statement per
  case-level table plus the provenance rows (eight, a constant); the
  timeline is assembled in `services.cases.build_timeline` from that
  same load, sorted by `at`, `TIMELINE_KIND_ORDER`, row id, with
  date-only facts at the start (`filed`) and end (`closed`) of their
  day. `/judges/{id}/cases` answers 404 from the empty-page count
  statement (`select(Judge.id, total)`), keeping the route at two
  statements. `/coverage` is one correlated-count statement over
  `source` plus one `DISTINCT ON` for the latest runs;
  `synthetic_present` means rows exist, not that a source is registered.
  The web root layout is `force-dynamic` because the demo-data banner
  reads `/coverage` per request, so no page is prerendered (builds still
  need no API). The `e2e` CI job ingests `tests/fixtures/golden` after
  the FJC fixture; the Playwright case flow discovers a synthetic judge
  and case through the API because the golden fixture and the demo seed
  name different judges. API integration test modules use the
  module-scoped `golden_fixture`, which purges the `synthetic` source
  before and after (the golden and demo datasets share natural keys, so
  the demo seed is gone after a local test run: `uv run poe seed`
  restores it); its merges leave append-only `audit_log` rows, so tests
  that count merge audits scope them to the persons kept.
  `scripts/verify_phase01.py` check 29 asserts the Phase 1 paths are a
  subset of `docs/openapi.json`, not the whole set.
- Tests (Phase 2 Step 5): every database test runs through the root
  conftest's `test_settings`; with `JUDGEMETRICS_TEST_DATABASE_URL` set
  (the scratch database `judgemetrics_test` that
  `infra/docker/postgres/03-test-database.sql` creates on `uv run poe
  up`, owned by the Compose superuser) its admin URL is that URL and the
  app and ingest role URLs are retargeted at that database, so the
  migration round trip and the fixture ingests never touch a live
  ingest and the role grants are still exercised; unset, the suite
  falls back to the configured database and warns once (never silently).
  CI points the variable at the service database. `tests/property/`
  (Hypothesis, profiles `ci`/`dev` from `HYPOTHESIS_PROFILE`) uses the
  `TINY` scale (2 courts, 3 judges, 12 persons, 16 cases) so a dataset
  generates and normalizes in well under a second; the two integration
  properties run each example in one rolled-back transaction, and the
  ingest-idempotency property is derandomized (five fixed seeds) so CI
  is reproducible; strategies never generate names. `tests/golden/` is
  the permanent, parametrized regression suite over the golden fixture
  (its conftest re-exports `golden_fixture` from
  `tests/integration/conftest.py`); a `GENERATOR_VERSION` or
  `TRUTH_VERSION` bump without regenerating the fixture fails it. The
  property tests found `tiny`-scale seeds whose world had no two unused
  persons in disjoint courts; the same-date-of-birth ambiguous plant
  now falls back to a same-court pair (still `review`) with its own
  `expected_behaviour` text, without a version bump because no
  previously generated dataset changed.
- The two secret scanners reconcile through `.gitleaks.toml`: the
  detect-secrets baseline records each allowlisted false positive as a
  `hashed_secret` sha1 fingerprint, which gitleaks' `generic-api-key`
  rule matches, so the CI `security` job failed on any baseline entry.
  The config extends the default rules and allowlists
  `.secrets.baseline` only; gitleaks (CLI and action) auto-detects it at
  the repository root.
- Metrics engine (Phase 3 Step 1, docs/ARCHITECTURE.md "Metrics engine",
  docs/METHODOLOGY.md, docs/DATA_MODEL.md "Metric registry"): the
  registry `data/reference/metric_registry.yaml` is the contract
  (`version` 1, `methodology_version` 0.1, the brief's eight warnings
  verbatim as `known_limitations`, thirty-three metrics); a
  data-semantics finding edits the entry, bumps its `version` and the
  registry `version` (old `metric_definition` rows stay as history —
  `sync_definitions` never deletes), and re-renders
  `docs/METHODOLOGY.md`, a committed snapshot that the unit test and
  `methodology render --check` compare with the render (the
  `docs/openapi.json` pattern; a relative `--out` resolves under the
  repository root). The registry carries `population`, `counted`, and
  `measure` for the compute functions beyond the fields the task named,
  and a fifth assignment gate `assigned_ever` (cases with any assignment
  of the judge), because `eligible_cases` cannot be expressed with a
  time-gated rule; a court subject always takes `court_of_case`. The
  frame (`metrics/frame.py`) is generic over the id dtype (`String` for
  the synthetic world and for UUIDs as text; Polars has no UUID type),
  every timestamp is a UTC `Datetime`, `filed_at`/`closed_at` sit at the
  start and end of their day like the case timeline, and `persons.id` is
  the only person column; no module under `metrics/` names a restricted
  attribute (the Step 6 verify script greps for it). Semantics fixed
  here and to be implemented identically by Step 2's `TRUTH_VERSION` 2:
  index events per kind, exposure deferred by the index case's own
  incarceration term only (other terms of the person are a documented
  limitation), outcomes in `(exposure_start, exposure_start + w]` with
  `new_case`/`new_charge`/`reconviction` in another case only (a null
  `related_case_id` never counts), followed = `exposure_start + w <
  coverage_end_exclusive_at`, Kaplan-Meier over the whole cohort with
  events before censorings at ties and `se = 0` when every member at
  risk fails, Wilson and Greenwood intervals rounded to six decimals at
  the boundary. A metric whose outcome the source cannot document is
  `NotObservable` (no observation, never a zero). Observations are keyed
  by snapshot (`uq_metric_observation_key`, `NULLS NOT DISTINCT`) with
  `superseded_at` history and `metric_observation_member` rows of entity
  ids (never a person id) as the provenance chain; `source.coverage_*`
  and `observable_outcomes` are the fields every connector declares from
  Step 2. The synthetic connector derives `new_case` and `reconviction`
  per participant id before merges and never derives `new_charge`, so
  the golden fixture's split persons lack two truth `new_case` events in
  `justice_event` (P-000029's `SYN-2020-000013`, P-000004's
  `SYN-2021-000021`): Step 2's snapshot loader must derive the
  other-case outcomes from the merged person's cases (or re-derive
  justice events after merges) for golden equality on the database path.
  Property tests (`tests/property/test_frame_invariants.py`) build the
  frame from an in-memory `TINY` world (`support.frame_from_world`, true
  person ids) in about a millisecond per example, check the window
  invariants in one pass per cohort because cohort building dominates,
  and derandomize the truth-equality test.
- Computation engine (Phase 3 Step 2, docs/ARCHITECTURE.md "Metrics
  engine"): `metrics/snapshot.py` exports the eleven tables a metric
  reads through SQLAlchemy Core into Polars and writes Parquet under
  `<snapshot_dir>/<content_hash>/` (`JUDGEMETRICS_SNAPSHOT_DIR`, default
  `data/snapshots`, git-ignored; the hash is the sha256 over the sorted
  `table:sha256` lines; rows ordered by id and Polars writes
  deterministically, so equal data reuses the existing directory — never
  overwritten, `mkdir(exist_ok=False)`); DuckDB is read-only over those
  files (in-memory database, views through the relation API, parameterized
  queries, a hash validated as 64 hex characters before it becomes a
  path, no extension installed or loaded — the bundled Parquet reader is
  in the wheel) and Polars does the arithmetic; timestamps are stored as
  naive UTC because DuckDB returns aware values only through `pytz`. The
  frame's `charges` carries `source_row_id` because the lead convicted
  charge breaks severity ties by the source's charge id (UUIDs would make
  a re-ingest choose differently; the demo world has 51 such ties). The
  frame's `justice_events` are the stored any-case rows plus `new_case`,
  `new_charge`, and `reconviction` derived at load time from the merged
  person's charges (the connector derives per participant id before
  merges); stored other-case rows are not read. `compute.py` dispatches
  on registry `kind`; shares, rates, and Kaplan-Meier estimates live in
  `observed_rate` (six decimals) with the bounds, medians in `value`,
  distributions in `distribution` (one observation per vocabulary value,
  zero counts included); `eligible_defendants`'s members are the cases
  (never a person id); a not-observable outcome yields no observation.
  `publish.py` refuses the whole publish (`ProvenanceError`, before any
  write) when a member id is not in the snapshot's tables, supersedes
  instead of deleting (`superseded_at`), skips a subject whose drafts
  equal its current observations column for column and member for
  member, revives a superseded row the same snapshot and definition
  produce again (the unique key spans superseded rows), and batches 500
  rows per statement; `code_version` is `<package version>+<short sha>`.
  `verify.py` compares `VERIFIED_COLUMNS` and the member multiset,
  reports an observation `unverifiable` when the current registry does
  not carry its version, and the CLI exits 1 on any problem. Pipeline
  step 13 (`Settings.metrics_recompute_on_ingest`, default true; the
  root conftest sets `JUDGEMETRICS_METRICS_RECOMPUTE_ON_INGEST=false`
  for the suite) computes the impacted subjects — the closure over the
  touched cases and their persons' other cases, so a changed charge or
  event moves every cohort it enters — inside the ingest transaction and
  records the snapshot in `ingest_run.metrics_snapshot_id` (migration
  0006: a column, not a `checkpoint` key, because the runner hands the
  whole checkpoint back to a checkpointing connector). Test fixtures
  that purge a source delete its observations first (RESTRICT FK) and
  the snapshot rows nothing cites. `SourceInfo.observable_outcomes` and
  the `SupportsCoverage` protocol fill `source.observable_outcomes` and
  `coverage_*` (written only when they differ); the synthetic manifest
  carries `corpus` from `GENERATOR_VERSION` 2 and the truth's
  `TRUTH_VERSION` 2 is the independent oracle (`tests/golden/truth_map.py`
  maps every truth path to its slug for both the unit and the golden
  suite). `duckdb` is a runtime dependency; `pytz` and `pyarrow` are not.
- Metrics API, provenance trace, and corrections intake (Phase 3 Step 3,
  docs/API.md "Metrics" and "Corrections", docs/PROVENANCE.md,
  docs/ARCHITECTURE.md "Public API v1"): suppressed numbers are stripped
  at the schema layer — `schemas.metrics.SuppressibleFigures` nulls
  `numerator`, `denominator`, `rate`, `value`, `distribution`, `lower`,
  `upper` in a validator whenever `suppressed` is true (the eligible
  count and the threshold stay), so no route can leak a withheld figure;
  `Observation.numerator` is `observed_count` and `denominator` is
  `cohort_size`; `interval_method` follows the kind (`wilson` for shares
  and fixed-window rates, `greenwood` for survival); `methodology_url`
  is `Settings.methodology_url_for(slug)` (`JUDGEMETRICS_METHODOLOGY_URL`
  + `#<slug>`, default `/methodology#<slug>`, the web route Step 4
  anchors). `SubjectMetrics.observations` is a dict keyed by slug (each
  list ordered by window, dimension, source). `/metrics/compare` cohorts
  are judges with a `judge_service` record at the court or a court of
  the jurisdiction (the `/judges?court_id=` linkage) with a current
  observation of the metric's *current* definition version; the page is
  one statement with a `LATERAL` subquery for the judge's court within
  the cohort, `count(*) OVER ()`, the cohort's reference period (the
  requested one, else the period most rows of the whole cohort share,
  from window functions), and sort columns that are null when the row is
  suppressed so the order never leaks a withheld number; `sort` is
  `rate|numerator|denominator|value|name`; an empty page costs one more
  statement that settles the cohort's existence (404). The trace
  (`metrics/provenance.py`) is three statements — the observation with
  its definition, snapshot, and source; the members outer-joined to
  their rows for `case_id` and `source_record_id`; the distinct source
  records over that statement as a subquery (never an `IN` list of
  ids) — and `complete` is `check_chain` re-checked against the live
  tables; the CLI prints the chain top-down and exits 1 when incomplete;
  the endpoint answers 404 for a superseded id and withholds the
  snapshot's `storage_uri` and any non-`http(s)` artifact URI the way
  `raw_object_path` is never returned. Migration 0007 grants the app
  role `INSERT` on `correction_request` and nothing else; the insert is
  `insert(CorrectionRequest).values(...)` with a client `uuid4()` and no
  `RETURNING` (PostgreSQL needs `SELECT` on every returned column), the
  contact is encrypted with `security.crypto.encrypt_contact` and
  nothing else, the response is `202 {id, status, received_at}`, and the
  route commits — the only commit in the API. A second token bucket,
  `app.state.corrections_limiter` (`TokenBucketLimiter(per_hour=…)`,
  default 5 an hour, burst 5, `None` under `env == test` unless
  `corrections_rate_limit_enabled`), runs before body validation.
  `create_app` requires a usable Fernet key outside `env == test`
  (`require_contact_key`, message names the variable) and
  `judgemetrics.main.app` is built lazily (PEP 562 `__getattr__`) so
  importing the module never constructs the process app. The logging
  denylist gained `correction_contact_key`, `contact`, `reason`, and
  `supporting_material`; operational log lines name their cause
  `failure`, `refusal`, or `because` so they survive the `reason` entry.
  `/search` and the judges `q` filter use word similarity (`<%`,
  `word_similarity()`, the query on the left as pg_trgm documents,
  `JUDGEMETRICS_SEARCH_WORD_SIMILARITY_THRESHOLD` default 0.5) for a
  one-token query and whole-name `%` for several tokens; the mode's
  threshold is the one `set_config` sets (`services.search.similarity_mode`).
  `/coverage` v1 adds the per-source coverage window, observable
  outcomes, latest snapshot, and methodology version (one `DISTINCT ON`
  over the current observations) plus the registry versions from the
  file; `/ready` reports the latest snapshot from one statement.
  `tests/integration/conftest.py` owns the module-scoped
  `golden_metrics` fixture (compute over the golden ingest, committed;
  the golden conftest re-exports it) so the metrics API, the provenance
  suite, and the public-contract test share one compute. The
  methodology renderer's "Sample size" prose now states that the
  denominator is withheld with a suppressed number (no version bump: the
  registry's suppression rule already said so).
- Metric pages (Phase 3 Step 4, docs/ARCHITECTURE.md "Web tier",
  web/AGENTS.md): `GET /metrics` now also serves the methodology prose
  (`how_to_read`, `semantics`, `attribution_notes`, `gate_descriptions`,
  `changelog`) and `windows_days` from the same constants
  `metrics/methodology.py` renders `docs/METHODOLOGY.md` from (the
  changelog moved into a `CHANGELOG` tuple there), so the web
  `/methodology` page is the registry the API serves, never a second
  copy; a change to that prose is a change to both surfaces and needs
  `docs/openapi.json` and `web/lib/api/schema.d.ts` regenerated.
  `web/components/metric-stat.tsx` is the only way an observation is
  rendered (numerator, denominator, period, coverage, sample size,
  interval and method, methodology anchor, synthetic badge; a suppressed
  row renders the threshold notice and no figure slot), `lib/metrics.ts`
  holds the grouping, window resolution from the registry's
  `windows_days`, null-safe formatters, cohort labels, links, and the
  cohort position (the one derived figure), and `JUDGE_PANELS` places
  unwindowed slugs while windowed metrics follow the registry's
  `index_event`. Page state is the URL: the judge page's `?cohort=` and
  `?window=` selectors and every `/compare` control are plain GET forms
  (`components/query-select.tsx`, client component, submits on change),
  and `/compare` validates its query against the registry before any
  fetch and renders `ErrorState` on an invalid value. The judge page
  makes one `/metrics/compare` call per compared definition (shares,
  rates, survival estimates, medians) under `Promise.all` — about two
  dozen cached-60s API reads per view at demo scale; the pooled value
  is `/courts/{id}/metrics` of the judge's current or latest court and
  no jurisdiction pooled value exists. The cases route has no pretrial,
  disposition, or sentence filter, so "View eligible cases" is
  `status=closed` for Disposition and Sentencing and unfiltered
  elsewhere. The banner's `/coverage` read goes through
  `lib/coverage-cache.ts` (sixty-second in-process TTL, failures never
  cached, bypassed under `NODE_ENV=test`); `NODE_ENV` joined `CI` and
  `PLAYWRIGHT_BASE_URL` in the hygiene test's allowed `process.env`
  reads because it is Node's own flag, not a setting. `/coverage`
  fetches `/metrics` beside `/coverage` to name the registry outcomes a
  source cannot observe. The Playwright metrics flow
  (`web/tests/e2e/metrics.spec.ts`) needs computed metrics over a
  synthetic dataset — the demo seed locally; Step 5 switches CI's `e2e`
  job to the seed — and the smoke test's coverage note now reads
  "Phase 5".

## End-of-session report (from the brief)

Every implementation session ends with: files created or changed;
architecture implemented; commands executed; test results; what
currently works; known issues; external access still needed; and the
next concrete development milestone.
