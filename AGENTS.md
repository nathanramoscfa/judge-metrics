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
- `docs/roadmap/ROADMAP.md` — the project roadmap (phases,
  architecture, branch, security, release, and operations strategy).
  Read §5 before any work.
- `docs/roadmap/phaseNN-roadmap.md` — the executable plan for one
  phase, one step per agent session. Start from the step you were given.
- `docs/ROADMAP.md` — the living status document: current phase,
  completed items, unresolved data-access questions, next milestones.
  Update it at the end of every step; record a data-access question
  there instead of inventing an answer.
- `docs/DATA_SOURCES.md` — the source register. A connector may depend
  only on facts marked verified there.
- `planning/` — the roadmodel planning kit. When asked to recommend a
  model for a step, run `planning/model-selector.txt` yourself against
  `planning/user-context.md`; do not call an external API or MCP tool
  (`planning/HOW-TO-USE.md`, "you are the engine"). The roadmodel
  updater (`/roadmodel-upgrade`, run daily on the maintainer's machine)
  keeps the kit current: it upgrades roadmodel inside `.venv` and
  re-exports `planning/`, so a phase starts on a current kit without
  anyone running anything. A step that finds that refresh uncommitted
  commits it first, on its own, together with the matching lock bump
  (`uv lock --upgrade-package roadmodel==<release>`), and names the
  release from the latest `[judge-metrics] <old> -> <new> | kit
  refreshed` line of `~/.config/roadmodel/update.log` — not from
  `roadmodel version` on `PATH`, which is a separate install. `uv sync`
  and every `uv run` put `.venv` back on the release `uv.lock` pins, so
  `uv run poe kit` exports the locked release: run it only when the
  lock is at least the kit's release, or it rolls `planning/` back to
  an older kit.

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
uv run poe up              # docker compose: minio volume owner, postgres + minio healthy, bucket, scratch DB
uv run poe down            # docker compose down
uv run poe kit             # re-export planning/ with the locked roadmodel (only when the lock is at least the kit's release)
uv run poe migrate         # alembic upgrade head as the admin role
uv run poe dev-api         # uvicorn with reload: /api/v1/health, /api/v1/ready
uv run poe dev-web         # Next.js dev server in web/ (pnpm) against the local API
uv run poe ingest-fjc      # FJC judges, courts, service records → raw lake + canonical tables (ingest role)
uv run poe ingest-cook     # the five Cook County SAO exports (1.2 GB) streamed → raw lake, parser 0 (not in bootstrap); a rerun downloads nothing
uv run judgemetrics sources profile cook_sao [--out PATH] [--check] [--from-fixture DIR]   # data/reference/cook_sao/profile.yaml from the stored exports (ingest role); --check exits 1 on drift
uv run judgemetrics sources excerpt cook_sao --out DIR [--from-fixture DIR]   # the stratified real-row fixture, blanked columns emptied; excerpting the fixture reproduces it
uv run judgemetrics        # CLI: db upgrade|downgrade|current, serve, ingest list-sources|run|runs, openapi export
uv run judgemetrics synthetic generate --seed 7 --scale golden --out DIR   # deterministic synthetic dataset: source/, truth/, manifest.json
uv run judgemetrics synthetic verify DIR                                   # recompute every file hash; exit 1 on a mismatch
uv run poe seed            # generate data/synthetic/20260916 (demo scale, skipped when current) and ingest it through the synthetic connector
uv run judgemetrics ingest run synthetic --from-fixture tests/fixtures/golden   # the golden fixture through the runner
uv run judgemetrics er run [--source synthetic]   # recompute person candidates, apply system merges (idempotent)
uv run judgemetrics er review list [--json]       # the manual-review queue: public keys, stage, score, feature flags
uv run judgemetrics er review decide <id> --decision matched|rejected --reviewer <label> --reason <text>
uv run judgemetrics methodology render [--out docs/METHODOLOGY.md] [--check]   # docs/METHODOLOGY.md from the metric registry; --check exits 1 on drift
uv run poe compute-metrics                       # judgemetrics metrics compute: snapshot → fit the snapshot's missing outcome models → every registry metric for every judge and court → observations (ingest role)
uv run judgemetrics metrics compute [--label TEXT] [--subject judge:<uuid> ...] [--json]
uv run judgemetrics metrics verify [--snapshot HASH] [--json]   # recompute every current observation from its snapshot; exit 1 on any mismatch
uv run judgemetrics provenance trace <observation id> [--json]  # the chain from a published number to the raw artifacts, top-down (app role; an adjusted observation's model artifact is checked under JUDGEMETRICS_SNAPSHOT_DIR); exit 1 when incomplete
uv run judgemetrics models fit [--snapshot HASH] [--json]       # fit and record every expected-outcome model the latest (or named) snapshot lacks (ingest role); idempotent
uv run judgemetrics models list|show <id or hash> [--json]      # the model catalogue and a model card (app role); never the storage URI
uv run judgemetrics models verify [--snapshot HASH] [--refit]   # every artifact hashes to its row; --refit reproduces it byte for byte; exit 1 on any mismatch
uv run judgemetrics validation report [--out docs/VALIDATION.md] [--check] [--truth DIR]   # the model validation from the latest snapshot (ingest role); --check exits 1 with a diff, 2 without a snapshot or model
uv run judgemetrics validation recovery --truth DIR [--json]   # the planted-effect recovery of the published figures; exit 1 below a tolerance, 2 for a truth no source ingested
# GET /api/v1/models/{id}: the model card an adjusted observation cites (docs/API.md "Models")
uv run poe bootstrap                             # up → migrate → ingest-fjc → seed → compute-metrics: the one-command startup (idempotent; `make bootstrap` runs `uv sync` first)
uv run judgemetrics seed --out data/synthetic/ci  # the seed into another directory (the CI e2e job)
```

`ingest run` and `seed` need `JUDGEMETRICS_IDENTIFIER_PEPPER` (a real
random value in the untracked `.env`; the tests set a fixed one). The
API (`dev-api`, `serve`) needs `JUDGEMETRICS_CORRECTION_CONTACT_KEY` (a
Fernet key in `.env`) outside the test environment and refuses to start
without one.

In `web/`: `pnpm lint`, `pnpm typecheck`, `pnpm test`, `pnpm build`,
`pnpm e2e` (smoke, metrics, first milestone; against `dev-api` and
`dev-web` after `bootstrap`), `pnpm generate:api`.

## Architectural decisions that matter for future sessions

- The dependency audit runs `pip-audit --strict --require-hashes` over
  an export of `uv.lock` (`scripts/audit_deps.py`), not over the live
  environment: the editable `judgemetrics` project is not on PyPI, so
  a raw `pip-audit --strict` fails for the wrong reason.
- `up` is a sequence task: `docker compose run --rm minio-volume-init`,
  `docker compose up -d --wait postgres minio`, and then `docker compose
  run --rm minio-init` and `postgres-test-init`, because `--wait`
  treats a cleanly exited one-shot job as a failure.
- MinIO images come from Chainguard (`cgr.dev/chainguard/minio`,
  `cgr.dev/chainguard/minio-client:latest-dev`) pinned by digest: MinIO
  no longer serves its own images anonymously (Docker Hub repository
  removed, `quay.io/minio` answers 401). Only the `latest`/`latest-dev`
  tags are free, so bump by updating the digest. The Chainguard MinIO
  image runs as uid 65532 (`nonroot`); a volume created by the earlier
  root-running image is owned by root and MinIO then exits "Unable to
  write to the backend", so `up` starts with `up-volumes`, the one-shot
  `minio-volume-init` service (profile `init`, root for the `chown`
  only). Never give the `minio` service a `user:` override instead.
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
  after which `.secrets.baseline` is refreshed by scanning only the files
  whose digests it allowlists (`uv run detect-secrets scan --baseline
  .secrets.baseline tests/fixtures/golden/manifest.json
  data/reference/cook_sao/profile.yaml data/reference/cook_sao/tables.yaml`,
  then forward slashes in the `results` keys and `filename` entries)
  because `detect-secrets` flags their digests as high-entropy strings — a
  scan given file arguments rewrites `results` to exactly those files, so
  naming one drops the others' entries; the case vocabulary Step 2 writes to
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
- Corrections form, court and jurisdiction pages, `bootstrap`, and the
  walkthrough (Phase 3 Step 5, docs/ARCHITECTURE.md "Web tier",
  docs/API.md "Corrections", web/AGENTS.md): `bootstrap = ["up",
  "migrate", "ingest-fjc", "seed", "compute-metrics"]` is a poe sequence
  whose every stage is idempotent (a second run starts nothing, migrates
  nothing, re-ingests nothing, regenerates nothing, publishes nothing);
  `uv sync` is its documented prerequisite because poe runs inside the
  environment (`make bootstrap` runs `install` first); `seed` fails
  loudly without the pepper, and the contact key is checked when the
  API starts (`dev-api`), not by `metrics compute`, which never needs
  it. `judgemetrics seed --out DIR` is the CI form. The `e2e` job
  generates a throwaway pepper and Fernet key into `$GITHUB_ENV`
  (masked; never a workflow value), seeds the demo dataset into
  `data/synthetic/ci`, runs `metrics compute` (a no-op after pipeline
  step 13, kept because it is the operator's sequence), and runs every
  Playwright suite; `verify_phase02.py` check 33 accepts the seed or the
  golden fixture and the pepper as a variable or a `$GITHUB_ENV` line,
  and the hygiene test asserts the generation lines. The web tier's one
  write path is `POST /api/corrections`, a Next route handler
  (`web/lib/corrections-handler.ts`) that validates the body against
  the limits mirrored in `web/lib/corrections.ts`, forwards exactly
  `ALLOWED_FIELDS` (never a spread) with the caller's `X-Forwarded-For`
  through `submitCorrection(body, { forwardedFor })`, returns `{id,
  status}` or the API's error body under the API's status (a transport
  failure is 503), sets no cookie, and logs nothing — the API's limiter
  keys on the forwarded chain only under `JUDGEMETRICS_TRUST_PROXY`,
  which the Compose `web` service documents. The corrections page
  never calls the API's write path from the browser. "Report a data
  error" (`components/report-error-link.tsx`) sits on the judge, court,
  and case headers and on every `MetricPanel` with its first
  observation's id; the court page's panels are `COURT_PANELS` (the
  court-only counts in Pretrial); the jurisdiction page derives its
  sources from the jurisdiction's provenance plus the synthetic sources
  when a court is synthetic (`web/lib/jurisdictions.ts`) because a court
  summary carries no provenance. Playwright's `toHaveURL` takes a
  predicate in the walkthrough because `eslint-plugin-security` flags a
  `new RegExp` over a discovered id. Security finding fixed in-step:
  `infra/docker/postgres/03-test-database.sql` reruns on every `uv run
  poe up` (so on every `bootstrap`) and its blanket `GRANT SELECT ON ALL
  TABLES … TO judgemetrics_app` re-opened `person_identifier`,
  `correction_request`, `audit_log`, and `entity_resolution_candidate`
  in the scratch database after the migrations had revoked them (the
  grants test then failed until the migration round trip restored
  them); the script now ends with a `DO` block re-applying the
  migrations' revokes for every restricted table that exists. A script
  that grants on `ALL TABLES` and can run after the migrations must do
  the same.
- Phase 3 verification (Phase 3 Step 6, docs/phase03-qa-findings.md):
  `scripts/verify_phase03.py` keeps the Phase 2 chassis (49 static
  checks, `phase-verify (03)` required beside `test`, `(01)`, `(02)`).
  Its static mode stays standard-library only by reading the registry's
  `known_limitations` with a minimal line reader and the brief's
  warnings with a regular expression over the one XML element (an XML
  parser is SAST-flagged); `test_phase03_verification.py` pins both
  against `yaml.safe_load`. Each phase's unit test and matrix check
  assert its own entries as a subset of the matrix, never the exact
  list, so a later phase's entry never fails an earlier phase's check.
  `--post` runs every writing probe (items 3–5 `up`/`migrate`/`seed`,
  the `bootstrap` rerun, the seed and compute idempotency probes,
  `metrics verify`, a random `provenance trace`) inside
  `probe_environment()`, which points the three role URLs at
  `JUDGEMETRICS_TEST_DATABASE_URL` and `JUDGEMETRICS_SNAPSHOT_DIR` at
  `data/snapshots/scratch-test-db` (persistent, git-ignored: the scratch
  database's observations cite their snapshots, so a deleted temporary
  directory would fail a later `metrics verify` there; captured children
  get `PYTHONIOENCODING=utf-8` because a piped CLI writes cp1252 on
  Windows), and only then the Python suites and item 17
  (`poe check`), which purge the scratch database's synthetic source;
  items 6–7 and the Playwright suites need `dev-api` and `dev-web`
  running and report `SKIP` otherwise. GitHub's required-checks
  endpoint is `PATCH …/protection/required_status_checks`.
- Planted effects and the restricted schema (Phase 4 Step 1,
  docs/SYNTHETIC_DATA.md "Planted effects", docs/DATA_MODEL.md "The
  restricted schema", docs/ARCHITECTURE.md "Restricted schema"):
  `GENERATOR_VERSION` and `TRUTH_VERSION` are `3`. `synthetic/effects.py`
  holds every functional form and constant (release and failure to appear
  logistic in the banded features, the next filing's skew exponent `k =
  max(0.25, 0.6 + 3.0·R + 2·propensity + b[band] + effect)`, the docket
  tilts ordered inversely to the new-case effects per court) and the
  exact window arithmetic; the `effects` and `attributes` streams are new
  (`STREAM_NAMES`), and `build_dataset(seed, spec, streams=)` lets a test
  re-seed one. The risk term in the exponent is a documented departure
  from the step's literal formula: without it the raw new-case rates
  ranked the effects as well as any adjustment could. Risk features are
  read from rows strictly before 00:00 UTC of the filing day — the
  instant the frame's `cases.filed_at` carries — so Step 2's history
  features must use the same instant. Every simulated case records what
  its draws knew (`Case.draws`: `ReleaseDraw`, `FtaDraw`, `FilingDraw`),
  and `truth.compute_effects` turns those into `truth/effects.json`
  (per-judge and per-court aggregates only): `p` with the judge's effect,
  `p0` with the decision-weighted mean effect of the case's court,
  other cases' outcomes entering as realized, so the oracle is exact for
  the draws a judge's effect enters and unbiased in total. Calibrated on
  the demo seed (release ρ 0.944, new case 0.846, failure to appear
  0.933; raw new-case ρ 0.716); `DEMO` keeps its size. Changing any
  constant changes every draw after it, so a recalibration re-runs
  `tests/unit/test_synthetic_effects.py` and regenerates the golden
  fixture. `edge_cases._ambiguous_pair` indexes the persons' courts in
  one pass (identical output; the demo world builds in under a second).
  The `tiny` seed that exercises the same-court ambiguous fallback is now
  117. Exposure (methodology `0.2`, `metrics/exposure.py` and
  `truth.deferred_start` independently): the disposition kind first moves
  to its own case's term end, then every kind moves past each
  incarceration term of the person that contains the start (the one
  ending last), `deferral_days` totalling the terms applied; a literal
  "contains" rule alone would have dropped the disposition kind's own
  term, because a sentence always follows its disposition. The registry's
  eighteen eligibility sentences that restated the old rule were
  corrected in place without an entry or registry bump (`version` stays
  1; `sync_definitions` updates the rows in place, as it does for the
  `methodology_version`). Revision 0008 creates the `restricted` schema
  (`USAGE` for the ingest and admin roles only, `PUBLIC` revoked, no app
  grant, default privileges for the migrating role and the admin role)
  with `restricted.party_attribute`, turns on `include_schemas` (filtered
  to `public` and `restricted`), and rewrites `case_party.source_row_id`
  to `<party_type>:<ordinal>` in `COLLATE "C"` order of the old key
  (dropping and recreating the unique index around the update); a
  downgrade keeps the ordinal keys. Creating a schema needs `CREATE` on
  the database: `02-roles.sql` grants it to the admin role on a fresh
  volume and the rerunning `03-test-database.sql` on an existing one (so
  `uv run poe up` must precede `uv run poe migrate` once), and the latter
  revokes the app role's usage of `restricted` whenever it exists. The
  model constants are `RESTRICTED_SCHEMA` and `RESTRICTED_SCHEMA_TABLES`;
  `Base.metadata.tables` keys the table `restricted.party_attribute`. The
  snapshot refuses any table of that schema by its schema
  (`refuse_restricted`), never by name, so no module under `metrics/`
  names a restricted attribute (the unit test and `verify_phase03.py`
  check 9 glob `metrics/**/*.py`). The connector (`parser_version` "2")
  maps `age_at_filing` through `normalization/age_bands.py` (a bounded
  integer 0-130, blank → `unknown`; the generator's `age_band_of` is a
  separate copy held equal by test) and publishes one
  `PartyAttributeDraft` per attribute, whose `repr` withholds the value;
  the runner upserts them after the parties and rejects one whose party
  is not in the run (`unresolved_party`). Vocabulary `version: 2` adds the
  restricted kinds; `age_band` is the third kind that lists `unknown`.
  The scrubber denylist gained `age_band`, `synthetic_group`, and
  `attribute_value`. `verify_phase03.py` check 14 reads both versions from
  the source constants (an earlier phase's check must never fail on a
  later bump). Test infrastructure: `purge_source` also removes the
  run-level (`source_record_id` NULL) issues of the case-level entity
  types, which no purge reached and which leaked into later modules' and
  sessions' issue counts.
- Expected-outcome model (Phase 4 Step 2, docs/ARCHITECTURE.md "Risk
  adjustment", docs/DATA_MODEL.md "Outcome model specification"):
  `data/reference/outcome_model.yaml` (`version` 1, `model_version`
  `expected-logit-v1`) is the third versioned reference file; a value that
  alters a fitted model or a published figure bumps `version`, a `recovery`
  tolerance does not. `metrics/adjustment/spec.py` validates every feature
  against `FEATURE_CONTRACTS` (kind, known-at instant, the exact frame
  columns read; the same keys as `features.FEATURE_BUILDERS`), so adding a
  feature means a builder, a contract, and a YAML entry together; a feature
  naming a `restricted_attribute` value (read from the vocabulary — no
  module under `metrics/` may spell one), an excluded name, or an excluded
  column is rejected first. Targets name registry metrics as populations
  (`pretrial_decisions`, `new_case_rate`, `failure_to_appear_rate`) and the
  design reuses `pretrial_decisions_for`, `index_events`, `with_exposure`,
  `first_outcomes`, and `member_windows` judge by judge (the published
  gate). History features read strictly before 00:00 UTC of the index
  case's filing date; the index case's own charges strictly before the
  pretrial decision. A prior case is pending as of the filing when one of
  its charges filed before it was pending then (disposed at or after it,
  or `pending`) or none was disposed before it — a charge without a
  recorded disposition is ignored; that rule is what keeps the features
  leakage-free (the "latest disposed charge" rule is not: it reads whether
  a later charge was disposed) and it equals the generator's on every
  synthetic world (`test_adjustment_features.py` compares the golden
  world's design with `case.draws.features`; the demo world matched on
  all 4,534 decisions). Data levels are ordered by row count and then a
  source-assigned key (a court's earliest `<filed_at>|<source_row_id>`),
  courts and jurisdictions labelled by rank, so artifacts carry no UUID;
  the catalogue row's `coefficients` map a rank back to the court id. The
  solver uses only `np.einsum` (default `optimize=False`, never BLAS) and a
  NumPy column Cholesky (never LAPACK) so fits are bit-identical; an
  unpenalized fit of separated data "converges" at a runaway coefficient
  because the gradient vanishes — only the calibration slope is
  unpenalized. Bootstrap streams are `bootstrap:<target>:<window or
  none>` derived like `synthetic/rng.py`'s; replicate refits start from the
  published coefficients. The events-per-column gate counts the limiting
  class (the fewer of outcomes and non-outcomes) against every design
  column including the intercept: every golden model is
  `insufficient_events`, every demo model `fitted` (13; about 30 s with
  500 replicates each). Artifacts are canonical JSON (sorted keys, twelve
  significant digits) at `<snapshot_dir>/<snapshot>/models/<sha256>.json`,
  written with `open(path, "xb")` through `artifacts.artifact_path`, which
  validates both hashes; `models verify` rebuilds the path from settings,
  never from `storage_uri`, and `--refit` renders under the row's
  `code_version` so a later commit does not count as a mismatch. Revision
  0009 adds `outcome_model` (unique key `NULLS NOT DISTINCT` over snapshot,
  source, spec version, target, window, seed; `SELECT` for the app role,
  DML for ingest) — twenty-seven `CANONICAL_TABLES`; `purge_source` in
  `tests/integration/conftest.py` deletes a source's models after its
  observations and before the snapshots they cite. The frame gained
  `courts` (id, jurisdiction) — the snapshot already exported it — so a
  `Frame(...)` construction must pass it (`snapshot.py`,
  `tests/property/support.frame_from_world`). Integration tests that
  invoke the CLI from a module-scoped fixture must clear `get_settings`
  first (the autouse per-test clear runs after module fixtures) and parse
  `result.stdout` (log lines go to stderr, which `result.output` mixes in).
  `metrics compute` did not fit in Step 2 (Step 3 changed that, below).
- Observed-to-expected ratios (Phase 4 Step 3, docs/ARCHITECTURE.md
  "Observed-to-expected ratios", docs/DATA_MODEL.md, docs/SYNTHETIC_DATA.md
  "Recovery"): registry `version` 2, methodology `0.3`, kind
  `observed_expected` (unit `ratio`, `registry.OBSERVED_EXPECTED`;
  `DESCRIPTIVE_KINDS` is the other six) with three judge metrics whose
  required `adjustment` field names the specification target and the minimum
  expected count (5; `suppression_threshold` 30) — the loader rejects the
  field on any other kind, a court subject, windows over decisions, and the
  `ratio` unit elsewhere. The computation is per source, never per subject:
  `compute_frame(..., kinds=, models=)` (kinds default to the descriptive
  ones; asking for the adjusted kind without models is a `ComputeError`, and
  `compute_metric` refuses it) hands each adjusted definition to
  `adjustment.ratios.adjusted_observations`, which builds one design per
  target and window over every eligible event (`features.design_rows`),
  scores it (`expected.expectations`: per judge n, O, E by `np.bincount` in
  design order), fits the gamma shape over every judge with E > 0
  (`pooling.fit_shape`: Σ_{k<O} log(α + k), no scipy; 200-point log grid over
  [0.5, 1000] whose end points are the bounds themselves, then golden-section
  in log α; judges summed in (E, O) order so relabelling changes nothing),
  and replays the fit's bootstrap (`bootstrap.interval`: the same
  `resample.replicates` stream per replicate, the artifact's replicate
  coefficients, a non-converged replicate skipped with its weights still
  drawn; linear-interpolation 2.5/97.5% quantiles). `ratios.estimate(design,
  parameters, spec)` is that pipeline for one design — the recovery test
  calls it. Models reach the compute as `expected.ModelParameters`, read from
  the artifact bytes the catalogue records (`catalog.read_parameters`,
  `snapshot_parameters`) or from an in-memory fit (`from_fitted` rounds to
  twelve significant digits as the artifact does, so both give identical
  floats); `engine.compute_and_publish(kinds=None)` records the snapshot row,
  runs `catalog.fit_snapshot`, reads every model back, computes, and
  publishes, and pipeline step 13 passes `kinds=DESCRIPTIVE_KINDS` (no fit, no
  adjusted figure). `publish(..., kinds=)` loads, compares, and supersedes
  only those kinds, so a judge an ingest touches keeps its adjusted rows (on
  the older snapshot) until the next full compute — the documented exception
  to ROADMAP §5 "Performance rules". Drafts carry `expected_count`,
  `expected_rate`, `standardized_ratio`, `pooling_weight`,
  `suppression_reason`, and `model_hash`; `publish` maps the hash to
  `outcome_model_id` (refusing an unrecorded one) and `VERIFIED_COLUMNS`
  include all six (`outcome_model_hash` is a pseudo-column read through an
  outer join in `load_observations`). Every suppressed row of every kind
  carries `suppression_reason` (`suppression.apply`: `below_threshold`, then
  `expected_below_minimum`, then `model_unavailable` — E is None exactly when
  the model is not fitted). Migration 0010 adds `outcome_model_id` (RESTRICT,
  indexed), `pooling_weight` Numeric(9, 6), `suppression_reason` (two
  checks: the three values, and reason ⇔ suppressed), backfills
  `below_threshold` on the stored suppressed rows, and names every
  constraint through `op.f()` — a plain name gets the naming convention
  applied twice (`ck_metric_observation_ck_…`), which `alembic check` does
  not notice because it does not compare check constraints. `metrics
  verify` recomputes a snapshot for the kinds it holds, reports a missing
  draft only where the subject holds that kind, and reads an adjusted
  observation's cited model from its artifact (missing or altered: a
  mismatch with column `outcome_model`). The provenance trace joins the model
  in its first statement (still three) and needs `settings` to check the
  artifact (`trace(..., settings=, kinds=)`; the CLI passes them). The public
  hold-out is `services.metrics.SERVED_KINDS` (the six Phase 3 kinds): the
  registry response, the subject statements (kind filter in SQL), compare
  (422), and the provenance route (404) — Step 5 adds the kind with its
  schema. `/api/v1/ready` adds `metrics.models` (`fitted`, `unavailable`,
  `spec_version`, `model_version`; `repositories.coverage.snapshot_models`,
  one statement). Golden adjusted observations are all `below_threshold`
  (cohorts under 30; models `insufficient_events`, so E is null);
  `test_golden_metrics.py` excludes the adjusted kind (its truth is
  `effects.json`, `test_golden_adjusted.py`). The recovery test
  (`tests/golden/test_golden_recovery.py`, demo world in memory, about 15 s)
  set the specification's `recovery` tolerances (Spearman 0.9/0.7/0.9, sign
  above 0.85, expected-count Pearson 0.95, interval coverage 0.55) with the
  measured values in the YAML comment; the new-case margin over raw rates is
  0.003 and the interval covers the true ratio for 60-68% of judges (the
  pooled estimate is shrunk), both carried to Step 4. `relabel_frame` moved
  into `tests/property/support.py`. CLI tests that invoke a command twice
  with different environments clear `get_settings` around each call.
- Validation report and methodology 1.0 (Phase 4 Step 4,
  docs/ARCHITECTURE.md "Validation", docs/VALIDATION.md,
  docs/METHODOLOGY.md "Adjusted statistics"): `judgemetrics.validation`
  (`inputs`, `fairness`, `sensitivity`, `stability`, `recovery`,
  `report`, `statistics`) renders `docs/VALIDATION.md` from the latest
  snapshot's models, the committed document being the demo seed's; the
  `e2e` job re-renders it from `data/synthetic/ci` (a byte-identical
  manifest) with `--check`, so a CI difference is an order-invariance bug,
  never a reason to drop the check. The report names no UUID, hash, code
  version, run timestamp, judge, judge code, or local path (a data level
  is its rank label; the coefficient rows' `level` holds the court id and
  is never read), every list has a data-fixed order, and the statistics
  over judges are tie-averaged rank correlations, medians, quartiles, and
  shares. After a registry, specification, or estimator change: `uv run
  poe compute-metrics`, then `uv run judgemetrics validation report`, and
  commit the document with the change. `validation/fairness.py` is the
  only reader of the `restricted` schema (`require_ingest_role` compares
  `current_user` with the ingest URL's user; one statement with the
  decision ids bound as one array; cells withheld below `minimum_cohort`
  events or `minimum_expected` expected events with no figure); the static
  `tests/unit/test_restricted_readers.py` matches `party_attribute`,
  `PartyAttribute`, `restricted.<name>`, and `schema="restricted"` (the
  ORM class too, which the step's three patterns alone would miss) and
  allows the reader, the ORM model, `db/models/__init__.py`, and Step 1's
  write path; `logging.py`'s comment no longer spells the table.
  Methodology `1.0` is the registry's `methodology_version` (registry
  `version` stays 2: no entry changed); `metrics/methodology.py`'s
  `adjustment_prose(spec, registry)` builds the "Adjusted statistics"
  section and `GET /api/v1/metrics`'s `adjustment` block from the outcome
  model specification and the registry — the old "Observed-to-expected
  ratios" section and `ADJUSTMENT_TEXT` are gone, and `INTERPRETATION`
  (the brief's O/E reading, verbatim) lives there. The served prose must
  name no restricted attribute value or name (`age_band`,
  `synthetic_group`, `party_attribute` are scanned by the public contract
  test; no module under `metrics/` may spell them, so the prose says "age
  band") and no feature source column (`charges.person_id` would trip the
  person marker). A methodology bump republishes every observation (the
  publish compares `methodology_version`; the demo compute took about
  three minutes) while a reused snapshot row keeps its first version. The
  subgroup-calibration test asserts the positive control's direction at
  the extreme bands and a Spearman of at least 0.8 with the planted
  effects, not a strict order (45-54 sits above 35-44 by chance on the
  demo world, Spearman 0.9). The new-case models' poor temporal transport
  is a generator artifact (next filing within the remaining corpus span:
  docs/SYNTHETIC_DATA.md "Temporal transport"), reported, not tuned.
- Serving the adjusted kind (Phase 4 Step 5, docs/API.md "Metrics" and
  "Models", docs/ARCHITECTURE.md "Public API v1" and "Web tier"):
  `SERVED_KINDS` is every registry kind (the SQL kind filters stay as the
  place a future kind is held out). Every `Observation`, `CompareRow`, and
  traced observation carries the required, nullable `expected`,
  `expected_rate`, `ratio`, `ratio_lower`, `ratio_upper`, `pooling_weight`,
  `model` (`ModelRef`, `url` = `/api/v1/models/{id}`), and
  `suppression_reason`; `SUPPRESSED_FIELDS` gained the six figures (the
  reason and the model survive suppression), and `services.metrics.figures`
  is the one stored-column mapping — an adjusted row's bounds become
  `ratio_lower`/`ratio_upper` while `lower`/`upper` (a share's `[0, 1]`)
  stay null. The model reference rides an outer join to `outcome_model` in
  the subject, compare, and trace statements (budgets unchanged).
  `MetricDefinitionOut.adjustment` (`target`, `minimum_expected`) is set
  for the adjusted kind only. `/metrics/compare`'s `sort` is `None` by
  default and resolves to `ratio` for the adjusted kind, `rate` otherwise
  (`services.metrics.default_sort`; the OpenAPI parameter is now an
  `anyOf`). `GET /models/{model_id}` is one statement from the catalogue
  row (never `storage_uri`, never the artifact) and a 404 once no current
  observation cites the model's snapshot. The provenance route passes
  `settings` to `trace`, so the API checks the model artifact under its own
  `JUDGEMETRICS_SNAPSHOT_DIR`: an API that cannot read the compute's
  snapshot directory answers an adjusted chain `complete: false`, so the
  Compose `api` service mounts `./data/snapshots` read-only at
  `/app/data/snapshots` (asserted by the hygiene test). `tests/integration/conftest.make_app`
  carries `snapshot_dir`, and `golden_api` is built from
  `golden_metrics.settings` (it now depends on the compute). Twenty-one
  OpenAPI paths, nineteen StrictQuery routes; the public contract allows
  the models' content hashes and walks every model card. Web:
  `AdjustedStat` is the only adjusted renderer (web/AGENTS.md), the judge
  page's adjusted panel is `JUDGE_PANELS`' `kind` entry, `KIND_TEXT` moved
  to `lib/metrics.ts` (a page module may export only Next's route
  conventions), `CompareTable`'s court and suppressed cells wrap
  (`whitespace-normal`) so a seven-column table fits the page, and
  `web/tests/e2e/adjusted.spec.ts` needs the demo seed's fitted models (CI's
  `e2e` job seeds it). `uv run poe dev-web` cannot spawn `pnpm` on Windows
  (uv finds no `pnpm.exe`); run `pnpm dev` in `web/` there.
- Audit exceptions: an advisory with no fixed release and no production
  path (`pnpm why <pkg> --prod` empty, absent from the runtime image) is
  excepted, never ignored silently: `auditConfig.ignoreGhsas` in
  `web/pnpm-workspace.yaml` (pnpm 10 reads it there, and YAML holds the
  inline justification JSON cannot), with an issue that removes it. The
  first is GHSA-vfj7-8cjw-p6xm (`braces`, lint tooling only; #47). An
  advisory an upgrade can fix is fixed in the step that meets it.
- Phase 4 verification (Phase 4 Step 6, docs/phase04-qa-findings.md):
  `scripts/verify_phase04.py` keeps the Phase 3 chassis (50 static checks,
  `phase-verify (04)` required beside `test` and `(01)`–`(03)`). Every
  version check compares the source constant (or the YAML scalar) with a
  `>=` minimum, never a literal, so a later phase's bump never fails this
  phase's required check. The specification's features are read with a
  line reader (`_spec_features`) and the brief's `<interpretation>` with a
  regular expression; `test_phase04_verification.py` pins both, the
  registry reader, and the changelog reader against `yaml.safe_load`, an
  independent expression, and the module. A guard that forbids a name
  matches uses, not mentions (check 15: `artifacts.py`'s docstring names
  `pickle`, `numpy.load`, and `eval`). `_function_body` ends a function at
  the next top-level `def`/`class`/decorator/comment/name, never at the
  column-0 `)` of a multi-line signature. `--post`'s first-milestone items
  carry no V id in Phase 4's matrix, so an `M` row folds them into the
  summary (otherwise a failed item would print `[FAIL]` and still exit 0).
  The validation probes read the truth of the probe's dataset
  (`JUDGEMETRICS_SYNTHETIC_DIR`, default `data/synthetic/20260916`); the
  adjusted trace probe picks a current `observed_expected` observation that
  cites a model and requires an `outcome model <hash>` line.

- Cook County source, streamed fetch, profile, and fixture (Phase 5 Step 1,
  docs/ARCHITECTURE.md "The raw lake" and "Cook County source",
  docs/DATA_SOURCES.md `cook_sao`): downloads of any size stream to a
  temporary file — `http.download_to_file` hashes while writing, enforces
  the caller's cap against `Content-Length` and while reading, and removes
  the partial file on a cap overrun, a failed attempt, or any exception;
  `make_client` refuses a non-HTTPS request in a request hook, so a
  redirect to plain HTTP is never sent. Every ingest run owns one
  `tempfile` directory (prefix `judgemetrics-ingest-`, never under the
  repository) handed to `SupportsWorkDir` connectors and removed when the
  run ends; the runner hashes a path-backed artifact in chunks
  (`base.sha256_file`), stores it with `RawObjectStore.put_file` (chunked
  copy + fsync + rename; boto3 managed multipart on S3), and reads lake
  objects back with `get_file` (verified against the key's digest) for a
  re-parse or `load_context` — never `read_bytes()` or `store.get()` on an
  export. A filesystem object's stored digest is its key's (the store
  writes nothing that does not hash to its key), an S3 object's the
  `sha256` metadata. The `cook_sao` connector (parser version `0`, parses
  nothing; Step 4 bumps it) reads each dataset's portal metadata first and
  returns `RawArtifact.unchanged` when the `rowsUpdatedAt` equals the
  previous record's `rows_updated_at` (the runner forwards it as
  `previous_rows_updated_at`), so a rerun over the frozen corpus costs five
  metadata requests and records nothing; the cap is `MAX_EXPORT_BYTES`
  (1.5 GiB, more than twice Initiation's 512,058,076 bytes). The export
  headers are the portal's display names (`CASE_ID`,
  `PRIMARY_CHARGE_FLAG`, `LENGTH_OF_CASE_in_Days`), not the API field
  names, and dates come in two formats (`schema.DATE_FORMATS`).
  `data/reference/cook_sao/profile.yaml` is generated by `judgemetrics
  sources profile cook_sao` from the stored exports and is never
  hand-edited (a unit test re-dumps it and compares); it lists race and
  gender as values only and the age as a range, never with a count; its
  five sha256 digests are allowlisted by the scoped baseline refresh, which
  must name every allowlisted file (the golden manifest's note above: a
  scan with file arguments keeps only those files' results).
  The fixture `tests/fixtures/cook_sao/` is generated by `judgemetrics
  sources excerpt cook_sao` with the strata read from the committed
  profile, so excerpting the fixture reproduces it byte for byte; every
  value of `schema.BLANKED_COLUMNS` (race, gender, age, the incident's
  city and dates, the arresting agency and unit) is empty in every row
  (unit test), and real `CASE_ID`/`CASE_PARTICIPANT_ID` values stay (public
  pseudonymous ids that join the datasets). Regenerate the profile, then
  the excerpt, then refresh the baseline — never edit either file. The
  corpus has no cross-case person key (the participant id is per case and
  re-hashed for every release), so the SAO's ids never key a person across
  cases.
- Florida pilot (Phase 5 Step 2, `docs/florida-data-inventory.md`,
  `docs/DATA_SOURCES.md` `fl_jdms`/`fl_cjdt`/`fl_clerks`): the selected
  pilot is Hillsborough County — the clerk's open weekly criminal name index
  files on `publicrec.hillsclerk.com` — with FDLE's Criminal Justice Data
  Transparency data (`fl_cjdt`) as the companion source, because §943.6871
  gives every person a random identifier that is "the same for that person
  in any court case" and bars a license or fee; Broward, then Miami-Dade, is
  the ranked fallback. Phase 7 §7.1 enters Florida only through a candidate
  verified on a machine-readable route, a judge for one decision family, and
  aggregates `yes` in writing (or by counsel's §6.4 opinion); otherwise the
  next-best verified state source enters first. Every `flcourts.gov` host,
  the Department of Corrections, and the Palm Beach and Pinellas clerks'
  sites refuse automated readers (robots or a challenge), so facts from them
  stay `unverified` until a person reads them in a browser or the office
  answers. The requests under `docs/florida/requests/` carry the operator's
  contact details only as bracketed fields; sent copies and answers stay
  outside the repository, and each answer is recorded the day it arrives in
  the register's Redistribution field, question 8, and "Florida acquisition
  requests" in `docs/ROADMAP.md`.
- Cook County rule tables, vocabulary 3, specification 2 (Phase 5 Step 3,
  docs/ARCHITECTURE.md "Cook County source", docs/DATA_MODEL.md
  "Vocabularies", docs/ENTITY_RESOLUTION.md "Judges by alias (Cook
  County)"): `data/reference/cook_sao/` holds seven reviewed tables
  (`attribution_rules.yaml`, `pretrial_rules.yaml`, `sentence_rules.yaml`,
  `offense_map.csv`, `courts.yaml`, `judge_aliases.csv`, `judges.csv`) and
  `tables.yaml`, which pins each one's file, version, and sha256;
  `ingest/cook_sao/rules.py` (`load_rules`, `RULE_VERSIONS`,
  `RULE_VERSION_TAG`) refuses a table whose digest or version differs and
  validates every field against the vocabulary (`RuleError` names the file,
  key, and field). **A table change bumps its version in three places — the
  YAML table's own `version` (a CSV has none), `tables.yaml` beside the new
  digest, and `RULE_VERSIONS` — and the connector's parser version embeds
  `RULE_VERSIONS`, so every stored export is re-parsed and every row
  re-derived; then refresh the scoped baseline (above: `tables.yaml`'s
  digests are allowlisted).** The tables are reviewed data, not generated:
  edit them by hand, and recompute the attribution `summary` with
  `rules.summarize` over the profile's Dispositions pairs (the unit test
  compares). Every value the documentation does not settle is `unknown`
  with the phrase "not settled by the source's documentation" (the loader
  requires it). Vocabulary 3 added values only for these tables; the
  generator draws, ranks, and codes `SYNTHETIC_SEVERITIES` and the truth
  iterates `FINAL_CHARGE_DISPOSITIONS`, so the golden fixture and the demo
  seed did not change — keep any future vocabulary addition out of the
  generator's draws the same way. The engine's disposition distribution
  reads `final_charge_disposition` (identical on the synthetic world;
  Step 5 wires finality into the disposed populations); the subgroup
  calibration skips a restricted attribute no index event records, so
  `race` and `gender` add no withheld rows to the synthetic validation
  report; `models verify --refit` counts a model of an earlier
  specification version `unverifiable` (its artifact still checked), so a
  specification bump does not fail it forever. Specification 2 only added
  levels with no rows: the demo refit reproduced all 3,730 published
  figures and `docs/VALIDATION.md` changed in its version line alone. The
  static guard in `tests/unit/test_metrics_snapshot.py` forbids `race` and
  `gender` under `metrics/` as whole words (a substring would match
  `trace`); the log scrubber matches substrings, so its `race` entry waits
  for Step 4, which logs the values first.

## End-of-session report (from the brief)

Every implementation session ends with: files created or changed;
architecture implemented; commands executed; test results; what
currently works; known issues; external access still needed; and the
next concrete development milestone.
