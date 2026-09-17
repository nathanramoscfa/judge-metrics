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
```

In `web/`: `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`,
`pnpm e2e`, `pnpm generate:api`. Later steps add `seed`,
`compute-metrics`, and `bootstrap`.

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
  a broken deliverable.
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
- The two secret scanners reconcile through `.gitleaks.toml`: the
  detect-secrets baseline records each allowlisted false positive as a
  `hashed_secret` sha1 fingerprint, which gitleaks' `generic-api-key`
  rule matches, so the CI `security` job failed on any baseline entry.
  The config extends the default rules and allowlists
  `.secrets.baseline` only; gitleaks (CLI and action) auto-detects it at
  the repository root.

## End-of-session report (from the brief)

Every implementation session ends with: files created or changed;
architecture implemented; commands executed; test results; what
currently works; known issues; external access still needed; and the
next concrete development milestone.
